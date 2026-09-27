# Chinese-translated PDFs (hjfy.top)

Chinese translations come from [hjfy.top](https://hjfy.top) (幻觉翻译). Use this step **only when the user explicitly asks for a Chinese PDF**, and only for papers that have an **arXiv ID**. Login and starting the translation happen in a browser; the bundled `scripts/hjfy_zh_pdf.py` handles planning, waiting, and placing the file.

## Site mechanics (verified 2026-09-27)

- The homepage input accepts an arXiv URL or ID; submitting it opens `https://hjfy.top/arxiv/<arxiv-id>`.
- **Creating a translation task requires login.** Read anonymously, a paper that was never translated answers `{"status":101,"msg":"required login"}`; an already-translated paper can be read without login.
- Task status: `GET https://hjfy.top/api/arxivStatus/<arxiv-id>` → `data.status` is one of `init`, `start`, `processing`, `finished`, `failed`, `fault`, `error`. The site itself polls every 10 seconds; the UI says translation "通常需要 1-10 分钟".
- Completed files: `GET https://hjfy.top/api/arxivFiles/<arxiv-id>` → `{id, title, origin, zhCN, zhCNTar, isDeepSeek}`. `zhCN` is the Chinese PDF and `origin` the original, both signed object-storage URLs; **the `zhCN` URL expires in about 360 seconds**, so download it promptly.
- A paper without downloadable LaTeX source cannot be translated (`hasSrc` is false; the app says "这篇论文未提供 Latex 源码"). Treat it as a best-effort failure.

## Workflow

1. Get the paper list and save it, then create the plan (this also creates the per-paper folders, using the same layout as the original-PDF step):
   ```bash
   python scripts/papers_cool_fetch.py arxiv cs.LG --show 5 --fetch-pdf > papers.json
   python scripts/hjfy_zh_pdf.py plan --papers papers.json --out zh_plan.json
   ```
   `plan` lists every eligible paper with its `hjfy_url` and the target `paper.zh.pdf`; papers without an arXiv ID are excluded.
2. **Browser.** Use the **built-in browser by default**; fall back to an external browser only when the built-in one is unavailable. Open `https://hjfy.top` and check the login state. If the user is not logged in, hand the browser over to them (in the agent runtime this is `browser_waiting_for_user_interaction`) and continue only after they confirm login—no translation can be created otherwise. Then open each `hjfy_url` from the plan to start/queue its translation (each tab shows "开始翻译，通常需要 1-10 分钟", then "翻译中").
3. Poll and download (default waits up to 10 minutes, checking every 15 seconds):
   ```bash
   python scripts/hjfy_zh_pdf.py fetch --plan zh_plan.json
   ```
   Each finished paper is saved as `paper.zh.pdf` inside that paper's folder, next to the original `paper.pdf`.

The two steps are separate on purpose: the browser step requires the user, while `fetch` can run afterwards (or be re-run later) without a browser.

## Result and limits

- File names are uniform: the original PDF is `paper.pdf`, the Chinese translation is `paper.zh.pdf`, both in the same per-paper folder.
- `fetch` prints `run_dir`, the `downloaded` list, and any `errors`. Errors use `source_collection: "zh_pdf"` and a plain-language reason (`需要登录…`, `翻译未成功…`, `等待超时…`). A timeout does not mean failure—just re-run `fetch` later.
- Best-effort: papers that need login, lack LaTeX source, or are still translating are reported, never fatal. `--force` re-downloads even when `paper.zh.pdf` already exists.
- Only arXiv papers are in scope; non-arXiv venue papers are skipped by design.
