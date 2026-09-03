# papers.cool source guide

Use this reference when selecting a source path or translating a research topic into arXiv categories.

## What the site aggregates

`papers.cool` is an immersive paper-discovery site with two distinct collections:

| Collection | What it provides | Best use |
|---|---|---|
| arXiv | All public arXiv subject categories, recent daily lists, substantial historical arXiv coverage, per-paper pages, and Atom feeds | New preprints and category-based discovery |
| Venue | Manually collected proceedings/accepted-paper lists for selected conferences | Recent or historical work from a named top venue |
| Onsite search | A Tantivy/BM25-style local index of title and summary text, with `arXiv` and `Venue` branches | Concept terms that cut across categories |

The current venue menu includes AAAI, ACL, COLM, COLT, CoRL, CVPR, ECCV, EMNLP, ICCV, ICLR, ICML, IJCAI, INTERSPEECH, IWSLT, MICCAI, MLSYS, NAACL, NDSS, NeurIPS, OSDI, UAI, USENIX FAST, and USENIX Security. The menu and coverage can change; inspect the homepage before promising a venue is available.

## Topic-to-category starting points

These are retrieval starting points, not labels that prove a paper's subject. Broaden with an onsite keyword search when the topic crosses fields.

| Topic | Start with | Often add |
|---|---|---|
| General artificial intelligence, planning, agents, knowledge representation | `cs.AI` | `cs.MA`, `cs.RO`, `cs.LG` |
| Machine learning, deep learning, optimization, representation learning | `cs.LG` | `stat.ML`, `cs.NE` |
| Large language models, NLP, speech/language | `cs.CL` | `cs.AI`, `cs.LG`, `eess.AS` |
| Computer vision, multimodal visual learning | `cs.CV` | `cs.LG`, `cs.AI`, `eess.IV` |
| Robotics and embodied AI | `cs.RO` | `cs.AI`, `cs.LG`, `cs.CV` |
| Reinforcement learning and sequential decision making | `cs.LG` | `cs.AI`, `cs.RO`, `cs.MA` |
| Information retrieval, RAG, search | `cs.IR` | `cs.CL`, `cs.AI`, `cs.LG` |
| AI safety, security, privacy | `cs.AI` | `cs.CR`, `cs.CY`, `cs.LG` |
| Systems for ML / efficient ML | `cs.LG` | `cs.DC`, `cs.PF`, `cs.AR`, `cs.OS` |
| Data mining / knowledge graphs / graph learning | `cs.LG` | `cs.DB`, `cs.SI`, `cs.AI` |

## URL forms and capabilities

- Category: `https://papers.cool/arxiv/cs.LG`
- Category union: `https://papers.cool/arxiv/cs.AI,cs.CL,cs.CV,cs.LG`
- Include/exclude categories: `https://papers.cool/arxiv/cs.AI+cs.LG-cs.CY-econ.GN`
- Known arXiv paper: `https://papers.cool/arxiv/2401.00001`
- A specific venue year: `https://papers.cool/venue/ICLR.2025`
- Latest indexed edition of a venue: `https://papers.cool/venue/ICLR`
- Latest venue Atom feed: `https://papers.cool/venue/latest/feed`
- Latest named-venue Atom feed: `https://papers.cool/venue/AAAI/feed`

Individual cards normally expose an original-source link, title, authors, abstract, subject labels, and—in the arXiv branch—a publication timestamp. They also offer a PDF viewer, copy action, optional Kimi explanation, and related-paper control. The related-paper control is a discovery hint generated through keywords plus full-text search; it is not a citation graph or a systematic-review similarity measure.

## Known constraints

- The site removed its bioRxiv/x-Rxiv stream in 2025 after source-side anti-bot restrictions. Do not advertise bioRxiv as a current source.
- Venue records are manually collected and may contain omissions or metadata errors. Verify a paper at its official proceedings page/OpenReview when publication status matters.
- Search has a maximum of 1,000 displayed results and does not provide documented advanced filters. Refine terms, choose a branch, or use a category/venue page rather than implying exhaustive keyword recall.
- The site supports preferences, personal reading history, stars, and Kimi summaries. These are personal/product features, not filters or authoritative metadata for a research report.


