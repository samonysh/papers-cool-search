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

## Automatic OpenAlex enrichment

When an OpenAlex API key is configured, the helper automatically resolves each paper to its OpenAlex work, records that work's URL, and merges the work's other landing pages into the record. With no key configured this step is skipped entirely and no OpenAlex request is made. The lookups use the public read-only API described at [help.openalex.org/api](https://help.openalex.org/api/).

**Configuration.** The key is read from the `OPENALEX_API_KEY` environment variable first, then from the Skill's own `config.json` (gitignored), overridable with `--config <path>`:

```json
{
  "openalex_api_key": "your-key-here"
}
```

A nested `{"openalex": {"api_key": "..."}}` object is also accepted. If a config file exists but cannot be parsed, the helper reports it in `errors` instead of silently continuing.

**Lookup order.** Identifiers are tried from most to least reliable, and the first hit wins:

1. a DOI found in `source_url` → the `works/doi:<doi>` singleton;
2. an arXiv ID found in `source_url` → `works?filter=locations.landing_page_url:...` for the exact `http://`/`https://` arXiv landing URL;
3. otherwise a `works?search=<title>` request whose candidates must match the normalized title exactly.

A `404` from a singleton lookup means "not in OpenAlex" and is not an error; genuine retrieval failures for a paper are appended to `errors` with `source_collection: "openalex"`.

**Added fields.** `source_url` is left untouched for backward compatibility. On a match the record gains:

- `openalex_url` — the OpenAlex web URL, e.g. `https://openalex.org/W2626778328`;
- `source_urls` — a de-duplicated array that starts with the original `source_url` and appends every distinct `landing_page_url` OpenAlex knows for the same work (preprint server, DOI, repository, publisher, …).

**Budget.** Enrichment is bounded to 50 paper lookups per invocation and rejects responses larger than 2 MiB. Following OpenAlex's own guidance for flaky connections, a *transport-layer* failure (connection reset, SSL EOF, timeout) is retried up to two times with exponential backoff; HTTP responses (including 4xx/5xx) and malformed payloads are never retried. This budget is separate from the papers.cool request cap above.

## Optional PDF retrieval (`--fetch-pdf`)

PDF download is **opt-in**: it runs only with `--fetch-pdf`, which the Skill uses only when the user explicitly asks to download or save the papers' PDFs. It is best-effort—some papers cannot be retrieved, and a failure never aborts the run.

Everything is written under one timestamped run folder:

```text
<pdf-dir>/<YYYYMMDD-HHMMSS>-<topic-slug>/<NN>-<identifier>-<title-slug>/paper.pdf
```

- **Run folder** — `<time>-<topic>`, where the topic comes from `--pdf-topic` or, by default, the query/category/venue/seed. A numeric suffix is appended if the name already exists.
- **Paper folder** — a zero-padded index, the paper's identifier when known, and a slug of its title, so every paper has a distinct folder.
- **File name** — always `paper.pdf`, so the layout is uniform and each folder holds exactly one original PDF.

Sources are tried in order and the first success wins:

1. a direct PDF derived from `source_url`/`source_urls` **without fetching the landing page** — an arXiv `abs`/`pdf` URL → `https://arxiv.org/pdf/<id>`, an OpenReview `forum?id=` → `pdf?id=`, an ACL Anthology page → `.pdf`, or an existing `*.pdf` link;
2. otherwise the OpenAlex content download, `https://content.openalex.org/works/<W-id>.pdf?api_key=<key>`, which needs the configured key and costs about $0.01 per PDF.

Each record gains `pdf_path` (the saved file) and `pdf_source_url` (the source that worked; the API key is never written into it), and the top-level output gains `pdf_dir`. Failures are appended to `errors` with `source_collection: "pdf"`, and the paper's now-empty folder is removed; if nothing was saved, the run folder is removed too.

Limits: at most 50 PDFs per invocation and 50 MiB per file, a one-second gap between downloads, and the same bounded transport retry as the enrichment calls. HTTP responses (for example, a 404 when OpenAlex has no cached PDF) and non-PDF bodies are recorded as failures without retrying.

## Do not call for retrieval

The same client code exposes state-changing or potentially costly endpoints. Do not use them as part of a search Skill:

- `POST /arxiv/star` and `POST /venue/star` alter popularity counters;
- `POST /arxiv/kimi` and `POST /venue/kimi` trigger a generated interpretation, while `.../progress` polls it;
- `POST /config` submits user configuration.

These routes are implementation details, may require browser state or change without notice, and are outside a read-only paper-discovery workflow.
