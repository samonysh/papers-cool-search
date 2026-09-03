# Public retrieval endpoints

`papers.cool` exposes useful public GET routes, discovered from its shipped client JavaScript on 2026-09-03. They return HTML (or Atom XML for feeds), not a supported JSON API. The bundled `scripts/papers_cool_fetch.py` parses their paper cards into JSON.

## Polite-use budget

This is a personal site, and its project history notes anti-scraping measures. Treat these routes as a human-scale research aid, not a bulk-data service:

- Make **one request at a time**; never parallelize category, search, detail, or feed requests.
- Wait **at least three seconds** between requests to `papers.cool`.
- Use a maximum of **20 list/search/detail requests per research session**. A session is one user research task; the default cross-source search consumes two of this budget. A `related` request consumes one seed-detail request plus one search request. When the cap is reached, summarize the data already obtained and ask before starting another batch.
- Request **10 results by default** and at most **50** per page. Prefer a narrower query/category to raising `show` or paginating deeply.
- Do not automatically retry failures, probe URL variants, crawl paper-detail pages, or bulk-download PDFs. A transient failure is one failed request; report it and wait for user direction.

The helper makes one GET per invocation for a single collection. Its default cross-source `search` makes two serial GET requests (arXiv, then Venue), with a fixed three-second gap. It rejects `show > 50`, limits `--related-top` to five seeds, counts all requests in the invocation, and refuses HTML bodies larger than 2 MiB. These safeguards limit a mistaken invocation, while the session-wide request budget is enforced by the Skill workflow.

## Safe, read-only routes

| Use | Route | Parameters |
|---|---|---|
| arXiv category / category expression | `/arxiv/<category-expression>` | `show`, `skip`, `date`, `sort` |
| arXiv keyword search | `/arxiv/search` | `query`, `highlight`, `show`, `skip`, `sort` |
| Venue edition/list | `/venue/<venue-or-edition>` | `show`, `skip`, `sort` |
| Venue keyword search | `/venue/search` | `query`, `highlight`, `show`, `skip`, `sort` |
| paper card used as a REL seed | `/arxiv/<id>` or `/venue/<id>` | `show` only when needed |
| Atom feed for a list | append `/feed` | `query` may be preserved for searches |

`show` defaults to 25 in the site client, but the helper defaults to 10 and permits no more than 50. `skip` is a zero-based offset used for progressive loading. `date` is relevant to arXiv category pages and uses `YYYY-MM-DD`. Search terms are normalized by the site client to sequences of letters/numbers separated by spaces; make no claim that operators, punctuation, quotes, or field syntax are supported.

Useful examples:

```text
https://papers.cool/arxiv/cs.LG?show=10
https://papers.cool/arxiv/cs.AI,cs.CL,cs.CV,cs.LG?show=20
https://papers.cool/arxiv/search?query=reinforcement+learning&highlight=1&show=20
https://papers.cool/venue/ICLR.2025?show=20
https://papers.cool/venue/search?query=large+language+model&show=20
```

The paper cards include their canonical source URL (for example, arXiv or OpenReview), a local paper page, title, authors, abstract, subjects, and—on arXiv cards—a publish time. Parse the external canonical URL as the source record; do not scrape the interactive PDF viewer to obtain metadata.

## One-hop related papers (`[REL]`)

The shipped browser client implements `[REL]` as `openRelatedPapers(paperId)`: it reads the card's `keywords` HTML attribute and opens the relative URL `search?query=<keywords>`. Since the URL is relative, an arXiv card searches `/arxiv/search` and a Venue card searches `/venue/search`.

The helper mirrors that behavior with either of these bounded modes:

```text
python scripts/papers_cool_fetch.py related arxiv/2506.18896 --show 10
python scripts/papers_cool_fetch.py related https://papers.cool/arxiv/2506.18896 --show 10
python scripts/papers_cool_fetch.py search "multimodal agent" --related-top 2 --show 10
```

`related` first retrieves the supplied seed card, then performs exactly one same-collection keyword search. `--related-top` expands at most the selected number of first-round records; its default is `0` and its hard limit is `5`. It never treats related results as new seeds. Output retains initial records with `relation_degree: 0`; related results have `relation_degree: 1` and a `related_from` object containing the seed link and keywords. Duplicate records are collapsed while preserving all REL provenance.

This is keyword-based relevance discovery. It must not be described as a citation relationship, paper-reference graph, or semantic-similarity result.

## Normalized JSON and preferences

The helper outputs one JSON object with `sources`, `request_count`, `count`, `papers`, and an optional `errors` array. Each paper record includes `title`, `abstract`, `papers_cool_url`, and `source_url`, plus the source collection (`arxiv` or `venue`) and any metadata visible in its card. This lets a caller convert the output to CSV, Markdown, BibTeX-enrichment inputs, or task-specific data without losing either link.

The site browser's Prefer setting is stored in the reader's browser. The helper instead accepts `--prefer "term1,term2"`, scores term occurrences in title/abstract/authors/subjects, and sorts descending by `preference_score`. Preference ranking is local and transparent; it does not send preference terms to the site as a server-side sort query.

## Do not call for retrieval

The same client code exposes state-changing or potentially costly endpoints. Do not use them as part of a search Skill:

- `POST /arxiv/star` and `POST /venue/star` alter popularity counters;
- `POST /arxiv/kimi` and `POST /venue/kimi` trigger a generated interpretation, while `.../progress` polls it;
- `POST /config` submits user configuration.

These routes are implementation details, may require browser state or change without notice, and are outside a read-only paper-discovery workflow.
