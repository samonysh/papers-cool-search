#!/usr/bin/env python3
"""Fetch public papers.cool list/search pages and normalize their paper cards to JSON.

This uses only documented-by-client, read-only GET routes. It intentionally does
not call Kimi, star, or configuration endpoints.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen


BASE_URL = "https://papers.cool"
USER_AGENT = "papers-cool-search/1.0 (read-only academic metadata retrieval)"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MIN_REQUEST_INTERVAL_SECONDS = 3
MAX_SESSION_REQUESTS = 20

# Bounded retry for transient transport failures (connection reset, SSL EOF, timeout).
TRANSPORT_MAX_ATTEMPTS = 3  # 1 initial try + 2 retries
TRANSPORT_RETRY_BACKOFF_SECONDS = 1

# Optional OpenAlex enrichment. Read-only, one work lookup per paper.
OPENALEX_BASE = "https://api.openalex.org"
OPENALEX_SELECT = "id,title,doi,primary_location,locations"
MAX_OPENALEX_LOOKUPS = 50

# Optional PDF retrieval, only triggered by --fetch-pdf.
OPENALEX_CONTENT_BASE = "https://content.openalex.org"
MAX_PDF_DOWNLOADS = 50
MAX_PDF_BYTES = 50 * 1024 * 1024
PDF_TIMEOUT_SECONDS = 90
PDF_REQUEST_INTERVAL_SECONDS = 1
PDF_FILE_NAME = "paper.pdf"

ARXIV_ID_PATTERN = re.compile(
    r"arxiv\.org/(?:abs|pdf)/((?:[a-z-]+(?:\.[A-Z]{2})?/\d{7})|\d{4}\.\d{4,5})(?:v\d+)?",
    re.IGNORECASE,
)
DOI_PATTERN = re.compile(r"(?:doi\.org/|doi:)(10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)


class PaperCardParser(HTMLParser):
    """Extract the stable metadata fields present in public paper-card HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.papers: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self.paper_div_depth = 0
        self.field: str | None = None
        self.parts: dict[str, list[str]] = {}

    @staticmethod
    def _classes(attrs: dict[str, str]) -> set[str]:
        return set(attrs.get("class", "").split())

    def handle_starttag(self, tag: str, attrs_raw: list[tuple[str, str | None]]) -> None:
        attrs = {key: value or "" for key, value in attrs_raw}
        classes = self._classes(attrs)
        if tag == "div" and self.current is None and "paper" in classes:
            self.current = {
                "id": attrs.get("id"),
                "authors": [],
                "subjects": [],
                # papers.cool's [REL] handler uses this exact attribute as its query.
                "papers_cool_keywords": attrs.get("keywords"),
            }
            self.paper_div_depth = 1
            return
        if self.current is None:
            return
        if tag == "div":
            self.paper_div_depth += 1
        if tag == "a":
            href = attrs.get("href", "")
            if "title-link" in classes:
                self.current["papers_cool_url"] = self._absolute(href)
                self.field = "title"
            elif "author" in classes:
                self.field = "author"
            elif any(item.startswith("subject-") for item in classes):
                self.field = "subject"
            elif href.startswith("http") and "source_url" not in self.current:
                self.current["source_url"] = href
        elif tag == "p":
            if "summary" in classes:
                self.field = "abstract"
            elif "date" in classes or attrs.get("id", "").startswith("date-"):
                self.field = "published"

    def handle_endtag(self, tag: str) -> None:
        if self.current is None:
            return
        if tag == "a" and self.field in {"title", "author", "subject"}:
            self._flush_field()
            self.field = None
        elif tag == "p" and self.field in {"abstract", "published"}:
            self._flush_field()
            self.field = None
        elif tag == "div":
            self.paper_div_depth -= 1
            if self.paper_div_depth == 0:
                self._finish_paper()

    def handle_data(self, data: str) -> None:
        if self.current is not None and self.field and data.strip():
            self.parts.setdefault(self.field, []).append(data.strip())

    def _finish_paper(self) -> None:
        assert self.current is not None
        self._flush_field()
        self.current = {key: value for key, value in self.current.items() if value not in (None, "", [])}
        self.papers.append(self.current)
        self.current = None
        self.parts = {}
        self.field = None

    def _flush_field(self) -> None:
        """Commit the active text buffer; authors/subjects are repeated fields."""
        if self.current is None or self.field is None:
            return
        pieces = self.parts.pop(self.field, [])
        value = " ".join(pieces).strip()
        if not value:
            return
        if self.field == "author":
            self.current["authors"].append(value)
        elif self.field == "subject":
            self.current["subjects"].append(value)
        elif self.field == "published":
            self.current[self.field] = value.split(":", 1)[-1].strip()
        else:
            self.current[self.field] = value

    @staticmethod
    def _absolute(href: str) -> str:
        return href if href.startswith("http") else BASE_URL + href


def build_urls(args: argparse.Namespace) -> list[tuple[str, str]]:
    if args.mode == "search":
        branches = ("arxiv", "venue") if args.branch == "all" else (args.branch,)
        paths = [(branch, f"/{branch}/search") for branch in branches]
        params: dict[str, str | int] = {"query": args.query, "highlight": "1"}
    else:
        paths = [(args.mode, f"/{args.mode}/{args.value}")]
        params = {}
    if args.show is not None:
        params["show"] = args.show
    if args.skip:
        params["skip"] = args.skip
    if args.date:
        params["date"] = args.date
    if args.sort:
        params["sort"] = args.sort
    suffix = "?" + urlencode(params) if params else ""
    return [(collection, BASE_URL + quote(path, safe="/.,+@-") + suffix) for collection, path in paths]


def parse_related_seed(value: str) -> tuple[str, str, str]:
    """Return collection, paper id, and canonical papers.cool URL for a REL seed."""
    if value.startswith(("http://", "https://")):
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.netloc != "papers.cool":
            raise ValueError("related accepts only a https://papers.cool/arxiv/<id> or /venue/<id> URL")
        path = parsed.path
    else:
        path = "/" + value.lstrip("/")
    parts = [part for part in path.split("/") if part]
    if len(parts) != 2 or parts[0] not in {"arxiv", "venue"} or not parts[1]:
        raise ValueError("related requires arxiv/<paper-id>, venue/<paper-id>, or the equivalent papers.cool URL")
    collection, paper_id = parts
    return collection, paper_id, BASE_URL + quote(path, safe="/.,+@-")


def related_search_url(collection: str, keywords: str, show: int) -> str:
    """Mirror openRelatedPapers(): a same-collection keyword search."""
    return f"{BASE_URL}/{collection}/search?" + urlencode({"query": keywords, "highlight": "1", "show": show})


def fetch(url: str) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    with urlopen(request, timeout=30) as response:
        content_type = response.headers.get_content_type()
        if content_type not in {"text/html", "application/xhtml+xml"}:
            raise ValueError(f"Expected HTML, received {content_type}")
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_RESPONSE_BYTES:
            raise ValueError(f"Response exceeds the {MAX_RESPONSE_BYTES} byte safety limit")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError(f"Response exceeds the {MAX_RESPONSE_BYTES} byte safety limit")
        return body.decode(response.headers.get_content_charset() or "utf-8", errors="replace")


def default_config_path() -> Path:
    """The Skill's own config file, next to this script's parent directory."""
    return Path(__file__).resolve().parent.parent / "config.json"


def load_openalex_api_key(config_path: str | None = None) -> str | None:
    """Return the OpenAlex API key, or None when the user has not configured one.

    Precedence is the OPENALEX_API_KEY environment variable, then the config file.
    Raises ValueError when a config file exists but is unusable, so the caller can
    report it instead of silently skipping enrichment.
    """
    env_key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if env_key:
        return env_key
    path = Path(config_path) if config_path else default_config_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    nested = data.get("openalex")
    key = data.get("openalex_api_key") or (nested.get("api_key") if isinstance(nested, dict) else None)
    return key.strip() if isinstance(key, str) and key.strip() else None


def extract_arxiv_id(url: str) -> str | None:
    match = ARXIV_ID_PATTERN.search(url or "")
    return match.group(1) if match else None


def extract_doi(url: str) -> str | None:
    match = DOI_PATTERN.search(url or "")
    return match.group(1).rstrip(").,;") if match else None


def normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").casefold()).strip()


def _openalex_fetch_once(url: str) -> Any:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=30) as response:
        content_type = response.headers.get_content_type()
        if content_type != "application/json":
            raise ValueError(f"Expected JSON from OpenAlex, received {content_type}")
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_RESPONSE_BYTES:
            raise ValueError("OpenAlex response exceeds the 2 MiB safety limit")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("OpenAlex response exceeds the 2 MiB safety limit")
        return json.loads(body.decode(response.headers.get_content_charset() or "utf-8"))


def openalex_get(path: str, params: dict[str, Any], api_key: str) -> Any:
    """One read-only OpenAlex GET, retrying transient transport errors only.

    Connection resets, SSL EOFs, and timeouts are retried up to
    TRANSPORT_MAX_ATTEMPTS - 1 times with exponential backoff, following OpenAlex's
    guidance for flaky connections. HTTP responses (including 4xx/5xx) and malformed
    payloads are surfaced immediately and never retried.
    """
    query = dict(params)
    query["api_key"] = api_key
    url = f"{OPENALEX_BASE}/{path}?" + urlencode(query)
    for attempt in range(TRANSPORT_MAX_ATTEMPTS):
        try:
            return _openalex_fetch_once(url)
        except HTTPError:
            raise
        except (URLError, TimeoutError, OSError) as error:
            if attempt == TRANSPORT_MAX_ATTEMPTS - 1:
                raise
            time.sleep(TRANSPORT_RETRY_BACKOFF_SECONDS * (2 ** attempt))
    raise RuntimeError("OpenAlex request attempts exhausted")


def lookup_openalex_work(paper: dict[str, Any], api_key: str) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve a paper to one OpenAlex work, returning (work, error_message).

    Identifiers are tried in decreasing reliability: an explicit DOI, the exact
    arXiv landing URL, then a title search whose candidates must match the title.
    """
    source_url = str(paper.get("source_url") or "")
    title = str(paper.get("title") or "").strip()
    doi = extract_doi(source_url)
    arxiv_id = extract_arxiv_id(source_url)

    def by_doi() -> dict[str, Any] | None:
        assert doi is not None
        payload = openalex_get(f"works/doi:{quote(doi, safe='/')}", {"select": OPENALEX_SELECT}, api_key)
        return payload if isinstance(payload, dict) and payload.get("id") else None

    def by_arxiv() -> dict[str, Any] | None:
        assert arxiv_id is not None
        landing = "|".join((f"http://arxiv.org/abs/{arxiv_id}", f"https://arxiv.org/abs/{arxiv_id}"))
        payload = openalex_get(
            "works",
            {"filter": f"locations.landing_page_url:{landing}", "select": OPENALEX_SELECT, "per_page": 1},
            api_key,
        )
        results = payload.get("results") if isinstance(payload, dict) else None
        return results[0] if isinstance(results, list) and results and isinstance(results[0], dict) else None

    def by_title() -> dict[str, Any] | None:
        payload = openalex_get("works", {"search": title, "select": OPENALEX_SELECT, "per_page": 5}, api_key)
        results = payload.get("results") if isinstance(payload, dict) else None
        normalized = normalize_title(title)
        for candidate in results or []:
            if isinstance(candidate, dict) and normalize_title(str(candidate.get("title") or "")) == normalized:
                return candidate
        return None

    attempts = [attempt for condition, attempt in ((doi, by_doi), (arxiv_id, by_arxiv), (title, by_title)) if condition]
    responded = False
    last_error: str | None = None
    for attempt in attempts:
        try:
            work = attempt()
        except HTTPError as error:
            # A 404 means "not in OpenAlex", not a retrieval failure.
            if error.code == 404:
                responded = True
            else:
                last_error = str(error)
            continue
        except (URLError, TimeoutError, ValueError, OSError) as error:
            last_error = str(error)
            continue
        responded = True
        if work:
            return work, None
    if attempts and not responded and last_error:
        return None, last_error
    return None, None


def landing_page_urls(work: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    locations = work.get("locations")
    if not isinstance(locations, list):
        return urls
    for location in locations:
        if not isinstance(location, dict):
            continue
        url = location.get("landing_page_url")
        if isinstance(url, str) and url.startswith("http") and url not in urls:
            urls.append(url)
    return urls


def enrich_with_openalex(papers: list[dict[str, Any]], api_key: str) -> list[dict[str, str]]:
    """Add `openalex_url` and a merged `source_urls` array; return per-paper errors.

    `source_url` is left untouched so existing consumers keep working; the new
    `source_urls` array starts with the original link and appends the distinct
    landing pages OpenAlex knows for the same work.
    """
    errors: list[dict[str, str]] = []
    for paper in papers[:MAX_OPENALEX_LOOKUPS]:
        work, error = lookup_openalex_work(paper, api_key)
        if error:
            errors.append({
                "source_collection": "openalex",
                "url": str(paper.get("source_url") or paper.get("papers_cool_url") or ""),
                "error": error,
            })
            continue
        if not work:
            continue
        if work.get("id"):
            paper["openalex_url"] = str(work["id"])
        merged: list[str] = [str(paper["source_url"])] if paper.get("source_url") else []
        for url in landing_page_urls(work):
            if url not in merged:
                merged.append(url)
        if merged:
            paper["source_urls"] = merged
    return errors


def slugify(text: str, max_length: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text or "").casefold()).strip("-")
    return slug[:max_length].rstrip("-") or "papers"


def extract_openalex_id(url: Any) -> str | None:
    match = re.search(r"openalex\.org/(W\d+)", str(url or ""))
    return match.group(1) if match else None


def derive_pdf_topic(args: argparse.Namespace) -> str:
    """A human-readable topic used in the run-folder name."""
    if args.pdf_topic:
        return str(args.pdf_topic)
    if args.mode == "search":
        return str(args.query or "search")
    if args.mode == "related":
        collection, paper_id, _ = args.related_seed
        return f"{collection}-{paper_id}"
    return str(args.value or args.mode)


def unique_run_directory(parent: Path, topic: str) -> Path:
    """`<parent>/<YYYYMMDD-HHMMSS>-<topic-slug>`, suffixed if it already exists."""
    parent.mkdir(parents=True, exist_ok=True)
    base = parent / f"{time.strftime('%Y%m%d-%H%M%S')}-{slugify(topic)}"
    run_dir, counter = base, 2
    while run_dir.exists():
        run_dir = base.with_name(f"{base.name}-{counter}")
        counter += 1
    run_dir.mkdir()
    return run_dir


def unique_paper_directory_name(index: int, paper: dict[str, Any], used: set[str]) -> str:
    """`<NN>-<identifier>-<title-slug>`, guaranteeing a distinct subfolder per paper."""
    identifier = str(paper.get("id") or "").strip() or (extract_openalex_id(paper.get("openalex_url")) or "")
    parts = [f"{index:02d}"]
    if identifier:
        parts.append(slugify(identifier, 30))
    parts.append(slugify(str(paper.get("title") or "paper"), 60))
    name = "-".join(part for part in parts if part)
    if name in used:
        counter = 2
        while f"{name}-{counter}" in used:
            counter += 1
        name = f"{name}-{counter}"
    used.add(name)
    return name


def pdf_candidates_from_url(url: str) -> list[str]:
    """Derive direct PDF URLs from a landing page without fetching the page."""
    candidates: list[str] = []
    if not url.startswith("http"):
        return candidates
    if url.split("?", 1)[0].casefold().rstrip("/").endswith(".pdf"):
        candidates.append(url)
    arxiv_id = extract_arxiv_id(url)
    if arxiv_id:
        candidates.append(f"https://arxiv.org/pdf/{arxiv_id}")
    openreview = re.match(r"https?://openreview\.net/forum\?id=([^&#]+)", url)
    if openreview:
        candidates.append(f"https://openreview.net/pdf?id={openreview.group(1)}")
    acl = re.match(r"https?://aclanthology\.org/([^?#]+?)/?$", url)
    if acl:
        candidates.append(f"https://aclanthology.org/{acl.group(1)}.pdf")
    unique: list[str] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def paper_pdf_sources(paper: dict[str, Any], openalex_key: str | None) -> list[tuple[str, str]]:
    """Ordered (request_url, display_url) PDF candidates: source links, then OpenAlex.

    The API key travels only in the request URL; ``display_url`` never carries it so
    it is safe to store in the output JSON.
    """
    sources: list[tuple[str, str]] = []
    urls: list[str] = []
    if paper.get("source_url"):
        urls.append(str(paper["source_url"]))
    for url in paper.get("source_urls") or []:
        urls.append(str(url))
    for url in urls:
        for candidate in pdf_candidates_from_url(url):
            if all(candidate != request for request, _ in sources):
                sources.append((candidate, candidate))
    openalex_id = extract_openalex_id(paper.get("openalex_url"))
    if openalex_key and openalex_id:
        display = f"{OPENALEX_CONTENT_BASE}/works/{openalex_id}.pdf"
        sources.append((f"{display}?api_key={quote(openalex_key, safe='')}", display))
    return sources


def download_pdf(url: str, destination: Path) -> str | None:
    """Best-effort single-PDF download; returns None on success, else an error string."""
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/pdf"})
    for attempt in range(TRANSPORT_MAX_ATTEMPTS):
        try:
            with urlopen(request, timeout=PDF_TIMEOUT_SECONDS) as response:
                content_type = response.headers.get_content_type()
                body = response.read(MAX_PDF_BYTES + 1)
        except HTTPError as error:
            return f"HTTP {error.code}"
        except (URLError, TimeoutError, OSError) as error:
            if attempt == TRANSPORT_MAX_ATTEMPTS - 1:
                return f"transport error: {error}"
            time.sleep(TRANSPORT_RETRY_BACKOFF_SECONDS * (2 ** attempt))
            continue
        if len(body) > MAX_PDF_BYTES:
            return f"PDF exceeds the {MAX_PDF_BYTES // (1024 * 1024)} MiB safety limit"
        if not body.startswith(b"%PDF"):
            return f"not a PDF (content-type: {content_type})"
        try:
            destination.write_bytes(body)
        except OSError as error:
            return f"could not write PDF: {error}"
        return None
    return "transport error"


def pdf_error(paper: dict[str, Any], message: str) -> dict[str, str]:
    return {
        "source_collection": "pdf",
        "url": str(paper.get("source_url") or paper.get("papers_cool_url") or ""),
        "error": message,
    }


def fetch_pdfs(
    papers: list[dict[str, Any]], args: argparse.Namespace, openalex_key: str | None
) -> tuple[Path | None, list[dict[str, str]]]:
    """Best-effort PDF retrieval into a timestamped run folder.

    Layout: ``<pdf-dir>/<YYYYMMDD-HHMMSS>-<topic>/<NN>-<paper>/paper.pdf``. Each paper
    folder holds exactly one PDF named `paper.pdf`. Failures are reported and never
    abort the run; an empty paper folder (or an entirely empty run folder) is removed.
    """
    errors: list[dict[str, str]] = []
    candidates = papers[:MAX_PDF_DOWNLOADS]
    if not candidates:
        return None, errors
    parent = Path(args.pdf_dir).expanduser() if args.pdf_dir else Path.cwd()
    run_dir = unique_run_directory(parent, derive_pdf_topic(args))
    used_names: set[str] = set()
    downloads = saved = 0
    for index, paper in enumerate(candidates, start=1):
        sources = paper_pdf_sources(paper, openalex_key)
        if not sources:
            errors.append(pdf_error(paper, "no PDF source could be derived"))
            continue
        folder = run_dir / unique_paper_directory_name(index, paper, used_names)
        folder.mkdir()
        target = folder / PDF_FILE_NAME
        failure = "all PDF sources failed"
        for request_url, display_url in sources:
            if downloads:
                time.sleep(PDF_REQUEST_INTERVAL_SECONDS)
            downloads += 1
            failure = download_pdf(request_url, target)
            if failure is None:
                paper["pdf_path"] = str(target.resolve())
                paper["pdf_source_url"] = display_url
                saved += 1
                break
        if failure is not None:
            folder.rmdir()
            errors.append(pdf_error(paper, failure))
    if not saved:
        run_dir.rmdir()
        return None, errors
    return run_dir, errors


class RetrievalSession:
    """Serial, bounded requests for a personal website; failures are never retried."""

    def __init__(self) -> None:
        self.request_count = 0

    def cards(self, url: str) -> list[dict[str, Any]]:
        if self.request_count >= MAX_SESSION_REQUESTS:
            raise ValueError(f"Request budget reached ({MAX_SESSION_REQUESTS}); ask before continuing")
        if self.request_count:
            time.sleep(MIN_REQUEST_INTERVAL_SECONDS)
        self.request_count += 1
        parser = PaperCardParser()
        parser.feed(fetch(url))
        return parser.papers


def apply_preferences(papers: list[dict[str, Any]], terms: list[str]) -> None:
    """Rank locally, so preference keywords are never submitted to the site."""
    if not terms:
        return
    for paper in papers:
        haystack = " ".join(
            str(paper.get(field, "")) for field in ("title", "abstract", "authors", "subjects")
        ).casefold()
        paper["preference_score"] = sum(haystack.count(term) for term in terms)
    papers.sort(key=lambda paper: paper["preference_score"], reverse=True)


def paper_key(paper: dict[str, Any]) -> str:
    return str(paper.get("source_url") or paper.get("papers_cool_url") or paper.get("id") or paper.get("title"))


def deduplicate(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep one record while retaining all first-degree REL provenance."""
    unique: dict[str, dict[str, Any]] = {}
    for paper in papers:
        key = paper_key(paper)
        if key not in unique:
            unique[key] = paper
            continue
        for relation in paper.get("related_from", []):
            # A REL search commonly returns its seed.  The seed remains degree 0.
            if str(unique[key].get("id")) == str(relation.get("seed_id")):
                continue
            if relation not in unique[key].setdefault("related_from", []):
                unique[key]["related_from"].append(relation)
    return list(unique.values())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("arxiv", "venue", "search", "related"))
    parser.add_argument("value", nargs="?", help="Category, venue, query, or REL seed (arxiv/<id> or venue/<id>)")
    parser.add_argument("--branch", choices=("all", "arxiv", "venue"), default="all", help="Search branch (default: all)")
    parser.add_argument("--query", help="Keyword query when mode is search")
    parser.add_argument("--show", type=int, default=10, help="Paper cards requested (default: 10; maximum: 50)")
    parser.add_argument("--skip", type=int, default=0, help="Zero-based paper-card offset")
    parser.add_argument("--date", help="arXiv date in YYYY-MM-DD")
    parser.add_argument("--sort", help="Pass-through site sort value")
    parser.add_argument("--prefer", help="Comma-separated local preference terms; never sent to papers.cool")
    parser.add_argument("--related-top", type=int, default=0, help="Expand first-round papers through [REL] (0–5; default: 0)")
    parser.add_argument("--config", help="Path to a JSON config file holding openalex_api_key (default: <skill>/config.json)")
    parser.add_argument("--fetch-pdf", action="store_true", help="Download each paper's PDF into a timestamped folder (best-effort; only when the user asked for PDFs)")
    parser.add_argument("--pdf-dir", help="Parent directory for the PDF run folder (default: the current directory)")
    parser.add_argument("--pdf-topic", help="Topic slug used in the PDF run folder name (default: derived from the query/category/venue)")
    args = parser.parse_args()
    if args.mode == "search":
        if args.value is not None and args.query is None:
            args.query = args.value
        if not args.query:
            parser.error("search requires a query, e.g. search --query 'large language model'")
    elif args.mode == "related":
        if not args.value:
            parser.error("related requires a papers.cool paper URL or arxiv/<paper-id>")
        try:
            args.related_seed = parse_related_seed(args.value)
        except ValueError as error:
            parser.error(str(error))
    elif not args.value:
        parser.error(f"{args.mode} requires a category expression or venue edition")
    if args.show < 1 or args.show > 50 or args.skip < 0 or args.related_top < 0 or args.related_top > 5:
        parser.error("show must be 1–50, skip must be non-negative, and related-top must be 0–5")
    if args.mode == "related" and args.related_top:
        parser.error("related already performs one REL expansion; omit --related-top")
    return args


def main() -> int:
    # JSON is intended for pipelines; avoid Windows console-codepage loss.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = parse_args()
    targets = [] if args.mode == "related" else build_urls(args)
    papers: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    source_urls: dict[str, str] = {}
    session = RetrievalSession()

    if args.mode == "related":
        collection, seed_id, seed_url = args.related_seed
        source_urls[f"seed:{collection}:{seed_id}"] = seed_url
        try:
            seed_cards = session.cards(seed_url)
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            errors.append({"source_collection": collection, "url": seed_url, "error": str(error)})
            seed_cards = []
        for paper in seed_cards:
            paper["source_collection"] = collection
            paper["relation_degree"] = 0
        papers.extend(seed_cards)
        seeds = seed_cards[:1]
    else:
        for collection, url in targets:
            source_urls[collection] = url
            try:
                fetched_cards = session.cards(url)
            except (HTTPError, URLError, TimeoutError, ValueError) as error:
                errors.append({"source_collection": collection, "url": url, "error": str(error)})
                continue
            for paper in fetched_cards:
                paper["source_collection"] = collection
                paper["relation_degree"] = 0
            papers.extend(fetched_cards)
        seeds = []

    terms = [term.casefold().strip() for term in (args.prefer or "").replace("\n", ",").split(",") if term.strip()]
    apply_preferences(papers, terms)
    if args.mode != "related" and args.related_top:
        seeds = papers[: args.related_top]

    for seed in seeds:
        keywords = str(seed.get("papers_cool_keywords") or "").strip()
        if not keywords:
            errors.append({"source_collection": str(seed.get("source_collection", "")), "url": str(seed.get("papers_cool_url", "")), "error": "REL keywords attribute was absent"})
            continue
        collection = str(seed["source_collection"])
        rel_url = related_search_url(collection, keywords, args.show)
        seed_id = str(seed.get("id") or seed.get("papers_cool_url"))
        source_urls[f"related:{collection}:{seed_id}"] = rel_url
        try:
            related_cards = session.cards(rel_url)
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            errors.append({"source_collection": collection, "url": rel_url, "error": str(error)})
            continue
        relation = {
            "type": "papers_cool_rel_keyword_search",
            "degree": 1,
            "seed_id": seed.get("id"),
            "seed_papers_cool_url": seed.get("papers_cool_url"),
            "keywords": keywords,
        }
        for paper in related_cards:
            paper["source_collection"] = collection
            paper["relation_degree"] = 1
            paper["related_from"] = [relation]
        papers.extend(related_cards)

    papers = deduplicate(papers)
    if not papers:
        print(json.dumps({"sources": source_urls, "errors": errors}, ensure_ascii=False), file=sys.stderr)
        return 1
    apply_preferences(papers, terms)

    # OpenAlex enrichment runs automatically whenever a key is configured; with no key
    # (and no config file) nothing OpenAlex-related happens. The key also powers the
    # OpenAlex content-download fallback used by --fetch-pdf.
    openalex_key: str | None = None
    try:
        openalex_key = load_openalex_api_key(args.config)
    except (OSError, ValueError) as error:
        errors.append({
            "source_collection": "openalex",
            "url": str(args.config or default_config_path()),
            "error": str(error),
        })
    if openalex_key:
        errors.extend(enrich_with_openalex(papers, openalex_key))

    pdf_run_dir: Path | None = None
    if args.fetch_pdf:
        pdf_run_dir, pdf_errors = fetch_pdfs(papers, args, openalex_key)
        errors.extend(pdf_errors)

    result: dict[str, Any] = {"sources": source_urls, "request_count": session.request_count, "count": len(papers), "papers": papers}
    if pdf_run_dir is not None:
        result["pdf_dir"] = str(pdf_run_dir.resolve())
    if terms:
        result["preference_terms"] = terms
    if errors:
        result["errors"] = errors
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
