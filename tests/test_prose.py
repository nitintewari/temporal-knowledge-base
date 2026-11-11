"""Phase 2E tests: prose facts. Each page below is a miniature copy of a real page (docs/RULES.md)."""
# pyright: reportOptionalMemberAccess=false
from types import SimpleNamespace as NS

from tkb.prose import clean_page, extract_prose, is_listing, parse_date, publish_date
from tkb.resolve import NEWEST_PUBLICATION, resolve_crawl
from tkb.store import VersionStore

D = "https://www.dupaco.com"
ABOUT = ("**ABOUT DUPACO COMMUNITY CREDIT UNION** A member-owned cooperative based in Dubuque, Iowa. Today it "
         "serves more than 160,000 members and reports assets exceeding $3.6 billion. Its staff: over 600 employees "
         "and {n} branch office locations. Details at "
         "[www.dupaco.com](https://www.dupaco.com/).")


def press(date: str, title: str, body: str, n: int = 22, teaser: str = "## Handpicked for You") -> str:
    """A press release as crawled: byline, title, body, ABOUT boilerplate, then a teaser block with old dates."""
    return (f"2 min read\n\n[Emily Kress]({D}/newsroom/author/emily-kress)\n{date}\n\n# {title}\n\n"
            f"[Branch Announcements]({D}/newsroom/tag/branch-announcements)\n\n{body}\n\n###\n\n{ABOUT.format(n=n)}\n\n"
            f"{teaser}\n\n2 min read\n\nJune 07, 2022\n\n#### [Old news]({D}/newsroom/old)\n\n"
            "DUBUQUE, Iowa-Forbes again listed Dupaco among top-rated credit unions in Iowa. "
            "Back then it had over 500 employees and 19 branch office locations...\n\n"
            f"[Keep reading]({D}/newsroom/old)\n\n✕\n\n[Continue]({D}/newsroom/x#) Cancel\n")


def facts(markdown: str, path: str = "/newsroom/x", kind: str = "press") -> list:
    return extract_prose(markdown, D + path, kind)[1]


def one(found: list, kind: str, **want):
    hits = [f for f in found if f.kind == kind and all(getattr(f, k) == v for k, v in want.items())]
    assert len(hits) == 1, f"expected 1 {kind} fact matching {want}, got {[(f.subject, f.value) for f in hits]}"
    return hits[0]


# ----------------------------------------------------------------------------- R11: boilerplate
def test_teaser_block_is_cut_under_both_of_its_names_R11():
    # "## Recent News" in snapshots 01-03, "## Handpicked for You" in 04-05: same block, renamed.
    for heading in ("## Recent News", "## Handpicked for You"):
        cleaned = clean_page(press("April 06, 2026", "Sycamore renovation", "Body.", teaser=heading))
        assert "Old news" not in cleaned and "June 07, 2022" not in cleaned
        assert "22 branch office locations" in cleaned            # the ABOUT boilerplate is a fact source: kept


def test_widget_chrome_image_data_and_chart_series_are_removed_E12_E24():
    page = ("Real text.\n\nThird Party Plugins\n\nMessenger Launcher\n\nMessenger\n\n✕\n\n"
            "![](data:image/svg+xml,%3Csvg%20width%3D%2220%22)\n\nAddress ![icon](data:image/png;base64,AAAA) here\n\n"
            "Balance data points: 0: 2000; : 2107; : 2216; : 2326; : 2439; : 2551; : 2666; : 2783; : 2902; 10: 3144;\n")
    cleaned = clean_page(page)
    assert "Real text." in cleaned and "Address" in cleaned
    for junk in ("Messenger", "✕", "data:image", "2107"):
        assert junk not in cleaned


def test_publish_date_is_the_byline_never_a_teaser_date_E22():
    cleaned = clean_page(press("April 21, 2025", "Volunteering pays off", "Body."))
    assert publish_date(cleaned, "press") == "2025-04-21"
    assert publish_date(cleaned, "product") is None             # only press releases and blog posts are dated


def test_parse_date_handles_full_and_abbreviated_months():
    assert parse_date("This location will close March 31, 2026.") == "2026-03-31"
    assert parse_date("last day of service will be Tuesday, Oct. 1, 2024.") == "2024-10-01"
    assert parse_date("Sept. 5, 2025") == "2025-09-05"
    assert parse_date("March 41, 2026") is None and parse_date("no date here") is None


def test_listing_pages_give_no_date_and_no_facts():
    teasers = "".join(f"May 5, 2026\n\n#### [Item {i}]({D}/newsroom/i{i})\n\n"
                      f"It has 23 branch office locations...\n\n[Read More]({D}/newsroom/i{i})\n\n" for i in range(3))
    assert is_listing(D + "/newsroom", "# Dupaco Newsroom\n\n" + teasers)
    assert is_listing(D + "/newsroom/tag/awards", "anything")
    assert extract_prose("# Dupaco Newsroom\n\nSort By:Most RecentOldest\n\n" + teasers, D + "/newsroom", "press") \
        == (None, [])
    # An article is NOT a listing just because its own teaser block has three "Keep reading" links.
    assert not is_listing(D + "/newsroom/x", press("April 06, 2026", "T", "Body.") + "[Keep reading](a)\n" * 3)


# ----------------------------------------------------------------------------- pattern facts
def test_boilerplate_facts_branches_employees_assets_E4():
    found = facts(press("April 06, 2026", "Sycamore renovation", "Body.", n=22))
    assert one(found, "branch_count").value == "22"             # the teaser's "19" was cut with the teaser block
    assert one(found, "employees").number == 600
    assets = one(found, "assets")
    assert (assets.value, assets.number, assets.published) == ("$3.6 billion", 3.6, "2026-04-06")


def test_forbes_recognition_is_an_ordinal_E6():
    body = "Forbes again named Dupaco a top-rated credit union. This was the fifth time Forbes recognized Dupaco."
    f = one(facts(press("June 18, 2024", "Forbes ranks Dupaco", body)), "forbes_recognition")
    assert (f.value, f.number) == ("fifth", 5)


def test_vto_year_is_the_subject_so_years_never_compete_R21_E22():
    body = ("- **294 Dupaco employees** used a paid benefit in 2023 called Volunteer Time Off, so staff "
            "can volunteer.")
    f = one(facts(press("April 19, 2024", "Volunteering pays off", body)), "vto_employees")
    assert (f.subject, f.value, f.key()) == ("2023", "294", ("vto_employees", "2023", None))


def test_routing_number_in_every_wording_E10():
    for text in ("**Routing Number:** 273974581", "share our routing number (273974581) and your info",
                 "Provide the payer with our ABA number (273974581).", "Dupaco's routing number is 273974581."):
        assert one(facts(text, "/contact", "other"), "routing_number").value == "273974581"
    assert facts("Call 800-373-7600 or 5635577600 today.", "/contact", "other") == []


# ----------------------------------------------------------------------------- structural readers
def test_locator_addresses_are_keyed_by_city_and_street():
    page = ("### Dupaco Credit Union\n\nDupaco Branch\n\n11375 Oldenburg Ln., Galena, IL, 61036\n\nClosed\n\n"
            "### Dupaco Credit Union\n\nDupaco Branch\n\n1465 Sycamore St., Dubuque, IA, 52001\n\n"
            "### MidWestOne Bank - Key West Drive-Up\n\nSurcharge-Free ATM\n\n2600 Rockdale Rd, Dubuque, IA, 52003\n")
    found = facts(page, "/contact", "other")
    galena = one(found, "address", subject="galena")
    assert (galena.value, galena.qualifier, galena.published) == ("11375 Oldenburg Ln., Galena, IL, 61036",
                                                                  "11375 oldenburg ln.", None)
    assert [f.subject for f in found if f.kind == "address"] == ["galena", "dubuque"]   # not the partner ATM


def test_hours_blocks_per_service_with_branch_label():
    body = ("MADISON, Wis.-Dupaco celebrated a ribbon cutting.\n\nThe phone number for the East Washington branch "
            "is (608) 282-6000. Branch hours are:\n\n**Lobby**\n\nMonday-Friday: 9 a.m.-5 p.m.\n\n"
            "Saturday-Sunday: Closed\n\n**Drive-up** Monday-Friday: 8 a.m.-6:30 p.m.\n\nSaturday: 9 a.m.-noon")
    found = facts(press("November 02, 2022", "East Washington ribbon cutting", body), "/newsroom/east-wash")
    lobby, drive = one(found, "hours", qualifier="lobby"), one(found, "hours", qualifier="drive-up")
    assert lobby.value == "Monday-Friday: 9 a.m.-5 p.m.; Saturday-Sunday: Closed"
    assert drive.value == "Monday-Friday: 8 a.m.-6:30 p.m.; Saturday: 9 a.m.-noon"   # "**Drive-up** Monday..." inline
    assert lobby.label == "Madison East Washington branch" and lobby.subject == "/newsroom/east-wash"


def test_branch_closure_date_and_where_members_go_E5():
    body = ("DUBUQUE, Iowa-Dupaco will close its branch inside the South Locust St. Hy-Vee store.\n\n"
            "This location will close March 31, 2026, and its staff will stay on.\n\n"
            "\"Hy-Vee branch members can access the same help at the full-service "
            "branches at Key West and Sycamore Street,\" a spokesperson said.")
    found = facts(press("June 20, 2025", "Dupaco plans Hy-Vee branch closure",
                        body))
    assert one(found, "closure", subject="hy-vee").value == "2026-03-31"
    assert one(found, "closure_alternatives", subject="hy-vee").value == "Key West and Sycamore Street"
    asbury = facts(press("June 06, 2024", "Dupaco closing Asbury branch to reduce locations",
                         "The branch's last day of service will be Tuesday, Oct. 1, 2024."))
    assert one(asbury, "closure", subject="asbury").value == "2024-10-01"


# ----------------------------------------------------------------------------- R4 / R27 resolution
def crawl(*pages):
    """pages: (path, markdown, page_type, fetched) -> Resolved, the way the store builds it."""
    built = {}
    for path, md, kind, fetched in pages:
        built[D + path] = NS(fetched_at=fetched, facts=[], prose=extract_prose(md, D + path, kind)[1])
    return resolve_crawl("05", built)


def test_newest_publication_wins_never_the_majority_R4_E4():
    old = [(f"/newsroom/old{i}", press(f"March {10 + i}, 2026", f"Old {i}", "Body.", n=23), "press", "2026-09-28")
           for i in range(3)]
    new = ("/newsroom/new", press("April 03, 2026", "New", "Body.", n=22), "press", "2026-09-28")
    [r] = crawl(*old, new).find_prose("branch_count")
    assert r.value == "22" and r.winner.path == "/newsroom/new"
    assert len(r.losers) == 3 and {loser.reason for loser in r.losers} == {NEWEST_PUBLICATION}


def test_undated_official_page_speaks_as_of_its_fetch_date_R27():
    contact = ("/contact", "**Routing Number:** 273974581", "other", "2026-09-28T03:00:00Z")
    blog = ("/learn/blog/taxes", press("February 06, 2026", "Taxes", "Dupaco's routing number is 273974581."),
            "blog", "2026-09-28T03:00:00Z")
    [r] = crawl(contact, blog).find_prose("routing_number")
    assert (r.winner.path, r.winner.stated, len(r.agree), r.losers) == ("/contact", "2026-09-28", 1, [])


def test_find_prose_lists_the_newest_year_first_R21():
    def vto(n: int, year: int, date: str) -> str:
        return press(date, "Volunteering pays off",
                     f"- **{n} Dupaco employees** used a paid benefit in {year} called Volunteer Time Off.")
    R = crawl(("/newsroom/vto", vto(294, 2023, "April 19, 2024"), "press", "2026-09-28"),
              ("/newsroom/vto-2", vto(256, 2024, "April 21, 2025"), "press", "2026-09-28"))
    assert [(r.key[1], r.value) for r in R.find_prose("vto_employees")] == [("2024", "256"), ("2023", "294")]
    assert all(not r.has_conflict for r in R.find_prose("vto_employees"))   # different years: not a conflict


def test_store_extracts_prose_once_and_resolves_by_as_of():
    def snap(sid, day, n):
        return NS(snapshot_id=sid, taken_on=day,
                  pages=[NS(url=D + "/newsroom/a", title="A", markdown=press("March 17, 2026", "A", "B.", n=23),
                            fetched_at=day),
                         NS(url=D + "/newsroom/b", title="B", markdown=press("April 03, 2026", "B", "B.", n=n),
                            fetched_at=day)])
    store = VersionStore()
    store.add_snapshot(snap("01", "2026-05-12", 23))
    store.add_snapshot(snap("05", "2026-09-28", 22))
    assert store.history[D + "/newsroom/a"][0].published == "2026-03-17"
    assert len(store.history[D + "/newsroom/a"]) == 1                # unchanged page: parsed once
    assert store.resolved("2026-05-31").find_prose("branch_count")[0].value == "23"
    assert store.resolved().find_prose("branch_count")[0].value == "22"
