"""Optional LLM layer (Phase 9): a small JSON-in / JSON-out client for the Anthropic Messages API.

    Off unless ANTHROPIC_API_KEY is set, and TKB_LLM=off forces it off. Without it the system is the rules-only
    system, unchanged. Standard library only (urllib): no package to install.

    Guarantees the rest of the system relies on:
      - an in-memory cache, so the same request in one run gives the same reply (the scorer's repeat check); the
        cache key holds the model, the prompt (which carries the question, as_of and the crawl ids) and the mode,
        so historical / current or LLM / rules-only replies can never mix. The current Haiku model rejects a
        `temperature` setting, so replies may differ slightly BETWEEN runs: validation, not sampling, keeps
        answers safe;
      - a timeout and a failure counter: a failed call returns None and the caller falls back; nothing raises;
      - a circuit breaker: after 3 failed calls in a row (network, timeout, HTTP error) the LLM is off for the rest
        of the run, so an API outage costs at most a few slow answers, never every answer (the scorer's speed
        credit is p95 <= 2 s, 0 at 20 s). An unusable reply (not JSON, cut off) is not an outage: that question
        gets the rules answer and the breaker count is not raised (but 5 unusable replies in a row, with no good one
        between, also switch the LLM off: the model has stopped following the format);
      - thinking off by default (`TKB_LLM_THINKING=on` turns it on, with more room in every reply limit): the
        jobs here are short (classify a question, word an answer from given evidence), and thinking tokens count
        against the reply limit, which cut off 13 of 51 replies on blind set B1;
      - one HTTPS connection reused for every call (no new TLS handshake per call), unless a proxy is configured,
        in which case urllib (which honours HTTPS_PROXY) is used;
      - the key is read from the environment only: never logged, never written, never put in a reply.

    The LLM never decides which value is true: rules resolve facts (resolve.py); the LLM reads questions and
    words answers from evidence it is given, and its claims are checked against that evidence.
"""
from __future__ import annotations

import hashlib
import http.client
import io
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

log = logging.getLogger("tkb")

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
KEY_ENV, MODE_ENV, MODEL_ENV, CACHE_ENV = "ANTHROPIC_API_KEY", "TKB_LLM", "TKB_LLM_MODEL", "TKB_LLM_CACHE"
THINKING_ENV = "TKB_LLM_THINKING"            # "on": let the model think first (slower); default off
DEFAULT_MODEL = "claude-haiku-5-5"          # small and fast: the scorer's speed credit is for p95 under 2 s
TIMEOUT_S = 8.0                             # per call at most; a slower reply falls back to the rules answer
# Time budget per question (blind set C: two slow API calls, 7.7 s and 8.9 s, set p95 alone). Reading the question
# gets READ_TIMEOUT_S; a written answer gets what is left of QUESTION_BUDGET_S, and is skipped if under MIN_CALL_S.
# Typical calls take 0.7-2.5 s, so only the API's slowest calls are cut, and they get the rules answer.
READ_TIMEOUT_S = 3.0
QUESTION_BUDGET_S = 6.0
MIN_CALL_S = 1.0
BREAKER = 3                                 # failures in a row that switch the LLM off for the rest of the run
BAD_REPLIES = 5                             # unusable replies in a row (no good one between) that do the same
# The model thinks before it answers unless told not to, and thinking counts against max_tokens: with a small
# limit a reply can stop before any text (blind set B1: 13 of 51 replies cut off). With thinking on, this much
# extra room is added to every limit.
THINKING_HEADROOM = 2000
_PROXY_ENVS = ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy")


class LLM:
    """`send` is the transport: (system, user, max_tokens) -> reply text, or raises. Tests pass a fake one."""

    def __init__(self, send: Callable[[str, str, int], str], model: str = DEFAULT_MODEL,
                 cache_file: Optional[str] = None, thinking: bool = True) -> None:
        self.model = model
        self.thinking = thinking          # part of the cache key: replies with and without thinking never mix
        self._send = send
        self._cache: dict = {}
        self._cache_file = cache_file     # TKB_LLM_CACHE: replies kept on disk (record a run, replay it later)
        if cache_file and os.path.exists(cache_file):
            with open(cache_file, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        row = json.loads(line)
                        self._cache[row["key"]] = row["reply"]
        self.calls = 0                    # requests actually sent
        self.failures: list = []          # (purpose, error) - visible, like kb.errors
        self.seconds = 0.0                # total time spent waiting for replies
        self.transport = "custom"         # "keep-alive" or "urllib" for the real API (from_env)
        self._in_a_row = 0                # consecutive failures (circuit breaker)
        self._bad_in_a_row = 0            # consecutive unusable replies
        self.off = False                  # True once the breaker has tripped
        self.call_timeout = TIMEOUT_S     # the limit for the call being sent (json(..., timeout=))

    @classmethod
    def from_env(cls) -> Optional["LLM"]:
        key = os.environ.get(KEY_ENV, "").strip()
        if not key or os.environ.get(MODE_ENV, "").lower() in ("off", "0", "false", "no"):
            return None
        model = os.environ.get(MODEL_ENV, "").strip() or DEFAULT_MODEL
        thinking = os.environ.get(THINKING_ENV, "").lower() in ("on", "1", "true", "yes")
        headers = {"content-type": "application/json", "x-api-key": key, "anthropic-version": API_VERSION}
        proxied = any(os.environ.get(v) for v in _PROXY_ENVS)
        post = _urllib_post(headers) if proxied else _KeepAlive(headers).post
        holder: list = []                 # the LLM object, so the transport can read the current call's limit

        def send(system: str, user: str, max_tokens: int) -> str:
            request: dict = {"model": model, "system": system, "messages": [{"role": "user", "content": user}]}
            if thinking:
                request["max_tokens"] = max_tokens + THINKING_HEADROOM
            else:
                request["max_tokens"] = max_tokens
                request["thinking"] = {"type": "disabled"}
            limit = holder[0].call_timeout if holder else TIMEOUT_S
            data = json.loads(post(json.dumps(request).encode("utf-8"), limit).decode("utf-8"))
            text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            if data.get("stop_reason") in ("max_tokens", "refusal"):
                raise BadReply(f"reply stopped by {data['stop_reason']} (limit {request['max_tokens']}; "
                               f"starts: {text[:60]!r})")
            return text

        llm = cls(send, model, os.environ.get(CACHE_ENV, "").strip() or None, thinking)
        holder.append(llm)
        llm.transport = "urllib" if proxied else "keep-alive"
        return llm

    @classmethod
    def replay(cls, cache_file: str, model: str = DEFAULT_MODEL) -> "LLM":
        """Answers only from a recorded cache file: no key, no network (offline analysis of a recorded run)."""
        def send(system: str, user: str, max_tokens: int) -> str:
            raise KeyError("not in the recorded cache")
        return cls(send, model, cache_file)

    def json(self, purpose: str, system: str, user: str, max_tokens: int = 500,
             timeout: Optional[float] = None) -> Optional[dict]:
        """One reply parsed as a JSON object, or None (failure, timeout, or not JSON). Cached per request."""
        model = self.model if self.thinking else f"{self.model}|no-thinking"    # older recordings: thinking on
        key = hashlib.sha256("\x1f".join((model, purpose, system, user)).encode("utf-8")).hexdigest()
        if key in self._cache:
            return self._cache[key]
        if self.off:
            return None                   # the breaker tripped: rules-only for the rest of the run
        started = time.perf_counter()
        self.call_timeout = min(timeout, TIMEOUT_S) if timeout else TIMEOUT_S
        try:
            self.calls += 1
            out = parse_json_object(self._send(system, user, max_tokens))
            self._in_a_row = self._bad_in_a_row = 0
        except (ValueError, KeyError) as e:
            # The API answered, but the reply is unusable (not JSON, cut off): this question falls back to the
            # rules, and it is NOT an outage, so it does not count towards the breaker (blind set B1: 5 unreadable
            # replies in 40 questions tripped the breaker and switched the LLM off for the last 17).
            self.failures.append((purpose, describe(e)))
            log.warning("tkb llm %s: unusable reply: %s", purpose, type(e).__name__)
            out = None
            self._in_a_row = 0
            self._bad_in_a_row += 1
            if self._bad_in_a_row >= BAD_REPLIES:     # the model has stopped following the format: stop asking
                self.off = True
                self.failures.append(("breaker", f"LLM off for the rest of this run after {BAD_REPLIES} "
                                                 "unusable replies in a row"))
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as e:
            self.failures.append((purpose, describe(e)))
            log.warning("tkb llm %s failed: %s", purpose, type(e).__name__)
            out = None
            self._in_a_row += 1
            if self._in_a_row >= BREAKER:
                self.off = True
                self.failures.append(("breaker", f"LLM off for the rest of this run after {BREAKER} failures in a row"))
                log.warning("tkb llm: %d failures in a row, answering rules-only from now on", BREAKER)
        self.seconds += time.perf_counter() - started
        if out is not None:
            self._cache[key] = out        # failures are not cached: a later identical request may succeed
            if self._cache_file:          # the question and the model's reply only: never the key
                with open(self._cache_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"key": key, "purpose": purpose, "user": user, "reply": out}) + "\n")
        return out


class BadReply(ValueError):
    """The API answered, but the reply cannot be used (cut off, or no JSON object in it)."""


class _KeepAlive:
    """One HTTPS connection to the API, reused for every call; reopened once if the server closed it."""

    def __init__(self, headers: dict) -> None:
        self.headers = headers
        self.conn: Optional[http.client.HTTPSConnection] = None

    def post(self, body: bytes, timeout: float = TIMEOUT_S) -> bytes:
        for attempt in (1, 2):
            reused = self.conn is not None
            if self.conn is None:
                self.conn = http.client.HTTPSConnection("api.anthropic.com", timeout=timeout)
            elif self.conn.sock is not None:
                self.conn.sock.settimeout(timeout)          # this call's limit on the reused connection
            try:
                self.conn.request("POST", "/v1/messages", body=body, headers=self.headers)
                resp = self.conn.getresponse()
                data = resp.read()
            except (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError):
                self.close()
                if reused and attempt == 1:
                    continue              # an idle connection the server had closed: one fresh retry
                raise
            except (OSError, http.client.HTTPException):
                self.close()
                raise
            if resp.status != 200:
                raise urllib.error.HTTPError(API_URL, resp.status, resp.reason, resp.headers, io.BytesIO(data))
            return data
        raise ConnectionError("unreachable")

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
        self.conn = None


def _urllib_post(headers: dict) -> Callable[[bytes, float], bytes]:
    """A fresh request per call through urllib, which honours HTTPS_PROXY (a proxied environment)."""
    def post(body: bytes, timeout: float = TIMEOUT_S) -> bytes:
        req = urllib.request.Request(API_URL, data=body, method="POST", headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    return post


def describe(e: Exception) -> str:
    """A failure in words, with the API's own message for an HTTP error ("`temperature` is deprecated...")."""
    if isinstance(e, urllib.error.HTTPError):
        try:
            message = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
        except (ValueError, OSError, AttributeError):
            message = ""
        return f"HTTP {e.code}: {message or e.reason}"[:200]
    return f"{type(e).__name__}: {str(e)[:120]}"


def parse_json_object(text: str) -> dict:
    """The first {...} object in a reply (models sometimes wrap JSON in prose or code fences)."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise BadReply(f"no JSON object in reply (starts: {(text or '')[:60]!r})")
    obj = json.loads(m.group(0))
    if not isinstance(obj, dict):
        raise ValueError("reply is not a JSON object")
    return obj
