# DESIGN_SPEC — pagetrace v0.18.20

| 项 | 值 |
|---|---|
| 版本 | 0.18.20（**与 `backend/app.py` 的 `version` 一致** · 版本号诚实规则见 `CLAUDE.md §5`） |
| 日期 | 2026-10-11 |
| 作者 | pm（Hermes） |
| 状态图例 | ✅ 已实现并验证 · ⚠️ 部分/未验证（须写原因）· ❌ 未实现 · 🔒 已冻结（不可单方改） |
| 定位 | owner 个人的**知识复习端**：把 brain 蒸馏出来的知识，变成他每天真正复习得动的卡片 |

> **本文件是唯一需求真相。** 代码与实现状态回写在 `§12`，每版一段、带证据。
> 与 `CLAUDE.md`（交付纪律）、`CHANGELOG.md`（版本流水）三者必须自洽。

---

## §1 目标与非目标

### 1.1 目标
- 单用户（owner）的**卡片复习**应用：`学科 → 书 → 章 → 概念 → 卡片` 五级可回溯。
- 上游吃 brain 的**知识库导出契约**（§5），不碰原始 PDF、不做切片、不做 OCR。
- 复习调度以 **SM-2 派生字段**为唯一真相（`learn_count` / `status` / `next_review_at`）。
- **掌握度解锁**作为唯一推进机制（§3 `SCHED`）：新内容按掌握度阈值解锁，不按日期、不按配额。
- **零配额**：当天学哪一科、学多少，完全由 owner 自己决定（2026-09-26 拍板）。

### 1.2 非目标（**禁止实现**，编码 agent 越界即缺陷）
| 不做 | 原因 |
|---|---|
| 多用户 / 注册 / 邀请 | 单用户应用（保留 `users` 单行 + JWT 骨架仅为复用既有认证层） |
| 教师资料与视频下载 | 仍不做；本功能是生成式讲解视频，不是下载他人视频。 |
| 教师端 / 班级 / 作业 / 排行榜 | 那是「AI 学习小组 app」的职责，两 app 边界已定 |
| RAG / 向量库 / chunks / tutor 问答 | 问答是 `brain` profile 的职责；本 app 只做卡片与复习 |
| OCR / 课件切片 / `课件/第N章` 上架流程 | 上游改为 KB 契约（§5），不需要课件目录 |
| 草稿-发布状态机 | 单用户无「学生看到什么」问题，写入即生效 |
| 每日配额 / 强制轮转 / 保底张数 | 2026-09-26 明确不做（`§3 SCHED-003`） |
| 社交压力机制（班级连胜榜、催学阶梯 19:00–23:00 五档） | 那是学生端设计；个人版只保留温和提醒（§3 `OPS-004`） |
| **AI 学习建议 / 智能提示 / 自适应推荐 / 自动学习规划** | **2026-09-27 明确不做**（§3.15 `ADV-001`）；建议类归 `brain`，本 app 的 AI 层只做「考点→卡面」「去重闸门」 |

**分期解除说明（2026-10-11 owner 拍板 · 细则见 `§11`）**：上表 **四项**——
`多用户 / 注册 / 邀请`、`OCR / 课件切片`、`草稿-发布状态机`、`每日配额 / 强制轮转`——
按 `§11` **分期解除**：**S1 先做单用户上传通路**（抽文本 / 分段 / 出卡 / 草稿态 / 配额），
**S2 做登录**，**S3 做多租户隔离**。S1 交付前，这四项对「S1 范围内」不再视为越界；
**S1 范围外一切照旧禁止**（教师端/班级/排行榜、RAG/向量库/tutor 问答、`ADV-001` AI 建议类**仍然禁止实现**）。

---

## §2 架构与数据流

```
上游（brain 拥有）                        本 app（pm 拥有）
data-local/                          pagetrace/
  raw/books/<书>/        原文层
  concepts/*.md          蒸馏层（带 sources: 书/章/页）
  moc/MOC-<书>-*.md      结构真相（章节地图）
  exports/<学科>/<书>.jsonl   ←—— 唯一交接口（契约，§5）——→   scripts/ingest_kb.py
                                                              ↓ cardgate 去重
                                                          data-local/review.sqlite3
                                                              ↓
                                                     复习队列 / 掌握度解锁 / PWA
```

- 技术栈沿用既有三项目契约：Flask + waitress + SQLite + 原生 JS PWA（无构建链）。
- **分层**：`backend/{app.py, api/, data/, services/, ai/, middleware/, scripts/}`、`frontend/{index.html, js/, css/, sw.js}`、`tests/`、`deploy/`、`reports/`、`backups/`。
- **命名与端口（🔒 已定）**：目录 `pagetrace/pagetrace`、slug `review`、端口 **5004**、域名 `example.invalid`、库 `data-local/review.sqlite3`、launchd `org.example.review` + `org.example.review`。
- **部署面**：`~/.cloudflared/config.yml` 加一行 ingress + `cloudflared tunnel route dns`（单隧道多子域，与四口之家/学习小组平行）。

---

## §3 需求（REQ 分域）

### 3.1 DATA — 学科与层级
- **DATA-001（P0）** 五级层级：`subjects → books → chapters → concepts → cards`，每级外键向上单亲；**一本书只属一个学科**（无多对多，2026-09-26 拍板）。
- **DATA-002（P0）** 每张卡必带：`concept_id`、`subject_id`、`source`（书/章/页）、`content_hash`；缺任一 = 不许入库。
- **DATA-003（P0）** 所有层级「上架即生效」，无草稿态；写入权限单一化：**只有 pm 写本 app 库**。
- **DATA-004（P1）** 每科常显汇总：`本书数 / 章数 / 已学 x / 共 y 张` + `未学 / 到期 / 已掌握`（§3.5 `UI-002`）。
  **学科级不出现「解锁到第几章」**（见 DATA-005）。
- **DATA-005（P0，🔒 口径）** **跨书聚合字段不得冒充单值。** 一科多书，各书进度独立：
  学科级凡是聚合出来的数（章数、已学、总数…）只能以**汇总**形态出现；
  「解锁到第几章」是**书的属性**，只能逐书取值（`books.unlocked_upto` / `books.chapters_total`），
  不得在学科级求和、取最大/最小或取首书冒充。
  - **触发点**：凡「学科级聚合字段」出现在 UI 或接口的位置。
  - **覆盖路径**：学科页 / 学科列表 / 首页学科卡片 / 书列表 / 任何通知或文案，**无旁路**。
  - **违规处置**：不得显示单一数字，改「汇总」或「按书展开」。
  - **理由**：2026-09-27 真实数据暴露 —— psychology 下 2 本书（合成示例书3 14 章 / 合成示例书9 6 章）
    仅首章解锁时聚合值恰好为 1；一旦 A 书到第 9 章、B 书到第 3 章，单一数字必然说谎。
- **DATA-006（P0，🔒 口径）** **学科显示名的唯一来源 = 库内 `subjects.name`。** 上游契约只提供 slug
  （`subject` 字段），**显示名由 app 侧维护**：`config.SUBJECT_LABELS = {slug: 显示名}`（单点，加学科补一行）。
  - **入库**：新建学科若映射命中 → `subjects.name` 写映射名；未命中 → 回落写 slug，并
    `logging.warning` 一行「学科 X 无显示名映射，暂用 slug」（不静默）。
  - **绝不覆盖既有显示名**：按 slug 命中既有学科时**完全不写 `name`** —— 重导入库（幂等复跑）
    不得把已改好的「演示学科」冲回 `psychology`，也不得覆盖手工修正值。
  - **回填**：既有数据用 `backend/scripts/backfill_subject_labels.py` 一次性按映射更新（幂等；
    映射里没有的行一动不动）；改数据前先 `wal_checkpoint` + 落带时间戳备份，跑完打印 before/after。
  - **UI 不新增映射**：所有展示处统一读 `subjects.name`，**禁止**在前端另存一份 slug→显示名（双份真源 = 旁路）。
  - **触发点**：任何 ingest / 学科写库 / 展示学科名的地方。
  - **覆盖路径**：首页学科行 / 学科列表 / 学科页面包屑 / 复习卡出处 / 测验页，**以及将来新增的任何页面**，无旁路。
  - **违规处置**：不合规不得提交；回归（学科名又显示成 slug）即回滚该 commit。
  - **理由**：2026-09-27 真机确认 —— `SELECT id,slug,name FROM subjects` → `(2,'psychology','psychology')`，
    UI 忠实渲染了库里的值。契约只管 slug 是**对的**（跨系统稳定标识不该是中文字面量），
    显示名属于 app 的展示层职责，两者分离。

- **DATA-006 · 章显示名（P0，🔒 口径）** `chapter` 始终是稳定锚点；可选 `chapter_title` 是纯标题。
  - **触发点**：`backend/scripts/ingest_kb.py` 导入任意书（`--book` / 全量共用入口）。
  - **覆盖路径**：`upsert_chapter()` 按 `(book_id, anchor)` 唯一定位，`chapters.name` = `锚点 · 标题`；
    缺标题的新章 `name = anchor`，已有人工改名不回退；`_source_text()` 从实际章显示名生成
    `cards.source = 书/章显示名[/页]`，命中旧卡且 hash 未变时只刷新不一致的 source，仍计「跳过」。
  - **违规处置**：`chapter_title` 非字符串、长度超过 40 字、含 `\n` 或 `\r` → 逐行拒绝写库并计「待人工」。
  - **机械断言**：带标题时 name/source 都含标题；缺标题的新章 name 逐字等于 anchor；
    相同文件复跑「新增 0 / 跳过 N」且 name/source 不变；非法标题行待人工且不入库；
    旧库人工补名重导不回退，source 不一致时只刷新 source。

### 3.2 CARD — 入库与质量闸门
- **CARD-001（P0）** 入库唯一入口 `scripts/ingest_kb.py`，只读契约文件（§5），**不读 Obsidian 原文**。
- **CARD-002（P0）** 逐张过**确定性预筛 + 相似度去重**（沿用学习小组 `ai/cardgate.py` 的口径）：同一概念内近似重复 → 合并并记 `merged_from`；跨概念重复 → 丢弃并记 `dropped_reason`。（相似度判定已被 CARD-006 覆盖）
- **CARD-003（P0）** 幂等：同 `(concept_id, content_hash)` 重复导入 → 跳过不重复计数；**跑两次的结果必须与跑一次一致**。
- **CARD-004（P1）** 导入结束打印三段账：`新增 N / 合并 M / 跳过 K`，并写 `reports/ingest-<日期>.md`。
- **CARD-005（P0）** 禁产四类（沿用既有口径）：课程元信息、纯数值罗列、代码细节、纯清单式罗列。

- **CARD-006（P0，🔒 口径 · v0.8.3 · 覆盖 CARD-002 的相似度判定）** **闸门只合并「批内完整重复」，不得按相似度合并或丢弃**：
  - **同一 concept_id**：`front` 归一后（`normalize_label`）完全相同且 `back` 逐字相同 → 合并；其余一律保留。
  - **跨 concept_id**：`front` 归一后完全相同且 `back` 逐字相同 → 丢弃信息量较小的一张并记 `dropped_reason`；相似但不同一律保留。
  - **废止 R1–R5 / `_cross_hit`** 相似度判定；跨批幂等仍由 `(concept_id, content_hash)` 唯一键兜底（CARD-003 不变）。
  - **机械断言**：同 concept 高相似不同卡不合并；跨 concept 完整重复丢弃、仅相似保留；同 fixture 第二次新增 0、跳过全部。

- **CARD-007（P0，🔒 口径 · v0.12.0 · owner 2026-09-30 拍板）** **契约 `title` 逐字落库（`cards.title`）**：
  上游 `title` 的实际格式 = **「概念名 · 子卡短名」**（未切分卡 = 概念名本身；语义归 brain 的 `exports/导出契约.md`）——
  app 侧**照收不猜**：只「原样存下来」，派生留给展示层（UI-019）。
  - **入库**：`cards.title` 由 `models.migrate()` **幂等加列**；新卡 INSERT 带 title；既有行（加列前入库的 1063 张）
    **不许手工 SQL 回填** —— 用**幂等重导**（`scripts/ingest_kb.py`：命中 `(concept_id, content_hash)` 的行
    `UPDATE title` **当且仅当**与契约文件不同）补齐，统计单列「**回填 N**」，与新增/合并/跳过/待人工同账。
  - **触发点**：任何 ingest / 卡片写库。**覆盖路径**：`backend/data/models.py`（SCHEMA + migrate）、
    `backend/scripts/ingest_kb.py`（唯一写入口）、`reports/ingest-<日期>.md`（含回填列）；**无旁路**（别处禁 `UPDATE cards SET title`）。
  - **违规处置**：`title` 丢失 / 被改写 / 被前端二次解析 → 缺陷，回滚。
  - **机械断言**：`tests/test_ingest.py::test_title_stored_and_idempotent_backfill`（逐行 title 落库；清空后重导 → `新增 0 / 回填 3`；
    再跑 → `回填 0 / 跳过 3`，库不膨胀）。

- **CARD-008（P0，🔒 口径 · v0.13.0 · 2026-10-01 定）** **上游换版时，复习进度按「知识点」保住，不按「题面」判生死**：
  上游重新导出（同一考点的题面/正文可能被重写）后，旧卡「就地采纳」还是「退场」一律**机械判定**，禁手写清单：
  - **就地采纳**（先做）：旧卡与新版契约行**同 `concept_id` 且 `back` 逐字相同** → 用
    `backend/scripts/reswap_card_text.py --match back` **原地**把 `front` 换成新版文本；
    **卡 id / `status` / `learn_count` / `next_review_at` / `card_reviews` 历史一律不动**（不是「删了重插」）。
    理由：卡的身份键含题面（`content_hash(front, back)`），但**进度属于知识点**；题面被上游重写不等于换了考点。
  - **退场**（后做）：`(concept_id, content_hash)` 不在新版契约产出集合里的旧卡 → 删（KB 侧 `retire_stale.py --apply`，
    由 pm 执行）；退场卡的复习进度按 owner 2026-10-01 口径清零（「旧卡退场、那批进度清零」）。
  - **配对规则（不许猜）**：同 concept 内背面命中**恰好 1 张** → 就地采纳；命中 **>1 张（撞车）→ 整批拒绝、库零改动**；
    命中 **0 张 = 上游新增 / 正文真变** → 跳过并计数，交 `ingest_kb.py` 新增 + 退场收尾（不是失败，也不许硬配到别的卡上）。
  - **触发点**：任何「同一本书的契约文件被重出后再 ingest」。**覆盖路径**：就地换文唯一入口 =
    `backend/scripts/reswap_card_text.py`；写库唯一入口 = `backend/scripts/ingest_kb.py`；退场 = KB 侧 `retire_stale.py`。
    **无旁路**：禁止手工 `UPDATE cards SET front=…` / `DELETE FROM cards` 换版。
  - **违规处置**：题面变了就把卡删掉重插（进度被清）→ 缺陷；背面不同却按顺序硬配 → 缺陷；两者都回滚该次入库
    （`--apply` 前必备份，见 `data-local/backups/`）。
  - **机械断言**：`tests/test_reswap_card_text.py::test_back_mode_adopts_rewritten_front_and_preserves_progress`、
    `::test_back_mode_counts_rows_without_counterpart_as_new`、`::test_back_mode_rejects_when_pairing_is_not_unique`。

### 3.3 REVIEW — 复习
- **REVIEW-001（P0）** 调度字段唯一真相：`learn_count`、`status`（`new/learning/review/mastered`）、`next_review_at`；**不引入第二套间隔算法**。
- **REVIEW-002（P0）** 当天队列 = **所有学科的到期卡混合排序**（`next_review_at` 升序）；先复习、后出新卡。
- **REVIEW-003（P0）** 复习卡组上限 100 张/次（沿用学习小组口径）；任务卡组（新卡）无配额上限，但单次展示 ≤ 30 张。
- **REVIEW-004（P1）** 进度无损迁移规则（若从学习小组库迁卡）：`learn_count` 取大、`status` 取进阶、`next_review_at` 取早、孤儿行 0。

### 3.4 SCHED — 推进机制（**掌握度解锁**，无配额）
- **SCHED-001（P0，🔒 口径）** 解锁规则：**本章掌握度 ≥ 80%**（`mastered / (已学)`，已学 ≥ 5 张才判定）**且本章到期复习 = 0** → 解锁下一章；**新书入库即解锁其第 1 章**（否则新书永远打不开）。
- **SCHED-002（P0）** 解锁是**单向的**：不因掌握度回落而重新上锁；解锁时间记入 `unlocked_at`（可看「解锁树」历史）。
- **SCHED-003（P0，🔒 禁令）** **不得实现任何配额/强制轮转/保底张数**（owner 2026-09-26：当天想学哪科就哪科）。
- **SCHED-004（P1）** 进度只能靠**信息**不能靠强制：每科显示「到期积压数」与「距上次触碰天数」（如「演示学科 · 12 天没动」）。
- **SCHED-005（P1）** 掌握度阈值（80% / 已学 ≥ 5）是本 spec 的**可调参数**，必须单点配置化，不得散落硬编码。

> **SCHED-006（P0，🔒 口径 · v0.8.3 · owner 2026-09-28 拍板「改用界面同一口径」）** **解锁门槛的「掌握度」= 界面展示的章级掌握度（MAST-006 同一入口）+ 修小章死锁**：
> - **口径**：上一章同时满足 ① `已学 ≥ min(UNLOCK_MIN_LEARNED, 本章卡数)`；② `level_mastery` 的 `state == 'master'`（`M ≥ 80` 且证据卡 ≥ `max(2, ceil(卡数 × 20%))`）；③ 本章到期 = 0 → 解锁下一章。
> - `chapter_stats.ratio` 仅供展示/诊断，不作门槛；`lock_reason` 必须引用同帧 `level_mastery.m`。
> - 保留首章入库解锁、单向解锁、连锁解锁与幂等 `maybe_unlock`。

### 3.5 UI
- **UI-001（P0，🔒 口径 · v0.5.2 修订）** 钻取式导航：科 → 书 → 章 → 概念 → 卡。**两态写清，避免将来误判**：
  - **浏览态（列表 / 卡片列表）**：**仍禁横向滑动 carousel**；窄屏改网格。CSS 不得出现 `overflow-x:auto|scroll`。
  - **闪卡复习态（复习卡）**：**允许并鼓励左右滑动手势切卡**（右滑=记得，左滑=忘了，UI-014）。
    该手势**不落 DOM `overflow-x`**，是 JS 手势 + `transform`，故与上一条不冲突。
    （**v0.5.4 修订**：测验页已改为**客观题**（选项点击作答），不再有「翻卡 / 切卡」语义 → **不再适用**滑动手势。）
  - **违规处置**：浏览态出现横滑容器、或闪卡手势方向反了 → 均按缺陷处理。**（书层缺口的违规处置见 UI-015。）**
- **UI-015（P0，🔒 口径 · v0.6.0 · owner 2026-09-27 拍板「保留概念层」）** **学科页 = 书列表（五层逐层可见，含「书」层）**：
    `#/subjects`（= **知识卡片**入口，UI-016）→ `#/subject/<id>` **只渲染书列表**（每本书一行可点「书的按钮」，左书名 + 右书级进度）→
    点书 `#/book/<id>` 才渲染**章** → 点章渲染**概念** → 点概念渲染**卡**。
    **禁止**学科页直接渲染某本书的章节（v0.6.0 前 `renderDrill(subject, books[0])` 的扁平写法属缺陷）、**禁止**用「另一本书」小节充当书层、**禁止**学科页无 `h1`。
    - **触发点**：`#/subject/<id>` / `#/book/<id>` 任何渲染改动。**覆盖路径**：`js/app.js` 的 `subject()` / `renderDrill()`（唯一渲染点），无旁路。
    - **违规处置**：学科页出现章行（`details.chap`）、或页内出现跨书跳转入口 → 回滚该 commit + 回规格重做。
    - **机械断言**：`make ui-audit ⑧`（学科页：存在 `h1`、`details.chap` 数 == 0、且每个可见交互块 `href` 均以 `#/book/` 开头；
      书页：`details.chap` 数 > 0 且无 `#/book/` 兄弟书列表）+ `tests/test_frontend.py::test_subject_page_lists_books_only`（源码反向断言）。
- **UI-002（P0 · v0.6.0 修订）** 首页块序固定为：**每日格言大标题（HOME-001）** → 汇总行 → 本周摘要（RPT-001）→
  **主行动 `.primary`「开始复习 N 张」** → **今日任务（TASK-001/002：两子项 + 去完成/绿勾+再来一组）** → **快捷入口（含「知识卡片」，UI-016）** → 学科进度（每科一条）+ 学科列表。
  首屏**只许一个复习数字口径**（GOAL-001：`.primary` 的 N == 今日任务 `review.target`）。
- **UI-003（P0）** 不可用控件**常显 + 置灰 + 写明原因**，绝不按条件隐藏。
- **UI-004（P1）** 视觉沿用暖纸 editorial 语法（既有 `ui-design-toolkit`），不换皮、不引新框架。
- **UI-005（P0，🔒 口径）** **聚合渲染口径**（配合 DATA-005，无旁路）：
  - 学科级位置（学科页 / 学科列表 / 首页学科卡片）→ 只渲染**汇总**文案，例：`2 本书 · 20 章 · 已学 x / 共 237 张`。
  - 书级位置（书列表 / 书内）→ 渲染**该书自身**的 `已解锁到第 N 章 / 共 M 章`，逐书取值、互不污染。
  - 违规处置：出现单一「学科级第 N 章」即缺陷，须改汇总或按书展开。

> **UI-006…UI-012（v0.5.0 起，🔒 口径）** 视觉世界规格，实现细则见 `backend/frontend/DESIGN.md`（唯一基准）。
> 对照稿 = `~/Desktop/review-ui-direction/index.html`。以下条款**对后续一律适用**。

- **UI-006（P0，🔒 口径）** **设计令牌与字号尺度**：CSS `:root` 必写四语义槽（暖纸底 / 墨字 / 草绿主色 / 陶橙警示）+
  禁用槽；字号四档拉开 —— 大标题 34–40px/900、区块题 22px/800、**正文 17.5px/400（行高 1.75、行宽 ≤70ch，不得低于 17px）**、
  次文 15px、微标签 11.5px/800；所有数字 `font-variant-numeric: tabular-nums`；圆角统一一套（卡 16 / 按钮 14 / 微块 8）。
  - **触发点**：任何前端样式或组件改动。**覆盖路径**：所有页面与组件（`backend/frontend/` 全部），无旁路。
  - **违规处置**：字号低于 17px 的正文、缺令牌、混用圆角 → 不得提交。
- **UI-007（P0，🔒 口径）** **主色锁定与 accent 唯一性**：全站唯一 accent = 草绿 `#1E7C50`（深色变体 `#14613C`）；
  陶橙 `#DD8A3E` **仅**用于未解锁/警示标记，不做按钮色；旧暗棕 `#9A6B3F` 废弃，不得回归。
  - **触发点**：任何引入配色的改动。**覆盖路径**：CSS 与内联样式全部（`?v=` 资产在内），无旁路。
  - **违规处置**：出现第二个 accent 或旧 accent 复现 → 不得提交；实测回归即回滚该 commit。
- **UI-008（P0，🔒 口径）** **一屏只有一个主行动**：深绿实心大按钮 `.primary`（如首页「开始复习 N 张」+ 一行时间估算）；
  其余入口一律 hairline 行（左标题+次文，右箭头）。结构靠 1px `--hair` 细线 + 留白，**禁卡片套卡片**，白卡只有一种样式。
  - **触发点**：任何新增/改动页面的动作区。**覆盖路径**：所有页面，无旁路。
  - **违规处置**：同屏出现两个同款实心主按钮或嵌套卡片 → 不得提交。
- **UI-009（P0，🔒 口径）** **状态齐全**：hover / `:active`（`translateY(1px)`）/ `:disabled`（**置灰 + 必写原因**，
  常显不隐藏，UI-003）/ loading（骨架或「加载中…」，**不出现圆形转圈**）/ error（`errorBox` 保留并套新语法）/
  empty（有构图 + 写明「怎么产生内容」）。
  - **触发点**：任何可交互控件与任何数据视图。**覆盖路径**：所有页面与组件，无旁路。
  - **违规处置**：缺状态或 disabled 无原因文案 → 不得提交。
- **UI-010（P0，🔒 口径）** **浏览器原生面主题化**：`:selection` / `caret-color` / 滚动条（窄条、暖纸色）/
  `:focus-visible`（草绿 2px 焦点环，**不许 `outline:none` 了事**）/ 链接下划线偏移，全部按令牌。
  - **触发点**：任何全局样式改动。**覆盖路径**：全站（`css/app.css` 根层），无旁路。**违规处置**：缺任一项 → 不得提交。
- **UI-011（P0，🔒 口径）** **动效预算**：仅一次「作者化」进场（列表错峰 `fadeUp`，`cubic-bezier(.16,1.22,.35,1)`，
  `--d` 控延迟）+ hover 抬升 6px；**禁无限循环动画**；`@media (prefers-reduced-motion: reduce)` 下全部关掉。
  - **触发点**：任何新增动画/过渡。**覆盖路径**：全站，无旁路。**违规处置**：出现循环动画或未处理 reduced-motion → 不得提交。
- **UI-012（P0，🔒 禁令清单）** 禁渐变**文字**、玻璃模糊装饰、`>1px` 彩色左边框、emoji 当图标、嵌套卡片、
  **横向滚动容器（浏览态 `overflow-x:auto|scroll` 一律不准出现，UI-001）**、系统字体当 display 字体；
  按钮文字必须一行放得下；白底白字 / 白字浅底一律禁止；不引依赖/框架（UI-004）。
  - **触发点**：任何前端改动。**覆盖路径**：`backend/frontend/` 全部，无旁路。**违规处置**：不合规不得提交；回归即回滚该 commit。

> **UI-013 / UI-014（v0.5.2 起，🔒 口径）** 实现细则见 `backend/frontend/DESIGN.md §3 / §6 / §10`。

- **UI-013（P0，🔒 口径）** **相邻可交互块间隙**：任何相邻可交互块，**竖向 ≥12px、横向 ≥10px**；
  **hairline 细线不得作为唯一分隔**。行式入口（`.row` / `.chap` / `.progline`）做成**独立块**
  —— 暖纸卡底 `--card` + 1px `--hair` 边 + `14px` 圆角，列表容器 `gap:12px`；**保留 editorial 语法**（大字号、细线、无嵌套卡）；
  未解锁章行同样块化并置灰（`.row.disabled`，UI-003）。
  - **触发点**：任何列表 / 行式入口 / 动作区改动。**覆盖路径**：所有页面与组件，无旁路。
  - **违规处置**：实测相邻可点块间隙不足（尤其靠 hairline 硬贴）→ 不得提交。
  - **机械断言（v0.5.3 固化）**：`make ui-audit`（`scripts/ui_audit.js`）在两档宽（390 / 1280）× 六条真实路由实测
    相邻可交互块间隙（竖向 ≥12px、横向 ≥10px，含重叠判定）；**非零退出码 = 失败**。
    另：**进场动画不得位移可交互块**（入场瞬间的 `translateY` 会让实测间隙掉到 ~2px）—— 可交互块与列表容器只做
    透明度淡入 `fadeIn`，位移型 `fadeUp` 仅留给页面级标题与状态块。
- **UI-014（P0，🔒 口径 · v0.5.4 修订：仅复习卡）** **闪卡手势**（**只属复习卡**）：点击卡面 3D 翻转（`rotateY(180deg)`，`0.45s`，
  `backface-visibility:hidden`）；拖动跟手 `translateX(dx) rotate(dx*0.045deg)`；`|dx|<6px` 不动、`|dy|>|dx|` 放弃横拖
  （**竖向滚动优先，必须保留**）；阈值 `70px` —— **右滑 = 记得，左滑 = 忘了（方向不许反）**；
  飞出 `.out-r/.out-l`（`translateX(±135%) rotate(±16deg)`，`opacity .35`，`320ms ease-in`，`pointer-events:none`）后下一张 `.kc-in` 入场
  （`340ms cubic-bezier(.2,.8,.3,1)`）；拖动结束 **400ms** 内抑制 click；`.dragging` 关 transition + `user-select:none`；
  桌面鼠标拖拽同样支持；底部按钮**保留**；卡片下方一行提示；
  **提交先播 `340ms` 动画再落库，失败回滚动画与状态**；`prefers-reduced-motion: reduce` 关掉飞出/入场/旋转，只保留瞬时切换与数据提交。
  - **v0.5.7 补漏 · 底部按钮顺序（同属 UI-014，不另立 REQ）**：按钮**顺序必须与手势方向一致 —— 左「忘了」(`#k-again`) / 右「记得」(`#k-good`)**；
    `记得` = 主行动，accent 实心 `#1E7C50` **在右**；`忘了` 走 hairline，**不得**用 accent（与 UI-008「一屏一个主行动」一致）。
    **触发点**：任何闪卡自评 UI 渲染。**覆盖路径**：DOM 顺序（`js/review.js` 动作区）+ 空间顺序（`getBoundingClientRect` 实测）+ CSS 不得反转视觉顺序（`.actions` 禁 `row-reverse` / `direction:rtl`）。**无旁路**：复习页是唯一自评 UI（测验页为客观题，不走此组件）。
    **违规处置**：按钮顺序与手势反向、或「忘了」抢 accent → 回滚该 commit + 回规格重做。
    **机械断言**：`make ui-audit` ⑦（源码顺序 + DOM 实测左右位次与背景色）+ `tests/test_frontend.py::test_flashcard_direction_not_reversed`（反向即失败）。
  - **触发点**：复习卡任何手势或卡面改动。**覆盖路径**：`js/flashcard.js + js/review.js + css/app.css` 的 `.kc-*`，无旁路。
  - **v0.5.4 修订说明（为什么改掉「测验页」）**：M2-B1 把测验页从「问答自评 + 翻卡」改为**客观题**（选项按钮 / 对错两键 → 提交 → 即时判分）。
    客观题在**一屏内原地作答**，没有「下一张卡」的方向语义 —— 左滑/右滑若保留，会与「选错/选对」的直觉冲突，且与选项竖排的滚动争手势。
    故测验页**取消**闪卡手势（`js/quiz.js` 不再引用 `Flashcard`）；`make ui-audit` 与源码反向断言（`tests/test_frontend.py::test_quiz_no_longer_swipes`）守护此事。
  - **违规处置**：方向反了、阈值漂移、丢失竖向滚动优先、reduced-motion 未关动画 → 不得提交；
    测验页重新出现 `Flashcard` / 手势钩子 → 缺陷（回滚）。

- **UI-016（P0，🔒 口径 · v0.6.0）** **「知识卡片」命名**：原「挑新卡」一律改称**「知识卡片」** —— 首页快捷入口文案、
  `#/subjects` 的 `h1`（文案 = 「知识卡片」）、任何说明文案；**全站不得再出现「挑新卡」**（owner 2026-09-27 拍板）。
  - **触发点**：任何渲染入口/标题/说明的改动。**覆盖路径**：`backend/frontend/` 全部文案位（`index.html` + `js/*.js`），无旁路。
  - **违规处置**：出现「挑新卡」字面量 → 缺陷，禁止提交。
  - **机械断言**：`tests/test_frontend.py::test_knowledge_cards_naming`（全前端 `挑新卡` 计数 == 0；`subjectList` 的 `h1` 文案 == `知识卡片`）
    + `make ui-audit ⑧`（`#/subjects` 实测 `h1` 文案）。

- **UI-017（P1，🔒 口径 · v0.6.0）** **动效工艺两禁**（审美检测器 `impeccable detect` 曾报 `bounce-easing` / `layout-transition`，均属 craft-floor）：
  ① 缓动**不得过冲** —— `cubic-bezier()` 的 y 控制点一律 ≤ 1（禁 elastic / bounce / overshoot；进场用指数 ease-out `cubic-bezier(.16,1,.3,1)`）；
  ② 进度条/条形填充**禁动 `width`**（layout thrash）→ 用 `transform: scaleX()` + `transform-origin: left`。
  - **触发点**：任何 CSS 动效/进度条改动。**覆盖路径**：`css/app.css` 全部（`.rise` / `.bar i` / `.primary` / `details`），无旁路。
  - **违规处置**：出现 y>1 的贝塞尔、或 `transition` 含 `width` → 缺陷，回滚。
  - **机械断言**：`tests/test_frontend.py::test_motion_craft_floor`（正则扫 CSS：贝塞尔 y 控制点 ≤1；`transition` 声明不得含 `width`）；
    复核：`impeccable detect` 对 `backend/frontend` 零 `bounce-easing` / `layout-transition`。

- **A11Y-001（P0，🔒 口径 · v0.6.0）** **次级文字对比度 ≥4.5:1**：`--muted` 系次级文字对暖纸底（`--paper` `#FAF6ED`）的对比度必须 ≥4.5:1（WCAG AA 正文）。
  现状缺陷：旧 `--muted` `#8C8371` 实测 **3.5:1**（检测器 `low-contrast` 命中），本版必须调深。
  - **触发点**：任何改 `--muted` 或文字色的改动。**覆盖路径**：`css/app.css` 的 `:root` 令牌 + 所有 `.sub` / `.mlabel` 使用处，无旁路。
  - **违规处置**：实测 <4.5:1 → 缺陷，禁止提交。
  - **机械断言**：`tests/test_frontend.py::test_muted_contrast_aa`（读 `:root` 的 `--muted`/`--paper`，按 WCAG 相对亮度公式现算 ≥4.5）
    + `make ui-audit ⑫`（页面实测 `.sub` 的 computed color 对 body 背景算比值 ≥4.5）。

- **UI-018（P1，🔒 口径 · v0.10.0）** **覆盖率环形图**（编号说明：UI-017 已被「动效工艺两禁」占用，按 DESIGN_SPEC 现状就位为 UI-018）：
  覆盖率改用**绿色环形图**显示 —— inline SVG（禁外链库 / 禁 emoji / 禁第三方图表库）；进度用 `stroke-dasharray`；
  **底环 = `--hair`**、**进度环 = 唯一 accent `--green`**（禁新颜色）；**环心显示 `覆盖率 c%`**（`c` 只读后端 `mastery.coverage`，前端零计算）。
  - **触发点**：书页 / 学科页 / 首页学科块三处覆盖率显示。**覆盖路径**：`js/app.js`（`coverageRing` 单点）+ `css/app.css`（`.ring*`），**无旁路**。
  - **违规处置**：环进度比例与后端 `coverage` 偏差 >±0.5%、或进度环 computed 色 ≠ `rgb(30,124,80)`、或三处任一缺失 → 缺陷，回滚。
  - **机械断言**：`make ui-audit ⑱`（三处各 ≥1 环；`stroke-dasharray` 比例 == `coverage` ±0.5%；computed `stroke` == `rgb(30,124,80)`；环心文本含 `%` 且数字 == `coverage`）
    + `tests/test_frontend.py::test_coverage_ring_hooks`（源码：`stroke-dasharray` / `.ring-bg` / `.ring-fg` / `.ring-num` 在位）。

- **UI-019（P0，🔒 口径 · v0.12.0 · owner 2026-09-30 拍板「卡面显示子卡短名」）** **卡面 = 来源 + 子卡短名 + 题面 + 要点；概念名不得被挤掉**：
  - **短名定义**：`subtitle` = `cards.title` 里「` · `」**之后最后一段**；无分隔符 → 整条 title 即子卡标题；
    结果为空**或等于概念名**（未切分卡 `title = 概念名`）→ **`null`：不显示**（禁「合成示例书10 · 合成示例书10」式重复）。
  - **后端下发、前端零推导**：`subtitle` 由 `services/labels.subtitle_of()` **单点**算（`/api/cards`、`/api/today`、`/api/plan`
    都带该字段）；`js/*` **不得** `split(' · ')`、不得引用 `title` 自行切分。
  - **版式（卡面四要素）**：概念页 `#/concept/<id>` —— `h1` = **概念名**（仍可用、只出现一次），
    每张卡：**首行 = 子卡短名**（有则显示）→ 题面（`.q`）→ 要点（`.points`）→ 页脚 = 四态标签 + `已学 n 次` + **来源**；
    闪卡（`#/review`）与今日清单行、计划行的出处行 = `书 · 章 · 概念[ · 子卡短名]`。
  - **触发点**：概念页 / 闪卡 / 今日清单 / 计划 的任何卡面渲染或字段改动。**覆盖路径**：`api/cards.py`、
    `api/review.py`（`_label_cards`）、`services/plan.py`、`services/labels.py` + `js/app.js`、`js/review.js`、`js/plan.js`，**无旁路**。
  - **违规处置**：卡面缺短名 / 出现「X · X」重复 / 概念名被短名顶掉 / 前端自行切分 title → 缺陷，回滚。
  - **机械断言**：`make ui-audit ㉒`（① `/api/cards` 的 `subtitle` 必为 `title` 右段且 ≠ 概念名；② 概念页 `.block` 数 == API 卡数、
    短名在卡面**首行**、`h1` == 概念名；③ 未切分卡 `subtitle` 全 `null` 且页面无「X · X」；④ 队列有带短名卡时闪卡出处行必含短名；
    ⑤ `app.js`/`review.js`/`plan.js` 接 `.subtitle` 且无 `split(' · ')`）
    + `tests/test_cards.py::test_subtitle_of_derivation` / `test_unsplit_card_subtitle_is_none` / `test_today_and_plan_carry_subtitle`。

### 3.6 OPS — 运维与交付
- **OPS-001（P0）** `Makefile` 五目标：`lint`（ruff）/ `test`（pytest，`--cov-fail-under=94.5`，机器真值以 `Makefile` 为准）/ `smoke`（起 **5006** 临时端口打 `/health`；**必须自证**：端口被占、响应缺 `contract_version`、或 `version != app.py` 一律 FAIL —— 旧 5005 被 `org.example.review` 常驻占用，会静默验到别的 App）/ `deploy` / `backup`。
- **OPS-002（P0）** 版本三件套：`backend/app.py version` = `CHANGELOG.md` 段号 = spec `§12` 段号；**前端资产改动必须 bump `sw.js` CACHE + `index.html` 全部 `?v=`**（CF 强发 max-age，bump SW 不够）。
  - **v0.9.1 收紧（推翻 v0.5.1 的「前端可落后」）**：前端三件套版本必须 == app version（含纯后端 bump 也同步三件套）。
    **触发点**：任何版本 bump。**覆盖路径**：`sw.js` `CACHE`/`V` + `index.html` 全部 `?v=` + 页脚 `#ver`，无旁路。
    **违规处置**：`make smoke` 断言 `GET /` 每个 `?v=` == `/health` 的 `version`（不等即 FAIL）→ 回滚该 commit 并同步三件套。
- **OPS-003（P0）** 编码 agent **不 push、不重启服务、不碰 launchd**（由 pm 验收上线）；保护文件不追踪，严禁 `git add -A`。
- **OPS-004（P0，默认口径 · 可一句话改）** 提醒：**每天最多 1 条温和提醒**，触发条件 = 「当天有到期卡未清零且当天未打开 App」，默认时刻 20:00；**不做阶梯催学、不做静音出口**（保持口径统一）。
- **OPS-005（P1）** 备份：`org.example.review` 每日导库到 iCloud，保留 7 份；备份脚本与学习小组同构。

### 3.7 QUIZ — 出题与判分（✅ 后端 v0.5.4 实现 · 前端 v0.5.5 视觉打磨完成）

> 口径：题型从「问答自评」升级为**客观题**（选择 / 是非），**机械判分**，可落库、可进错题本。
> 生成复用「AI 学习小组app」`ai/agents.py`（quizzer）+ `ai/quizzer.py` 的做法（DeepSeek 生成草稿题），但**判分与出题分离**：判分绝不走 LLM。
>
> **状态（v0.5.4 · M2-B1）**：`services/quizgen.py`（出题：缓存优先 → LLM → 机械降级）+ `services/quiz.py`（会话 / 判分 / 错题本）
> + `data/models.py`（`quiz_items` / `quiz_attempts`）已落地，`api/quiz.py` 暴露 4 个新端点；测验页改为客观题（最小可用，**视觉打磨留 B2**）。
> 证据：`reports/quiz-2026-09-27.md`（真跑 curl）+ `tests/test_quiz.py`（逐条断言）。

- **QUIZ-001（P0，🔒 口径）** **题型**：**选择题（choice）+ 是非题（bool）**两种；**不出问答题（open）**，
  不引入主观题/填空题。每题必有唯一正确答案。
  - **触发点**：任何出题入口（会话生成 / 单题重刷 / 错题重刷）。
  - **覆盖路径**：`services/quiz*.py` 出题器 + `api/quiz.py` + 测验页，**无旁路**。
  - **违规处置**：出现 `type=open` 或题干需自由作答才能判分的题 → 不得上线。
  - **断言**：`tests/` 对出题结果逐题断言 `type ∈ {choice, bool}` 且 `answer_key` 非空、选项数 ≥2；
    会话响应中**不含** `answer_key` 字段（反向断言：题干响应零答案泄漏）。
  - **状态（v0.5.4）**：**✅ 后端 + 前端（最小可用）** —— `test_session_types_and_no_answer_key_leak` / `test_db_items_have_answer_key_and_type`；
    `POST /api/quiz/session` 只回 `id/card_id/type/stem/options/book/chapter`。

- **QUIZ-002（P0，🔒 口径）** **出题来源与缓存**：题目由 **AI 生成**（DeepSeek，做法照抄 `ai/quizzer.py`：
  以卡的 `front` / `back` 要点为上下文生成草稿题）→ **入库缓存**（表 `quiz_items`，`content_hash` 去重，
  **同题不重复生成**）→ 选择时**会话内不重复**、**跨会话尽量不重复**（优先取未作答过的缓存题）。
  - **触发点**：每次开一次测验会话 / 每次需要新题。
  - **覆盖路径**：出题服务 + `quiz_items` 表 + 会话选取逻辑，**无旁路**（不得绕过缓存直连 LLM）。
  - **违规处置**：同一 `content_hash` 二次生成入库 → 缺陷；生成前未查缓存 → 缺陷。
  - **断言**：① 同输入连跑两次 → 第二次 `新增 0`（幂等，仿 CARD-003）；② 一次会话内 `card_id` 不重复；
    ③ 跨会话优先命中未答缓存题（给出反例断言：缓存足够时不得重复出已答过的题）。
  - **状态（v0.5.4）**：**✅ 后端 + 前端（最小可用）** —— `test_second_run_adds_zero_items_and_calls_no_llm`（第二次 `_chat` 零调用）/ `test_session_card_ids_unique` /
    `test_cached_item_prefers_unanswered`；`content_hash = sha256(card_id|type|stem)` UNIQUE。

- **QUIZ-003（P0，🔒 口径）** **失败降级（保证永远能出题）**：LLM 不可用 / 超时 / 返空 → 降级为
  **机械派生**：由卡自身机械成题（是非题取 `answer_points` 一条为一命题；选择题**干扰项取同章其他卡的答案要点**），
  题干与选项全部来自库内已有文本，**不新增事实**（§5 契约纪律）。
  - **触发点**：LLM 调用返回错误 / 空 / 超时。
  - **覆盖路径**：出题服务降级分支，**无旁路**（任何 LLM 失败都必须走降级，不得直接报错让用户无题可做）。
  - **违规处置**：LLM 失败时抛错/空会话 → 缺陷；降级静默无日志 → 缺陷。
  - **断言**：mock LLM 返错/返空 → 仍返回 ≥1 题且每题 `source=fallback`；**降级必记 `logging.warning`**
    （`caplog` 断言 warning 存在）；干扰项断言：选项集合 ⊆ 同章卡答案要点 ∪ `{正确项}`。
  - **状态（v0.5.4）**：**✅ 后端 + 前端（最小可用）** —— `test_fallback_when_llm_fails`（None / 空串 / 非 JSON / 空 items，四种返错）+
    `test_fallback_choice_distractors_from_same_chapter`（干扰项 ⊆ 同章其他卡答案要点）。

- **QUIZ-004（P0，🔒 禁令）** **确定性判分**：choice/bool 一律**确定性判分** —— 用户所选与 `answer_key`
  **完全匹配 → 满分，否则 0**。**不得**引入 LLM 判分、模糊匹配或「大意对」。
  - **触发点**：任何作答提交（会话 / 重刷 / 错题重刷）。
  - **覆盖路径**：判分函数单一入口，**无旁路**（前端不判分、后端不调 LLM）。
  - **违规处置**：出现任何非确定性判分路径 → 缺陷（回滚）。
  - **断言**：对 `answer_key` 逐项对拍（正确 → 1；近义/大小写/前后空白 → 仍判**错**，除非规范化口径显式定义）；
    反向断言：判分代码无 LLM/网络调用（禁用 `requests`/`httpx`/`openai` 于判分路径）。
  - **状态（v0.5.4）**：**✅ 后端 + 前端（最小可用）** —— `quiz.grade()` 单一入口（**完全匹配**，不做 trim/大小写，口径显式写死）；
    `test_grading_module_has_no_network_client` 静态断言 `services/quiz.py` 无网络客户端字样。

- **QUIZ-005（P0，🔒 口径）** **得分口径（分子分母写死）**：一次 **N 题**、**每题等分**（每题 `1/N`），
  展示 `答对 x/y · 得分 z`，其中 **分母 y = 本轮总题数 N**（含未作答？→ **否**：`y = 已作答题数`，
  未答不入分母），**分子 x = 判对题数**，`z = round(x / y * 100)`（`y=0 → z=0`）。
  - **触发点**：测验进行中的进度、测验结束页、任何展示得分处。
  - **覆盖路径**：测验会话进度 API + 测验页，**无旁路**（前端不得自行另算一套）。
  - **违规处置**：分子分母口径漂移（如把未答计入分母、或按题难度加权）→ 缺陷。
  - **断言**：给定作答序列（含对/错/未答）→ 断言 `x/y/z` 精确值；`y=0` → `z=0`（反向断言除零）。
  - **状态（v0.5.4）**：**✅ 后端 + 前端（最小可用）** —— `GET /api/quiz/session/<sid>/result` 由库内 `quiz_attempts` 重算
    `answered/correct/score`；测例 `test_score_formula_with_correct_wrong_unanswered` / `test_score_zero_when_no_answers` / `test_score_rounding`（1/3 → 33）。

- **QUIZ-006（P0，🔒 口径）** **作答记录落库**：**每题**写入作答表（`quiz_attempts`：题 ID / 卡 ID /
  我的答案 / 对错 / 时间戳 UTC），供**错题本（WRONG-001）**与**掌握度（MAST-001）**使用；同一题重做**追加**记录
  （保留历史，不覆盖）。
  - **触发点**：每次提交作答（含重刷）。
  - **覆盖路径**：作答 API，**无旁路**（不得只在内存累计）。
  - **违规处置**：作答不落库 / 覆盖历史 → 缺陷。
  - **断言**：一次作答 → `quiz_attempts` +1 行且字段齐全；重复作答同一题 → 追加 N 行（不覆盖）；
    时间戳为 UTC ISO 8601。
  - **状态（v0.5.4）**：**✅ 后端 + 前端（最小可用）** —— `quiz_attempts(id,item_id,card_id,session_id,my_answer,is_correct,created_at)`，
    重复作答追加；测例 `test_repeat_answer_appends_rows_not_overwrite`（3 行、`created_at` 以 `+00:00` 结尾且可 `fromisoformat`）。

- **QUIZ-007（P0，🔒 口径 · v0.8.0 · owner 2026-09-27 拍板）** **题源 = 已学卡池**（作废「只从今日队列取题」）：
  会话题源 = **已解锁章内 `cards.status <> 'new'`** 的卡（= 已学卡），**不再**以「到期池 ∪ 未学新卡池」为唯一来源
  （旧行为导致「当天的卡学完 → 到期池 0 + 未解锁章吃掉全部 new 卡 → 只剩零星题」）。
  - **取卡优先级（写死）**：① 有错答记录（`quiz_attempts.is_correct = 0`，错次降序）→ ② 到期卡（`next_review_at ≤ now` 升序）
    → ③ 薄弱/久未练（`M_card`（MAST-001）升序，同级按距上次作答时间降序）→ ④ 其余已学卡（按 `next_review_at`、`id` 升序轮转，跨天不重复同批）。
  - **每日目标题数 = `QUIZ_TASK_TARGET`（GOAL-002：5）**；**已学卡池非空时必须凑满 `min(5, 池大小)` 题**，
    只有**一张已学卡都没有**时才允许空态（空态文案保持「无配额、不催」）。
  - **缓存复用**：同卡同题型命中 `content_hash` → **复用旧题，不重复调用 LLM**（QUIZ-002 缓存规则不变）；同一会话内 `card_id` 不重复。
  - **触发点**：`POST /api/quiz/session`。**覆盖路径**：`services/quiz.py::start_session` 单一入口，**无旁路**
    （错题重刷走 `retry_session`，不受本条影响；`services/queue.py` 仍是复习队列的唯一来源，**不因本条改动**）。
  - **违规处置**：已学卡池非空却 0 题、或题源回退到「仅到期 ∪ 新卡」→ 缺陷。
  - **断言**：`tests/test_quiz.py`：①队列为空 + 池中 5 张已学卡 → 会话必出 5 题（旧行为下 = 0 题）；②同一批卡二次开会话 → 复用缓存、**不新增** `quiz_items`、不调用 LLM；
    ③错题卡优先于其他已学卡；④池为空（无已学卡）→ 空态且 `size = 0`。

- **QUIZ-008（P0，🔒 口径 · v0.8.0 · 对齐 AI 学习小组）** **批改后逐题解析**（题干 + 选项 + 考生选项 + 正确答案）：
  - **单题判分即刻**：选项行标注「**正确答案**」（正确项）与「**你的选择**」（所选），**题干保持可见**（现状保留）。
  - **结果页**：**每一道已作答的题**（答对、答错都算）渲染一张解析卡 —— 结构照抄 AI 学习小组 `fmtWrongCard`：
    `题干` + **全部选项**（正确项标 `✅ 正确答案`、所选标 `❌ 你的答案`）+「你的答案」+「参考答案」；
    bool 题按文本渲染，choice 题按选项文本渲染（**不得**只回显索引）。
  - 保留既有「答对 x / 已作答 y · 得分 z」与返回入口；错题本页（WRONG-001）保持既有形态。
  - **后端**：`GET /api/quiz/session/<sid>/result` 增字段 `items: [{item_id, card_id, type, stem, options, my_answer, correct_answer, is_correct}]`
    （**追加不破坏**：`wrong` 字段保留，向后兼容）。
  - **触发点**：作答提交后、会话结束。**覆盖路径**：`services/quiz.py::result` + `js/quiz.js::finish`，无旁路。
  - **违规处置**：结果页缺题干/选项/正确答案任一、或只列错题 → 回滚。
  - **断言**：`tests/test_quiz.py`（`result.items` 题数 = 已作答题数、字段齐全、`my_answer` 与 `correct_answer` 对错关系正确）
    + `make ui-audit`（新组：结果页解析卡数量 = 已作答题数，每张卡含题干/选项/「正确答案」标记）。

> **QUIZ-009（P0，🔒 口径 · v0.8.3 · owner 2026-09-28 拍板「下一题就代表提交，省得按两次按钮」）** **分页按钮即提交动作：页面内不做逐题判分**：
> - 流程：点选项 = **只做选中**（`.sel` 高亮，**不判分、不发请求**）→ 底部唯一按钮「**下一题**」（末题 = 「**看结果**」）→ **点它才提交**（`POST /api/quiz/answer`）**并推进**；每题 2 击（旧版「选 → 提交 → 下一题」3 击）。
> - **页面内不显示逐题对错**：选项**不得**出现 `correct` / `wrong` 标色，也不得出现「你的选择 / 正确答案」标记；判分结果统一在**结果页逐题解析**（QUIZ-008，不变）呈现。
> - **不再有「提交」按钮**：`#q-submit` 元素与「提交」文案从 `js/quiz.js` **移除**。底部按钮 id 固定为 `#q-next` 且**常显**：未选中 → `disabled` + `.why` 文案「请先选择答案」（UI-003：常显置灰写明原因，**绝不隐藏**）；已选中 → 启用，末题文案「看结果」。
> - **失败不前进**：提交失败 → 停在本页 + 错误行提示，按钮恢复可用可重试；不得跳题、不得丢已选项。
> - **幂等防双写**：提交进行中按钮 `disabled`，连点不得发出第二个 `POST`。
> - 判分仍在后端（QUIZ-004 不变），`answer_key` 仍不下发前端。
> - **触发点**：`#/quiz` 作答（含错题本一键重刷 `QuizView.run()` 复用路径）。**覆盖路径**：`js/quiz.js`（唯一作答 UI），无旁路。
> - **机械断言**：`make ui-audit ⑰` 改造：无 `#q-submit`；未选中 `#q-next` 置灰并含「请先选择答案」；点选项后无逐题标色；点按钮后题干推进且已作答数 +1；末题看结果后解析卡数等于已作答数。

- **QUIZ-010（P0，🔒 口径 · v0.9.0 · owner 2026-09-29 拍板）** **题面语言跟随卡语种**：按 `front + back` 的确定性 CJK 比例函数选择中文/英文提示词与 bool 标签。
> - **触发点**：生成判断题或渲染结果解析卡。
> - **覆盖路径**：`services/language.py` 单点判定 + `quizgen` 生成/校验 + `quiz` 降级数据契约 + `js/quiz.js` 结果渲染，无旁路；所有 bool 标签均来自 options，前端不判定语言。
> - **违规处置**：标签与卡语种不符或 `answer_key` 不逐字命中 options → 拒绝题目并走降级。
> - **机械断言**：`test_card_language_boundaries`、`test_english_bool_validation_requires_exact_labels` 覆盖中文/英文/混排边界与精确匹配；UI ⑰ 覆盖解析标记。
> - 结果解析卡：`.opt.mine` 恰 1 个；答对仅 `.correct` + `✓`，答错 `.mine.wrong` + `✗` 且正确项 `✓`；无底部答案行、无 emoji。

- **QUIZ-011（P0，🔒 口径 · v0.9.1 · owner 2026-09-29 拍板）** **卡文变化 → 缓存失效（题面跟随卡文）**：
  `quiz_items` 复用前必须校验其 `card_content_hash` 与**该卡当前** `front/back` 的 `content_hash` 一致；
  不一致 → 视为未命中、重新出题并**同 `id` 覆盖**该行（保留 `id`，不删不插，`quiz_attempts` 外键与行数不动）。
  - **触发点**：`quizgen.cached_item`（缓存命中判定）+ `quizgen.ensure_items`（重生落库路径）。
  - **覆盖路径**：`quiz_items.card_content_hash`（出题时该卡 front/back 指纹，与 `cards.content_hash` 同源）+ 迁移回填，
    **无旁路**（任何卡文被 reswap/改字后，旧题 `card_content_hash` 必与卡当前 `content_hash` 不符 → 不再命中）。
  - **违规处置**：卡文已变却仍复用旧题 → 缺陷；重生时删/插行导致 `quiz_attempts` 断链 → 缺陷。
  - **断言（可证伪）**：①「卡文语种 = 题面语种」—— 英文卡题面不得含汉字、中文卡不得出现 `True/False` 选项
    （`test_quiz_refresh.py::test_is_stale_language_boundaries` + 刷新后 `stale_rows` 为空）；②「卡文变化 → 题面重生」——
    把某卡 `front`/`back` 改一字后取题必重新生成（`test_card_text_change_regenerates_in_place_preserving_attempts`，
    断言同 `id` 覆盖、行数不变、`quiz_attempts` 关联不变）；③ `quiz_attempts` 计数刷新前后不变（本轮生产实测 = 58）。
  - **一次性刷新脏数据**：`backend/scripts/refresh_stale_quiz_items.py`（默认 dry-run / `--apply` 落地）把生产库 mgmt 10 条
    中文旧题按新英文卡同 `id` 覆盖重生；刷新后 `quiz_attempts` 58 行及逐题关联全不变（实测）。

- **QUIZ-012（P0，🔒 口径 · v0.13.1 · 2026-10-03 owner 报障后固化）** **题型必须逐字兑现 + 干扰项不得取「纯名词标签」**：
  ① **题型兑现**：提示词必须**按题型分别给规则**，并给**与各卡 `want` 同型**的 JSON 骨架；LLM 返回的 `type` ≠ 请求的 `want`
  → 该卡产出**一律作废**（走降级）并记 `logging.warning`（"题型不符"）。**禁止**在提示词里给出与请求题型的样例
  （旧版骨架写死 `{"type":"bool",…}` 且规则只讲判断题 → 模型照抄样例，要选择题也返 `bool`）。
  ② **干扰项质量**：机械降级的选择题，其干扰项（含正确答案本身）**不得是纯名词标签**（判据 `is_gloss_label`：
  形如「了解（knowledge）」「care (care)」的「词＋括号英文」且无任何句读），且须**按 `card_id` 确定性抽签**产生
  （同库同卡结果逐字可复现，但同章不同卡的干扰项不得恒等）；抽签前先按「与正确答案长度相近」取候选，
  可用干扰项为 0 → 该题降级为是非题（不生造烂选择题）。
  - **触发点**：`quizgen._system_prompt`（提示词构造）、`quizgen._validate`/`llm_batch`（题型校验）、
    `quizgen.mechanical_item` + `pick_distractors`（机械干扰项选取）、`refresh_stale_quiz_items.reason_of`（脏题判据）。
  - **覆盖路径**：LLM 路径与降级路径**两条都要过**（`_validate` 拒收 → 降级 → 降级仍不得产出标签干扰项），**无旁路**。
  - **违规处置**：题型不符的产出被采纳 → 缺陷；干扰项为纯名词标签、或同章多题干扰项恒等 → 缺陷；
  `source='fallback'` 的选择题被当作干净缓存长期复用 → 缺陷（须由刷新脚本重生）。
  - **断言（可证伪，旧实现下 5 条全红，实测）**：① `test_prompt_skeleton_follows_wanted_types`（要选择题时骨架不得含 `type":"bool"`）；
  ② `test_llm_batch_rejects_wrong_type_and_warns`（返错题型 → 空 + warning）；
  ③ `test_mechanical_choice_never_uses_gloss_label_distractors` / `test_gloss_label_boundaries`；
  ④ `test_mechanical_choice_distractors_vary_between_cards`（旧实现 `pool[:2]` → 全章干扰项恒为 `{了解（knowledge）, 关心（care）}`，断言 `len(set(pairs)) > 1` 直接红）；
  ⑤ `test_mechanical_degrades_to_bool_when_correct_is_label`；
  ⑥ 刷新：`test_reason_of_covers_fallback_choice` / `test_refresh_regenerates_fallback_choice_in_place` /
  `test_refresh_keeps_warning_when_llm_still_wrong_type`（LLM 不可用时只 warning，不崩、不删行）。
  - **一次性刷新**：`refresh_stale_quiz_items.py` 的脏题判据新增 `fallback_choice`（`source='fallback'` 且 `type='choice'`），
    同 `id` 覆盖重生；`language` 类刷新后必须为 0（断言），`fallback_choice` 残留只 warning（不许把 LLM 故障当刷新失败）。

- **QUIZ-014（P0，🔒 口径 · v0.16.3 · 2026-10-13 owner 报障后固化）** **选项呈现顺序不得固定（正确答案位置近似均匀）**：
  ① **根因**：旧提示词骨架把正确项写成第一项（`"options":["选项一",…],"answer_key":"选项一"`）→ 模型照抄位置
  → 生产库 76 题里 **72 题（94.7%）正确答案都在首位**（选择题 97%），已有作答记录里 93.6% 选 A，等于白送。
  ② **口径**：题面交付前端的**唯一出口**必须对 `options` 做**按（会话 id, 题 id）播种的确定性置换**：
  **同一会话内同一题顺序恒定**（结果页必须复现用户当时看到的顺序），**跨会话重新置换**（位置记不住）。
  打乱是**呈现层保证**：库内 `quiz_items.options` 原样保留，缓存复用与幂等（QUIZ-002/011）不受影响。
  ③ **不得改判分**：仍按**文本**比对（QUIZ-004），`answer_key` 仍不下发（QUIZ-001）；「选项在第几位」不得成为判分依据。
  ④ **提示词侧同时拆除位置暗示**：选择题骨架三条选项文字**同形**、`answer_key` 不落在固定位置；规则显式写「禁止总放在第一项」。
  - **触发点**：`quiztext.display_options`（唯一置换函数）、`services/quiz.public_item`（会话下发）、
    `services/quiz.result`（结果页逐题解析）、`quiztext.choice_example` + `system_prompt`（骨架与规则）。
  - **覆盖路径**：会话出题（`start_session`）、错题重刷（`retry_session`）、结果页（`result`）**三条都要过，无旁路**；
    今后任何新增下发 `options` 的入口都必须走 `display_options`（`public_item` 的 `ctx` 为必填参数，漏传即 TypeError）。
  - **违规处置**：任一位置占比 > 60%、或三个位置未全部出现、或结果页顺序与作答时不一致 → 缺陷，回滚该 commit。
  - **断言（可证伪）**：`tests/test_quiz_option_order.py` —— ① 300 题正确答案恒首位 → 呈现位置覆盖 {0,1,2} 且无位置 > 45%；
  ② 同会话恒定 + 跨会话重排 + 退化输入（<2 项）原样返回；③ 4 题 × 12 会话集成：库内位置全为 0，呈现位置必须散开；
  ④ 零 `answer_key` / `correct_answer` 泄漏；⑤ 结果页选项顺序 == 作答时顺序。
  **反证实测**：临时关闭 `display_options` 里的打乱 → ①②③ 三条立即变红（已跑，随后还原）。

## 3.8 MAST — 掌握度（✅ v0.5.5 实现 · 后端 `services/progress.py` + 前端四级展示）

- **MAST-001（P0，🔒 口径 · 2026-09-27 owner 拍板 · **两个 app 同一套**）** **统一掌握度：卡级公式 + 四级 rollup + 覆盖率并列显示**
  - **L1 卡级**：`state ∈ {new, learning, reviewing, mastered}`（内部值两个 app 统一；显示 未学习/学习中/复习中/已掌握）；
    `state_score` = new 0 / learning 40 / reviewing 70 / mastered 100；
    `acc`（作答正确率）= `Σ(w·earned) / Σ(w·earned_max)`，`w = 0.5^自作答起的周数`（半衰期 1 周）；
    作答事件 = 闪卡自评（记得 1 / 忘了 0，满分 1）+ 练习题与测评（earned = score，possible = points）；
    无作答事件 → `acc = null`、`evidence = false`、`M_card = state_score`；
    `M_card = round(0.5 × state_score + 0.5 × acc)`（`acc = null` 时 `M_card = state_score`）。
    **卡级 `mastered` 判定 = 调度器条件 且 作答事件 ≥ 2 且 `acc ≥ 80`**（治「一道题就掌握」）。
  - **L2/L3/L4（章 / 书 / 学科）= 同一条公式、不同集合**：
    `learned` = 该层 `state ≠ new` 的卡数；`cards_total` = 该层全部卡数；
    `M_level = round(Σ_{learned} M_card / learned)`；`learned = 0` → `m = null, started = false`（**不除零**）；
    `coverage = round(learned / cards_total × 100)` —— **覆盖率是独立指标，与掌握度并列显示**（不是分母、不参与 M）；
    `evidence_cards` = 该层 `evidence = true` 的卡数。
  - **层级四态（章 / 书 / 学科）**：词表与卡级四态**含义不同、不得挤在同一 UI 位** ——
    `已掌握` ⟺ `M ≥ 80` 且 `evidence_cards ≥ max(2, ceil(cards_total × 0.2))`；
    `进行中` ⟺ `M ≥ 50`；`薄弱` ⟺ `learned > 0 且 M < 50`；`未评估` ⟺ `learned = 0`。
  - **废除的旧口径（写进规格以免复活）**：① 卡级 0/1（`mastered / 已学`）；②「已掌握卡按 5 分满分、**仅奖不罚**」；
    ③ 测评 / 练习分数**直接**进层级 M（今后一律只经卡级 `acc` 进入）。
  - **单一计算点**：本 app 的掌握度实现模块为**唯一**实现（复习 app `services/progress.py` / 学习小组 `ai/mastery.py`）；
    API 一律下发 `mastery: {m, learned, cards_total, coverage, evidence_cards, state, state_label}`；
    **前端零计算、零映射**（沿用既有铁律）。
  - **触发点**：任何计算或展示掌握度的位置（含通知文案、排行、周报）。
  - **覆盖路径**：后端计算模块 + 全部 API + 全部展示页 + 通知文案，**无旁路**。
  - **违规处置**：层级 M 用了别的分母或别的权重、覆盖率缺失、前端自算 → 缺陷，回滚。
  - **机械断言**：`tests/test_mastery_unified.py`（构造已知库：4 卡 = mastered/acc100、learning/acc0、new、new →
    卡级 `100 / 20 / 0 / 0`；章级 `M = 30`、`coverage = 50%`、`evidence_cards = 2`；阈值边界 79/80/49/50 与证据门槛；
    `learned = 0` 不除零）+ `make ui-audit ⑮`（四级**同时**渲染 `掌握度 x%` 与 `覆盖率 y%`）；
    反断言：前端源码不得出现 `mastered` 除法或四态映射表。
  - **汇总不得冒名单值（沿用 DATA-005）**：学科 / 书级是**跨章 / 跨书的聚合**，只能是聚合数字（M + 覆盖率），
    **不得**以「第 N 章」之类单值冒充；`learned = 0` 时按「未评估」而非除零。

- **MAST-002（P0）** **展示**：四级**每级**都要有**进度条 + 百分比**，且**四级都能点进去钻取**
  （学科 → 书 → 章 → 卡），与 UI-001 钻取式导航一致；进度条走设计令牌（UI-006）。
  - **触发点**：掌握度展示相关改动。
  - **覆盖路径**：首页学科进度行 / 学科页 / 书页 / 章 / 卡，**无旁路**。
  - **违规处置**：某级只有数字无进度条、或不可钻取 → 缺陷。
  - **断言**：`make ui-audit` 扩展点（路由可达 + 每级进度条存在）；源码断言各级均渲染 `.bar` 与百分比文案。
  - **状态（v0.5.5）**：**✅ 实现** —— 首页/学科列表 `.progline .bar` + 百分比；书页 `.meter .bar`；章行 `.chap .bar`；
    卡级 `js/app.js::cardMastery`（`已掌握` / `未掌握`，令牌色文字、非 emoji）。分母 0 → 「未开始」（`UI.mLab`）。
    证据：`scripts/ui_audit.js` 循环断言四级 `.bar` 存在；`tests/test_frontend.py::test_mastery_bar_and_percent_four_levels`。

- **MAST-003（P0，🔒 口径 · v0.6.0）** **卡片四状态标签（与调度状态机一一对应 · 前端零计算）**：

  | 库内 `cards.status` | 唯一标签 |
  |---|---|
  | `new` | **未学习** |
  | `learning` | **学习中** |
  | `review` | **复习中** |
  | `mastered` | **已掌握** |

  - 标签由**后端下发**（`api/cards.py` / `api/review.py` 响应字段 `status_label`），前端**只读、不映射**（前端零计算铁律）；
    未知 `status` → 后端回落「未学习」并**记 warning**（不得静默）。
  - **每张卡必有状态**：卡列表 / 闪卡复习页 / 复习计划 / 错题本的**每一张卡**都要显示四态之一；
    v0.6.0 前只显示「已掌握 / 未掌握」两态 → 属缺陷（掌握度因此不可解释，owner 2026-09-27 指出）。
  - **触发点**：任何渲染单张卡的改动。**覆盖路径**：后端 `api/cards.py`（唯一标签来源）+ `js/app.js`（卡列表）/ `js/review.js`（闪卡）/
    `js/wrong.js` / `js/plan.js`，无旁路。
  - **违规处置**：前端出现 status→中文映射表、或某张卡无状态标签 → 回滚。
  - **机械断言**：`tests/test_cards.py::test_status_label_four_states`（四态 → 四标签；未知态 → 未学习 + warning）
    + `tests/test_frontend.py::test_card_status_labels_from_backend`（反断言：前端不得出现四词映射表）
    + `make ui-audit ⑪`（卡页每张卡的标签 ∈ 四词表）。

- **MAST-004（P0，🔒 口径 · v0.6.1 立规 / v0.7.0 换公式 / v0.10.1 数值去重）** **掌握度口径必须自解释（公式 + 分子分母 + 覆盖率可见，分母不许错位，数字不重复）**（owner 2026-09-27：「掌握度我的计算公式」；owner 2026-09-30：「学科行只留已学/共，86%/14% 交给环与星」）：
  - **数值去重（v0.10.1 修订）**：某层级若已渲染「覆盖率环形图 + 掌握度五星」，其**文字行不得再重复**掌握度/覆盖率数字
    （只留 `已学 x / 共 y` + 状态标签）；**未渲染环星的层级**，文字行保留双数 `掌握度 m% · 覆盖率 c%`。
    环心写覆盖率、星旁写掌握度，**全站每个数字在每个层级只出现一次**。
    环星两态（v0.11.1 补）：**有已学卡** → 星旁 `掌握度 m% · n 星`；**无已学卡（`mastery.m === null`，
    新入库学科即此态）** → 星位显「**掌握度 —**」，**不得显 0%**，覆盖率（= 0%）照常显示。
    这与下面三数规则的 `—` 口径同源，**不得为了「形态统一」给无证据层级编一个 0% 掌握度**。
  - 每一级掌握度出现处**同时显示**：`掌握度 {m}%`、`覆盖率 {coverage}%`、`已学 {learned} / 共 {cards_total}`
    （三个数字**只读后端** `mastery.{m,coverage,learned,cards_total}`，**前端零计算**）；
  - **学科页与书页必须常显口径说明句**（原文固定，不得改写、不得省略）：
    「掌握度 = 已学卡掌握度平均（卡级 = 50% 状态分 + 50% 作答正确率）；覆盖率 = 已学卡 ÷ 全部卡」
  - **禁止分母错位**：**覆盖率不得冒充掌握度分母** —— v0.6.0 前的 `掌握 0% · 已学 2/237` 属缺陷；
    掌握度括号里只能是「已学卡」的聚合，总卡数一律写「共 N 张」，**不得混进掌握度括号**。
  - **触发点**：任何渲染层级汇总的改动。**覆盖路径**：`js/app.js`（首页学科进度 / 学科列表 / 书页 / 章行）+ `services/progress.py`（唯一数字来源），无旁路。
  - **违规处置**：缺三数中任一项、口径说明句缺失、覆盖率与掌握度混用分母、前端自算、或**同一层级数字重复**（文字行又重复环星已有的掌握度/覆盖率）→ 缺陷，回滚。
  - **机械断言**：`make ui-audit ⑬`（渲染环星的层级：文字行匹配 `^已学 \d+ / 共 \d+ · ` 且不含「掌握度」「覆盖率」，
    同一行环心含 `覆盖率 <后端 coverage>%`、星旁**按后端 `mastery.m` 分流两态**——
    有证据 `^掌握度 <后端 m>% · \d(\.\d+)? 星$`、无证据（`m === null`）恰为 `掌握度 —`，逐行对回 `/api/subjects`；
    未渲染环星的层级：保留双数全文（无已学卡显 `掌握度 —`）；口径说明句常显；
    **反断言**：① 把文字行改回带 `掌握度 86% · 覆盖率 14%` → 断言必须 FAIL；
    ② 把无已学卡层级的星位文案改成 `掌握度 0%`（或去掉星位 `aria-label`）→ 断言必须 FAIL）
    + `tests/test_frontend.py::test_mastery_formula_visible`（源码断言 `mCount` 短文案 / `mText` 双数文案分工 + 反断言无 `已学 \d+/237` 混写）。

- **MAST-005（P0，🔒 口径 · v0.6.1）** **概念行显示卡状态（钻取路径上每张卡的状态可见）**（owner 2026-09-27：「前端看不到卡片状态」）：
  - 章展开后的**每一个概念行**必须显示该概念下卡片的状态：**全部同态** → 该态标签（四词表 UI）；**多态** → 四态计数（例 `未学习 2 · 学习中 1`，顺序固定 新→学→复→掌）；
  - 状态与计数**一律由后端下发**（`/api/concepts` 的 `status_label` / `status_counts`），前端**只读**；
  - **触发点**：章展开渲染、`/api/concepts` 响应。**覆盖路径**：`api/concepts.py`（唯一来源）+ `js/app.js` 概念行（唯一渲染点），无旁路。
  - **违规处置**：概念行无状态、或前端自行统计状态 → 缺陷。
  - **机械断言**：`make ui-audit ⑭`（书页展开首章：概念行数 > 0 且**每行**文本含四词表之一 + `N 张卡`）
    + `tests/test_concepts.py::test_status_counts_and_label`（四态分布 → 计数与标签正确；未知态 → 未学习 + warning）
    + `tests/test_frontend.py::test_concept_row_status_from_backend`（反断言：前端不得出现四态映射表）。

- **MAST-006（P0，🔒 口径 · v0.7.0）** **层级四态（章 / 书 / 学科）阈值与最小证据**（治「几道题就掌握」）：
  `已掌握` ⟺ `M ≥ 80` **且** `evidence_cards ≥ max(2, ceil(cards_total × 0.2))`；`进行中` ⟺ `M ≥ 50`；
  `薄弱` ⟺ `learned > 0 且 M < 50`；`未评估` ⟺ `learned = 0`。四态**由后端下发**（`mastery.state` / `mastery.state_label`）。
  - **触发点**：任何显示层级掌握状态的位置（含通知文案、周报、解锁提示）。**覆盖路径**：`services/progress.py` + 全部展示页 + `services/*` 通知文案，**无旁路**。
  - **违规处置**：任一位置自行用别的阈值或只按题目对错定状态 → 缺陷，回滚。
  - **机械断言**：`tests/test_mastery_unified.py` 覆盖 `79/80`、`49/50`、证据门槛 `max(2, ceil(0.2n))` 边界；
    反断言：全仓 grep 不得出现第二处 `>= 80` 式掌握状态判定（只允许 `services/progress.py` 一处）。

- **MAST-007（P0，🔒 口径 · v0.7.0）** **四态内部值统一为 `new / learning / reviewing / mastered`**（与 AI 学习小组一致）：
  本 app 现行 `review` 一律迁移为 `reviewing` —— 含 `cards.status` 的 CHECK 约束、后端全部 SQL 与导出契约的 `status` 字段、
  前端词表与测试夹具；**显示词不变**（未学习 / 学习中 / 复习中 / 已掌握）。迁移脚本必须**幂等**、先备份 `data-local/review.sqlite3`。
  - **触发点**：任何读写卡片状态的位置。**覆盖路径**：`backend/data/*`、`backend/api/*`、`backend/services/*`、`backend/scripts/*`、前端、测试，**无旁路**。
  - **违规处置**：残留 `'review'` 状态字面量、或两套值并存 → 缺陷。
  - **机械断言**：`sqlite3 data-local/review.sqlite3 "SELECT COUNT(*) FROM cards WHERE status='review'"` = 0；
    全仓 grep `'review'` 作为**状态字面量**为 0 处；`tests/test_status_vocab.py::test_only_reviewing_four_states`。

- **MAST-008（P1，🔒 口径 · v0.10.0）** **掌握度五星图**：
  `stars = round(m / 20, 1)`：86% → **4.3 星**（保留原百分比与进度条，**不做替换**）。
  5 颗 **inline SVG** 星；小数部分用 **clip/mask 遮罩**（overlay clip）表达，**不得用圆点近似**；
  **空星 = `--hair`**、**实星 = accent `--green`**；常显一行 `掌握度 86% · 4.3★`（`★` 用 **SVG**，**不是字符/emoji**）；数值只读后端 `mastery.m`，前端零计算。
  - **触发点**：学科页 / 书页 / 首页学科块（与 UI-018 同块）的掌握度显示。**覆盖路径**：`js/app.js`（`starsOf` / `masteryStars` 单点）+ `css/app.css`（`.stars*`），**无旁路**。
  - **违规处置**：`m=86` 实星填充比例 ≠ 4.3/5、`m=0` 非 0 星、`m=100` 非 5 星、`m` 缺失非 `—`、或出现 emoji / 字符 `★` → 缺陷，回滚。
  - **机械断言**：`make ui-audit ⑲`（`MasteryGauge.starsOf({m:86})==4.3`；`m=0/100/null` 边界；三处页面无 emoji）
    + `tests/test_frontend.py::test_mastery_stars_hooks`（源码：`clipPath`/`clip-path`、`--hair`/`--green` 填充、`starsOf` 单点换算在位）。

### 3.9 WRONG — 错题本（✅ v0.5.5 前端 + 后端实现）

- **WRONG-001（P0）** **错题本**：以**卡为单位聚合**错题（依据 `quiz_attempts` 判错记录），**按错次降序**排列；
  每条**可展开**看「**正确答案 / 我的答案**」；**可一键重刷**（对该卡发起一次单题测验，作答追加 `quiz_attempts`）。
  - **触发点**：进入错题本 / 重刷错题。
  - **覆盖路径**：`api/quiz.py`（错题查询 + 重刷）+ 错题本页，**无旁路**。
  - **违规处置**：按「答题次数」而非「错次」排序、或不可展开对照答案 → 缺陷。
  - **断言**：造 2 卡（错次 3 / 1）→ 断言排序为 [3,1]；展开返回 `correct_answer` 与 `my_answer` 两字段；
    重刷后 `quiz_attempts` 追加且错题本计数随之更新。
  - **状态（v0.5.5）**：**✅ 后端 + 前端全部实现** —— 后端 `GET /api/wrong` + `POST /api/wrong/retry`；
    前端 `#/wrong` + `js/wrong.js`（按卡聚合、错次降序、`details` 展开对照、一键重刷复用 `QuizView.run`、空态「还没有错题」+ 指路）。
    证据：`tests/test_quiz.py::test_wrong_book_sorted_desc_and_expandable` / `::test_wrong_retry_appends_and_updates_count`；
    `tests/test_frontend.py::test_wrong_book_page_hooks`；`scripts/ui_audit.js` 断错题本页可达且非空白。

### 3.10 HOME — 首页（✅ v0.5.5 实现 · `services/quotes.py` + `GET /api/quote` + 首页重构）

- **HOME-001（P0，🔒 口径）** **首页每日格言**：格言**当天固定**、**按日轮转**——
  索引 = `自固定起始日（`QUOTE_EPOCH`）起的天数 % 句数`（同一自然日恒定，跨日切换）；
  **不带未经验证的出处**（**不编造作者/来源**，无出处就只出句、不署名）；**列表为空回落**「今日复习」
  （不得空白、不得编造）。
  - **触发点**：首页渲染 / 日切。
  - **覆盖路径**：首页格言组件 + 格言数据源，**无旁路**。
  - **违规处置**：同一天两次访问格言不一致、或出现编造作者 → 缺陷。
  - **断言**：冻结「今天」→ 连取两次 ID 相同；跨一日 → 索引 +1（模句数）；数据源为空 → 回落文案；
    反向断言：数据源每条要么无 `author` 字段、要么 `author` 来自白名单（不得运行期拼接）。
  - **状态（v0.5.5）**：**✅ 实现** —— `services/quotes.py`（`QUOTES` 48 句纯字符串、**无 author 字段**；`QUOTE_EPOCH=2026-01-01`；
    `quote_index = (本地日 - epoch).days % 句数`；空表 → `{id:null, text:"今日复习"}`）+ `GET /api/quote`；
    首页大标题 = 格言。证据：`tests/test_quotes.py`（同天同 ID / 跨日 +1 / 空表回落 / 无 author / 不除零）；
    `scripts/ui_audit.js` 连取两次同 ID + 首页大标题等于 API 文案。

### 3.11 TASK — 今日任务与打卡（✅ v0.5.5 实现 · `services/tasks.py` + `GET /api/task`）

- **TASK-001（P0，🔒 口径）** **今日任务清单 / 打卡**：
  - **任务构成**：**今日复习 N 张**（N = 当天到期卡数）+ **出题 M 题**（M = 今日测验目标题数，配置文件化）。
  - **完成判定**：复习已完成数 ≥ N **且** 测验已完成数 ≥ M → 当日**任务完成**；两子项各自单独可勾。
  - **与连胜的关系（2026-09-27 改写 · 旧口径作废）**：连胜**只读展示**，**不催促**（沿用 OPS-004 / SCHED-003：无配额、无催学、无弹窗）；
    但**自 2026-09-27 起，当日目标的达成与否直接决定连胜**（STREAK-001）：`done = true` ⇔ 当日连胜计入。
    「任务完成与否**不改变**连胜定义」的旧口径**作废**（owner 2026-09-27 拍板：每日连胜目标 = 30 卡 + 5 题）。
  - **触发点**：首页/今日页渲染、日切、完成动作。
  - **覆盖路径**：任务计算服务 + 今日页，**无旁路**。
  - **违规处置**：出现催促文案/阶梯提醒、或任务完成反过来改写连胜口径 → 缺陷。
  - **断言**：造 N=3/M=10 → 复习 3、测验 10 后 `done=true`；`done=false` 时不得出现催学文案
    （反向断言：禁用词表，见 `tests/test_frontend.py::test_no_nagging_copy`）；`done` 与连胜**同一入口**（STREAK-001：`done=true` 才计入当日连胜，未达成不得虚增）。
  - **状态（v0.5.5）**：**✅ 实现** —— `services/tasks.py`（N = `当前仍到期 ∪ 今日已复习`，一天内稳定；M = `config.QUIZ_TASK_TARGET`）
    + `GET /api/task`；首页「今日任务」两子项（各自可勾，纯 CSS 勾选框）+ 快捷入口。
    （**v0.8.0 变更**：M 默认 10 → 5；连胜不再「任务不改写」——见 STREAK-001。）
    证据：`tests/test_tasks.py`（N=3/M=10 完成 / 部分完成不 done / 分母 0 / 昨日不计入 / API）；`tests/test_frontend.py::test_home_daily_quote_and_task_hooks`。

- **TASK-002（P0，🔒 口径 · v0.6.0）** **今日任务行动按钮（对齐 AI 学习小组）** —— 任务子项**不得只有勾位/整行链接**，按完成态渲染行动控件：
  - **未完成** → 按钮**「去完成」**（复习 → `#/review`；出题 → `#/quiz`），`href` 指向该子项目标路由；
  - **已完成** → **绿勾**（`✓` = accent 草绿描边，**禁 emoji**）**且同时**渲染按钮**「再来一组」**（复习 → `#/review?extra=1`；出题 → `#/quiz`）；
  - 进度「已完成 x / 目标 N」**常显**；**目标值一律后端下发**（`GET /api/task`），前端**禁硬编码**任何阈值。
  - **触发点**：首页任务块渲染（含完成态切变）。**覆盖路径**：`js/app.js::taskRow()`（唯一渲染点）+ `/api/task`（唯一数据源），无旁路。
  - **违规处置**：完成态缺「再来一组」、未完成态缺「去完成」、用 emoji 当勾、或前端硬编码阈值 → 回滚。
  - **机械断言**：`make ui-audit ⑨`（造两态实测：未完成 → 存在含「去完成」的可点控件且 `href` == 目标路由；
    完成 → 存在 `.tick.on` **且**存在含「再来一组」的可点控件；全页无 emoji）+ `tests/test_frontend.py::test_task_row_actions`（源码断言两个按钮 + 无字面阈值）。

- **GOAL-001（P0，🔒 口径 · v0.6.0）** **每日复习卡片目标 = 30 张**（owner 2026-09-27 拍板；新增 `config.REVIEW_TASK_TARGET`，默认 30，env 可覆写 = 单一真相）：
  - 今日任务「复习卡片」的 `target` = **30**（**不再**等于「当天到期数」）；
  - **补足规则（拍板原话：不足时用新卡自动补足到 30）**：到期 < 30 时**用未学新卡（`status='new'`）自动补足到 30**，
    队列顺序 = **到期在前（`next_review_at` 升序）→ 新卡补足**；补足会**消耗新卡池**（本口径接受该代价）；
  - **队列上限 = `target`（保证首屏只有一个数字）**：到期卡也只取**前 `target` 张**；到期 ≥ 30 时**不再补新卡**。
    **未进队的到期卡不得丢失** —— 仍在 `#/plan` 可见可作答（PLAN-001 既有入口）；
  - **「再来一组」= 额外组**（`#/review?extra=1`）：口径同本条（上限 `target`），但**不计入当日任务进度**（纯加练；完成态绿勾不回退）。
  - **退化态**：可复习总数（到期 ∪ 未学新卡）**为 0** 时，`target` 退回实际可用数（0），并**常显 + 置灰 + 写明原因**（UI-003，例「新卡池已空，今日无卡可复习」）——
    不得出现永远做不满的 0/30；
  - **首屏单一复习数字口径**：首页 `.primary`「开始复习 N 张」的 N **必须等于**今日任务 `review.target`（消除 v0.6.0 前 `31 vs 2` 打架）。
  - **触发点**：`/api/task` 计算、`/api/today` 队列构造、首页渲染。**覆盖路径**：`services/tasks.py`（唯一目标计算点）+ `services/queue.py`（补足）
    + `js/app.js` 首页（唯一展示点），无旁路。
  - **违规处置**：目标 ≠ `min(30, 可用)`（退化态除外）、前端硬编码 30、或首屏两处数字不一致 → 回滚。
  - **机械断言**：`tests/test_tasks.py`（到期 1 + 新卡足 → target=30 且队列前 1 张为到期；新卡不足 → 补到可用数；可用 0 → target=0 且 `reason` 非空；
    `REVIEW_TASK_TARGET` env 覆写生效）+ `make ui-audit ⑩`（首页 `.primary` 的 N == 任务块 `review.target`）
    + `tests/test_frontend.py::test_no_hardcoded_goal`（源码反断言：`app.js` 不得出现把 30 当目标的字面量）。

- **GOAL-002（P0，🔒 口径 · v0.8.0 · owner 2026-09-27 拍板）** **每日出题目标 = 5 题**：`config.QUIZ_TASK_TARGET` 默认 **10 → 5**
  （单一真相，env 可覆写）；今日任务「出题」子项 `target` = 5，由 `/api/task` 下发，**前端禁硬编码**。
  - **触发点**：`/api/task`、测验会话目标提示。**覆盖路径**：`config.py` + `services/tasks.py` + `js/app.js`，无旁路。
  - **违规处置**：前端出现字面 5/10、或两处目标不一致 → 回滚。
  - **机械断言**：`tests/test_tasks.py`（默认 = 5、`QUIZ_TASK_TARGET` env 覆写生效）+ `tests/test_frontend.py`（反断言：`app.js` 不得把 5 当目标字面量）。

- **STREAK-001（P0，🔒 口径 · 2026-09-27 owner 拍板 · 作废旧「有复习记录即算」）** **每日连胜目标 = 30 张卡 + 5 道题**：
  连胜 = **达成当日目标的连续天数**。**达成 = 当日已复习卡数 ≥ `REVIEW_TASK_TARGET`(30) 且 当日已作答题数 ≥ `QUIZ_TASK_TARGET`(5)**
  （两子项**都**满足；判定入口**复用** `services/tasks.py::today_task()` 的 `done`，**不得另写一套口径**）。
  - **口径切换日 = 2026-09-27（含）**（owner 拍板「今天算达标，保留连胜」）：`config.STREAK_GOAL_FROM_DATE = "2026-09-27"`；
    **早于该日**的日期按**旧口径**（当天有复习记录即算）判定 → 既有连胜**不清零**；**该日之后**按新口径判定。
  - **今天未达成**（新口径 + 当天未达标）→ 今天**不计入**，但**不得**判定为断连（保留到昨天为止的天数）。
  - **数据口径**：已复习卡数 = `card_reviews.learned_at` 换算**东八区本地日**、按 `card_id` 去重计数；
    已作答题数 = `quiz_attempts.created_at`（**UTC**，TIME-001 例外）换算东八区本地日、按 `item_id` 去重计数。
  - **触发点**：`GET /api/streak`。**覆盖路径**：`services/streak.py`（**唯一判定点**），无旁路（前端/报告/通知一律只读该接口）。
  - **违规处置**：只在「有复习记录」上增量、或只达标一项就 +1、或切换日之前按新口径回溯 → 缺陷。
  - **机械断言**：`tests/test_streak.py`：①两子项都达标 → 连续 +1；②只达标一项 → 不计入；
    ③切换日之前按旧口径判定（相邻两天有记录 → 连续 2）；④今天未达标**不断连**（保留昨日天数）；
    ⑤`/api/streak` 返回 `days` + `today_met`（布尔）。

- **STREAK-002（P0，🔒 展示口径 · 2026-09-27 owner 拍板）** **页头连胜 = 四叶草标志 + 数字 + 「连胜」**（Duolingo 式）：
  - 文案**必须**是「**N 连胜**」；**禁用**旧文案「N 天连续」，全站**不得**出现「连续」字样（旧字面量 `<span class="n">—</span> 天连续` 必须消失）。
  - **四叶草 = 内联 SVG**（`<svg class="clover">`，accent 草绿 `#1E7C50`）；**不得**用 emoji / 字体图标（跨设备渲染不一致）。
  - 数字用等宽（`.tnum`），与图标同一基线；**0 天常显 + 置灰**（UI-003：绝不隐藏、绝不按条件消失）；
  - 后端只下发数字（`days`），**前端零计算**。
  - **触发点**：页头渲染（每次导航 / 数据刷新）。**覆盖路径**：`backend/frontend/index.html` 页头 + `js/app.js::refreshStreak()`，无旁路。
  - **违规处置**：出现「连续」字样、四叶草用 emoji、0 天隐藏 → 回滚。
  - **机械断言**：`make ui-audit`（新组）：页头存在 `svg.clover` **且**存在 `.streak .n` 数字 **且**页头文本含「连胜」**且**全页文本不含「连续」；
    `tests/test_frontend.py` 反断言（源码中不得含「天连续」字面量）。

- **STREAK-003（P0，🔒 口径 · v0.8.2 · 修 STREAK-001 与 GOAL-001 的口径打架）** **当日达标 ⇔ 当日 `today_task().done`；达标状态当日落库快照，连胜只读快照**：
  - **缺陷（本版修 · 实测）**：`services/streak.py::_date_met()` 硬用 `REVIEW_TASK_TARGET`(30) 判「当日已复习数」，
    而 `services/tasks.py::today_task()` 的当日目标 = `min(REVIEW_TASK_TARGET, 当日可复习总数)`（GOAL-001 退化态）。
    实测 2026-09-28：可复习总数 28（已解锁章 42 张卡全部学过、新卡池 0）→ `GET /api/task` 返回 `done=true`，
    但 `GET /api/streak` 同一时刻返回 `{"days":0,"today_met":true}` —— **自相矛盾，且 `days` 会永久为 0**
    （只要可复习池 < 30，任何一天都不可能进连胜）。
  - **口径（对后续一律适用）**：**当日达标 ⇔ 当日 `today_task().done == true`**
    （= 当日已复习卡数 ≥ `min(REVIEW_TASK_TARGET, 当日可复习总数)` 且 当日已作答题数 ≥ `QUIZ_TASK_TARGET`）。
    **「当日目标」全仓只有一个计算点 = `services/tasks.py`**；`services/streak.py` **不得**再出现 30 / 5 字面量，
    也不得自行比较阈值。
  - **快照表（唯一判定依据）**：`streak_days(day TEXT PRIMARY KEY, target INT, review_done INT, quiz_done INT, met INT, updated_at TEXT)`，
    `day` = **东八区本地日**（`YYYY-MM-DD`）。
    - **今日行**：在任何影响「今日完成」的**写路径**（`POST /api/review/result`、`POST /api/quiz/answer`）与
      **读路径**（`GET /api/streak`、`GET /api/task`）用**同一份** `today_task()` 结果**覆盖式 upsert**（`INSERT ... ON CONFLICT DO UPDATE`）；
    - **早于今日的行冻结**：任何路径**不得**改写历史行（防「补昨天的分」与历史回放漂移）。
  - **连胜计算**：`days` = 从今日（今日 `met=1` 时）或昨日起、向前连续 `met=1` 的天数；遇「无行」或 `met=0` 即停。
    `today_met` = 今日行的 `met`（= `done`）。**禁止按历史日志回放**（历史时刻的可用池不可重建，回放只能给近似值
    —— 本 app 拒绝近似，owner 2026-08-31 明确口径：「数据宁精确或砍掉不要近似」）。
  - **历史回填（在 `data/models.py::migrate()` 内做，幂等 · `INSERT OR IGNORE`）**：
    ① 早于切换日的日：按**旧口径**「当日有复习记录 → `met=1`」；
    ② 切换日（`config.STREAK_GOAL_FROM_DATE = "2026-09-27"`）起至昨日的日：
    `met = (当日复习卡数 ≥ REVIEW_TASK_TARGET 且 当日作答题数 ≥ QUIZ_TASK_TARGET)` —— **只回填能由日志确证的达标日**
    （复习数 ≥ 30 ⇒ 当日可用池必 ≥ 30 ⇒ 当日目标必为 30，判定无歧义）；不足 30 的历史日一律 `met=0`（不猜可用池）。
    实测回填结果：`2026-09-27`（33 卡 / 17 题）→ `met=1`，修复后页头连胜 = **2**。
  - **切换日豁免分支删除**：`today_met` / `days` 上那条一次性「切换日算达标」补丁（`if today.isoformat() == STREAK_GOAL_FROM_DATE`）
    **移除**，由本条回填覆盖（`2026-09-27` 回填 `met=1`，连胜不清零）。`config.STREAK_GOAL_FROM_DATE` **保留**（回填分界线）。
  - **触发点**：`GET /api/streak`、`GET /api/task`、复习/作答写路径、`init_db` 迁移。
    **覆盖路径**：`services/streak.py`（唯一判定点）+ `services/tasks.py`（唯一目标计算点）+ `data/models.py::migrate()`（建表 + 回填），**无旁路**。
  - **违规处置**：再次出现「当日 `done=true` 而 `days` 不增」、streak 内出现 30/5 字面量、历史行被写、或未达标日虚增 → 回滚。
  - **机械断言**：`tests/test_streak_snapshot.py`（**新建**）：
    ①**核心反证（修前必红）**：造「已解锁章内恰好 28 张新卡」→ `/api/task` 的 `review.target == 28` → 复习满 28 张 + 作答 5 题 →
    `met=1` 且 `days ≥ 1`（修前 `_date_met` 硬 30 → `days=0`）；
    ②可用池充盈（≥ 30）时只复习 27 张 + 5 题 → `met=0`（**不得虚增**）；
    ③今日未达标 + 昨日 `met=1` → `days` 保留昨日连续数且 `today_met=false`（不断连）；
    ④**历史冻结**：今日行落库后，改写 `card_reviews` / `quiz_attempts` 的历史行 → 历史快照与 `days` 不变；
    ⑤`/api/streak` 的 `today_met` 与 `/api/task` 的 `done` 同一时刻必须一致（同一入口自证）；
    ⑥迁移幂等：连跑两次 `migrate()` → `streak_days` 行数不变；
    ⑦回填正确：造 09-27「33 卡 / 17 题」→ 回填 `met=1`；造 09-27「20 卡 / 17 题」→ `met=0`。
    + `tests/test_streak.py` 既有用例适配：删「切换日豁免」用例（`test_switch_day_grace_only_on_that_day`）与其在
    `test_api_endpoint` 里的 `STREAK_GOAL_FROM_DATE` monkeypatch（语义已由回填覆盖），其余日期注入保持**不读墙钟**。

- **STREAK-004（P0，🔒 口径 · v0.8.3）** **当日达标单调不可撤销**：当日行 upsert 时 `met = max(旧 met, 当前 done)`，
  `target` / `review_done` / `quiz_done` 用**当前值覆盖**；`days` 的连续性用快照 `met`，而 `today_met` 仍返回**当前** `done`
  （与 `/api/task.done` 同源，同帧必须一致，允许同时为 `false`）。
  - **理由（实测场景）**：内容重入库（例：2026-09-28 合成示例书7重出卡，删掉 9 张旧卡）会让「当日已复习」从 28 掉到 19；
    若按当前值覆盖，**当天已挣到的达标会被追溯抹掉**、连胜断掉。同理重复提交 / 复习记录被替换也不得回溯改历史。
  - **违规处置**：当日行 `met` 出现回落、或 `today_met` 与 `/api/task.done` 同帧不一致 → 回滚。
  - **机械断言**：先达标后删当日复习记录，快照 `met` 仍 1、`days` 不减；`today_met` 与 `/api/task.done` 同帧一致；`days` 计入今日快照 `met=1` 但当前 `done=false` 的当天。

### 3.12 PLAN — 复习计划视图（✅ v0.5.6 实现 · `services/plan.py` + `GET /api/plan` + `#/plan`）

- **PLAN-001（P0，🔒 口径）** **复习计划视图**：路由 `#/plan`；列出**状态非 new** 的卡，
  按「**已到期（`next_review_at <= now`）在前**」→「**下次复习时间升序**」排；每条显示
  **书 · 章 · 卡面（`front`）** + 间隔人类可读（`已到期` / `N 天后` / `N 小时后`）；
  已到期的提供**直接作答**入口（复用复习卡的作答路径，唯一调度 `review_sched.apply_result`）。
  - **触发点**：进入复习计划 / 渲染计划列表。**覆盖路径**：`services/plan.py` + `api/plan.py` + `#/plan`，**无旁路**。
  - **违规处置**：排序错（到期不在前 / 未按时间升序）、**前端另算一套间隔或写死文案** → 缺陷。
  - **断言**：`展示的「N 天后」必须由 `next_review_at` 机械换算`（后端单点 `plan.when_label`）——
    造 `next_review_at = now+3天` → 显示 `3 天后`；`now-1h` → `已到期`；跨 24 小时必须走「天后」而非「24 小时」；
    前端 `js/plan.js` 只读后端 `when_label`（反断言：不得出现 `'天后'`/`'小时后'` 字面量）；空态有话说。
  - **状态（v0.5.6）**：**✅ 实现** —— `services/plan.py`（`when_label()` + `plan_items()`，只读）+ `GET /api/plan`
    + `js/plan.js`（`#/plan`，已到期行 → `#/review`）。证据：`tests/test_plan.py`（间隔机械换算 / 恰好到点=已到期 /
    24 小时边界 / 到期在前升序 / `new` 排除 / 空态）；`tests/test_frontend.py::test_plan_page_hooks`；
    `scripts/ui_audit.js`（`#/plan` 入 ①②⑤⑥）。

### 3.13 WEAK — 薄弱点页（✅ v0.5.6 实现 · `services/report.weak_chapters()` + `GET /api/weak` + `#/weak`）

- **WEAK-001（P0，🔒 口径）** **薄弱点页**：路由 `#/weak`；**按章聚合**（与错题本按卡不同），
  章内显示 `错次总数 · 涉及卡数`，**按错次降序**；点章可展开涉及的具体卡与错次；
  数据源 = `quiz_attempts(is_correct=0)` → 卡 → 章。
  - **触发点**：进入薄弱点页。**覆盖路径**：`services/report.py` 的 `weak_chapters()` + `api/weak.py` + `#/weak`，**无旁路**。
  - **违规处置**：出现无错题的章、或排序不按错次降序 → 缺陷。
  - **断言**：**只出现有错题的章**；排序按错次降序；章内错次总数 = 涉及卡错次之和；空态有话说。
  - **状态（v0.5.6）**：**✅ 实现** —— `services/report.weak_chapters(con, since_utc=None)`（单查询按章/卡聚合，
    章级降序、章内卡降序）+ `GET /api/weak` + `js/weak.js`（`details` 展开）。证据：`tests/test_weak.py`
    （只含有错题的章 + `[4,2]` 降序 + 章内 `[3,1]` + 空态）；`tests/test_frontend.py::test_weak_page_hooks`；
    `scripts/ui_audit.js`（`#/weak` 入 ①②⑤⑥，空态文案在位）。

### 3.14 RPT — 本周概况（✅ v0.5.6 实现 · `services/report.weekly_report()` + `GET /api/report` + `#/report`）

- **RPT-001（P0，🔒 口径）** **本周概况**：路由 `#/report`；统计窗口 = **本周一 00:00（本地时区）起**；
  至少给：`复习卡数`（`card_reviews` 去重卡数）、`出题作答数` / `判对数` / `正确率`（`quiz_attempts`）、
  `最弱一章`（同 WEAK-001 口径，窗口内取）。
  - **触发点**：进入本周概况 / 首页一行摘要。**覆盖路径**：`services/report.weekly_report()` + `api/report.py`
    + `#/report`（`js/report.js`）+ 首页摘要（复用同一接口字段），**无旁路**。
  - **违规处置**：窗口起点错、**前端自算正确率**、0 作答显示 `0%` → 缺陷。
  - **断言**：正确率 = 判对 ÷ 已作答（**与 `QUIZ-005` 同一分子分母口径，单一入口** `services/quiz.score_pct`）；
    **反断言：前端不得自行计算正确率，必须来自后端字段**；作答数为 0 → 正确率显示 `—`（**不得显示 `0%`**）；
    窗口边界：周一 00:00 **前 1 分钟**的数据**不计入**。
  - **状态（v0.5.6）**：**✅ 实现** —— `services/report.weekly_report()`（`week_start()` = 本地周一 00:00，
    `card_reviews.learned_at` 本地 ISO 比较、`quiz_attempts.created_at` 先转 UTC 再比较）+ `GET /api/report`；
    `accuracy = score_pct(...) if answered else None`（0 作答 → null）。证据：`tests/test_report.py`
    （起点前 1 分钟不计入 / 正确率 3 答 1 对 → 33 / 0 作答 → None / 复习卡去重 / 最弱章窗口内）；
    `tests/test_frontend.py::test_report_page_and_no_client_side_accuracy`（反断言 `Math.round(...correct...)` 不得出现）；
    `scripts/ui_audit.js`（`#/report` 入 ①②⑤⑥）。

### 3.15 ADV — AI 学习建议（**❌ 明确不做** · 已拍板 2026-09-27）

- **ADV-001（P2，❌ 明确不做）** owner **2026-09-27 拍板：不加 AI 学习建议**（原话「ai学习建议不加」）。
  本条自**声明边界**升格为**禁令**：**任何 agent 一律不得实现**「AI 学习建议 / 智能提示 / 自适应推荐 / 学习规划」类功能
  （理由：与 §1.2 非目标一致——本 app 的 AI 层只有两件事：契约考点→卡面文本、去重闸门；建议/规划类属 `brain` 的职责）。
  - **触发点**：任何试图新增「AI 建议 / 智能提示 / 自适应推荐 / 自动学习规划」的改动（含「顺手补上」「先做个最小版」）。
  - **覆盖路径**：**无旁路** —— 后端 `/api/*` 新增建议类端点、前端新增建议卡片、定时任务生成建议，三条路径全禁。
  - **违规处置**：**越界即缺陷**，回滚该 commit 并回到本规格；已在 v0.5.6 集成前拦截过一次（ADV 未实现）。
  - **状态（v0.5.6 冻结）**：**❌ 明确不做**（技术债台账**不留此项**，视为已闭合）。

### 3.16 TIME — 时间口径（🔒 口径落定 2026-09-27 · **零业务改动**）

- **TIME-001（P0，🔒 口径）** **时间一律 ISO 8601 且带显式时区偏移；跨口径比较必须 `astimezone` 后比，禁止跨偏移字符串直比。**
  - **默认口径**：业务时间（`cards.created_at` / `card_reviews.learned_at` / `quiz_items.created_at` /
    `chapters.unlocked_at`）统一经 `backend/services/clock.py`（`TZ8` 东八区）产出，库内实测均为 `+08:00`。
  - **唯一例外**：`quiz_attempts.created_at` = **UTC**（`backend/services/quiz.py::_utc_iso`，QUIZ-006 明文规定，**不得改**）。
    故一次作答会同时落两种偏移——**这是有意为之**，不是散乱口径。
  - **取时入口单点**：除 `services/clock.py::now` 与该例外，新增任何 `datetime.now(` 调用**必须**列入
    `tests/test_clock_source.py` 的白名单，并在白名单条目写明「用途 + 为何不能走 `clock`」。
  - **触发点**：任何新增时间戳 / 任何「今天 / 本周 / 到期」判定 / 任何 SQL 里对时间列的过滤或排序。
  - **覆盖路径**：`backend/**/*.py` 全部；前端只做展示（「今天」判定在前端本地时区，不经库）。
  - **违规处置**：跨偏移字符串直比（如按字典序比 `+08:00` 串与 `+00:00` 串会**静默差 8 小时**）→ 缺陷，回滚该 commit。
  - **断言**：`tests/test_clock_source.py::test_single_now_source`（AST 扫 `backend/**/*.py`，白名单外出现
    `datetime.now(` → fail）+ `::test_clock_iso_offset`（`clock.now_iso()` 以 `+08:00` 结尾、UTC 例外以 `+00:00` 结尾）。
  - **状态（2026-09-27）**：**✅ 口径落定 + 断言入库；未改任何业务行为、未重写既有数据。**
    注：`CLAUDE.md §3` 旧措辞「一律 UTC（ISO 8601）」由本条覆盖（该行待人工授权后同步）。

### 3.17 SCOPE — 图书多选复习范围（v0.10.0）

> 口径：首页新增「图书」入口，进**独立钻取页** `#/scope` 多选「纳入复习 / 出题 / 今日任务计数」的书集；
> 持久化在 `prefs(key='book_scope', value=JSON 数组)`。`key 缺失` = 全部书（默认）；`[ids]` = 只在这些书内；**空集合不再是合法状态**（SCOPE-003 修订）。
> **范围只读不改卡状态 / 调度 / 连胜 / 解锁**（STREAK-004 / SCHED-001 与本域无关）；范围外到期卡**仍到期**（不吃卡 / 不改期 / 不丢卡，仍可在 `#/plan` 作答）。

- **SCOPE-001（P1，🔒 口径 · v0.10.0 / v0.11.0 修订）** **范围持久化与过滤**：`book_scope` 存选中书 id（JSON 数组），重启后不丢。
  - **触发点**：`GET /api/scope`（读范围与书列表）/ `PUT /api/scope`（写，`{"all":true}` 或 `{"book_ids":[...]}`；**空数组 `[]` 非法**，返回 `e_input("至少选择一本书")`）。
  - **覆盖路径**：`backend/services/scope.py`（`get_book_scope` / `set_book_scope` / `book_filter`）+ `backend/data/models.py`（`prefs` 表），**无旁路**。
  - **违规处置**：范围未持久化（重启丢失）、`book_filter` 拼装错（空范围非恒假 / IN 参数错位）、或 `PUT` 校验缺失（非法 id 未拒 / 非数组未拒 / 空数组未拒）→ 缺陷，回滚。
  - **机械断言**：`tests/test_scope.py::test_scope_persist_and_filter`（None/[ids] 往返 + `book_filter` 拼装 + `scope_state` 文案两态）+ `::test_scope_rejects_empty_scope`（`PUT {book_ids:[]}` 非 0 code + msg 含「至少选择一本书」+ prefs 未变）+ `::test_scope_normalizes_empty_on_read`（预置 `"[]"` → `all==True` / `repaired==True` / pref 行被删）。

- **SCOPE-002（P1，🔒 口径 · v0.10.0）** **范围影响三处**：复习队列（`/api/today`、`/api/review`）、出题会话（`/api/quiz/session`）、今日任务计数（`/api/task`）。
  - **触发点**：首页「图书」入口选定范围后，复习 / 出题 / 今日任务数字立即按范围收窄。
  - **覆盖路径**：`queue.today_queue(book_ids=)` + `quiz.start_session(book_ids=)` + `tasks.today_task(book_ids=)`；`api/review.py` / `api/quiz.py` / `api/task.py` 统一从 `scope.get_book_scope(con)` 取值，**无旁路**。
  - **违规处置**：选书后复习 / 出题 / 任务计数任一仍含范围外卡 → 缺陷；或空选态 `[]` 时三处非空 / 目标非 0 → 缺陷（**空态只允许经服务层 `book_filter` 恒假触发，不允许经 `PUT` 写入**）。
  - **机械断言**：`tests/test_scope.py::test_scope_affects_queue_task_quiz`（`[1]` 只出书 1 卡 / `[]` 空队列 + 目标 0 / `None` 全量）。

- **SCOPE-003（P1，🔒 口径 · v0.10.0 / v0.11.0 修订）** **范围面板 UI + 空集合非法**：首页「图书」按钮常显当前范围文案（`图书：全部` / `图书：2/N 本（书名、书名）`，**不再出现「未选择」**）；点进 `#/scope` 独立钻取页（禁横向滚动、禁弹窗内滚动列表）。
  - 每行 = 书名 + `已学 x / 共 y` + 覆盖率 + 掌握度 + 勾选框（复用现有 `.tick` 视觉，accent 绿；**禁系统 checkbox 原生样式**）。顶部/底部 `全选`、`清空`（hairline）+ **`确认`（`.primary`，本页唯一主行动）**。
  - **空集合不是合法状态**：前端「确认」环节拦截（草稿空 → 错误「至少选择一本书」，`role="alert"`，不发请求、不跳转）；后端 `PUT /api/scope` 同样拒绝空数组（防旁路）；历史遗留 `"[]"` 读取时归一为「全部」并提示「检测到空范围，已恢复为全部图书」（幂等迁移删除该 pref 行）。
  - **触发点**：`#/scope` 页面渲染与交互；首页 `#/scope` 入口按钮文案；`PUT /api/scope` 写范围。
  - **覆盖路径**：`js/scope.js`（`ScopeView`）+ `js/app.js`（首页按钮 + 路由 `scope`）+ `css/app.css`（`.scope-*`）+ `api/scope.py` + `services/scope.py` + `data/models.py`（迁移），**无旁路**。
  - **违规处置**：出现 `<input type="checkbox">` 原生控件、确认按钮缺失、空草稿确认未拦 / 未弹「至少选择一本书」、`PUT` 空数组未拒、首页出现「未选择」、或 `#/scope` 横滑 → 缺陷，回滚。
  - **机械断言**：`make ui-audit ⑳/㉑`（`#/scope` 三按钮 `#scope-all`/`#scope-clear`/`#scope-confirm` 在位；点行不点确认 → 「尚未确认」且重载后勾选未变；清空→确认 → `role=alert` + 「至少选择一本书」且 h1 未变；全选→确认 → 首页「图书」文案不含「未选择」）+ `tests/test_frontend.py::test_scope_hooks`（scope.js 源码无原生 checkbox、含「至少选择一本书」「尚未确认」、确认按钮 `.primary`）。

- **SCOPE-004（P1，🔒 口径 · v0.11.0 新）** **范围改动先草稿、后确认**：`全选 / 清空 / 勾选` 都是**草稿操作**（只改本地内存，不发请求）；只有点「确认」才 `PUT /api/scope` 写库；确认前离开页面**不改变已保存范围**。
  - 草稿与已保存范围不一致时显示「尚未确认」提示；确认成功后提示消失。
  - **触发点**：任何修改图书范围的路径。
  - **覆盖路径**：范围页（三种操作 + 确认 + 空草稿）/ `PUT /api/scope` / 读取归一 / 首页「图书」文案，**无旁路**。
  - **违规处置**：勾选 / 全选 / 清空即发请求（未确认就写库）、确认前离开页面改变了已保存范围、或空草稿确认被放行 → 缺陷，回滚该 commit。
  - **机械断言**：`make ui-audit ㉑`（点行不确认 → 重载后勾选与操作前一致，= 没写库；清空→确认 → `role=alert` + 文案；全选→确认 → 首页「图书」文案更新）。

---

## §4 数据模型（草案，实现时以迁移脚本为准）

| 表 | 关键字段 |
|---|---|
| `subjects` | `id, name, slug, order_no, created_at` |
| `books` | `id, subject_id→subjects, title, slug, source_path, status, created_at` |
| `chapters` | `id, book_id→books, name, order_no, anchor（第N章/P1/ch09）, unlocked_at, status` |
| `concepts` | `id, chapter_id→chapters, name, source_pages, confidence, tags` |
| `cards` | `id, concept_id→concepts, subject_id, front, back, source, content_hash, status, created_at, learn_count, next_review_at, title`（`title` = 契约 `title` 逐字入库；CARD-007） |
| `card_reviews` | `id, card_id→cards, learned_at, result, next_review_at, learn_count, status` |
| `ingest_runs` | `id, subject_id, book_id, new/m, skipped, contract_version, started_at, finished_at` |
| `reminder_log` | `id, date, kind, sent_at`（幂等：每人每天每类 1 条） |
| `prefs` | `key TEXT PRIMARY KEY, value TEXT NOT NULL`（SCOPE-001；`book_scope` 存选中书 id 的 JSON 数组） |
| `quiz_items` | `id, card_id→cards, type('choice'/'bool') CHECK, stem, options(JSON), answer_key, points, source('ai'/'fallback') CHECK, content_hash UNIQUE, card_content_hash, model, created_at`（QUIZ-001/002/003/011；`content_hash = sha256(card_id\|type\|stem)` 去重；`card_content_hash` = 出题时卡 front/back 指纹） |
| `quiz_attempts` | `id, item_id→quiz_items, card_id→cards, session_id, my_answer, is_correct(0/1), created_at`（QUIZ-006；**追加不覆盖**，`created_at` 为 **UTC** ISO 8601；供错题本 / 掌握度） |
| `users` | `id, username, password_hash, role='owner'`（单行，仅复用认证层） |

---

## §5 上游契约 🔒（**阻塞项：冻结后才能开工 ingest**）

**唯一交接口**：`data-local/exports/<学科 slug>/<书 slug>.jsonl` —— 每行一个 JSON 对象 = 一个**考点单元**（不是最终卡面；app 负责成卡）。

**生产方 = brain**（跑 `data-local/scripts/export_cards.py <书>`）；**消费方 = pm**（`scripts/ingest_kb.py`）。

| 字段 | 必填 | 说明 |
|---|---|---|
| `contract` | ✅ | 契约版本，本期常量 `1`。app 读到 ≠1 必须拒绝并报错，不猜 |
| `concept_id` | ✅ | 稳定 ID，来自 KB 概念页的 slug（如 `冲煮变量`）。**同一概念不许出现两个 ID** |
| `subject` | ✅ | 学科 slug，必须与 app `subjects.slug` 一致 |
| `book` | ✅ | 书名 slug |
| `chapter` | ✅ | 章锚点：`第N章` / `P1`（PART 级）/ `ch09`（前言·附录） |
| `chapter_title` | ⭕ | 章的纯标题（不含锚点；字符串、≤40 字、不可含换行）。章显示名为 `chapter · chapter_title`，缺省沿用章锚点；`chapter` 本身格式不变（DATA-006） |
| `pages` | ⭕ | 页码数组或区间字符串（如 `[12,13]` / `"12-13"`）。**2026-09-26 起改为可选**：KB 源为 EPUB，raw 层只到章粒度，页码在链路上不可得。缺失/空数组时卡片 `source` 退化为「书/章」；**给了就必须合法**（非数组/非区间字符串仍拒收） |
| `title` | ✅ | 考点的短标题；**现行格式「概念名 · 子卡短名」**（语义以 brain 的 `exports/导出契约.md` 为准，app 侧逐字落库、不解析 —— CARD-007 / UI-019） |
| `question` | ✅ | 这张卡要问什么（**可直接作为卡面正面**） |
| `answer_points` | ✅ | 答案要点数组（≥1 条），每条一个事实 |
| `tags` | ⭕ | 标签数组 |
| `confidence` | ⭕ | `high/medium/low`（来自 KB frontmatter） |
| `contradicts` | ⭕ | 若该考点与库内某结论冲突，填对方 `concept_id`（沿用 brain 的 `contradictions:` 机制） |

**示例行**
```json
{"contract":1,"concept_id":"变量","subject":"demo","book":"示例书","chapter":"第1章","chapter_title":"基础概念","pages":[12,13],"title":"变量 · 三个基本量","question":"冲一杯手冲时，水温、粉水比、研磨度各自决定什么？","answer_points":["水温决定萃取速度：水越热溶出越快，偏低会留下尖酸，偏高容易带出苦味。","粉水比决定浓度：同一支豆子，1:15 比 1:17 更浓、更有重量感。","研磨度同时影响速度与水流路径：越细接触面越大，但过细会让水走偏、局部过萃。","三者要一起调，单独改一个，另外两个的既有结果就被推翻。"],"tags":["示例","变量"],"confidence":"high"}
```

**契约纪律（🔒 对后续一律适用）**
- **违规处置**：任一必填字段缺失 → 该行**拒绝入库**并计入「待人工 M′」，不得静默补默认值。
- **不许新增事实**：`answer_points` 必须来自 KB 概念页与原文（`source` 可回溯到「书/章」，有页码时到「书/章/页」）；app 侧**不得**自行扩写内容。
- **页码不假装**（2026-09-26 定，🔒 对后续一律适用）：KB 无页码时 `pages` 留空即可，**禁止**用虚拟页、段序号或估算值填充 —— 宁可粒度退到「书/章」，不要假精度。
- **章显示名（DATA-006）**：可选 `chapter_title` 只影响显示名与卡面 `source`，不改变 `chapter` 锚点、章序和去重键；已有人工补全章名不能被无标题的旧契约冲掉。
- **章序按章号**（2026-09-26 定，🔒 对后续一律适用）：`chapters.order_no` 一律从章锚点（`第N章`）抽 N，**禁止**用写入序；ingest 对既有行幂等纠正。原因：导出文件按概念排列，写入序会把第 12 章排到第 1 章前，并让 `maybe_unlock` 误解锁非首章。
- **`title` 只存不猜**（2026-09-30 定，🔒 对后续一律适用）：`title` 的**语义归 brain**（`exports/导出契约.md` 单点定义，现行「概念名 · 子卡短名」）；
  app 侧**逐字落库、不解析、不回填**，短名派生只发生在展示层（`services/labels.subtitle_of` → UI-019）。
- **不许丢事实**：同一 `concept_id` 的多行合并时，正文 = 各行的并集；数字忠实度要自动校验。
- **契约版本升级**：改字段 = 同时改 KB 侧导出脚本与本文档 `contract` 常量，**双向同步后才许跑 ingest**。
- **覆盖路径（无旁路）**：app 只允许从 `exports/` 读入；**禁止**直接读 `data-local/concepts|raw` 或 Obsidian 文件。

---

## §6 部署与运维

- 服务：`org.example.review`（waitress，`127.0.0.1:5004`）；公网 `example.invalid`（CF ingress 一行 + CNAME）。
- 上线验收：本机 `/health` 与公网 `/health` 版本一致；**前端改动必须强刷旁路缓存**（冷加载 + `reload(true)` + 特征串核验，不能只看体积）。
- 备份：每日 iCloud 导库 + 保留 7 份；改动前一律带时间戳副本。
- 目录不在 iCloud 内，避免 Obsidian/同步冲突。

## §7 验收口径

1. `make lint test smoke` 全绿：**覆盖率不得低于门槛**（机器真值 = `Makefile` 的 `--cov-fail-under`；
   口径 = 上一版实测**减 0.5 个点**作**防抖余量**（避免新增未覆盖行即卡死门禁），**门槛只许上调**，
   禁止为通过而下调；审计脚本另有「实测覆盖率 ≥ 门槛」断言）。
2. ingest 幂等：同一契约文件连跑两次，第二次 `新增 0 / 跳过 N`。
3. 解锁规则可复现：造 5 张已掌握卡把某章推过 80% + 到期清零 → 下一章 `unlocked_at` 落库；**未达阈值时不得解锁**（反向断言必须写）。
4. 契约违规：删掉某行 `answer_points` → 跑 ingest 报「待人工 M′=1」且不写库。
5. UI：五级钻取可点通；窄屏无横向滚动；置灰控件带原因文案。
6. 端到端：从 KB 现有三本书真实导出 → 入库 → 复习一轮 → 到期队列正确。

## §8 交付纪律

- 手术式修改：不加依赖、不重构既有模块、不动无关代码。
- 每完成一个交付点立刻独立 commit；版本号诚实（改动必 bump + CHANGELOG + `§12` 回写）。
- 编码 agent 不 push / 不重启服务 / 不碰 launchd；验证由 pm 跑，上线由 pm 做。
- 口径类改动一律写成「对后续适用」的条款（触发点 / 覆盖路径 / 违规处置），不写历史流水账。
- **代码规模口径**：PEP8 + `ruff` 必须过；**后端 Python 单文件 < 300 行**（超则拆模块）；
  **前端 JS 不设行数上限**（按页面切片组织，不受 300 行约束）。
  机械断言：`tests/test_frontend.py::test_backend_files_under_300_lines`（扫 `backend/**/*.py`，不含 `backend/scripts/`）。
### [0.16.2]
首页上传入口、一次性邀请码与首屏三态引导。
S1-SQL-SCOPE：非 cards 的已知表名拼接不保证拦截；违规处置：阻断合入。
S1-DISPLAY-SCOPE：运行时计算属性名不保证拦截；违规处置：阻断合入。

### [0.16.3]
出题选项呈现顺序按（会话 id, 题 id）确定性置换，正确答案位置不再恒在首位（库内数据与判分口径不变）。

### [0.16.4]
冻结余额为 0 时的提示文案独占页头下方一行（仅 0 时显示）；页头标题、连胜组与退出登录一律不收缩、不折行。

### [0.18.20] 2026-10-31

**REQ-ACCT-01 账号管理（对后续一律适用）**

- 顶栏固定顺序：头像（进入 `#/account`）→「退出登录」；头像不可按条件隐藏。
- 账号页只读本人：进度、覆盖率、连胜、今日三项全部由 `g.user_id` 解析，禁止接受外部 `user_id`。
- 改密码：必须验旧密码；新密码 <8 位或与旧密码相同 → 400；成功后旧密码立即失效。
- 违规处置：`tests/test_account.py`（本人数据 / 错旧密码 / 短密码 / 改后旧密码登不进）转红即失败。

### [0.18.5] — 2026-10-31

**REQ-FAM-06 小组的建立与可见性（对后续一律适用）**

- 名词：对外一律称**小组**（不再出现「家庭」）。
- 建组路径：注册页邀请码留空 → 新建独立小组（名为「<用户名> 的小组」），新组无任何书/卡/记录（干净空间）。
- 入组路径：填邀请码 → 并入邀请者小组，共享知识资产。
- 可见性：同组成员互相可见「今日三项 / 覆盖率 / 连胜 / 最近活跃」；`share_progress=0` 的成员对他人的详情请求返回 403 且不返回任何数字；跨组 404。
- 违规处置：`tests/test_journey.py`（视频去重 / 成员共享开关 / 自建组）与 `tests/test_s2_invites.py`（邀请并入组）转红即失败。

### [0.18.4] 2026-10-31

**REQ-JOURNEY-01 用户旅程与每日连胜（对后续一律适用）**

- 旅程三段：**学习＝看视频 / 复习＝过卡片 / 巩固＝刷题**；三个入口常显，不可用时置灰写明原因，禁止隐藏。
- 每日连胜口径＝`video_done ≥ 5` **且** `review_done ≥ 20` **且** `quiz_done ≥ 5`（`QUIZ_TASK_TARGET` / `REVIEW_TASK_TARGET` / `VIDEO_TASK_TARGET` 单点配置）。
- 视频「看过」＝当天有 `video_views` 行（每日每片去重，播放即记）；无观看记录不得计入。
- 触发点：`services/tasks.today_task` 与 `services/streak.record_day` 必须同源，禁止 UI 另算一套。

**REQ-FAM-05 小组（家庭）语义**

- 共享＝知识资产：书 / 章 / 概念 / 卡片内容 / 题目 / 视频映射（household 谓词）。
- 私有＝学习进度：`card_reviews`、`quiz_attempts`、连胜、覆盖率、每日三项一律按 `user_id`；覆盖率＝本人学过的卡 / 本户可见卡。
- 成员进度钻取：`GET /api/family/member/<id>` + 前端 `#/member/<id>`；未开启「允许成员查看我的学习进度」→ 403，且不泄露任何数字。
- 注册：普通注册（bootstrap）开独立家庭；只有邀请码注册并入邀请者家庭。

### [0.18.3] 2026-10-30

**REQ-FAM-04 共享维度 / 个人维度（对后续一律适用）**

- 触发点：任何按书/章/概念/卡/题读取或写入的 SQL。
- 共享维度（同 household 可见）：`books` 可见性、`chapters`、`concepts`、`cards` 内容、`quiz_items` 题面、`card_videos` 映射。
  → 一律内联规范谓词 `b.owner_id IN (SELECT u2.id FROM users u2 WHERE u2.household_id=(SELECT u1.household_id FROM users u1 WHERE u1.id=?))`。
- 个人维度（禁止跨成员）：`card_reviews`、`quiz_attempts`、连胜、个人进度、个人额度、上传任务。
  → 继续 `user_id=?`，且必须是 `g.user_id`，不是 `owner_id`。
- 写操作：只允许 `books.owner_id == g.user_id`（本人创建的书才可改）。
- 违规处置：`scripts/s2_sql_scope_scan.py` 静态门禁转红（裸 `owner_id=?` 或缺规范谓词即失败）；
  `tests/test_household_scope_no_bypass.py` 对白名单外文件计数，出现即失败；跨户反证测试 `tests/test_s2_invites.py`。

### [0.18.2] 2026-10-30

- REQ-VIDEO-UI-05 详情页播放器 `.video-player`：竖屏视频在手机上宽度自适应、高度 ≤56dvh、`object-fit:contain`、水平居中；桌面 ≥721px 时宽 100%（≤900px）。

### [0.18.1] 2026-10-30

- REQ-VIDEO-UI-01 视频接口一律返回 `{code:0,data:...}`；`tests/test_video_queue.py::test_all_json_endpoints_use_code_envelope` 机械断言。
- REQ-VIDEO-UI-02 首页「视频讲解」必须是 `<a class="row" href="#/videos">`，不得用 `span`/`aria-disabled` 代替入口。
- REQ-VIDEO-UI-03 闪卡「讲解」点击后 1 秒内必须出现 `.video-sheet`；`scripts/ui_audit.js` 实测点击断言。
- REQ-VIDEO-UI-04 视频列表行必须包在 `.rowlist`（行间 12px 间隙）；深色面板内按钮前景 `#FBF8F0`。

### [0.18.0] 2026-10-30
家庭空间骨架：household 归属迁移、共享书架与学习进度共享接口/页面。完成状态以 FAMILY-delivery 审计证据为准。

### [0.17.0] 2026-10-30
视频讲解初版：数据表、能力接口、幂等队列、媒体 Range 路由、VideoKit worker（FIFO、失败记录、时长校验、每日 owner 预热与启动恢复）、首页/卡片/闪卡入口及分层列表播放器。验证状态以交付审计报告为准。


## 14. 家庭空间（REQ-FAM）

- REQ-FAM-01 households 迁移需幂等；启动迁移并检查每用户 household_id 均指向 household。
- REQ-FAM-02 同家庭书籍可见性必须由 `services/household.py` 唯一入口生成；跨家庭书籍不得出现在书目、复习范围、统计。
- REQ-FAM-03 禁止散落 owner_id 可见性判断；grep 发现即阻断提交，仅服务入口及迁移允许。
- REQ-FAM-04 `/api/family` 每人数字只按对应 user_id 统计；shared=false 只允许 id/username/shared。
- REQ-FAM-05 分享开关仅修改本人，关闭后本人仍可读自身数据；接口测试验证即时生效。
- REQ-FAM-06 空书架显示「书架空着 · 等书入库」，禁止假数据与 0/0 环图。
- REQ-FAM-07 首页家庭入口无条件常显。覆盖路径：迁移、书籍/复习/统计查询、家庭 API、家庭路由和首页。违规处置：停止发布，回滚对应提交，补齐机械断言后重验。

### REQ-STATE-01 卡片学习状态按人（v0.18.20）

- 触发点：任何读取卡片学习状态（已学/到期/今日完成/进度条/覆盖率）的查询。
- 口径：状态唯一来源 = 本人 `card_reviews` 最新一条；无记录 = `new`。
  `cards.status / learn_count / next_review_at` 只作历史兜底，且仅对 `books.owner_id` 本人生效。
- 覆盖路径：`services/cards.py`、`services/card_quiz_pool.py`、`services/coverage.py`、
  `services/card_state_queries.py`、`services/plan.py`（经 `scheduled_plan_cards`）。
- 违规处置：`tests/test_journey.py::test_card_state_is_per_member` 转红即不得合并。

