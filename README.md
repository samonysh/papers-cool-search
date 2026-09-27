# Papers Cool Search

[![skills.sh](https://skills.sh/b/samonysh/papers-cool-search)](https://skills.sh/samonysh/papers-cool-search)

An agent skill for discovering research papers through [papers.cool](https://papers.cool). It searches both the arXiv and Venue collections, normalizes cards into reusable JSON, preserves the papers.cool and original-source links, and applies conservative request limits for the personal website.

[中文文档](README.zh-CN.md)

## What it does

- Searches arXiv and the curated Venue collection in one command.
- Maps common AI/ML topics to arXiv categories, including category unions and exclusions.
- Returns JSON records with `title`, `abstract`, `papers_cool_url`, and `source_url`, plus author, subject, publication, and collection metadata when available.
- Enriches each record through the [OpenAlex API](https://help.openalex.org/api/) whenever an OpenAlex key is configured — adding `openalex_url` and a merged `source_urls` array. Without a key the step is skipped and no OpenAlex request is made.
- Downloads each paper's PDF on request (`--fetch-pdf`): it tries a direct PDF from the paper's source links first, falls back to the OpenAlex content download, and stores exactly one `paper.pdf` per paper under a timestamped `<time>-<topic>` folder. Best-effort—papers whose PDF is unavailable are reported, not fatal.
- Fetches **Chinese-translated PDFs** on request, for arXiv papers only, via [hjfy.top](https://hjfy.top): the built-in browser handles login and starting the translation, then the helper waits and downloads each result as `paper.zh.pdf` in the paper's folder.
- Supports transparent local preference ranking through `--prefer`; preference terms are never sent to papers.cool.
- Supports an explicit, one-hop `[REL]` expansion from a supplied paper or up to five first-round results, with seed and query provenance in JSON.
- Distinguishes preprints from venue papers and preserves both links when a work has multiple versions.

## Install

### Codex

Install the repository as a project skill with the Skills CLI:

```bash
npx skills add samonysh/papers-cool-search --skill papers-cool-search --agent codex
```

Codex also recognizes a `SKILL.md` placed directly in `~/.codex/skills/papers-cool-search/`.

### Other supported agents

The same repository follows the portable `SKILL.md` convention used by [skills.sh](https://www.skills.sh/docs). Select a target agent with `--agent`:

```bash
npx skills add samonysh/papers-cool-search --skill papers-cool-search --agent claude-code
```

## Programmatic retrieval

The helper uses public HTML routes exposed by papers.cool and emits JSON. It is a read-only helper; it never calls star, Kimi, configuration, or PDF-download endpoints.

```bash
# arXiv category
python scripts/papers_cool_fetch.py arxiv cs.LG --show 10

# Default: query both arXiv and Venue
python scripts/papers_cool_fetch.py search "retrieval augmented generation" --show 10

# A specified conference edition
python scripts/papers_cool_fetch.py venue NeurIPS.2025 --show 10

# Local, reproducible preference ranking
python scripts/papers_cool_fetch.py search "multimodal agent" --prefer "agent,planning,vision" --show 10

# One-hop related papers for a supplied seed
python scripts/papers_cool_fetch.py related arxiv/2506.18896 --show 10

# Expand only the top two first-round candidates (disabled unless requested)
python scripts/papers_cool_fetch.py search "multimodal agent" --related-top 2 --show 10

# Download each paper's PDF into a timestamped folder (only when asked)
python scripts/papers_cool_fetch.py search "retrieval augmented generation" --show 10 --fetch-pdf
```

Example output shape:

```json
{
  "sources": {
    "arxiv": "https://papers.cool/arxiv/search?...",
    "venue": "https://papers.cool/venue/search?..."
  },
  "request_count": 2,
  "count": 2,
  "papers": [
    {
      "title": "Example paper",
      "abstract": "...",
      "papers_cool_url": "https://papers.cool/arxiv/2401.00001",
      "source_url": "https://arxiv.org/abs/2401.00001",
      "source_collection": "arxiv",
      "relation_degree": 0,
      "openalex_url": "https://openalex.org/W2626778328",
      "source_urls": [
        "https://arxiv.org/abs/2401.00001",
        "https://doi.org/10.48550/arxiv.2401.00001"
      ]
    }
  ]
}
```

### OpenAlex enrichment (automatic with a key)

This step is not opt-in and has no flag: whenever an OpenAlex key is configured, each record also gets `openalex_url` and a `source_urls` array. `source_url` is never changed; `source_urls` starts with it and appends the distinct landing pages OpenAlex knows for the same work. The lookup tries a DOI from `source_url`, then the exact arXiv landing URL, then a title search that must match the title exactly. Enrichment is capped at 50 lookups per run; transient transport failures (connection reset, SSL EOF, timeout) are retried up to two times with backoff, while HTTP and data errors are not. Without a key, the whole step is skipped.

Configure the key either as an environment variable or in `config.json` at the repo root (gitignored); pass `--config <path>` to point elsewhere:

```json
{
  "openalex_api_key": "your-key-here"
}
```

```bash
# Environment variable
OPENALEX_API_KEY=your-key python scripts/papers_cool_fetch.py arxiv cs.LG --show 10

# Or a config file
python scripts/papers_cool_fetch.py arxiv cs.LG --show 10 --config config.json
```

Get a free key at [openalex.org/settings/api](https://openalex.org/settings/api).

### Downloading PDFs (optional)

Add `--fetch-pdf` only when you actually want the papers' PDFs. The helper then writes one timestamped run folder:

```text
<pdf-dir>/<YYYYMMDD-HHMMSS>-<topic>/<NN>-<identifier>-<title-slug>/paper.pdf
```

- the run folder is `<time>-<topic>`, where the topic comes from `--pdf-topic` or the query/category/venue/seed;
- each paper gets its own folder (`<NN>-<identifier>-<title-slug>`), so papers are never mixed;
- the file is always named `paper.pdf`, so every folder holds exactly one original PDF.

PDFs are resolved without scraping landing pages: a direct PDF is derived from `source_url`/`source_urls` first (arXiv `abs`/`pdf` → `https://arxiv.org/pdf/<id>`, OpenReview `forum?id=` → `pdf?id=`, ACL Anthology → `.pdf`, or an existing `*.pdf` link); if that fails, the [OpenAlex content download](https://help.openalex.org/api/llm-quick-reference/) (`https://content.openalex.org/works/<W-id>.pdf?api_key=...`) is used, which needs the configured key and costs about $0.01 per PDF.

On success a record gains `pdf_path` and `pdf_source_url`, and the output gains `pdf_dir`; the API key is never written into the result. The step is best-effort: failures are collected in `errors` (`source_collection: "pdf"`) and the empty folder is removed, and a paper without any usable source is simply skipped. Limits: 50 PDFs per run, 50 MiB per file, one-second spacing, and the same bounded retry as the API lookups.

```bash
# Default parent directory is the current one; override with --pdf-dir
python scripts/papers_cool_fetch.py venue NeurIPS.2025 --show 20 --fetch-pdf --pdf-dir ./downloads --pdf-topic neurips-2025
```

### Chinese-translated PDFs (optional)

Available **only for arXiv papers**, and only when you ask for a Chinese PDF. Translations come from [hjfy.top](https://hjfy.top) and **require login**, so the browser does the part that needs a session, while the helper does the waiting and the download. Use the **built-in browser by default** (an external browser only when the built-in one is unavailable):

```bash
# 1. Fetch the papers and save the JSON, then create the plan (also creates the folders)
python scripts/papers_cool_fetch.py arxiv cs.LG --show 5 --fetch-pdf > papers.json
python scripts/hjfy_zh_pdf.py plan --papers papers.json --out zh_plan.json

# 2. Built-in browser: make sure you are logged in at https://hjfy.top (if not, the agent hands
#    the browser over so you can log in), then open every "hjfy_url" from zh_plan.json
#    (each tab starts/queues that paper's translation; this typically takes 1-10 minutes)

# 3. Wait for completion and place each result as <paper folder>/paper.zh.pdf
python scripts/hjfy_zh_pdf.py fetch --plan zh_plan.json
```

Each finished paper gets `paper.zh.pdf` next to its original `paper.pdf`. `fetch` prints the `downloaded` list and any `errors` (`需要登录…` when the browser session is missing, `翻译未成功…` for a failed job, `等待超时…` when it simply is not finished yet—just re-run `fetch`). It waits up to 10 minutes by default (`--wait-seconds`, `--interval`) and is best-effort. See [references/zh-pdf.md](references/zh-pdf.md) for the verified hjfy.top mechanics.

### Actual `[REL]` run

The following is a selected-field snapshot from an actual run on 2026-09-03 (results can change as the site index changes):

```bash
python scripts/papers_cool_fetch.py related arxiv/2506.18896 --show 3
```

```json
{
  "sources": {
    "seed:arxiv:2506.18896": "https://papers.cool/arxiv/2506.18896",
    "related:arxiv:2506.18896": "https://papers.cool/arxiv/search?query=prm%2Creasonflux%2Cprms%2Ctrajectory%2Creward%2Creasoning%2Cthought%2Cmath500%2Caime%2Cgpqa&highlight=1&show=3"
  },
  "request_count": 2,
  "count": 3,
  "papers": [
    {
      "id": "2506.18896",
      "title": "ReasonFlux-PRM: Trajectory-Aware PRMs for Long Chain-of-Thought Reasoning in LLMs",
      "papers_cool_url": "https://papers.cool/arxiv/2506.18896",
      "source_url": "https://arxiv.org/abs/2506.18896",
      "relation_degree": 0
    },
    {
      "id": "2502.06772",
      "title": "ReasonFlux: Hierarchical LLM Reasoning via Scaling Thought Templates",
      "papers_cool_url": "https://papers.cool/arxiv/2502.06772",
      "source_url": "https://arxiv.org/abs/2502.06772",
      "relation_degree": 1,
      "related_from": [{
        "type": "papers_cool_rel_keyword_search",
        "seed_id": "2506.18896",
        "keywords": "prm,reasonflux,prms,trajectory,reward,reasoning,thought,math500,aime,gpqa"
      }]
    }
  ]
}
```

## Responsible use

papers.cool is a personal website, not a bulk-data API. This project uses one request at a time, waits three seconds between every request, limits an invocation to 20 requests, caps each result page at 50 cards and REL expansion at five seeds, caps HTML responses at 2 MiB, and never retries automatically. See [the endpoint reference](references/public-endpoints.md) for the complete policy.

## About `[REL]`

The site’s `[REL]` control reads a paper card’s keyword attribute and opens a same-collection search using those keywords. This project mirrors that behavior, returns the seed URL and query in `related_from`, and never expands a related result again. It is keyword-based relevance discovery, not a citation graph or an embedding-based similarity claim.

## Project layout

```text
SKILL.md                         # Portable agent instructions
agents/openai.yaml               # Codex UI metadata
scripts/papers_cool_fetch.py     # Read-only HTML-to-JSON helper
scripts/hjfy_zh_pdf.py           # Plan/poll/download hjfy.top Chinese PDFs
references/source-guide.md       # Collection coverage and topic/category routing
references/public-endpoints.md   # Public routes, JSON schema, and request policy
references/zh-pdf.md             # hjfy.top Chinese-translation mechanics
config.json                      # Optional, gitignored: OpenAlex API key
```

## Citation and acknowledgement

This independent integration depends on the paper-discovery service provided by [Cool Papers / papers.cool](https://papers.cool/) and the product documentation maintained in the [bojone/papers.cool](https://github.com/bojone/papers.cool) repository. Thank you to its maintainer and contributors for making the site and its public research-discovery routes available.

Two optional add-ons build on further third-party services, gratefully acknowledged:

- [OpenAlex](https://openalex.org/) — the open scholarly catalog (its data is CC0) behind the `openalex_url`/`source_urls` enrichment, queried through its read-only [API](https://help.openalex.org/api/).
- [hjfy.top](https://hjfy.top) (幻觉翻译) — the translation service behind the optional Chinese PDFs. This project only drives a browser/HTTP workflow against it; the service, its login requirement, and its terms are controlled by its maintainers.

If this skill or data obtained through papers.cool contributes materially to a publication, report, or software artifact, cite the service and preserve the original paper URLs returned in `source_url`:

```bibtex
@misc{paperscool,
  author       = {bojone},
  title        = {Cool Papers: Immersive Paper Discovery},
  howpublished = {\url{https://papers.cool/}},
  note         = {Accessed 2026-09-03}
}
```

If OpenAlex enrichment contributed to your dataset, please cite OpenAlex as well:

```bibtex
@article{priem2022openalex,
  title   = {OpenAlex: A fully-open index of scholarly works, authors, venues, institutions, and concepts},
  author  = {Priem, Jason and Piwowar, Heather and Orr, Richard},
  journal = {arXiv preprint arXiv:2205.01833},
  year    = {2022}
}
```

## Notes

papers.cool's Venue collection is curated and may have gaps. The helper reports the original canonical URL from every card, but publication status, DOI, and PDF version should be verified at that original source when precision matters. This project is an independent integration: it is not affiliated with papers.cool, OpenAlex, or hjfy.top, and does not imply endorsement by their maintainers.

## License

[MIT](LICENSE)
