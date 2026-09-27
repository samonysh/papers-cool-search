#!/usr/bin/env python3
"""Retrieve Chinese-translated arXiv PDFs from hjfy.top (幻觉翻译).

Use this only when the user explicitly asks for Chinese PDFs, and only for
papers that have an arXiv ID. Login and triggering the translation happen in a
browser: see references/zh-pdf.md. This helper covers the deterministic rest —
it plans the target files, polls hjfy.top for completion, downloads the signed
Chinese PDF, and places it as `paper.zh.pdf` inside each paper's folder.

Typical flow:

    python scripts/papers_cool_fetch.py arxiv cs.LG --show 5 --fetch-pdf > papers.json
    python scripts/hjfy_zh_pdf.py plan  --papers papers.json --out zh_plan.json
    # ... browser: log in to https://hjfy.top and open each hjfy_url ...
    python scripts/hjfy_zh_pdf.py fetch --plan zh_plan.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
import papers_cool_fetch as base  # noqa: E402


HJFY_BASE = "https://hjfy.top"
DEFAULT_TOPIC = "arxiv-zh"
DEFAULT_WAIT_SECONDS = 600
POLL_INTERVAL_SECONDS = 15
REQUEST_GAP_SECONDS = 1
HTTP_TIMEOUT_SECONDS = 60
ZH_PDF_FILE_NAME = "paper.zh.pdf"
PENDING_STATUSES = {"", "init", "start", "processing"}
FAILED_STATUSES = {"failed", "fault", "error"}


def hjfy_get_json(path: str) -> Any:
    """One bounded, read-only GET against hjfy.top; failures are never retried."""
    request = Request(
        f"{HJFY_BASE}{path}",
        headers={"User-Agent": base.USER_AGENT, "Accept": "application/json"},
    )
    with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        body = response.read(base.MAX_RESPONSE_BYTES + 1)
        if len(body) > base.MAX_RESPONSE_BYTES:
            raise ValueError("hjfy.top response exceeds the 2 MiB safety limit")
        return json.loads(body.decode("utf-8"))


def paper_arxiv_id(paper: dict[str, Any]) -> str | None:
    """The paper's arXiv ID, or None when it is not an arXiv paper."""
    urls = [paper.get("source_url"), *(paper.get("source_urls") or [])]
    for url in urls:
        arxiv_id = base.extract_arxiv_id(str(url or ""))
        if arxiv_id:
            return arxiv_id
    return base.extract_arxiv_id(f"https://arxiv.org/abs/{str(paper.get('id') or '').strip()}")


def load_papers(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("papers"), list):
        raise ValueError(f"{path} is not output from papers_cool_fetch.py")
    return data


def build_plan(
    document: dict[str, Any], pdf_dir: str | None, pdf_topic: str | None
) -> dict[str, Any]:
    """Target paths for each arXiv paper, reusing the fetch helper's folder layout."""
    papers = document.get("papers") or []
    run_dir: Path | None = None
    for paper in papers:
        if paper.get("pdf_path"):
            run_dir = Path(str(paper["pdf_path"])).resolve().parent.parent
            break
    if run_dir is None:
        parent = Path(pdf_dir).expanduser() if pdf_dir else Path.cwd()
        run_dir = base.unique_run_directory(parent, pdf_topic or DEFAULT_TOPIC)

    used: set[str] = set()
    for paper in papers:
        if paper.get("pdf_path"):
            used.add(Path(str(paper["pdf_path"])).resolve().parent.name)

    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, paper in enumerate(papers, start=1):
        arxiv_id = paper_arxiv_id(paper)
        if not arxiv_id or arxiv_id in seen:
            continue
        seen.add(arxiv_id)
        if paper.get("pdf_path"):
            folder = Path(str(paper["pdf_path"])).resolve().parent
        else:
            folder = run_dir / base.unique_paper_directory_name(index, paper, used)
        folder.mkdir(parents=True, exist_ok=True)
        items.append({
            "arxiv_id": arxiv_id,
            "title": str(paper.get("title") or ""),
            "hjfy_url": f"{HJFY_BASE}/arxiv/{arxiv_id}",
            "target_path": str(folder / ZH_PDF_FILE_NAME),
        })
    return {"run_dir": str(run_dir), "items": items}


def hjfy_status(arxiv_id: str) -> str | None:
    """Return 'login' when login is required, else the raw status, or None on error."""
    try:
        payload = hjfy_get_json(f"/api/arxivStatus/{arxiv_id}")
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("status") == 101:
        return "login"
    data = payload.get("data")
    return str(data.get("status") or "") if isinstance(data, dict) else None


def hjfy_files(arxiv_id: str) -> dict[str, Any] | None:
    """The paper's file record (with the signed `zhCN` URL) once translation is done."""
    try:
        payload = hjfy_get_json(f"/api/arxivFiles/{arxiv_id}")
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else None


def zh_error(item: dict[str, str], message: str) -> dict[str, str]:
    return {"source_collection": "zh_pdf", "arxiv_id": item["arxiv_id"], "url": item["hjfy_url"], "error": message}


def fetch_zh_pdfs(
    plan: dict[str, Any], wait_seconds: int, interval: int, force: bool
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Poll hjfy.top and download each pending `zhCN` PDF; never raises."""
    downloaded: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    pending: dict[str, dict[str, str]] = {}
    for item in plan.get("items", []):
        target = Path(item["target_path"])
        if target.exists() and not force:
            downloaded.append({"arxiv_id": item["arxiv_id"], "target_path": str(target)})
            continue
        pending[item["arxiv_id"]] = item
    if not pending:
        return downloaded, errors

    deadline = time.monotonic() + max(wait_seconds, 0)
    requests_made = 0
    while pending:
        for arxiv_id, item in list(pending.items()):
            if requests_made:
                time.sleep(REQUEST_GAP_SECONDS)
            requests_made += 1
            status = hjfy_status(arxiv_id)
            if status == "login":
                errors.append(zh_error(item, "需要登录：请先在浏览器登录 hjfy.top，并打开该论文页发起翻译"))
                del pending[arxiv_id]
                continue
            if status in FAILED_STATUSES:
                errors.append(zh_error(item, f"翻译未成功（status={status}）"))
                del pending[arxiv_id]
                continue
            files = hjfy_files(arxiv_id)
            zh_cn = str(files.get("zhCN") or "") if files else ""
            if not zh_cn:
                continue  # still queued or translating
            target = Path(item["target_path"])
            failure = base.download_pdf(zh_cn, target)
            if failure is None:
                downloaded.append({"arxiv_id": arxiv_id, "target_path": str(target)})
            else:
                errors.append(zh_error(item, failure))
            del pending[arxiv_id]
        if not pending:
            break
        if time.monotonic() >= deadline:
            for item in pending.values():
                errors.append(zh_error(item, "等待超时，翻译可能仍在进行；稍后重跑 fetch 即可"))
            break
        time.sleep(interval)
    return downloaded, errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan = subparsers.add_parser("plan", help="Resolve eligible arXiv papers and their target files")
    plan.add_argument("--papers", required=True, help="JSON output saved from papers_cool_fetch.py")
    plan.add_argument("--pdf-dir", help="Parent directory when no run folder exists yet (default: current directory)")
    plan.add_argument("--pdf-topic", help=f"Topic slug when a run folder must be created (default: {DEFAULT_TOPIC})")
    plan.add_argument("--out", help="Write the plan to this file in addition to stdout")

    fetch = subparsers.add_parser("fetch", help="Poll hjfy.top and download the Chinese PDFs")
    source = fetch.add_mutually_exclusive_group(required=True)
    source.add_argument("--plan", help="Plan file written by the `plan` command")
    source.add_argument("--papers", help="Papers JSON; builds the plan inline when no plan file exists")
    fetch.add_argument("--pdf-dir", help="Only with --papers: parent directory for a new run folder")
    fetch.add_argument("--pdf-topic", help="Only with --papers: topic slug for a new run folder")
    fetch.add_argument("--wait-seconds", type=int, default=DEFAULT_WAIT_SECONDS, help=f"How long to wait for translations (default: {DEFAULT_WAIT_SECONDS})")
    fetch.add_argument("--interval", type=int, default=POLL_INTERVAL_SECONDS, help=f"Seconds between polling rounds (default: {POLL_INTERVAL_SECONDS})")
    fetch.add_argument("--force", action="store_true", help="Re-download even when paper.zh.pdf already exists")
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    args = parse_args()
    try:
        if args.command == "plan":
            plan = build_plan(load_papers(Path(args.papers)), args.pdf_dir, args.pdf_topic)
            if args.out:
                Path(args.out).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            return 0
        if args.plan:
            plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        else:
            plan = build_plan(load_papers(Path(args.papers)), args.pdf_dir, args.pdf_topic)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"errors": [{"source_collection": "zh_pdf", "error": str(error)}]}, ensure_ascii=False), file=sys.stderr)
        return 1

    downloaded, errors = fetch_zh_pdfs(plan, args.wait_seconds, args.interval, args.force)
    result: dict[str, Any] = {
        "run_dir": plan.get("run_dir"),
        "downloaded": downloaded,
        "count": len(downloaded),
    }
    if errors:
        result["errors"] = errors
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if downloaded else 1


if __name__ == "__main__":
    raise SystemExit(main())
