---
name: papers-cool-search
description: Discover and summarize papers for a research topic through papers.cool's arXiv categories, onsite index, and curated top-conference collections. Use when the user wants a current topic-focused paper list from papers.cool; do not use for broad multi-database scholarly searches or bibliometric analysis.
---

# Papers Cool Search

Use [papers.cool](https://papers.cool) as the discovery layer for a focused topic, then report the paper metadata and direct canonical links it exposes. It is strongest for fresh arXiv browsing and a selected set of AI/CS venues—not a comprehensive substitute for Crossref, Semantic Scholar, or a citation index.

For reliable programmatic retrieval, use the bundled read-only helper. It calls the site's public HTML endpoints and emits normalized JSON; it does not depend on browser interaction:

```powershell
python scripts/papers_cool_fetch.py arxiv cs.LG --show 10
python scripts/papers_cool_fetch.py search "retrieval augmented generation" --show 10
python scripts/papers_cool_fetch.py venue NeurIPS.2025 --show 20
python scripts/papers_cool_fetch.py search "multimodal agent" --prefer "agent,planning,vision" --show 10
```

Read [references/public-endpoints.md](references/public-endpoints.md) before adding a new retrieval mode or calling an endpoint directly. The endpoints are public web routes rather than a documented JSON API. Follow its request budget: one request at a time, wait at least three seconds between requests, cap a research session at 20 list/search requests, and do not retry failures automatically. Stop at the cap and ask the user whether to continue.

## Choose the discovery route

Clarify only if it materially changes the result. Otherwise infer the scope from the topic and state the assumption.

- For a current CS/AI/ML topic, use **both** collections: start with the most relevant arXiv category page, then run the same topic as a keyword search over the Venue collection. Map the topic to categories using [references/source-guide.md](references/source-guide.md). For keyword-first requests, `search` queries both arXiv and Venue by default.
- To cover more than one category, use the category-union URL: `https://papers.cool/arxiv/cs.AI,cs.CL,cs.CV,cs.LG`. The page may contain duplicates; deduplicate them by arXiv ID before reporting.
- To exclude a noisy adjacent category, use the documented set expression: `https://papers.cool/arxiv/cs.AI+cs.LG-cs.CY-econ.GN`. `+` means include and `-` means exclude. Use it only when the exclusion is relevant to the user's scope.
- For an exact arXiv ID or a known historical paper, open `https://papers.cool/arxiv/<arxiv-id>`.
- For accepted work in a named supported conference, use `https://papers.cool/venue/<venue>.<year>` (for example, `NeurIPS.2025`). `https://papers.cool/venue/<venue>` resolves to its newest indexed edition. Read the venue notes in the source guide before presenting it as exhaustive.
- The direct helper's default `search` mode calls both `/arxiv/search` and `/venue/search`, serially with the required delay. Its `--branch arxiv` or `--branch venue` switch is only for an explicitly scoped request. The onsite index searches title and abstract text.
- papers.cool's browser **Prefer** feature is personal browser-local storage. In automated work, ask for or infer a small set of user-approved preference terms and pass them as `--prefer "term1,term2"`. The helper performs transparent client-side ranking and writes each paper's `preference_score`; it does not claim to reproduce the user's private browser profile.

## Gather and verify

1. Read enough of each results page to capture a useful, bounded candidate set; default to the 10 most relevant or newest results unless the user specifies a count, time range, or venue.
2. Treat the list page as the metadata source. Capture the canonical source link, title, full author list when shown, abstract, subjects, and published timestamp. Capture the venue/track for venue papers. Every output record must retain both `papers_cool_url` and `source_url` (the original arXiv, OpenReview, ACL Anthology, proceedings, or journal landing page exposed by the card).
3. Follow the paper's canonical source link (arXiv, OpenReview, ACL Anthology, or other source shown by the site) when the user asks for a precise PDF, version, DOI, publication status, or information absent from papers.cool. Prefer that canonical source for those facts.
4. A `[PDF]` link in papers.cool is a viewer/proxy. It is suitable for reading, but report the original PDF/source URL when available. Do not treat `[Kimi]` output, popularity counts, reading history, or stars as scholarly evidence; only use Kimi summaries if the user explicitly requests them.
5. Deduplicate across categories and venue pages. Keep an arXiv preprint and a venue version together when they are clearly the same work; label both records rather than claiming they are independent papers. Preserve both URLs even after deduplication.

## Present the result

Give a compact shortlist first, followed by one detailed entry per paper. For every result include:

- title and authors;
- arXiv ID or venue/source identifier, date, subjects, and venue/track when applicable;
- a two-to-four sentence faithful summary based on the listed abstract (clearly separate this from claims independently verified at the source);
- direct canonical landing-page link and PDF link when available;
- why it matches the requested topic, plus a caveat if relevance is weak or tangential.

State the retrieval route and date. Distinguish **arXiv preprints** from **peer-reviewed venue papers**. Do not infer peer-review status from an arXiv category, and do not assert that a category/venue page is exhaustive beyond what the site itself represents.

When data will feed another tool, return the normalized JSON directly or attach it after the human-readable shortlist. Each `papers` object must include at least `title`, `abstract`, `papers_cool_url`, and `source_url`; normally also include `id`, `source_collection`, `authors`, `subjects`, `published`, and `preference_score` when preferences were applied.

## Freshness and coverage limits

papers.cool mirrors arXiv updates with a typical delay of up to about ten minutes, normally updating around 10:00 Beijing time on weekdays; schedules can shift and there are no weekend or some holiday updates. Its historical arXiv records are substantial but not guaranteed complete, and its conference collections are manually curated. Mention either limitation when freshness or completeness matters. Use the site's Atom feeds only when the user asks to subscribe or monitor new papers.


