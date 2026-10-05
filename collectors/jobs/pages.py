"""watch_pages and scrape_programs: hash watched pages and record what changed.

watch_pages (daily) covers each curated org's ideas page, plus a guessed next-year ideas URL
(2026 -> 2027): many orgs publish next year's ideas in January, before the official org list.
scrape_programs (weekly) covers every program's official pages. A changed program page is
flagged for a human to confirm; dates found on it are suggestions, never written to content/.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from selectolax.lexbor import LexborHTMLParser
from sqlalchemy import select

from collectors.db.models import Idea, Org, PageSnapshot, ProgramYear, WatchedPage
from collectors.jobs import JobContext, emit
from collectors.sync import effective_links

DROP_TAGS = (
    "script",
    "style",
    "noscript",
    "svg",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "iframe",
)
MAIN_SELECTORS = (
    "#wiki-body",
    ".markdown-body",
    "main",
    "article",
    "[role=main]",
    "#content",
    "#main-content",
    ".content",
)
# Headings that structure an ideas page but are not ideas themselves. Section names must match
# the whole heading ("Mentors" is generic, "Mentor dashboard API" is an idea); the prefixes are
# page furniture that is never an idea.
GENERIC_EXACT = re.compile(
    r"^(?:intro(?:duction)?|overview|about|contents|table of contents|ideas?(?: list)?|"
    r"(?:project )?ideas(?: list)?|list of ideas|mentors?|skills?(?: required| needed)?|"
    r"required skills|difficulty(?: level)?|duration|(?:project |expected )?size|"
    r"expected (?:outcomes?|results?)|outcomes?|resources|links|description|deliverables|"
    r"notes?|requirements|prerequisites|faq|timeline|contact(?: us)?|communication|questions|"
    r"key dates|important dates|eligibility|steps|feedback|summary|background|motivation|"
    r"goals?|tasks?|references|acknowledg(?:e)?ments|community|support|help)"
    r"\s*[:.?]?$",
    re.IGNORECASE,
)
# Pages that number their ideas ("Project 3: ...", "Idea #2 - ...") make the job easy.
NUMBERED_IDEA = re.compile(r"^(?:project|idea|proposal)\s*#?\s*\d+\b", re.IGNORECASE)
GENERIC_PREFIX = re.compile(
    r"^(?:getting started|how to (?:apply|get started|contribute)|before you apply|"
    r"important dates|proposal (?:template|guidelines)|application (?:template|process)|"
    r"guidelines|google summer of code)",
    re.IGNORECASE,
)
MIN_PAGE_CHARS = 400
DATE_LINE = re.compile(
    r"\b(?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}"
    r"(?:\s*[-–]\s*\d{1,2})?,?\s+20\d\d|\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
    r"[a-z]*\.?\s+20\d\d|20\d\d-\d\d-\d\d)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Target:
    url: str
    kind: str  # ideas | ideas_next | program
    entity_type: str  # org | program
    entity_slug: str
    label: str


@dataclass(frozen=True)
class Extracted:
    text: str
    headings: list[str]


def fetch_url(url: str) -> str:
    """GitHub blob pages render through JavaScript; their raw file is plain markdown."""
    parts = urlsplit(url)
    if parts.netloc == "github.com" and "/blob/" in parts.path:
        owner_repo, _, rest = parts.path.lstrip("/").partition("/blob/")
        return f"https://raw.githubusercontent.com/{owner_repo}/{rest}"
    return url


def extract(body: str, content_type: str) -> Extracted:
    """Visible main text and heading titles from HTML or markdown."""
    if "html" not in content_type and not body.lstrip().startswith("<"):
        levels: dict[str, list[str]] = {"h2": [], "h3": [], "h4": []}
        for m in re.finditer(r"^(#{2,4})\s+(.+?)\s*$", body, re.MULTILINE):
            levels[f"h{len(m.group(1))}"].append(m.group(2).strip("*`"))
        return Extracted(_normalise(body), _pick_level(levels))
    tree = LexborHTMLParser(body)
    for tag in DROP_TAGS:
        for node in tree.css(tag):
            node.decompose()
    root = next((n for sel in MAIN_SELECTORS if (n := tree.css_first(sel)) is not None), None)
    root = root or tree.body or tree.root
    if root is None:
        return Extracted("", [])
    by_level: dict[str, list[str]] = {"h2": [], "h3": [], "h4": []}
    for level, titles in by_level.items():
        titles.extend(n.text(strip=True) for n in root.css(level))
    text = _normalise(root.text(separator="\n"))
    return Extracted(text, _pick_level(by_level))


VOLATILE_LINE = re.compile(
    r"\b\d+\s+(?:seconds?|minutes?|mins?|hours?|hrs?|days?|weeks?|months?|years?)\s+ago\b"
    r"|^(?:last\s+)?(?:updated|edited|modified)\b"
    r"|\b\d[\d,.]*\s*[km]?\s+(?:views?|watchers?|reads?)\b",
    re.IGNORECASE,
)


def fingerprint(text: str) -> str:
    """Order-insensitive hash of the page's stable lines.

    Pages shuffle testimonials and print "updated 3 hours ago"; neither is a real change. Hashing
    the sorted set of lines, minus relative timestamps and view counters, ignores both while still
    catching any line that is added, removed or edited.
    """
    stable = sorted({line for line in text.splitlines() if not VOLATILE_LINE.search(line)})
    return hashlib.sha256("\n".join(stable).encode()).hexdigest()


def _normalise(text: str) -> str:
    lines = (re.sub(r"[ \t\u00a0]+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def _clean(titles: list[str]) -> list[str]:
    seen: list[str] = []
    for title in titles:
        title = re.sub(r"\s+", " ", title).strip(" :#*")[:300]
        generic = GENERIC_EXACT.match(title) or GENERIC_PREFIX.match(title)
        if len(title) >= 4 and not generic and title not in seen:
            seen.append(title)
    return seen


def _pick_level(by_level: dict[str, list[str]]) -> list[str]:
    """Ideas are usually the most numerous heading level that has at least three entries."""
    cleaned = {level: _clean(titles) for level, titles in by_level.items()}
    numbered = [t for titles in cleaned.values() for t in titles if NUMBERED_IDEA.match(t)]
    if len(numbered) >= 3:
        return numbered
    best = max(cleaned.values(), key=len)
    return best if len(best) >= 3 else []


def date_lines(text: str, limit: int = 12) -> list[str]:
    found: list[str] = []
    for line in text.splitlines():
        if DATE_LINE.search(line) and line not in found:
            found.append(line[:200])
            if len(found) >= limit:
                break
    return found


# Confluence and Google Docs address pages by ID; a year in their URL is a cosmetic title slug,
# so swapping it returns this year's page, not next year's.
ID_ADDRESSED = re.compile(r"/pages/\d+/|/document/d/|/spreadsheets/d/")


def next_year_url(url: str | None, year: int) -> str | None:
    if not url or str(year) not in url or ID_ADDRESSED.search(url):
        return None
    return url.replace(str(year), str(year + 1))


def org_targets(ctx: JobContext) -> Iterator[Target]:
    latest = ctx.session.scalar(
        select(ProgramYear.year)
        .where(ProgramYear.program == "gsoc")
        .order_by(ProgramYear.year.desc())
    )
    for org in ctx.content.orgs:
        links = effective_links(org, ctx.session.get(Org, org.slug))
        if links["ideas"]:
            yield Target(links["ideas"], "ideas", "org", org.slug, f"{org.name} ideas page")
        upcoming = links["ideas_next"] or (latest and next_year_url(links["ideas"], latest))
        if upcoming and upcoming != links["ideas"]:
            yield Target(
                upcoming, "ideas_next", "org", org.slug, f"{org.name} next-year ideas page"
            )


def program_targets(ctx: JobContext) -> Iterator[Target]:
    for program in ctx.content.programs:
        urls = [str(program.url), *(str(u) for u in program.watch_urls)]
        for url in dict.fromkeys(urls):
            yield Target(url, "program", "program", program.slug, f"{program.name} page")


def _redirected_away(requested: str, resp: httpx.Response) -> bool:
    """A missing wiki page often redirects to the wiki home; that is not the page we asked for."""
    asked, got = urlsplit(requested), urlsplit(str(resp.url))
    return (asked.netloc, asked.path.rstrip("/")) != (got.netloc, got.path.rstrip("/"))


def check(ctx: JobContext, target: Target) -> str:
    """Fetch one target and record what happened. Returns a one-word outcome for the summary."""
    session = ctx.session
    page = session.get(WatchedPage, target.url)
    if page is None:
        page = WatchedPage(
            url=target.url,
            kind=target.kind,
            entity_type=target.entity_type,
            entity_slug=target.entity_slug,
            consecutive_errors=0,
            needs_confirmation=False,
        )
        session.add(page)
    now = ctx.now
    page.last_checked_at = now
    url = fetch_url(target.url)
    if not ctx.http.allowed_by_robots(url):
        page.note = "skipped: disallowed by robots.txt"
        return "robots"
    try:
        resp = ctx.http.get(url, etag=page.etag, last_modified=page.last_modified)
    except httpx.TransportError as exc:
        page.consecutive_errors = (page.consecutive_errors or 0) + 1
        page.note = f"network error: {type(exc).__name__}"
        return "error"
    if resp.status_code == 304:
        # Not modified: the page still answers with its last real status (normally 200).
        page.consecutive_errors = 0
        return "unchanged"
    page.last_status = resp.status_code
    if target.kind == "ideas_next":
        published = resp.status_code == 200 and not _redirected_away(url, resp)
        return _check_upcoming(ctx, target, page, resp, published)
    if resp.status_code != 200:
        page.consecutive_errors = (page.consecutive_errors or 0) + 1
        page.note = f"HTTP {resp.status_code}"
        return "error"

    extracted = extract(resp.text, resp.headers.get("content-type", ""))
    digest = fingerprint(extracted.text)
    page.etag = resp.headers.get("etag")
    page.last_modified = resp.headers.get("last-modified")
    page.consecutive_errors = 0
    page.note = (
        None if len(extracted.text) >= MIN_PAGE_CHARS else "little text: page may need JavaScript"
    )
    if digest == page.last_hash:
        return "unchanged"

    previous = session.scalars(
        select(PageSnapshot)
        .where(PageSnapshot.url == target.url)
        .order_by(PageSnapshot.fetched_at.desc())
    ).first()
    dates = date_lines(extracted.text)
    session.merge(  # merge, not add: a re-check within the same second replaces the snapshot
        PageSnapshot(
            url=target.url,
            fetched_at=now,
            content_hash=digest,
            headings=extracted.headings,
            dates=dates,
            text_chars=len(extracted.text),
        )
    )
    first_sight = page.last_hash is None
    page.last_hash = digest
    page.last_changed_at = now
    if target.kind == "ideas":
        _record_ideas(ctx, target, extracted.headings)
    if first_sight:
        return "baseline"  # nothing to compare against yet; no alert

    old_headings = list(previous.headings) if previous else []
    added = [h for h in extracted.headings if h not in old_headings]
    removed = [h for h in old_headings if h not in extracted.headings]
    new_dates = [d for d in dates if d not in (previous.dates if previous else [])]
    # Only changes a person would act on raise an alert: ideas added or removed, or (on program
    # pages) new dates. Other edits are still snapshotted and show as "last changed" on the site.
    meaningful = bool(added or removed or (target.kind == "program" and new_dates))
    if not meaningful:
        return "edited"
    detail: dict[str, object] = {"added": added[:20], "removed": removed[:20]}
    if target.kind == "program":
        page.needs_confirmation = True
        detail["dates_found"] = new_dates or dates
    emit(
        session,
        key=f"page-changed:{target.url}:{digest[:16]}",
        kind="ideas_changed" if target.kind == "ideas" else "program_page_changed",
        title=f"{target.label} changed"
        + (f": {len(added)} ideas added, {len(removed)} removed" if added or removed else ""),
        entity_type=target.entity_type,
        entity_slug=target.entity_slug,
        url=target.url,
        detail=detail,
        when=now,
    )
    return "changed"


def _check_upcoming(
    ctx: JobContext, target: Target, page: WatchedPage, resp: httpx.Response, published: bool
) -> str:
    """The guessed next-year ideas page: alert once, the first time it exists with real content.

    A wiki may answer any page name with this year's page, a redirect, or a "create this page"
    stub, so a page only counts as published when it is substantial, mentions the year it
    appears to be for, and is not identical to the current ideas page.
    """
    page.consecutive_errors = 0
    if not published:
        page.note = "not published yet"
        return "not-yet"
    extracted = extract(resp.text, resp.headers.get("content-type", ""))
    if len(extracted.text) < MIN_PAGE_CHARS:
        page.note = "exists but nearly empty"
        return "not-yet"
    digest = fingerprint(extracted.text)
    years_in_url = re.findall(r"20\d\d", target.url)
    if years_in_url and years_in_url[-1] not in extracted.text:
        page.note = f"page exists but never mentions {years_in_url[-1]}"
        return "not-yet"
    current = ctx.session.scalars(
        select(WatchedPage).where(
            WatchedPage.entity_slug == target.entity_slug, WatchedPage.kind == "ideas"
        )
    ).first()
    if current is not None and current.last_hash == digest:
        page.note = "same content as the current ideas page"
        return "not-yet"
    first_sight = page.last_hash is None
    page.last_hash, page.note = digest, "published"
    if first_sight:
        page.last_changed_at = ctx.now
        emit(
            ctx.session,
            key=f"ideas-published:{target.url}",
            kind="ideas_published",
            title=f"{target.label} is up"
            + (f" with {len(extracted.headings)} ideas" if extracted.headings else ""),
            entity_type="org",
            entity_slug=target.entity_slug,
            url=target.url,
            detail={"headings": extracted.headings[:30]},
        )
        return "published"
    return "unchanged"


def _record_ideas(ctx: JobContext, target: Target, headings: list[str]) -> None:
    for title in headings:
        idea = ctx.session.get(Idea, (target.entity_slug, target.url, title))
        if idea is None:
            ctx.session.add(
                Idea(
                    org=target.entity_slug,
                    url=target.url,
                    title=title,
                    first_seen=ctx.today,
                    last_seen=ctx.today,
                )
            )
        else:
            idea.last_seen = ctx.today


def _run(ctx: JobContext, targets: list[Target]) -> str:
    outcomes: dict[str, int] = {}
    for target in targets:
        outcome = check(ctx, target)
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
        ctx.session.flush()
    parts = ", ".join(f"{n} {k}" for k, n in sorted(outcomes.items()))
    return f"{len(targets)} pages: {parts}" if targets else "no pages to watch"


def watch_pages(ctx: JobContext) -> str:
    return _run(ctx, list(org_targets(ctx)))


def scrape_programs(ctx: JobContext) -> str:
    return _run(ctx, list(program_targets(ctx)))
