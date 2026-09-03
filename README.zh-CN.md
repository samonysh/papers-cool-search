# Papers Cool Search

[![skills.sh](https://skills.sh/b/samonysh/papers-cool-search)](https://skills.sh/samonysh/papers-cool-search)

一个基于 [papers.cool](https://papers.cool) 的智能体 Skill：同时检索 arXiv 与 Venue 集合，将论文卡片规整为可复用 JSON，并保留 papers.cool 与原始论文来源链接。

[English](README.md)

## 功能

- 默认同时搜索 arXiv 和网站收录的 Venue（会议）集合。
- 为 AI、机器学习、自然语言处理、视觉、检索等主题映射 arXiv 分类，并支持分类并集、差集。
- 每篇论文至少返回 `title`、`abstract`、`papers_cool_url` 和 `source_url`；同时尽可能返回作者、分类、发布时间与来源集合。
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
```

输出是一个 JSON 对象，其中 `sources` 记录检索路由、`request_count` 记录实际请求数、`papers` 是论文数组。每一项同时包含 papers.cool 页面链接和原始 arXiv、OpenReview、ACL Anthology、论文集或期刊链接，便于后续转为 Markdown、CSV 或其他工作流数据。一度相关结果标记为 `relation_degree: 1`，并以 `related_from` 记录种子链接和关键词查询。

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
references/source-guide.md       # 覆盖范围、主题和分类映射
references/public-endpoints.md   # 公开路由、JSON 字段、访问限制
```

## 引用与致谢

本项目是基于 [Cool Papers / papers.cool](https://papers.cool/) 提供的论文发现服务，以及 [bojone/papers.cool](https://github.com/bojone/papers.cool) 仓库维护的产品说明所开发的独立适配。感谢维护者和贡献者提供该网站及其公开的论文发现路由。

如果本 Skill 或通过 papers.cool 获取的数据实质性地用于论文、报告或软件成果，请引用该服务，并保留结果中 `source_url` 所对应的原始论文链接：

```bibtex
@misc{paperscool,
  author       = {bojone},
  title        = {Cool Papers: Immersive Paper Discovery},
  howpublished = {\url{https://papers.cool/}},
  note         = {Accessed 2026-09-03}
}
```

## 注意事项

Venue 集合为人工整理，可能有遗漏或元数据错误。需要准确确认 DOI、出版状态、PDF 版本时，应再访问结果中的 `source_url`。本项目为独立适配，和 papers.cool 无隶属关系，也不代表获得其维护者的背书。

## 许可证

[MIT](LICENSE)
