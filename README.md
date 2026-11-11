# Temporal knowledge base

Answers questions about a credit union's website from five dated crawls, keeps track of what was true when,
and reports where the site contradicts itself. Python standard library only; no packages to install.

**Two modes, chosen by one environment variable:**

| Mode | How | Measured (kit scorer) |
|---|---|---|
| Rules only (default) | nothing to set | public set 0.969, p95 0.04 s; blind sets lower (see NOTES) |
| Rules + LLM | `export ANTHROPIC_API_KEY=...` (Claude Haiku via the Anthropic API) | better on unseen questions (blind sets +0.05 to +0.34); public set 0.92-0.95; p95 about 2-3.5 s |

Without a key the submission runs rules-only and never calls the network. With a key, the LLM only reads
questions and words answers from checked evidence; every value still comes from the rules, and any failure
falls back to the rules answer. No key is stored in this repository.

- How it works, results and limitations: `submission/NOTES.md`
- Rules and decisions with their evidence: `docs/`
- Tests: `pip install pytest && pytest -q` (tests that need the event's scoring harness are skipped without it)

The website snapshots and evaluation datasets belong to the event and are not included.
