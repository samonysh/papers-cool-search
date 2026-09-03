#!/usr/bin/env python3
"""Fetch public papers.cool list/search pages and normalize their paper cards to JSON.

This uses only documented-by-client, read-only GET routes. It intentionally does
not call Kimi, star, or configuration endpoints.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import time
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://papers.cool"
USER_AGENT = "papers-cool-search/1.0 (read-only academic metadata retrieval)"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


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
            self.current = {"id": attrs.get("id"), "authors": [], "subjects": []}
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("arxiv", "venue", "search"))
    parser.add_argument("value", nargs="?", help="Category expression or venue edition")
    parser.add_argument("--branch", choices=("all", "arxiv", "venue"), default="all", help="Search branch (default: all)")
    parser.add_argument("--query", help="Keyword query when mode is search")
    parser.add_argument("--show", type=int, default=10, help="Paper cards requested (default: 10; maximum: 50)")
    parser.add_argument("--skip", type=int, default=0, help="Zero-based paper-card offset")
    parser.add_argument("--date", help="arXiv date in YYYY-MM-DD")
    parser.add_argument("--sort", help="Pass-through site sort value")
    parser.add_argument("--prefer", help="Comma-separated local preference terms; never sent to papers.cool")
    args = parser.parse_args()
    if args.mode == "search":
        if args.value is not None and args.query is None:
            args.query = args.value
        if not args.query:
            parser.error("search requires a query, e.g. search --query 'large language model'")
    elif not args.value:
        parser.error(f"{args.mode} requires a category expression or venue edition")
    if args.show < 1 or args.show > 50 or args.skip < 0:
        parser.error("show must be 1–50 and skip must be non-negative")
    return args


def main() -> int:
    # JSON is intended for pipelines; avoid Windows console-codepage loss.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = parse_args()
    targets = build_urls(args)
    papers: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    source_urls: dict[str, str] = {}
    for index, (collection, url) in enumerate(targets):
        if index:
            time.sleep(3)
        parser = PaperCardParser()
        source_urls[collection] = url
        try:
            parser.feed(fetch(url))
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            errors.append({"source_collection": collection, "url": url, "error": str(error)})
            continue
        for paper in parser.papers:
            paper["source_collection"] = collection
        papers.extend(parser.papers)
    if not papers:
        print(json.dumps({"sources": source_urls, "errors": errors}, ensure_ascii=False), file=sys.stderr)
        return 1
    terms = [term.casefold().strip() for term in (args.prefer or "").replace("\n", ",").split(",") if term.strip()]
    apply_preferences(papers, terms)
    result: dict[str, Any] = {"sources": source_urls, "count": len(papers), "papers": papers}
    if terms:
        result["preference_terms"] = terms
    if errors:
        result["errors"] = errors
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


