#!/usr/bin/env python3
"""Fetch public papers.cool list/search pages and normalize their paper cards to JSON.

This uses only documented-by-client, read-only GET routes. It intentionally does
not call Kimi, star, or configuration endpoints.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen


BASE_URL = "https://papers.cool"
USER_AGENT = "papers-cool-search/1.0 (read-only academic metadata retrieval)"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MIN_REQUEST_INTERVAL_SECONDS = 3
MAX_SESSION_REQUESTS = 20


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
    result: dict[str, Any] = {"sources": source_urls, "request_count": session.request_count, "count": len(papers), "papers": papers}
    if terms:
        result["preference_terms"] = terms
    if errors:
        result["errors"] = errors
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
