# Papers Cool Search

[![skills.sh](https://skills.sh/b/samonysh/papers-cool-search)](https://skills.sh/samonysh/papers-cool-search)

An agent skill for discovering research papers through [papers.cool](https://papers.cool). It searches both the arXiv and Venue collections, normalizes cards into reusable JSON, preserves the papers.cool and original-source links, and applies conservative request limits for the personal website.

[中文文档](README.zh-CN.md)

## What it does

- Searches arXiv and the curated Venue collection in one command.
- Maps common AI/ML topics to arXiv categories, including category unions and exclusions.
- Returns JSON records with `title`, `abstract`, `papers_cool_url`, and `source_url`, plus author, subject, publication, and collection metadata when available.
- Supports transparent local preference ranking through `--prefer`; preference terms are never sent to papers.cool.
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
```

Example output shape:

```json
{
  "sources": {
    "arxiv": "https://papers.cool/arxiv/search?...",
    "venue": "https://papers.cool/venue/search?..."
  },
  "count": 2,
  "papers": [
    {
      "title": "Example paper",
      "abstract": "...",
      "papers_cool_url": "https://papers.cool/arxiv/2401.00001",
      "source_url": "https://arxiv.org/abs/2401.00001",
      "source_collection": "arxiv"
    }
  ]
}
```

## Responsible use

papers.cool is a personal website, not a bulk-data API. This project uses one request at a time, waits three seconds between the two requests of a cross-source search, limits a session to 20 list/search requests, caps each result page at 50 cards, caps HTML responses at 2 MiB, and never retries automatically. See [the endpoint reference](references/public-endpoints.md) for the complete policy.

## Project layout

```text
SKILL.md                         # Portable agent instructions
agents/openai.yaml               # Codex UI metadata
scripts/papers_cool_fetch.py     # Read-only HTML-to-JSON helper
references/source-guide.md       # Collection coverage and topic/category routing
references/public-endpoints.md   # Public routes, JSON schema, and request policy
```

## Citation and acknowledgement

This independent integration depends on the paper-discovery service provided by [Cool Papers / papers.cool](https://papers.cool/) and the product documentation maintained in the [bojone/papers.cool](https://github.com/bojone/papers.cool) repository. Thank you to its maintainer and contributors for making the site and its public research-discovery routes available.

If this skill or data obtained through papers.cool contributes materially to a publication, report, or software artifact, cite the service and preserve the original paper URLs returned in `source_url`:

```bibtex
@misc{paperscool,
  author       = {bojone},
  title        = {Cool Papers: Immersive Paper Discovery},
  howpublished = {\url{https://papers.cool/}},
  note         = {Accessed 2026-09-03}
}
```

## Notes

papers.cool's Venue collection is curated and may have gaps. The helper reports the original canonical URL from every card, but publication status, DOI, and PDF version should be verified at that original source when precision matters. This project is an independent integration, is not affiliated with papers.cool, and does not imply endorsement by its maintainer.

## License

[MIT](LICENSE)
