# Papers Cool Search

[![skills.sh](https://skills.sh/b/samonysh/papers-cool-search)](https://skills.sh/samonysh/papers-cool-search)

一个基于 [papers.cool](https://papers.cool) 的智能体 Skill：同时检索 arXiv 与 Venue 集合，将论文卡片规整为可复用 JSON，并保留 papers.cool 与原始论文来源链接。

[English](README.md)

## 功能

- 默认同时搜索 arXiv 和网站收录的 Venue（会议）集合。
- 为 AI、机器学习、自然语言处理、视觉、检索等主题映射 arXiv 分类，并支持分类并集、差集。
- 每篇论文至少返回 `title`、`abstract`、`papers_cool_url` 和 `source_url`；同时尽可能返回作者、分类、发布时间与来源集合。
- 只要配置了 OpenAlex API Key，就会自动通过 [OpenAlex API](https://help.openalex.org/api/) 为每条记录补充 `openalex_url` 与合并后的 `source_urls` 数组；未配置 Key 时完全跳过，不会发起任何 OpenAlex 请求。
- 按需下载 PDF（`--fetch-pdf`）：优先从论文来源链接推导直链 PDF，失败则回退到 OpenAlex 内容下载；每篇论文在形如 `<时间>-<主题>` 的时间戳目录下各存一份统一命名的 `paper.pdf`。属于尽力而为，取不到的论文会记录但不影响整体。
- 按需获取**中文翻译 PDF**（仅限有 arXiv ID 的论文，基于 [hjfy.top](https://hjfy.top)）：优先使用**内置浏览器**完成登录并发起翻译，助手脚本负责等待并把结果下载为该论文文件夹下的 `paper.zh.pdf`。
- 可通过 `--prefer` 进行本地、可解释的偏好关键词排序；偏好词不会被发送给 papers.cool。
- 支持从给定论文或至多五篇首轮结果显式进行一度 `[REL]` 扩展，并在 JSON 中保留种子和查询溯源。
- 区分预印本和会议论文；若同一工作存在多个版本，保留相应链接。

## 安装

### Codex

```bash
npx skills add samonysh/papers-cool-search --skill papers-cool-search --agent codex
```

也可以将包含 `SKILL.md` 的目录放入 `~/.codex/skills/papers-cool-search/`。

### 其他智能体

本项目遵循 skills.sh 使用的可移植 `SKILL.md` 规范。替换 `--agent` 即可安装至其他支持的智能体：

```bash
npx skills add samonysh/papers-cool-search --skill papers-cool-search --agent claude-code
```

## 直接获取 JSON

```bash
# arXiv 分类
python scripts/papers_cool_fetch.py arxiv cs.LG --show 10

# 默认双源搜索：arXiv + Venue
python scripts/papers_cool_fetch.py search "retrieval augmented generation" --show 10

# 指定会议届次
python scripts/papers_cool_fetch.py venue NeurIPS.2025 --show 10

# 本地偏好排序
python scripts/papers_cool_fetch.py search "multimodal agent" --prefer "agent,planning,vision" --show 10

# 从指定论文进行一度相关论文扩展
python scripts/papers_cool_fetch.py related arxiv/2506.18896 --show 10

# 仅扩展首轮的前两篇结果（默认不扩展）
python scripts/papers_cool_fetch.py search "multimodal agent" --related-top 2 --show 10

# 下载每篇论文的 PDF 到时间戳目录（仅在用户要求时使用）
python scripts/papers_cool_fetch.py search "retrieval augmented generation" --show 10 --fetch-pdf
```

输出是一个 JSON 对象，其中 `sources` 记录检索路由、`request_count` 记录实际请求数、`papers` 是论文数组。每一项同时包含 papers.cool 页面链接和原始 arXiv、OpenReview、ACL Anthology、论文集或期刊链接，便于后续转为 Markdown、CSV 或其他工作流数据。一度相关结果标记为 `relation_degree: 1`，并以 `related_from` 记录种子链接和关键词查询。

### OpenAlex 补充信息（配置 Key 后自动生效）

该步骤**不是可选开关**，也没有对应参数：只要配置了 OpenAlex Key，每条记录就会额外获得 `openalex_url` 与 `source_urls` 数组。原有的 `source_url` 保持不变；`source_urls` 以原始链接开头，并追加 OpenAlex 中同一篇论文的其它落地页（预印本、DOI、机构库、出版社等）。查找顺序为：`source_url` 中的 DOI → 精确的 arXiv 落地页 URL → 标题搜索（要求标题精确匹配）。每次运行最多补充 50 篇；仅对传输层瞬时错误（连接重置、SSL 中断、超时）做最多 2 次指数退避重试，HTTP 错误与数据格式错误不重试；未配置 Key 时完全跳过。

Key 可通过环境变量或仓库根目录下的 `config.json`（已加入 `.gitignore`）配置，也可用 `--config <路径>` 指定其它位置：

```json
{
  "openalex_api_key": "your-key-here"
}
```

```bash
# 环境变量
OPENALEX_API_KEY=your-key python scripts/papers_cool_fetch.py arxiv cs.LG --show 10

# 或使用配置文件
python scripts/papers_cool_fetch.py arxiv cs.LG --show 10 --config config.json
```

可在 [openalex.org/settings/api](https://openalex.org/settings/api) 免费申请 Key。

### 下载 PDF（可选）

仅在确实需要 PDF 时加上 `--fetch-pdf`。工具会新建一个时间戳运行目录：

```text
<pdf-dir>/<YYYYMMDD-HHMMSS>-<主题>/<NN>-<标识>-<标题 slug>/paper.pdf
```

- 运行目录为 `<时间>-<主题>`，主题取自 `--pdf-topic`，否则由查询/分类/会议/种子推导；
- 每篇论文单独一个目录（`<NN>-<标识>-<标题 slug>`），保证不同论文互不混淆；
- 文件统一命名为 `paper.pdf`，每个目录只放一份原文 PDF。

PDF 来源不抓取落地页：优先从 `source_url`/`source_urls` 推导直链（arXiv `abs`/`pdf` → `https://arxiv.org/pdf/<id>`；OpenReview `forum?id=` → `pdf?id=`；ACL Anthology → `.pdf`；或本身就是 `*.pdf` 链接）；若都不可行，再回退到 [OpenAlex 内容下载](https://help.openalex.org/api/llm-quick-reference/)（`https://content.openalex.org/works/<W-id>.pdf?api_key=...`），它需要已配置的 Key，约 $0.01/篇。

成功时该记录会得到 `pdf_path` 与 `pdf_source_url`，输出顶层得到 `pdf_dir`；API Key 绝不会写入结果。整个过程尽力而为：失败会进入 `errors`（`source_collection: "pdf"`）并删除空目录，完全没有可用来源的论文直接跳过。限制：每次最多 50 篇、单个文件 50 MiB、下载间隔 1 秒，并沿用前面的有限传输重试。

```bash
# 默认父目录为当前目录，可用 --pdf-dir 指定
python scripts/papers_cool_fetch.py venue NeurIPS.2025 --show 20 --fetch-pdf --pdf-dir ./downloads --pdf-topic neurips-2025
```

### 中文翻译 PDF（可选）

**仅限有 arXiv ID 的论文**，且仅在你要求"获取中文 PDF"时使用。译文来自 [hjfy.top](https://hjfy.top)，**必须先登录**，因此由浏览器完成需要登录的部分，助手脚本负责等待与下载。**默认使用内置浏览器**（仅当内置浏览器不可用时才退回外置浏览器）：

```bash
# 1. 抓取论文并保存 JSON，然后生成计划（同时创建好各论文文件夹）
python scripts/papers_cool_fetch.py arxiv cs.LG --show 5 --fetch-pdf > papers.json
python scripts/hjfy_zh_pdf.py plan --papers papers.json --out zh_plan.json

# 2. 内置浏览器：确认已在 https://hjfy.top 登录（若未登录，助手会把浏览器交还给你登录），
#    然后逐个打开 zh_plan.json 里的 hjfy_url（每个标签页会发起/排队该论文的翻译，通常需要 1-10 分钟）

# 3. 等待完成后，把结果存为 <论文文件夹>/paper.zh.pdf
python scripts/hjfy_zh_pdf.py fetch --plan zh_plan.json
```

翻译完成的论文会在原文 `paper.pdf` 旁多出一份 `paper.zh.pdf`。`fetch` 会输出 `downloaded` 列表与 `errors`：`需要登录…` 表示缺少浏览器登录态，`翻译未成功…` 表示任务失败，`等待超时…` 只是"还没翻完"——稍后重跑 `fetch` 即可。默认最多等待 10 分钟（`--wait-seconds`、`--interval`），整体尽力而为。hjfy.top 的接口与状态说明见 [references/zh-pdf.md](references/zh-pdf.md)。

### 实际 `[REL]` 运行示例

以下是于 2026-09-03 真实运行所得的关键字段快照；网站索引更新后，返回结果可能变化：

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

## 友好访问策略

papers.cool 是个人维护的网站，不应被当作批量数据 API。本项目强制或约定：

- 单线程请求；任意两次请求间隔至少 3 秒；
- 每次调用最多 20 次请求；`REL` 扩展最多 5 个种子；
- 默认 10 篇、每页最多 50 篇；HTML 响应最大 2 MiB；
- 不自动重试、不并发、不深度翻页、不批量拉取论文详情或 PDF；
- 不调用 star、Kimi、config 等会造成状态变化或额外计算的端点。

完整端点说明见 [references/public-endpoints.md](references/public-endpoints.md)。

## 关于 `[REL]`

网站的 `[REL]` 会读取论文卡片的关键词属性，并以这些关键词在同一个集合中打开搜索页面。本项目如实复现该行为：输出在 `related_from` 中记录种子与查询，且绝不把相关结果再次作为种子扩展。它是基于关键词的相关性发现，不是引用关系网络，也不是向量语义相似度结果。

## 目录结构

```text
SKILL.md                         # 跨智能体的 Skill 指令
agents/openai.yaml               # Codex UI 元数据
scripts/papers_cool_fetch.py     # 只读 HTML → JSON 工具
scripts/hjfy_zh_pdf.py           # 规划/轮询/下载 hjfy.top 中文 PDF
references/source-guide.md       # 覆盖范围、主题和分类映射
references/public-endpoints.md   # 公开路由、JSON 字段、访问限制
references/zh-pdf.md             # hjfy.top 中文翻译机制
config.json                      # 可选，已 gitignore：OpenAlex API Key
```

## 引用与致谢

本项目是基于 [Cool Papers / papers.cool](https://papers.cool/) 提供的论文发现服务，以及 [bojone/papers.cool](https://github.com/bojone/papers.cool) 仓库维护的产品说明所开发的独立适配。感谢维护者和贡献者提供该网站及其公开的论文发现路由。

两个可选附加功能还依赖以下第三方服务，在此致谢：

- [OpenAlex](https://openalex.org/)——`openalex_url`/`source_urls` 补充所依据的开放学术目录（数据为 CC0），通过其只读 [API](https://help.openalex.org/api/) 查询。
- [hjfy.top](https://hjfy.top)（幻觉翻译）——可选中文 PDF 所依赖的翻译服务。本项目仅对其驱动浏览器/HTTP 流程；该服务的可用性、登录要求与条款均由维护者掌控。

如果本 Skill 或通过 papers.cool 获取的数据实质性地用于论文、报告或软件成果，请引用该服务，并保留结果中 `source_url` 所对应的原始论文链接：

```bibtex
@misc{paperscool,
  author       = {bojone},
  title        = {Cool Papers: Immersive Paper Discovery},
  howpublished = {\url{https://papers.cool/}},
  note         = {Accessed 2026-09-03}
}
```

如果 OpenAlex 补充信息对您的数据集有贡献，请同时引用 OpenAlex：

```bibtex
@article{priem2022openalex,
  title   = {OpenAlex: A fully-open index of scholarly works, authors, venues, institutions, and concepts},
  author  = {Priem, Jason and Piwowar, Heather and Orr, Richard},
  journal = {arXiv preprint arXiv:2205.01833},
  year    = {2022}
}
```

## 注意事项

Venue 集合为人工整理，可能有遗漏或元数据错误。需要准确确认 DOI、出版状态、PDF 版本时，应再访问结果中的 `source_url`。本项目为独立适配，和 papers.cool、OpenAlex、hjfy.top 均无隶属关系，也不代表获得其维护者的背书。

## 许可证

[MIT](LICENSE)
