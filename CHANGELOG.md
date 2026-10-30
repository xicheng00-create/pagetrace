# Changelog

## [0.18.20] — 2026-10-31

- 小组页「我的进度」覆盖率/连续改与个人空间同源（/api/account），同一数字不再两页不一致。

## [0.18.19] — 2026-10-31

- 首页三项任务缺字段时按退化态渲染（不再因 `task.video.done` 抛错白屏）。
- 小组页未共享成员文案改为「对方未共享进度」。
- ui-audit 修到全绿：`.loading` 只认 main 下、幂等 JSON 包装、按标题定位任务行、上传进度成对采样、注入前重登。

## [0.18.18] — 2026-10-31

- 修复并发写引发的 `database is locked`（出题会话/复习作答等写接口偶发 500）：写请求在进程内串行化，读不受影响。
- 补 6 线程并发写/读反证测试。

## [0.18.17] — 2026-10-31

- 首页遇到 401（未登录/会话过期）不再停在「加载中…」：显示「请先登录后查看」并唤起登录面板；其它异常落到错误提示。

## [0.18.16] — 2026-10-31

- ui-audit 注入改走受支持测试缝 `window.__taskStub`（不再改写 `window.api.get`）；等待改为有界轮询，超时给出明确条件名而非 CLI ETIMEDOUT。
- 注入脚本自身异常会记录到 `window.__err` 并作为断言异常上报。

## [0.18.15] — 2026-10-31

- 修复并发下 `database is locked` 导致 /api/task、/api/account 偶发 500：连胜快照写入改为短退避重试（6 次），读接口捕获写失败不再连坐。
- ui-audit：CLI 超时 20s→60s；会话名固定 `ui-audit-main` 复用已启动浏览器，避免每次冷启动超时。

## [0.18.14] — 2026-10-31

- 个人空间页「0/0」不再打勾（目标为 0 视为无任务，不显示完成标记）。

## [0.18.13] — 2026-10-31

- 修复个人空间页偶发 500（`database is locked`）：连胜快照写入失败不再让读接口失败；`busy_timeout` 5s→15s。
- 空书架首页也提供「个人空间」入口。

## [0.18.12] — 2026-10-31

- 修复路由被页头刷新打断：`refreshStreak` / `refreshVideoCapability` 异常不再阻断页面渲染（此前点「个人空间」会被吞掉、停在原页）。
- 路由异常改为 `console.error`，不再静默。

## [0.18.11] — 2026-10-31

- 新增「个人空间」入口：首页快捷入口、小组页各一处；账号页标题改「个人空间」（我的进度 / 账号与密码）。

## [0.18.10] — 2026-10-31

- 修复顶栏账号区脚本报 `avatarLetter is not defined` 导致头像与「退出登录」整块不渲染：
  首字母改存 `documentElement.dataset`，不再依赖闭包变量。

## [0.18.9] — 2026-10-31

- 修复顶栏头像与「退出登录」偶发整块不出现：账号区改为独立 `mountAccountUI()`，
  在 `DOMContentLoaded` 已过时立即挂载；头像首字母未取到时显示「我」。

## [0.18.8] — 2026-10-31

- 修复头像入口在顶栏重建后变空圈：头像首字母缓存并同步到所有 `#avatarBtn`，未取到用户名时显示「我」。

## [0.18.7] — 2026-10-31

- 修复：同组成员互相看见对方学习进度（Test 账号看到 owner 的已学/到期/今日完成）。
  根因是 `cards.status / learn_count / next_review_at` 全组共用一列。
- 卡片状态改为按人：读口径统一走本人 `card_reviews` 最新记录（临时视图 `_mine`），
  从未复习即视为未学；历史数据按「书主」归属兜底，组员不再继承。
- 覆盖：首页今日任务、计划、复习队列、刷题池、错题本、书目/章节进度。
- 新增回归测试 `tests/test_journey.py::test_card_state_is_per_member`。

## [0.18.6] — 2026-10-31

- 顶栏「退出登录」左侧新增头像按钮，进入账号管理页 `#/account`：我的进度（今日三项 / 覆盖率 / 连胜 / 今日是否达成）、小组归属、进度共享开关、修改密码。
- 新增 `GET /api/account`（只返回本人数据）与 `POST /api/account/password`（校验旧密码、新密码 ≥8 位、不得与旧密码相同）。


## [0.18.5] — 2026-10-31

- 「家庭」统一改名「小组」（导航 / 页面标题 / 引导文案）。
- 新用户可自助开组：注册页邀请码**留空＝新建自己的小组**（`POST /api/auth/register` 无 code 分支），填邀请码＝加入对方小组；新建组不继承任何书架。
- 注册后自动登录，不再需要二次手动登录。


## [0.18.4] — 2026-10-31

- 每日连胜口径改为三合一：看 **5 个视频** + 复习 **20 张卡** + 刷 **5 道题**，三项都达标才算当天（新增 `video_views` 表、`POST /api/videos/<id>/view` 上报）。
- 首页「今日任务」并列显示三项进度，并写明连胜口径。
- 小组成员头像可点进 `#/member/<id>` 看 TA 的今日三项 / 覆盖率 / 连胜 / 近 7 天；未共享进度者 403。
- 覆盖率改为**按本人复习记录**算（`card_reviews.user_id`），不再继承同户他人的进度。
- 自助注册（bootstrap）自动开独立家庭；邀请注册才并入邀请者家庭。


## [0.18.3] — 2026-10-30

- 家庭空间收口：书/章/概念/卡/题等**共享维度**统一走 household 谓词（29 处裸 `owner_id=?` 清零）；复习记录/答题/连胜/额度仍按 `user_id`。
- 新增 `tests/test_household_scope_no_bypass.py`（源码门禁 + 白名单）与「同户可见 / 跨户 403 且不泄露标题」反证。
- `models.py`/`cards.py` 拆到 300 行以下（`schema_sql` 已回并，实际拆出 `migration_helpers.py`、`card_sql_fragments.py`）。
- `/api/videos` 与 `/api/videos/<id>` 补家庭谓词（原来全库可见）。


## [0.18.2] — 2026-10-30

- 修复：视频详情页播放器按手机宽度自适应（竖屏 720×1280，高度≤56dvh，居中，object-fit:contain），不再超出屏幕。


## [0.18.1] — 2026-10-30

- 修复：视频接口统一 `{code,data}` 信封（此前裸对象导致 `#/videos` 白屏、能力文案卡在「正在检查」）。
- 修复：首页「视频讲解」由置灰 `span` 改为常显链接。
- 修复：闪卡「讲解」点击后立即打开面板并轮询，成片自动播放（旧实现只改按钮文字）。
- 修复：视频列表行移入 `.rowlist`（书目按钮之间有 12px 间隙）；深底面板内按钮改浅色（「关闭」原来不可见）。


## [0.18.0] — 2026-10-30

- 新增家庭空间骨架：家庭书架共享、成员进度看板及个人进度共享开关。


## [0.17.0] — 2026-10-30

- 新增 VideoKit 可选讲解视频数据表、能力探测及视频 API；无依赖时明确降级。
- 提供视频 worker 入口与 launchd 配置（本任务不加载），前端首页增加视频讲解入口与列表页。
- 视频文件支持 Range；视频由外部 VideoKit 生成，仓库不包含渲染器。


## [0.16.4] — 2026-10-20

- 修页头被冰冻说明挤压变形：v0.14.0 起「冰冻已用完，漏卡将清空连胜」这串文案塞在页头连胜组内，余额为 0 时把「个人复习」标题与「退出登录」按钮都挤成竖排（iPhone 实测，owner 报障）。
- 该说明移到页头之下独占一行（`.topbar-note`，`hidden` 控制显隐，仅余额 0 时出现）；页头三段（品牌 / 连胜组 / 退出登录）一律 `flex:0 0 auto` + `white-space:nowrap`，任何余额态都不缩、不折行。
- 新增 `make ui-audit` ⑯d：强制把说明写成最长文案并显示后，品牌与退出登录必须仍各占一行、按钮文字不溢出、页头行高不变（反证：把说明移回连胜组 → ⑯d 必红）。
- 冰冻余额口径不变（基数 3 + 连续段内每第 5 个达标日 +1，冰冻日占位不发）；本次只修呈现。
- 后端与前端 CACHE / V / 资产引用、页脚统一至 0.16.4。

## [0.16.3] — 2026-10-14

- 修复「出题答案几乎总在 A」：提示词骨架把正确项写死在第一项、模型照抄 —— 生产 76 题里 72 题（94.7%）正确答案在首位，作答记录里 93.6% 的正确答案是 A。
- 题面交付前端的唯一出口按（会话 id, 题 id）确定性置换选项顺序（`quiztext.display_options`）：同一会话内顺序恒定、跨会话重排；库内 `quiz_items.options` 与判分口径（按文本比对，QUIZ-004）均不变。
- 结果页逐题解析沿用同一置换，选项顺序与作答时一致；`answer_key` 仍不下发。
- 提示词选择题骨架改为同形占位、拆除「正确项恒第一」的位置暗示。
- 新增 `tests/test_quiz_option_order.py`（5 条断言；反证：关闭打乱后 3 条立即红）。
- 后端与前端 CACHE / V / 资产引用、页脚统一至 0.16.3。

## [0.16.2] — 2026-10-13

- 首頁新增常顯「上傳自己的書」入口，修正 S1 只做通路漏入口；空库也可访问，额度不可用时置灰并写明原因，不隐藏。
- 新增 owner 生成 24h 一次性邀请码、member 凭码注册与首屏三态引导，邀请码只存带盐哈希并事务性消费。
- ui-audit 新增首页上传/邀请码入口、首次引导与 can_upload=false 保留入口的 DOM 机械断言。
- 后端与前端 CACHE / V / 资产引用、页脚统一至 0.16.2；不部署、不重启服务。

## [0.16.1] — 2026-10-13

- 演示学科 slug `demo` 显示为「演示学科」。
- S2 迁移账号读取 `S2_OWNER_USERNAME`（默认 `owner`）；首次登录以自设 ≥8 位密码认领，无默认密码。
- 开源只读快照导出器与负空间校验器；公开树使用合成夹具与演示卡，不携带私有历史或运维资料。
- 后端版本与前端 CACHE / V / 资产引用、页脚同步至 0.16.1。

## [0.16.0] — 2026-10-13

- S2：多用户与租户隔离；账号密码登录、HttpOnly cookie / Bearer JWT、登出及私有 API 401 自动提示登录。29 条私有出口按当前用户过滤，跨用户资源不可访问；公开 `/health` 保持可用。
- S3：每人上传自己的书；上传任务、草稿、上传配额与学习范围按用户归属隔离。生产数据库迁移由 PM 在上线窗口执行，本次不部署。
- 同一用户的数值语义不变（连胜/报表/掌握度口径未动），复习与出题仅增加用户维度。
- 后端版本、Service Worker CACHE/V 与前端资产引用统一为 0.16.0。

## [0.15.14] — 2026-10-12

- S1 十四轮 C：回写隔离全流程及七条 RED 的真实证据；新增 stdlib closure 声明校验（版本一致、证据路径与原始输出），未完成项不标 PASS。

- S1-UPLOAD-BLOCK-012：保留成功块草稿/缓存、逐块重试及任务摘要；新增重试边界和隐私契约测试。
- S1-UPLOAD-ERROR-CLASS-013：抽取、分段、模型 JSON 解析使用专用异常，解析失败归类 parse。


## [0.15.13] — 2026-10-12

- 返回导航改版：**首页不再出现任何返回控件**（去掉「常显置灰」占位）；非首页改为 **banner 之下的左上角小箭头**（无文字、无底色、无边框，40×40 触控盒 / 22px 细箭头）。顶部 banner 本身未改。
- 门禁同步：㉙ 改为「首页无返回箭头」、㉚ 改为「非首页返回＝小箭头」的几何不变量（在 banner 之下 / 无文字 / 无按钮外观 / 触控盒 32–44 / 图形 ≤24 / 不遮挡 / 无横滑），并保留 ㉗ 逐层返回点击断言。

## [0.15.12] — 2026-10-12

- 上传失败分类按 LLM provider / 卡片 gate 专用异常映射，避免服务故障误导为卡片校验错误。


## [0.15.10] — 2026-10-12

- SQL 边界补未知动态表名、函数返回与变量 join 扫描，输出行号及命中片段，保留固定表名/参数化正例。
- JS AST 补数组 join、解构别名与转义后出处拼接反证；测验、答案、结果、错题与薄弱点统一后端 display_fields。
- 四组并发扫描/出卡中断断言：线程表/通知表清理，日志、响应与任务 error 零正文泄漏。
- 版本四处与规格封面同步；详见 reports/S1-round10.md。

## [0.15.9] - 2026-10-12

- 父级导航统一由只读 services/nav.py 提供，四个出口追加 nav，深链不再猜学科 id。
- 修复返回栈 pop 后反向入栈，保留 sessionStorage 与重复层级；首页返回常显置灰。
- 范围确认保留成功首页 aria-live / 失败 role=alert，将确认组移到列表前确保首屏可达。
- 追加 UI 断言 ㉗–㉛，保留既有全部断言；合入上一轮 worker BaseException 清理。

## [0.15.8] - 2026-10-12

- 修复生产库事实隔离与孤立连接 ATTACH 边界。
- 修复 worker 启动失败登记与异常退出入队竞态，增加 Event 确定性测试。
- 按块持久化草稿，恢复不重写既有行，kill 后七字段对拍。
- 后端提供出处与答案展示字段，前端采用真正 Acorn AST 边界断言。
- 补齐 SQL 扫描八类反证、封面精确版本比较及 round6 门禁更正。

## [0.15.7] - 2026-10-11 · S1 六轮隔离与线程恢复
- samefile 拒绝生产硬链接别名，归一 URI/相对路径/尾斜杠，明确只在孤立运行强制。
- worker 异常退出 finally 清登记，固定无正文日志，下次上传无需重启恢复消费；单任务承诺限单进程。
- AST 扫描增加 exec/eval/getattr、%s/format/join、跨行 CTE/JOIN 反证；读路由差分范围明确。
- 前端零计算精确为禁止原文推导，纯数值展示/手势 Math 函数白名单断言；保留暖纸 UI，无布局样式变动。
- 同步四件套、页脚与规格封面，真 provider 与门禁证据见 reports/S1-round6.md。

## [0.15.6] - 2026-10-11 · S1 五轮隔离与恢复修复
- 测试/冒烟自隔离，真实生产路径（含符号链接）在迁移/worker 启动前拒绝；环境路径覆盖 import 时快照。
- 卡池扫描覆盖全部 backend Python，例外限定具名函数/操作；识别 schema、f-string、拼接 SQL。
- worker 持续消费并锁内握手退出；增加运行期间入队与真实子进程 kill/重启断言。
- 恢复保证已完成缓存块不重跑，不保证外部调用 exactly-once；LLM 返回至缓存持久化窗口可能重复花费。
- 扩充冻结时钟 HTTP 状态/响应 bytes 差分矩阵；同步版本四件套和页脚，无布局/样式改动。
- 断言、反证、生产只读对账与门禁证据见 `reports/S1-round5.md`。

## [0.15.5] - 2026-10-11 · S1 四轮（UP-005 真跑已通过）
- UP-006 卡池 SQL 收拢至 services/cards.py 具名操作；源码反断言与裸 SQL 反证，既有读响应逐字保持。
- UP-008 两任务并发实测与去锁反证，worker 日志不含正文。
- UP-009 上传提交/后端可用性/轮询；副本临时实例注入 stub provider，浏览器 PDF→进度→保留删除→.primary 确认→卡池正向验收通过。
- UP-005 首次真跑失败（根因 = 接线缺失，见下），**pm 复验已通过**：同一 PDF 连上两次 → 第二次 `reused=true`、LLM 账本 +0 行、`books 1→1`、`reasoning_tokens=0`；证据 `reports/r4-logs/up005-real-pm-rerun.log`（首跑失败原文保留在 `up005-real.log`，不覆盖）。
- **缺陷修复（LLM 接线自检，pm 补）**：本机 `.env` 原先**没有**任何 `LLM_*` 接线 → config 默认 `provider=proxy` + 空 `LLM_API_KEY` → 本地 LiteLLM 返回 **401** → 出卡必失败（异常被收敛成 `job failed`，真跑现场几乎不可查）。修：`.env` 补 `LLM_PROVIDER/LLM_BASE_URL/LLM_MODEL/LLM_API_KEY`（备份 `.env.bak-20261011-230632`，`.env` 不入库）；`proxy` 档缺 key → `create_app` 启动 WARNING（`backend/app.py`）；`.env.example` 补模板（占位不含真密钥）。断言 `tests/test_llm.py::test_proxy_provider_without_key_warns_at_boot`；口径 `DESIGN_SPEC §11 UP-012 接线口径` + `§12 [0.15.5]`。
- 同步后端与前端版本 0.15.5；未改复习/出题/掌握度/连胜口径，未写生产库。详见 reports/S1-round4.md。

## [0.15.4] - 2026-10-11 · S1 三轮收口
- P0-1 上传身份只新增 upload 行；`tests/test_upload.py::test_upload_book_identity_isolated`。P0-2 cardlen 逐项命名兜底；`tests/test_cardlen.py::test_names_fallback_per_item`。P0-3 finalized cache/draft 不二次闸门；`tests/test_cardgen.py::test_final_split_rows_never_regated`。P0-4 reasoning 解析/拒收统一；`tests/test_llm.py::test_top_level_reasoning_rejected_and_logged`。P0-5 探针三校验；审计探针入口见 `reports/S1-round3.md`。
- P1 启动迁移排除 upload DDL，显式入口输出 DDL/路径并幂等；`tests/test_migration.py::test_startup_migration_excludes_upload_ddl`、`::test_explicit_upload_migration_is_idempotent`。
- 门禁隔离（pm 补）：`make ui-audit` 自举实例改跑**生产库副本**（`sqlite3 .backup` → `DATABASE_PATH`），兑现「绝不回灌生产库」的既有设计意图；实测跑前跑后生产库计数完全一致（426/115 不变）。此前实现接了生产库，审计的写入型断言把 +32 `card_reviews` / +5 `quiz_attempts` 落到了生产。
- 门禁修复（pm 补）：`ui_audit.js` ㉒「闪卡出处行」在可复习池为空（今日组达标 + 无到期/新卡）时改为断言复习页空态 + 引导（UI-003），不再假红；日志明示该档未覆盖卡面（后续适用条款见 `DESIGN_SPEC §12 [0.15.4]`）。
- P2 provider payload 测试显式设档；命名兜底序号限定块内、非全局唯一；分别由 `tests/test_llm.py::test_payload_thinking_disabled`、`tests/test_cardlen.py::test_fallback_name_uniqueness_is_block_local` 断言。local provider 未实测时如实标记受阻。

## [0.15.3] - 2026-10-11 · S1 真跑打通（pm 手改两处阻塞）
- UP-004 关思考修正：**实测**经本地 LiteLLM（proxy 档）时顶层 `thinking` 不生效——deepseek-flash 单块仍产出 **4059** reasoning token 并被闸门拒绝；改送 `extra_body.thinking` 后 `reasoning_tokens=0`。official 档仍用顶层 `thinking`。断言：proxy 档 payload 含 `extra_body` 且不含顶层 `thinking`，official 档反之。
- UP-014 命名兜底：**实测**模型可返回 `subcards: null`，原「缺命名即拒」会整块丢弃；改为确定性兜底（短名 = 该要点首 8 字去标点/空白，重名补序号；问句 = 原 question + 「（要点N）」）。命名缺失不再阻塞机械切分，正文仍逐字节不动。
- **首次真跑端到端出卡**（真书文 → proxy `deepseek-flash` → 卡闸/222 切分/契约 → 块缓存）：单块 8 张、超 222 张数 0、八字段齐、`prompt_cache_hit_tokens` 384、`reasoning_tokens` 0、账本 1 行且无正文；**二次跑命中块缓存 → 0 次 LLM 调用**。
- 覆盖率 95.55% ≥94.5%；`make lint test` PASS。未写生产库、未 push、未重启服务。

## [0.15.2] - 2026-10-11 · S1 二轮修正（仍为部分交付）
- 起点 c270e15，既有 REQ 不改。UP-014 唯一纯函数实现与 KB 两本真实产物逐字节对拍，六条断言通过；无标点长要点拒收，不改写正文。
- UP-006 九读接口夹具已有真实 cards/card_reviews，泄漏探针能变红；递归源码白名单扫描通过。全部既有卡池读取尚未集中到 services/cards.py，仍受阻。
- UP-012 测验 provider 旁路已去除，网络出口扫描覆盖 backend 全部 Python 含 scripts；迁移重复非 NULL hash 预检中止打印冲突，接收 DB 失败清理本次新建 PDF。
- UP-004 块缓存、卡闸/222切分/契约验证、草稿写入已实现并 mock 验证；UP-005 已确认书池复用；UP-009 草稿保留删除与显式事务确认已接入。真实 PDF→块→mock卡→草稿通过，真实 proxy 出卡未通过验收，不能视为真跑完成。
- UP-008 单线程锁与中间态缓存续跑接口已实现；线程生命周期/并发接收尚未充分验证，默认不开 worker。上传页仍常显置灰，上传提交/轮询及完整正向浏览器确认仍受阻。
- lint/test、compileall、临时库 smoke、受阻态 UI audit 的实际结果与逐项反证在 reports/S1-round2.md。未降低94.5%门槛，未写生产库、未 push/重启/触碰 launchd。事实审计部署/push项目不能在本任务红线内变绿。
- 两份 UI 必读规范及 minimalist 路由技能已读；沿用暖纸令牌、细线留白、可读灰色 low、唯一确认主行动；无新依赖/横滑/原生 checkbox，后端下发可确认状态。前端版本面同为0.15.2。

## [0.15.1] - 2026-10-11 · UP-013 补充（S1 整体仍受阻）
- UP-013 适配层已实现：集中 cardgen/dedupe 前缀，动态块只在最后 user 消息；单点强制校验，无时间戳/随机 ID。现有 quiz 提示词/业务口径不变。
- 每次出站调用落账七字段白名单（TZ8 timestamp、配置 model、白名单 feature、四项 token 数）。兼容 DeepSeek cache_hit 和 OpenAI cached_tokens；无 usage 的失败调用计数 null，不伪造零用量；先落账再拒收 reasoning。文件 0600、跨进程锁、flush/fsync；落账失败拒绝结果，错误不回显正文。
- 三条指定断言与动态前缀反证见 reports/S1-2026-10-11.md。仅 mock 临时账本验证；未触网、未实测供应商缓存命中，完整出卡/去重通路仍受 UP-004/005 阻塞。本补充不解除原 S1 缺口。
- lint/test PASS，coverage 95.61% ≥94.5%；compileall、临时库 smoke、UI 审计 PASS。
- 版本面统一 0.15.1；仅版本文本更新，无 UI 布局/交互变更。两份必读设计规范已重读，保留原暖纸视觉与常显告知/禁用原因。

## [0.15.0] - 2026-10-11
- S1 部分实现，受阻未上线。UP-001/002/003/010 已实现校验、缓存抽文、确定性分段、幂等迁移和 pm 备份对账脚本；UP-007/011/012 配额、逐字告知与单一 LLM 出口已实现。
- UP-004/005 未实现：仓库无 CARD-LEN-01 既有实现和完整切分定义。UP-006 部分：9 个读 API 草稿差分通过，但 status='active' 与既有卡四态 CHECK 冲突，未实现该单点过滤。UP-008 部分：状态守卫已实现，线程与续跑未完成。UP-009 部分：两个受阻态页面已实现，逐卡操作/确认未完成。
- 覆盖率 95.57% ≥94.5%，lint/test、临时库 smoke、UI 审计通过；断言和反证见 reports/S1-2026-10-11.md。生产库未写，真实 394/110 历史未迁移（合成同量临时库对账通过）。未 push、未重启、未碰 launchd。local 默认 skip、未连接外部机器。
- review-audit-facts.sh 未运行：内部 smoke 默认写生产库，与任务只读约束冲突；由 pm 复跑。既有 REQ 和状态未修改，仅授权追加 UP-011/012。
- 前端规范自查：完整读取两份必读规范及 taste minimalist 路由技能；沿用暖纸/墨字/草绿令牌、字号层级、细线留白，无新依赖/emoji/嵌套卡/横滑/原生 checkbox；配额/进度只读后端，控件常显置灰附原因，告知在 loading/error/success 均保留。


## [0.14.2] - 2026-10-09
- **修复（冰冻符号与数字比连胜「小一号」· owner 追问）**：页头冰冻 chip 原为 `font: inherit`（继承 13px）+ emoji `❄` 文本节点，
  而连胜那组是 17px 显示字体 + 18×18 描边 SVG → 实测 连胜数字 17px / 冰冻数字 13px、四叶草 18×18 / ❄ 字形 13.3px。
  现改为**与四叶草同款的内联描边雪花 SVG**（`svg.flake`，18×18 · stroke-width 2 · currentColor）+ 数字用 `--disp` 17px，
  与连胜那组完全同尺寸；chip 改 `inline-flex` 让图标与数字同基线。
- **断言**：`make ui-audit` 新增 ⑯c（拿屏幕实测值对两组：图标盒 ±1px、数字计算字号相等、chip 内禁 emoji 字形）；
  `tests/test_frontend.py::test_freeze_icon_matches_streak_source` 源码级反断言。**反证**：`.freeze-chip .flake` 还原成 13px → ⑯c 真红。
- 前端三件套 bump 到 0.14.2（`sw.js` CACHE `review-v0.14.2` / `const V` / `index.html` 全部 `?v=` + 页脚）。

## [0.14.1] - 2026-10-09
- **修复（页头冰冻 chip 恒显示 0）**：`frontend/js/app.js` 原先写成 `const d = r.data.days || 0; … const f = d.freezes || {}`
  —— 从**数字**上取属性恒为 `undefined` → 接口 `available=4` 而 chip 恒显「❄ 0」+「冰冻已用完，漏卡将清空连胜」（公网实测）。
  改为先留响应对象再取字段（`data.freezes.available`，前端零计算）。
- **断言补齐（防复发）**：`scripts/ui_audit.js` 新增 **⑯b**（`#freezeCount` 必须 == `/api/streak.freezes.available`；有余额不得置灰、
  余额 0 必须置灰且写明原因）；`tests/test_frontend.py::test_freeze_chip_reads_freezes_off_response_object` 源级反断言（禁 `d.freezes`）。
- **反证**：还原旧写法 → `make ui-audit` 真红（「显示 0 / 接口 4」「有余额却置灰」「有余额却提示用完」）。
- 前端三件套 bump 0.14.1（`sw.js` CACHE `review-v0.14.1` + `const V` + `index.html` 15 处 `?v=` + 页脚）—— 绕开 CF 对 `.js` 的 4h 强缓存。

## [0.14.0] - 2026-10-09
- **FREEZE-001/002/003（新）连胜冰冻**（对齐 AI 学习小组 REQ-CHECKIN-013）：初始 **3 次**（`FREEZE_BASE`，env 可覆写）；
  连续段内位置 5 的倍数**且当日达标**才 +1（冰冻日占位不加冕）；漏卡自动消耗锁住连胜，缺口 > 余额则一行都不写、连胜按原规则归零；
  **只结算最后一段缺口**（旧断点不回溯扣）。落表 `streak_freezes(day, streak_kept, created_at)` 只记已消耗；
  `streak_kept` = 冻结前连胜天数。前端右上角 `.clover` 旁 ❄ + 余次（常显，0 时置灰并写明原因），点击出规则/最近 3 条记录，消耗时播一次性「数字被冰封」动画。
- **GOAL-003（修）复习队列 = 当日一组内的剩余**：今日一组 = 30 张；`done` = 今日已过关（最新一条 hard/good 且未到期）的不同卡数，
  打开 = `min(30 − done, batch_max)`；已过关且未到期的卡不再重复推送；判「忘了」（again）的卡不算过关、**排最前**到期即回队；
  组满 30 后由「再来一组」开新组。响应新增 `group={target,done,remaining}`（只增不删）。
- **QUIZ-013（修）出题每次 5 道**：`frontend/js/quiz.js` 删掉写死的 `const SIZE = 10`（它盖掉了后端 `QUIZ_TASK_TARGET=5`），
  题量此后只由后端下发（前端零计算）。
- **证据**：`make lint test` 全绿（覆盖率 ≥94.5）、`make smoke` 自证、`make ui-audit` 全绿；真库副本探针见 `DESIGN_SPEC §12 [0.14.0]` 补记。


## [0.13.1] - 2026-10-03
- **QUIZ-012（新，🔒 口径）出题题型必须逐字兑现 + 干扰项不得取「纯名词标签」**（owner 报障：出题自测里两个选项竟是「了解」「关心」）。
  根因两条，都在出题服务：① `_system_prompt` 的 JSON 骨架写死 `{"type":"bool",…}`、规则只讲判断题 → LLM 照抄样例，
  要选择题也返 `type=bool`，被 `_validate` 拒收 → **2026-09-27 起 28 道选择题全部降级**为机械题（AI 选择题最后出现在 09-28）；
  ② 机械降级取 `chapter_point_pool()[:2]` → 池按卡序，第 1 章首卡是「合成示例书10」概念卡（背面 6 条纯名词标签
  `了解（knowledge）`/`关心（care）`/…）→ **全章每题干扰项恒为那两条**。
- 修复：提示词改为**按题型分别给规则 + 与各卡 `want` 同型的骨架**（并明令「必须逐字照办」）；题型不符的产出记
  `logging.warning`（"题型不符"）便于事后定位；机械干扰项改 `pick_distractors()`——排除纯名词标签（`is_gloss_label`）、
  按「与正确答案长度相近」取候选后**按 `card_id` 确定性抽签**（同章不同题不再恒等，同库同卡可复现）；正确答案本身是标签
  → 该题降级为是非题，不生造烂选择题。
- 一次性刷新：`refresh_stale_quiz_items.py` 脏题判据新增 `fallback_choice`（`source='fallback'` 且 `type='choice'`），同 `id` 覆盖重生；
  `language` 类必须刷到 0（断言），`fallback_choice` 残留只 warning（不把 LLM 故障当刷新失败）。
- 机械断言（**旧实现下 5 条全红**，反证实测）：`test_prompt_skeleton_follows_wanted_types` /
  `test_llm_batch_rejects_wrong_type_and_warns` / `test_gloss_label_boundaries` /
  `test_mechanical_choice_never_uses_gloss_label_distractors` / `test_mechanical_choice_distractors_vary_between_cards`
  / `test_mechanical_degrades_to_bool_when_correct_is_label` + 刷新三例（见 `tests/test_quiz_refresh.py`）。
  旧代码下 ④ 的失败输出逐字复现用户截图：`frozenset({'了解（knowledge）', '关心（care）'})`。
- 版本 bump 到 0.13.1：`config.py` / `CHANGELOG` / spec 头一致；前端资产三件套
  （`sw.js` `CACHE`/`V` + `index.html` 全部 `?v=` 与静态页脚 `#ver`）一处不漏。

## [0.13.0] - 2026-10-01
- **CARD-008（新，🔒 口径）换版入库：复习进度按「知识点」保住，不按「题面」判生死**。
  上游重新导出后，若旧卡与新版契约行**同 `concept_id` 且 `back` 逐字相同**（= 同一知识点的同一正文），
  用 `backend/scripts/reswap_card_text.py --match back` **就地**把题面换成新版文本 —— 卡 id、`status`、
  `learn_count`、`next_review_at` 与 `card_reviews` 复习历史一律不动（不是「删了重插」）；
  命中 >1 张（撞车）→ **整批拒绝、库零改动**；库内没有同正文的行 = 上游新增/正文真变 → 跳过并计数
  （交 `ingest_kb.py` 新增 + 退场收尾），**不硬配到别的卡上**。默认 `--match order` 行为不变（QUIZ-010 英文卡面换文路径不受影响）。
  成卡文本统一走 `ai.cardtext.to_card`（与 ingest 同源，含要点去重）。
- 机械断言：`tests/test_reswap_card_text.py::test_back_mode_adopts_rewritten_front_and_preserves_progress`
  （3 张只改题面 → `changed=3 unchanged=0`，卡 id 集合不变、`learn_count`/`status`/`next_review_at` 前后相等、再跑幂等）
  + `::test_back_mode_counts_rows_without_counterpart_as_new`（上游新增行 → `new_rows=1`，不报错）
  + `::test_back_mode_rejects_when_pairing_is_not_unique`（背面撞车 → 非零退出且库零改动）。
- 《合成示例书2》按修复后的契约重出（328 行 → 598 行）后换版入库：账见 `reports/ingest-2026-10-01.md`。
- 版本 bump 到 0.13.0：`app.py` / `config.py` / `CHANGELOG` / spec 头一致；前端资产三件套
  （`sw.js` `CACHE`/`V` + `index.html` 全部 `?v=` 与静态页脚 `#ver`）一处不漏。

## [0.12.0] - 2026-09-30
- **DATA-006 章显示名（2026-10-01 补充）**：契约可选 `chapter_title`（纯标题、≤40 字、不含换行），章以 `(book_id, anchor)` 复用，显示名为 `anchor · chapter_title`；旧契约不覆盖既有人工章名。卡片 `source` 使用实际章显示名，跳过的旧卡只在 source 不符时刷新；无效标题逐行拒收并计「待人工」。同版本补丁：后端/前端版本各处本已为 0.12.0，不做无效 bump。
- **CARD-007（新）+ UI-019（新）：契约 `title`（「概念名 · 子卡短名」）逐字落库 + 卡面显示子卡短名**（owner 2026-09-30 拍板）。
  事实校正（brain 实测）：四本书 jsonl 的 `title` **本来就是**「概念名 · 子卡短名」复合格式、全库都有 →
  **无需给数据源补字段**，缺的只是 app 侧「存下来 + 显示出来」这一层。
  - **落库**：`cards.title` 由 `models.migrate()` 幂等加列；`ingest_kb` 新卡 INSERT 带 title，既有行按
    `(concept_id, content_hash)` **幂等重导**回填（新增「回填」计数 + 审计列）。本次全库重导 4 本书：
    合成示例书4 100 / 合成示例书1 508 / 合成示例书3 328 / 合成示例书9 127 = **1063 行全部回填，
    新增 0 / 合并 0 / 待人工 0**；复跑 **回填 0 / 跳过 1063**（幂等自证）。
  - **显示**：`services/labels.subtitle_of()` 单点派生 `subtitle`（取 ` · ` 右段；为空或 == 概念名 → `null` 不显示，防「合成示例书10 · 合成示例书10」），
    由 `/api/cards`（附带 `concept_name`）、`/api/today`、`/api/plan` 三处下发；概念页 `h1` = 概念名（不重复），
    卡面首行 = 子卡短名 → 题面 → 要点 → 页脚（四态 · 已学 n 次 · 来源）；闪卡/今日清单/计划出处行 = `书 · 章 · 概念[ · 子卡短名]`；前端零 split。
  - **实测**：1063 张卡 title 全落库（NULL = 0），其中 **916 张有可见短名**、147 张不显示
    （111 张未切分 `title = 概念名` + 36 张「右段 == 概念名」）；概念 504「心智层级」（ch-L057）3 张短名
    `技能树高度取各线均值` / `停思根源与高压退化` / `层级对话与体验升级` 已在 API 与页面命中。
- `make ui-audit` 新增 **㉒**（CARD-007 / UI-019）：① `subtitle` 必为 `title` 右段且 ≠ 概念名；② 概念页 `.block` 数 == API 卡数、
  短名在卡面**首行**、`h1` == 概念名；③ 未切分卡 `subtitle` 全 `null` 且页面无「X · X」；④ 队列有带短名卡时闪卡出处行必含短名；
  ⑤ `app.js`/`review.js`/`plan.js` 均接 `.subtitle` 且无 `split(' · ')`（前端零推导）。
- 范围口径未动：`prefs.book_scope`（SCOPE-001~004）与复习范围行为零改动。
- 版本 bump 到 0.12.0：`app.py` / `config.py` / `CHANGELOG` / spec 头一致；前端资产三件套一处不漏
  （`sw.js` `CACHE`/`V` + `index.html` 全部 `?v=` 与静态页脚 `#ver`）。

## [0.11.1] - 2026-09-30
- creator 学科入库（CARD-001 / DATA-006）：`exports/creator/合成示例书4.jsonl`（97 行 / 28 概念 / 22 章）
  四段账 **新增 97 · 合并 0 · 丢弃 0 · 待人工 0**，复跑幂等（新增 0 / 跳过 97）；
  `config.SUBJECT_LABELS` 补 `"creator": "创作者经济"`（单点映射，显示名写入库内 `subjects.name`）。
- MAST-004（修订）：`make ui-audit ⑬` 首页学科块环心/星旁断言补 **na 分支** —— 无已学卡
  （`mastery.m === null`，如本次新入库学科）的层级星位必须显「掌握度 —」、**不得显 0%**，
  覆盖率照常显示；断言改为逐行对回 `/api/subjects` 的 `mastery` 字段（行数 + 环心覆盖率 + 星位
  `aria-label` 两态），与既有的 `FORMULA`/`ZERO` 同口径。
- 版本 bump 到 0.11.1：`app.py` / `config.py` / `CHANGELOG` / spec 头一致；前端资产三件套一处不漏
  （`sw.js` `CACHE`/`V` + `index.html` 全部 `?v=` 与静态页脚 `#ver`）。

## [0.11.0] - 2026-09-30
- SCOPE-003（修订）+ SCOPE-004（新）：图书范围「至少 1 本」显式选择，空集合不再是合法状态。
  范围页改为「先草稿、后确认」：勾选 / 全选 / 清空只改本地草稿、不发请求，只有「确认」（`.primary`）
  才 `PUT /api/scope`；草稿为空时确认被拦（「至少选择一本书」，`role="alert"`，不发请求、不跳转）。
  后端 `PUT /api/scope` 同样拒绝空数组（`e_input("至少选择一本书")`，防旁路）；历史遗留 `book_scope="[]"`
  读取时归一为「全部」并提示「检测到空范围，已恢复为全部图书」（幂等迁移删除该 pref 行）。
  首页「图书」文案不再出现「未选择」。
- F 门禁确定性：`agent-browser` 调用失败自动重试（3 次退避）+ 区分「工具失败 / 断言失败」；
  ⑰ 加就绪守卫（等 `.opt`/`.state`，「加载中」重新 open + 等就绪）+ 每轮状态快照历史；
  连跑 `make ui-audit` 3 次 3/3 全绿（每次 99 ✓：⑳ 6 项 + ㉑ 5 项 ×2 宽；耗时 118.6s / 118.4s / 118.3s）。
  反证实测：① 去掉 API 空数组校验 → `test_scope_rejects_empty_scope` FAIL（`assert 0 != 0`）；
  ② 去掉确认按钮空判 → `ui-audit ㉑` 第 3 条两宽必红（`alert:false`）；均已 `git checkout -- <file>` 还原。
- 版本 bump 到 0.11.0：`app.py` / `config.py` / `CHANGELOG` / spec 头一致；前端资产三件套一处不漏
  （`sw.js` `CACHE`/`V` + `index.html` 全部 `?v=` 与静态页脚 `#ver`）。

## [0.10.1] - 2026-09-30
- MAST-004（修订）：渲染环星的层级文字行只留「已学 x / 共 y · 状态」，掌握度/覆盖率数字只出现一次
  （环心写覆盖率、星旁写掌握度）；未渲染环星的层级（学科列表 / 章行）文字行保留双数全文。
  前端 `js/app.js` 新增 `mCount` 短文案单点，`mText` 继续服务未渲染环星层级；`ui-audit ⑬`/`⑮` 与
  `test_frontend.py::test_mastery_formula_visible` 同步改为分环星/非环星两档断言（含反证：文字行改回带
  `掌握度 86% · 覆盖率 14%` → 断言 FAIL）。
- 版本 bump 到 0.10.1：`app.py` / `config.py` / `CHANGELOG` / spec 头一致；前端资产三件套一处不漏
  （`sw.js` `CACHE`/`V` + `index.html` 全部 `?v=` 与静态页脚 `#ver`）。

## [0.10.0] - 2026-09-30
- UI-018：主页覆盖率由进度条改为绿色环形图（inline SVG `stroke-dasharray`，底环 `--hair`、进度环 `--green`，环心「覆盖率 c%」）。
- MAST-008：掌握度加五星图（`stars = round(m/20, 1)`，clip 遮罩表达小数星；空星 `--hair`、实星 `--green`），与百分比同点渲染。
- SCOPE-001~003：首页「图书」入口 + `#/scope` 多选复习范围；`prefs` 表持久化 `book_scope`（`None`=全部 / `[]`=空选态 / `[ids]`=过滤），
  范围作用于今日复习队列、测验选题、今日任务计数，只读过滤不改卡状态 / 调度 / 连胜 / 章节解锁，范围外到期卡仍到期不丢卡。
- 版本 bump 到 0.10.0：`app.py` / `config.py` / `CHANGELOG` 一致；前端资产三件套一处不漏（`sw.js` `CACHE`/`V` +
  `index.html` 全部 `?v=` 与静态页脚 `#ver`）；`make smoke` 断言 `GET /` 每个 `?v=` == `/health` version。

## [0.9.1] - 2026-09-29
- QUIZ-010 结果页解析标记统一为粗框我的答案、勾选正确项、错选叉号；删除底部重复答案行。
- 补 bump 前端三件套（`sw.js` `CACHE`/`V` + `index.html` 全部 `?v=` + 页脚 `#ver`）到 `0.9.1`；
  此前停在 `0.8.3`，CF 对 `.js/.css` 强发 `max-age=14400` 会吞掉结果页修复。新增 `make smoke` 断言
  `GET /` 每个 `?v=` == `/health` version，前端版本面自此必须 == app version（见 OPS-002 收紧）。
- QUIZ-011 卡文变化 → 缓存失效：`quiz_items` 复用前校验 `card_content_hash` 与卡当前 `front/back`
  指纹一致，不一致则同 `id` 覆盖重生（不删不插，`quiz_attempts` 外键不动）；一次性刷新生产库 mgmt 10 条
  中文旧题（`scripts/refresh_stale_quiz_items.py`），刷新后 `quiz_attempts` 58 行关联不变。


## [0.9.0] - 2026-09-29
- QUIZ-010：测验题面按卡语种生成，英文判断题使用 True/False；新增安全的英文卡面就地替换 dry-run/apply 脚本。


## [0.8.3] - 2026-09-28
- 测验页改为「选项 → 下一题即提交」，页面内不判分，结果页保留逐题解析。
- 解锁门槛统一使用章级 `level_mastery`，并按卡数缩小已学门槛，修复小章死锁。
- STREAK-004：当日达标快照 `met` 单调不可撤销，当前任务完成态仍实时返回。
- CARD-006：入库仅对 front 归一且 back 完全相同的卡做批内去重，相似卡全部保留。
- 《合成示例书1》重出卡入库：旧 49 张（每页 1 张，答案均约 810 字、最长 1530）→ 508 张（一考点一卡，答案 7–149 字、均 77 字；原 460 条要点逐字保留）；删旧换新：删 49 张卡 + 9 条调度记录（删前备份 `backups/review-2026-09-28-224843-pre-mgmt-resplit.sqlite3`），入库实测 `新增 508 / 合并 0 / 跳过 0 / 待人工 0`。
- 门禁：修 `make ui-audit` ⑰ 的等待竞态与布尔类型比较错误；恢复逐张解析卡断言。

## [0.8.2] - 2026-09-28
- 修复 STREAK-001 与 GOAL-001 口径冲突：连胜改读 `streak_days` 快照，并与 `today_task().done` 统一；迁移幂等回填历史达标日。
- 未动前端、解锁算法、调度或 API 契约。

## [0.8.1] - 2026-09-28
- 修：`index.html` 静态页脚版本串自 `0.6.1` 起未随版本 bump（0.7.0 / 0.8.0 两次漏改）→ 现 `v0.8.1`，版本诚实四处恢复一致；
  同批 bump 三件套（`sw.js` `CACHE`/`V` + `index.html` 全部 14 处 `?v=`）——前端资产改动必须同步，否则已安装客户端长期吃旧壳。
- 断言：`tests/test_frontend.py::test_pagefoot_version_matches_shell`（页脚静态串 == `sw.js` 的 `const V`，且必须是 CHANGELOG 里的真实版本）；
  该漂移此前只有日审脚本一道闸，属「版本诚实」铁律的机械断言缺口。
- 修（**门禁假绿两处 · 审计未覆盖，本次连带发现**）：
  ① `make smoke` 端口 5005 被 `org.example.review` 常驻占用 → 子进程 EADDRINUSE 即死、`curl` 照样 200，
  「冒烟通过」实际是**别的 App 的 `/health`**（返回 `2.20.0`）→ 改 `SMOKE_PORT ?= 5006` + 端口预检 + 响应必须带
  `contract_version` 且版本 == `app.py`（实测输出 `OK: smoke 自证通过（本应用 v0.8.1 @ 5006）`）。
  ② `make ui-audit` 自举（5099）同源缺陷：旧版只要该端口**有东西应答**就继续跑 → 会把历史残留实例当自己的验收对象
  （实况：09-27 17:39 的探针实例一直挂着，09-28 04:17 的审计 ⑰ 写入落进 `/tmp/probe-db.sqlite3`，即当日「ui-audit 全绿」验的是旧进程）→ 加端口预检 + 子进程退出标记，端口被占/子进程先死一律响亮失败。

## [0.8.0] - 2026-09-27
- STREAK-001/002：每日 30 张卡 + 5 道题达标连胜，页头四叶草展示。
- QUIZ-007/008：已学卡池优先出题，结果页逐题解析。
- UNI-MASTER 收口（v0.7.0 规格）：卡级 `M = 0.5×状态分 + 0.5×作答正确率`（7 天半衰期加权），四级 rollup + 覆盖率并列；
  前端四级一律读后端 `mastery.{m,coverage,learned,cards_total,state_label}`（零自算）；四态内部值 `reviewing` 全链统一 + 迁移脚本（幂等、默认 dry-run、`--apply` 先备份）。
- 《合成示例书9》36 → 37 卡：补原书第六部分第四条「真心赞美」漏抽页（brain 核查 → 重导 jsonl → 重新 ingest：新增 1 / 跳过 36）。
- 修：LLM 降级出题必 `KeyError`（`_quiz_pool` 漏 `chapter_id`）；390px 掌握度文本横向溢出（UI-001）；
  空态文案旧题源口径；层级证据卡判定对齐 AI 学习小组（≥1 次）。
- 断言：`make ui-audit` 新增 ⑮（双数逐字等于后端）/ ⑯（页头四叶草 + 数字 + 「连胜」）/ ⑰（真答一局 → 结果页逐题解析）；
  审计改**自举副本实例**（库副本 + 5099），含写入的断言不回灌生产库。`tests/test_mastery_unified.py`、`tests/test_status_vocab.py`、`tests/test_migrate_status.py` 新建。
  实测：覆盖率 95.36%（门槛 94.5%）、ui-audit 69 条全绿、两条植入反证均能证伪且 sha256 还原一致。


## [0.6.1] - 2026-09-27 · 掌握度口径可见 + 概念行卡状态（MAST-004 / MAST-005）

> owner 2026-09-27 真机反馈：「前端看不到卡片状态和掌握度我的计算公式」。口径已冻结进
> `DESIGN_SPEC.md`（MAST-004 / MAST-005 新）、`CLAUDE.md §8`；每条都落**机械断言**
> （`make ui-audit` ⑬⑭ + `tests/` 反向断言）。**纯口径/展示修正：不动 API 既有字段、不动调度/出题/入库。**

### 新增 / 变更
- **MAST-004 掌握度口径可见**：四级掌握度（学科 / 书 / 章，及学科页书行）一律显示
  `{pct}% · 已掌握 {num} / 已学 {den}`，数值**只读**后端 `mastery.num/den`（前端零计算）；
  学科页与书页**常显**口径说明句「掌握度 = 已掌握卡数 ÷ 已学卡数；未学卡不计入分母（卡级按 0/1 计）」。
- **MAST-004 禁分母错位**：删掉旧 `掌握 0% · 已学 2/237` 混写（0% 的分子分母实为 0/2）；
  总卡数一律**另写**「共 N 张」/「共 N 张卡」，不得与掌握度同括号。
- **MAST-005 概念行卡状态**：章展开与 `#/chapter/<id>` 的每个概念行显示后端下发的 `status_label`
  （同态 → 四态标签；多态 → `未学习 2 · 学习中 1`，顺序固定 新→学→复→掌、只列非零；无卡 → `无卡`）。
- **后端**：`GET /api/concepts?chapter_id=` 每个概念项新增 `status_counts`（恒四键）与 `status_label`；
  未知 `status` → 计入 `new` 并追加响应顶层 `warnings` + `logging.warning`（不静默吞）；
  四态中文词表唯一来源上移到 `config.BaseConfig.STATUS_LABELS`（`services.labels` 只取词）。
- **前端**：`js/app.js` 新增 `mFormula` / `mText` / `masteryNote()` 单点；概念行沿用既有 `.mlabel .cm` 皮肤；
  `backend/frontend/DESIGN.md` 同步对应描述（视觉世界不变：暖纸 editorial + 草绿 `#1E7C50`）。

### 断言
- `make ui-audit` 新增 **⑬**（四级 `已掌握 x / 已学 y` + 学科页/书页口径说明句原文；
  **反断言**：掌握度元素自身文本内不得出现总卡数）与 **⑭**（书页展开首章 → 概念行数 > 0 且每行 = 四词表之一 + `N 张卡`）。
- `tests/test_concepts.py::{test_word_table_single_source,test_status_counts_and_label}`
  （四态分布 / 多态顺序 / 无卡 / 未知态回落 + warning / 未解锁口径不变）。
- `tests/test_frontend.py::{test_mastery_formula_visible,test_concept_row_status_from_backend}`
  （反断言：前端不得出现四态映射表、不得 `已学 x/237` 混写、不得自算状态计数）。
- 反证：① 概念行去掉 `status_label` → ⑭ FAIL（30/30 行缺四态标签）；② 改写口径说明句（`÷`→`/`）→
  ⑬ FAIL（学科页 + 书页均缺原文）；③ 首页塞回 `已学 4/237` 混写 → ⑬ FAIL（实测值 `0% · 已学 4/237`）。三者还原后全绿。

### 版本
- `backend/config.py VERSION` / `backend/app.py version` / `CHANGELOG.md` 段号 / `DESIGN_SPEC.md` 文档头 → **0.6.1**；
  前端三件套（`sw.js` CACHE+V、`index.html` 全部 `?v=` + 页脚）同版。

## [0.6.0] - 2026-09-27 · UI 更正六条（书层 / 任务按钮 / 目标 30 / 知识卡片 / 卡四态 / 工艺与可读性）

> owner 2026-09-27 用 `impeccable` 审视后拍板六条更正。口径已冻结进 `DESIGN_SPEC.md`
> （UI-015/016/017、A11Y-001、TASK-002、GOAL-001、MAST-003）与 `CLAUDE.md §8`；
> 每条都落**机械断言**（`make ui-audit` ⑧⑨⑩⑪⑫ + `tests/` 反向断言）。

### 新增 / 变更
- **UI-015 书层**：`#/subject/<id>` = 书列表（h1 + 每本书行：书名 + 书级 `.bar` + 百分比）→
  `#/book/<id>` = 章 → 概念 → 卡；删掉扁平直落 `books[0]` 与「另一本书」小节。
- **TASK-002 任务按钮**：未完成「去完成」/ 完成绿勾（`.tick.on`，非 emoji）+ 「再来一组」；
  目标值一律后端下发（`/api/task`）；退化态（`target=0`）按钮常显 + 置灰 + 写明原因（UI-003）。
- **GOAL-001 目标 30**：`config.REVIEW_TASK_TARGET = 30`（env 可覆写）为单一真相；
  今日复习目标 = `min(30, 到期 ∪ 未学新卡)`（仅计已解锁章）；队列 = 到期（升序）优先 + 新卡补足到 `target`；
  首页 `.primary` 的 N == `review.target`（清掉两口径打架）。
- **UI-016 命名**：「挑新卡」→「知识卡片」（含 `#/subjects` 的 h1）；全站零残留。
- **MAST-003 卡四态**：`status_label` 由**后端**下发（new/learning/review/mastered →
  未学习/学习中/复习中/已掌握），卡列表 / 闪卡 / 错题本 / 复习计划每张卡显示；前端**零映射**，删旧两态。
- **UI-017 动效工艺**：贝塞尔 y 控制点 ≤1（`--ease` → `.16,1,.3,1`）；进度条填充禁 `transition: width`
  → `transform: scaleX(var(--p))` + `transform-origin: left`。
- **A11Y-001 对比度**：`--muted` `#8C8371`(3.5:1) → `#6E6553`（对 `--paper` 现算 **5.34:1** ≥4.5）。

### 断言
- `make ui-audit` 新增 **⑧⑨⑩⑪⑫**（书层 / 任务按钮两态 / 单一目标 / 卡四态 / 对比度）。
- `tests/test_frontend.py`：`test_subject_page_lists_books_only` / `test_knowledge_cards_naming` /
  `test_task_row_actions` / `test_no_hardcoded_goal` / `test_card_status_labels_from_backend` /
  `test_motion_craft_floor` / `test_muted_contrast_aa`。
- `tests/test_tasks.py`（GOAL-001 目标 / 补足 / 退化 reason / env 覆写）+
  `tests/test_cards.py::test_status_label_four_states`（四态 + 未知态 warning）。
- 反证：逐条植入违规 → 对应断言 FAIL → 还原 PASS（见交付报告）。

### 版本
- `backend/config.py` / `backend/app.py` / `CHANGELOG.md` / `DESIGN_SPEC.md` 文档头 → **0.6.0**；
  前端三件套（`sw.js` CACHE+V、`index.html` 全部 `?v=` + 页脚）同版。

## [0.5.7] - 2026-09-27 · 闪卡自评按钮顺序对齐手势方向（UI-014 补漏）

> **用户实测发现**：复习页底部按钮「左 记得 / 右 忘了」与提示「**右滑 = 记得 · 左滑 = 忘了**」**方向相反**。
> 根因 = `UI-014` 只锁了手势方向、**没锁按钮顺序**（口径漏一半 → 门禁全绿也照样错）。
> 本次把口径补进 `UI-014`（触发点 / 覆盖路径 / 违规处置 / **机械断言**），并落 `make ui-audit` ⑦ + pytest 反向断言。

### 修复
- `js/review.js`：动作区按钮顺序改为 **左「忘了」(`#k-again`) → 右「记得」(`#k-good`)**；
  主行动 `记得` 保持 accent 实心并**在右**，`忘了` 走 hairline（一屏仍只有一个主行动，UI-008）。
  手势方向（右滑记得 / 左滑忘了）、阈值 70px、提交契约（`good`/`again`）**未改**。

### 规格
- `DESIGN_SPEC.md`：`UI-014` 增补「底部按钮顺序与手势同向」条款（含触发点 / 覆盖路径 / 违规处置 / 断言）。

### 断言
- `scripts/ui_audit.js` 新增 **⑦**：源码顺序 + DOM 实测左右位次 + accent 归属 + `.actions` 未反转视觉顺序。
- `tests/test_frontend.py::test_flashcard_direction_not_reversed` 扩充：按钮 DOM 顺序 + 主行动归属（反向即失败）。

## [0.5.6] - 2026-09-27 · 复习计划视图 + 薄弱点页 + 本周概况（M2-B3）

> M2-B3：把「复习计划 / 薄弱点 / 本周概况」三页补齐（PLAN-001 / WEAK-001 / RPT-001），
> 后端各一个**只读**统计入口，**前端零计算**。首页「快捷入口」改网格并新增三入口 + 一行本周摘要。
> **本轮不实现「AI 学习建议」**（规格 `ADV-001` 保持 ❌）；**同日 11:57 owner 拍板：不加 → `ADV-001` 升格为禁令**
> （见 `DESIGN_SPEC §1.2` 非目标 + `§3.15`，无旁路）。原文「未拍板」措辞已由本节末「同日补记」取代。

### 新增
- **复习计划视图（PLAN-001）**：`services/plan.py` + `GET /api/plan` + `#/plan`（`js/plan.js`）。
  列出**状态非 new** 的卡，按「**已到期（`next_review_at <= now`）在前** → 下次复习时间升序」排；
  每条显示 `书 · 章 · 卡面` + 间隔人类可读 —— `when_label` 由后端按 `next_review_at` **机械换算**
  （`已到期` / `N 天后` / `N 小时后` / `N 分钟后`），**前端不另算一套、不写死**。
  已到期卡提供**直接作答**入口（`#/review`，复用复习卡作答路径，唯一调度 `review_sched.apply_result`）。
- **薄弱点页（WEAK-001）**：`services/report.weak_chapters()` + `GET /api/weak` + `#/weak`（`js/weak.js`）。
  **按章聚合**（与错题本按卡不同）：章内给 `错次总数 · 涉及卡数`，**按错次降序**；点章 `details` 展开涉及的卡与错次；
  数据源 = `quiz_attempts(is_correct=0)` → 卡 → 章；**只出现有错题的章**。
- **本周概况（RPT-001）**：`services/report.weekly_report()` + `GET /api/report` + `#/report`（`js/report.js`）。
  统计窗口 = **本周一 00:00（本地时区）起**；给出 `复习卡数`（`card_reviews` 去重卡数）/
  `出题作答数` / `判对数` / `正确率` / `最弱一章`（同 WEAK-001 口径，窗口内取）。首页可放一行摘要（复用同一接口字段）。
- **单一入口**：`services/quiz.score_pct(correct, answered)` —— 会话进度 / 结果页（QUIZ-005）与本周概况（RPT-001）
  **共用同一分子分母口径**（分母 = 已作答题数，未答不入）。

### 变更
- **首页「快捷入口」改网格**（`.rowlist.grid`，两列、竖向/横向 gap 均 12px，**不横滑**，UI-001/UI-013）：
  在 出题自测 / 挑新卡 / 错题本 之外新增 **复习计划 / 薄弱点 / 本周概况** 三入口；
  并加一行本周摘要（`本周：复习 N 张 · 作答 M 题 · 正确率 X`）。
- 三页均含**面包屑（`首页 › XX`）** 与返回首页路径；**空态必须有话说**（不空白、不「暂无数据」孤零零）。
- `DESIGN_SPEC.md` 新增 §3.12/§3.13/§3.14（PLAN / WEAK / RPT + ADV 边界声明；**ADV 已于同日 11:57 升格为禁令**）并 §12 回写；
  `backend/frontend/DESIGN.md` 补三页视觉语法与首页网格条款。
- 三件套 bump `0.5.6`：`sw.js` `CACHE`+`V`+SHELL 加 `js/{plan,weak,report}.js`；`index.html` 全部 `?v=` 与页脚同步；
  `backend/app.py` 与 `backend/config.py` → `0.5.6`。

### 说明
- **机械断言（元规则 §10）**：`scripts/ui_audit.js` 扩断言 —— 三新路由入 ①②（块间隙 / 无横滑）+ ⑤（可达 + 面包屑 + 非空白 / 空态）
  + ⑥（源码级：空态文案在位、正确率**只用后端字段**，反断言 `Math.round(...correct...)` 不得出现）。
- 测试（逐 REQ）：`tests/test_plan.py`（间隔换算 `now+3天`→`3 天后`、`now-1h`→`已到期`、排序 / 过滤）、
  `tests/test_weak.py`（只含有错题的章 + 错次降序）、`tests/test_report.py`（周一 00:00 前 1 分钟**不计入**、0 作答 → `accuracy=null`）、
  `tests/test_frontend.py`（三页钩子 + 前端零自算正确率反向断言 + 网格）。
- **未越界声明**：未改上游契约 / 解锁算法 / 复习调度 / 判分路径；三页均**只读**；不引依赖/框架（UI-004）；
  **未实现「AI 学习建议」**（同日 11:57 owner 拍板：不加，`ADV-001` = 禁令）；**不 push、不碰 launchd**。

- **同日补记（2026-09-27 11:57）**：`ADV-001` 由「待拍板」升格**禁令**（owner 拍板「AI 学习建议不加」）——见 §1.2 非目标 + §3.15；上文原文保留作历史记录。

## [0.5.5] - 2026-09-27 · 掌握度四级 + 每日格言 + 今日任务 + 错题本页 + 首页重构（M2-B2）

> M2-B2：把 M2-B1 留下的「前端最小可用 / MAST / HOME / TASK 未实现」补齐并打磨。
> 后端新增**掌握度四级**（MAST-001）、**每日格言**（HOME-001）、**今日任务**（TASK-001）三个单一入口；
> 前端首页重构 + 错题本页（WRONG-001）+ 测验页视觉打磨。

### 新增
- **掌握度四级（MAST-001/002）**：`services/progress.mastery(learned, mastered)` 单点计算 ——
  卡级 0/1（`status='mastered'` 才算），章 / 书 / 学科级 = `mastered / 已学`（`status<>'new'`）；
  分母 0 → `pct=0` 且 `started=False`（**不除零**），前端据此显示「未开始」。
  接入 `GET /api/subjects`（学科级 `mastery` 汇总比例）、`GET /api/books`（书级）、`GET /api/chapters`（章级）；
  卡级由 `GET /api/cards` 的 `status` 表达。**学科 / 书级只出比例**，不出现「第 N 章」单值冒名（沿用 DATA-005）。
- **每日格言（HOME-001）**：`services/quotes.py`（`QUOTES` **48 句**中文格言，纯字符串、**无 author 字段**，
  不编造署名）+ `GET /api/quote` → `{id, text, total}`；索引 = `(本地日 - QUOTE_EPOCH).days % 句数`，
  **同一自然日恒定、跨日 +1（模句数）**；数据源为空 → 回落「今日复习」。
- **今日任务（TASK-001）**：`services/tasks.py` + `GET /api/task` → `{review:{target,done,complete}, quiz:{...}, done}`。
  N = 当天到期卡数（`当前仍到期 ∪ 今日已复习`，**一天内稳定**，不会随复习缩到 0）；M = `config.QUIZ_TASK_TARGET`
  （默认 10，单点配置）。`done = 复习完成数 ≥ N 且 测验完成数 ≥ M`；两子项各自 `complete`。**不含任何催学文案/接口**。
- **错题本页（WRONG-001）**：`#/wrong` 路由 + `js/wrong.js` —— 按**卡**聚合（依据 `quiz_attempts` 判错记录）、
  **按错次降序**；每条 `details` 可展开看「正确答案 / 我的答案」；「重刷这一题」走 `POST /api/wrong/retry`
  发起单题测验，**复用 `QuizView.run`**（不另写一套判分/作答）；空态有话说（「还没有错题」+ 指路），绝不空白。
- **首页重构（HOME-001 + TASK-001 + MAST-002）**：大标题 = 每日格言；副行 = 汇总数字（沿用）；
  主按钮 = 开始复习 N 张；**今日任务**两子项（`今日复习 N 张` / `出题 M 题`，各自可勾，纯 CSS 勾选框、非 emoji）；
  次级入口三行（出题自测 / 挑新卡 / **错题本**）；学科进度行带**进度条 + 百分比**。

### 变更
- **文案修复（缺陷）**：`js/app.js` 首页「出题自测」行由 `10 题 · 看答案后自评，不判分` 改为
  `10 题 · 选择题 / 是非题 · 自动判分`（与新行为一致；全仓 grep `不判分` / `看答案后自评` 无其它残留）。
- **测验页视觉打磨**：进度改「第 x / N 题」；选项三态（选中 `.opt.sel` / 判对 `.opt.correct` / 判错 `.opt.wrong`
  + 正确项同时标出）；结果页「答对 x/y · 得分 z」+ 错题明细排版；选项长文本换行 + `tabular-nums`。
- **`DESIGN_SPEC.md` §3.8 / §3.9 / §3.10 / §3.11 状态回写**：MAST-001/002、WRONG-001（前端）、HOME-001、TASK-001 全部 ❌ → ✅。
- 三件套 bump `0.5.5`：`sw.js` `CACHE` + `V` + SHELL 加 `js/wrong.js`；`index.html` 全部 `?v=` 与页脚同步；
  `backend/app.py` 与 `backend/config.py` → `0.5.5`。

### 说明
- **机械断言（元规则 §10）**：`scripts/ui_audit.js` 扩断言 —— 首页格言**当天固定**（两次取同 ID）+ 四级进度条存在
  + 错题本空态/列表文案。python 侧新增 `tests/test_quotes.py`（HOME-001）、`tests/test_tasks.py`（TASK-001）、
  `tests/test_progress.py` 四级比例对拍（1 章 5 卡 4 mastered → 章/书/学科 80%、分母 0 不除零、学科级无 `unlocked_upto`）、
  `tests/test_frontend.py` 反向断言（错题本页注册 / 格言与任务钩子 / 四级进度条 / 无催学辞）。
- **未改上游契约 / 解锁算法 / 复习调度 / 判分**；不引依赖/框架（UI-004）；**不 push、不碰 launchd**。

## [0.5.4] - 2026-09-27 · 客观题出题管道 + 确定性判分 + 错题本（M2-B1）

> 口径升级：测验从「问答自评（不判分）」改为**客观题**（choice / bool）+ **机械判分**，可落库、可进错题本。
> 出题「缓存优先 → LLM 批量一次 → 机械降级」，**判分与出题彻底分离**（判分绝不走 LLM）。

### 新增
- **数据（迁移幂等）**：`quiz_items`（`card_id/type/stem/options/answer_key/points/source/content_hash UNIQUE/model/created_at`）、
  `quiz_attempts`（`item_id/card_id/session_id/my_answer/is_correct/created_at`，**追加不覆盖**、`created_at` = **UTC ISO 8601**）。
  建表走 `SCHEMA`（`CREATE TABLE IF NOT EXISTS`）→ 可重复执行；迁移前已 `wal_checkpoint` + 带时间戳备份。
- **`backend/services/quizgen.py`（出题）**：照抄「AI学习小组app」`ai/agents.py` 的 `requests` + 超时 + 异常返 None 做法，
  读 `DEEPSEEK_BASE_URL/API_KEY/MODEL`；**批量一次出题**（默认 `QUIZ_SESSION_SIZE=10`、配比 `choice:bool = 7:3`，全部配置化）；
  `content_hash = sha256(card_id|type|stem)` 命中**直接复用不重生成**；会话内 `card_id` 不重复、优先未作答过的缓存题；
  **降级（QUIZ-003）**：LLM 返错/返空/超时 → 机械派生（bool 取 `answer_points` 一条为命题；choice 正确项 + 干扰项取同章其他卡答案要点），
  `source='fallback'` 且必记 `logging.warning`；题干/选项文本全部回溯库内、**不新增事实**。
- **`backend/services/quiz.py`（会话 + 判分 + 错题本）**：`grade()` 单一入口 —— `my_answer == answer_key` **完全匹配** → 1，否则 0
  （**不做 trim/大小写/模糊**）；作答落 `quiz_attempts` 并**复用 `review_sched.apply_result`**（唯一一套调度）；
  得分口径（QUIZ-005）：`y = 已作答数`（未答不入分母）、`z = round(x/y*100)`、`y=0 → z=0`。
- **API**：`POST /api/quiz/session`（返回 `items`，**响应零 `answer_key`**）、`POST /api/quiz/answer`（判分 + 追加 + 正确项）、
  `GET /api/quiz/session/<sid>/result`（`{answered,correct,score,wrong[]}`）、`GET /api/wrong`（按卡聚合、按错次降序、含 `correct_answer/my_answer`）、
  `POST /api/wrong/retry`（对该卡发起单题测验）。旧自评端点 `GET /api/quiz/session/<sid>/answer/<card_id>` **保留可用**（避免线上 500）。
- **前端（最小可用，视觉打磨留 B2）**：测验页改客观题 —— 选项按钮 / 对错两键 → 提交 → 即时判分（我的错选标陶橙警示、正确项标草绿）→ 下一题 →
  结束页「答对 x/y · 得分 z」+ 错题明细；新增 `.opts/.opt`（竖向 `gap:12px`、文本换行不横滑、置灰 `.why` 写明原因）。

### 变更
- **UI-014 口径修订**：闪卡手势**只属复习卡**；**测验页因改为客观题不再左右滑切卡**（`js/quiz.js` 不再引用 `Flashcard`）——
  原因：客观题原地作答，无「下一张卡」方向语义，滑动会与选项滚动争手势。同步修订 `DESIGN_SPEC.md`（UI-001 / UI-014）与 `DESIGN.md §3/§8/§10`。
- **`DESIGN_SPEC.md` §3.7 / §3.9 状态回写**：QUIZ-001…006 后端 ✅（前端最小可用）；WRONG-001 后端 ✅（错题本页留 B2）；
  §4 数据模型 `quiz_items` / `quiz_attempts` 字段与实现对齐。
- 三件套 bump `0.5.4`：`sw.js` `CACHE` + `V`；`index.html` 全部 `?v=` 与页脚同步。

### 说明
- **判分路径零网络**：反向断言 `tests/test_quiz.py::test_grading_module_has_no_network_client`（`services/quiz.py` 无 `requests`/`httpx`/`openai` 字样）。
- **未改 `.env`、未打印任何密钥值、不 push、不碰 launchd**；M2-B1 不含 MAST / HOME / TASK（仍 ❌）。
- `backend/app.py` 与 `backend/config.py` 同步 → `0.5.4`。

## [0.5.3] - 2026-09-27 · 规格与规则固化（UI 机械断言）

> 事故复盘：v0.5.2 的 UI-013「相邻可交互块竖向间隙 ≥12px」**条款写了、实现漏验**，
> 而 `make lint test smoke` 全绿照样放过 —— 根因是 **UI 条款没有机械断言**，且 runbook 不含 UI 自检。
> 本次不写新功能，只把「口径」变成「可跑的判据」并堵住流程。

### 新增
- **`scripts/ui_audit.js` + `make ui-audit`（UI 机械断言，非零退出码 = 失败）**：
  两档宽（**390 / 1280**）× 六条真实路由（`#/`、`#/subjects`、`#/subject/<真实id>`、`#/book/<id>`、`#/review`、`#/quiz`），
  ① 相邻可交互块间隙（竖向 ≥12px、横向 ≥10px，含重叠判定）；② 无 `overflow-x:auto|scroll` 容器且
  `document.body.scrollWidth === innerWidth`；③ 旧 accent `#9a6b3f` 零残留、`theme-color = #FAF6ED`；
  ④ `:focus-visible` / `::selection` / `caret-color` / `tabular-nums` 仍在。用本机 `agent-browser` 实测
  （set viewport → open → eval）；服务没起 → 报错退出并提示先 `launchctl kickstart`。
- **`CLAUDE.md` 新增三节**：**UI 铁律总表**（UI-001…UI-014 每条一句话）；**Runbook（每轮交付固定流程）**
  （写规格 → 实现 → `make lint test smoke` → **`make ui-audit`** → 三件套 bump → 独立 commit → 回写状态）；
  **元规则**「新增/修改任何 UI 条款，必须同时给出机械断言或自检脚本，否则视为未完成」。
- **`DESIGN_SPEC.md` 落详细 REQ（本期只落规格、不实现）**：`QUIZ-001…QUIZ-006`（题型 / 出题来源与缓存 /
  失败降级 / 确定性判分 / 得分口径 / 作答记录）、`MAST-001/002`（四级掌握度 + 展现）、`WRONG-001`（错题本）、
  `HOME-001`（每日格言）、`TASK-001`（今日任务清单/打卡）。每条写全「触发点 / 覆盖路径 / 违规处置 / 断言」。

### 修复
- **UI-013 硬化（相邻块间隙的根因之一）**：进场动画 `.rise` 对**可交互块与列表容器**不再做 `translateY` 位移，
  只做透明度淡入 `fadeIn`。原因：入场瞬间若块自带位移，相邻块的**实测**竖向间隙会从 12px 掉到 ~2px
  （正是本次机械扫描复现 0–1px 的形态）。位移型 `fadeUp` 仅保留给页面级标题与状态块。

### 变更
- **`CLAUDE.md §7` 验证清单**：覆盖率口径由「≥ 50%」改为 **「不得低于上一版实测（现 92.83%）」**；
  新增 **`make ui-audit` 必跑项**。
- 三件套 bump `0.5.3`：`sw.js` `CACHE` + `V`；`index.html` 全部 `?v=` 与页脚同步。

### 说明
- **未改后端 API 契约**（字段不删不改名，无新增字段）；不引依赖/框架（UI-004）。
- **未实现 §3.7–§3.10 的新 REQ**（QUIZ/MAST/WRONG/HOME/TASK）—— 本期只落规格，状态 = ❌ 未实现。
- `backend/app.py` 与 `backend/config.py` 同步 → `0.5.3`。

## [0.5.2] - 2026-09-27 · 闪卡手势 + 相邻块间隙 + 微标签修正

### 修复
- **相邻可交互块间隙不足（pm 机械扫描实测）**：首页「出题自测 ↔ 挑新卡」竖向间隙 **1px**；
  学科页 13 个章行之间 **0–1px**；复习卡「记得/忘了」行底边 y=612 与置灰「看答案」块顶边 y=612 → **0px**。
  规则（UI-013）：任何相邻可交互块**竖向 ≥12px、横向 ≥10px**，hairline 细线**不得作为唯一分隔**。
  改法：`.row` / `.chap > summary` / `.progline` 一律改**独立块**（暖纸卡底 `--card` + 1px `--hair` 边 +
  `14px` 圆角），`.rowlist` 用 `gap:12px` 撑开；保留 editorial 语法（大字号、细线、无嵌套卡）；
  未解锁章行同样块化并置灰（`.row.disabled`）。
- **测验页微标签把「题干」当出处**：`js/quiz.js` 的 `题干 · ${chapter}` → `${book} · ${chapter}`
  （与复习卡一致；`/api/quiz/session` 已返回 `book`）。

### 新增
- **闪卡手势（复习卡 + 测验页共用，`js/flashcard.js`）**（UI-014）：
  - **点击卡面** = 3D 翻转看答案 / 收起（`rotateY(180deg)`，`0.45s`，正反面 `backface-visibility:hidden`）。
  - **拖动** = 跟手 `translateX(dx) rotate(dx*0.045deg)`；滑动期 `.dragging` 关 `transition` + `user-select:none`。
  - **方向判定**：`|dx| < 6px` 不动；`|dy| > |dx|` → 放弃横拖（**竖向滚动优先，必须保留**）。
  - **阈值 70px**：右滑 = 「记得」/「记住了」；左滑 = 「忘了」/「没记住」（**方向不许反**）。
  - **飞出** `.out-r` / `.out-l`（`translateX(±135%) rotate(±16deg)`，`opacity .35`，`320ms ease-in`，`pointer-events:none`）；
    下一张 `.kc-in` 入场（`340ms cubic-bezier(.2,.8,.3,1)`）。
  - **抑制误触**：拖动结束后 400ms 内抑制 click。**桌面**：鼠标拖拽同样支持（`mousedown` + document 级监听）。
  - **按钮保留**：底部「没记住 / 记得」仍在；卡片下方一行提示「拖动卡片：右滑 = 记得 · 左滑 = 忘了」。
  - **单手可达**：提交**先播 `340ms` 动画再落库**；失败**回滚动画与状态**。
  - **`prefers-reduced-motion: reduce`**：关掉飞出/入场/旋转，只保留瞬时切换与数据提交。
  - 测验页答案改为**翻转卡面后懒加载**（铁律不变：题干不含答案）。

### 变更
- **`DESIGN.md`**：§3 补「相邻可交互块间隙（UI-013）」；§6 说明闪卡动画属手势词汇、受 reduced-motion 约束；
  §8 明确 UI-001 只禁**浏览态**横滑容器；新增 **§10 闪卡手势**整节。
- **`DESIGN_SPEC.md`**：**UI-001 口径修订** —— 浏览态（列表/卡片列表）仍禁横向滚动 carousel；
  **闪卡复习态允许并鼓励左右滑动手势切卡**（不落 DOM `overflow-x`）；新增 **UI-013**（相邻块间隙）/ **UI-014**（闪卡手势）。
- 三件套 bump `0.5.2`：`sw.js` `CACHE` + `V` + SHELL 加 `/js/flashcard.js`；`index.html` 全部 `?v=` 与页脚同步。

### 说明
- **未改后端 API 契约**（字段不删不改名，无新增字段）；不引依赖/框架（UI-004）。
- `backend/app.py` 与 `backend/config.py` 同步 → `0.5.2`。

## [0.5.1] - 2026-09-27 · 学科显示名修复（slug → 中文显示名）

### 修复
- **学科名显示为英文 slug `psychology`**（首页学科行 / 学科列表 / 学科页面包屑）。
  根因不在 UI：库里 `subjects.name` 的值本身就是 `psychology`（上游契约 `subject` 字段是 slug，
  ingest 直接把它当显示名写库）。UI 一直忠实渲染 `subjects.name`，本次修**数据侧 + 入库侧**。

### 新增
- **`config.SUBJECT_LABELS`**（`{"psychology": "演示学科"}`）：契约只管 slug，
  **显示名由 app 侧维护**（单点、可扩展；加学科在这里补一行）。
- **`backend/scripts/backfill_subject_labels.py`**：一次性回填既有学科显示名，幂等、
  映射未命中的行一动不动；改数据前先 `wal_checkpoint` + 落带时间戳备份到 `backups/`，跑完打印 before/after 账。
- **REQ-ID `DATA-006`（🔒 口径）**：学科显示名的唯一来源 = 库内 `subjects.name`（条款见 `DESIGN_SPEC §3.1`）。

### 变更
- `ingest_store.upsert_subject`：**已存在的学科完全不写 `name`**（重导入不得冲掉已改好的显示名）；
  仅新建时按 `SUBJECT_LABELS` 取显示名，未命中回落 slug 并 `logging.warning` 一行。

### 修正（诚实记录）
- 反向断言收紧过头：v0.5.0 把「`index.html` 全部 `?v=` == app version」写成硬断言，
  与 CLAUDE.md §5「纯后端改动**不** bump 前端三件套」冲突（本次 0.5.1 即纯后端）。
  现改为正确的**三件套内部一致性**（`sw.js` `const V` == `CACHE` 后缀 == `index.html` 全部 `?v=`）
  + 「该版本号必须在 CHANGELOG 有真实条目」防呆 + 「前端版本不得领先于 app version」。
  前端资产本次**未改动**，`?v=` 保持 `0.5.0`（前端三件套按铁律不动）。

### 说明
- **未改契约与采集链路**：上游 JSONL 的 `subject` 仍是 slug；`contract` 仍为 `1`。
- **未改前端**：所有出现处（首页学科行 / 学科列表 / 面包屑 / 复习卡出处 / 测验页）继续统一读
  `subjects.name`，**不新增前端映射**（避免双份真源、旁路）。
- `backend/app.py` 与 `backend/config.py` 同步 → `0.5.1`；无前端资产改动 → 三件套不动。

## [0.5.0] - 2026-09-27 · 前端大修：暖纸 editorial 精修升级

### 变更
- **设计令牌重写（四语义槽）**：`--paper/--paper-2/--card`、`--ink/--ink-2/--muted`、
  `--hair/--green/--green-deep/--green-tint`、`--orange`（仅未解锁·警示，不做按钮色）+ 禁用槽。
- **主色锁定草绿 `#1E7C50`**（深色 `#14613C`）：旧暗棕 `#9A6B3F` 全站移除，accent 唯一。
- **字号尺度四档拉开**：大标题 34–40px/900（Archivo Black 栈）· 区块题 22px/800 ·
  **正文 17.5px/400**（行高 1.75、行宽 ≤70ch、不得低于 17px）· 次文 15px · 微标签 11.5px/800；
  数字全站 `tabular-nums`。
- **结构语法**：结构靠 1px `--hair` 细线 + 留白；白卡只有一种样式；**禁止卡片套卡片**
  （「学科进度」不再是大卡内嵌小卡）；**一屏只有一个主行动**（深绿实心 `.primary`，其余为 hairline 行）。
- **浏览器原生面主题化**：`::selection` / `caret-color` / 窄滚动条 / `:focus-visible` 草绿 2px 焦点环 / 链接下划线偏移。
- **动效预算**：一次「作者化」错峰 `fadeUp`（`--d` 控延迟）+ hover 抬升 6px；
  **禁无限循环动画**；`prefers-reduced-motion: reduce` 下全部关闭。
- **状态齐全**：hover / `:active`(`translateY(1px)`) / `:disabled`（置灰 + 必写原因）/
  loading（静态骨架 +「加载中…」，无圆形转圈）/ error（`errorBox` 保留套新语法）/ empty（含「怎么产生内容」说明）。
- **首页移除技术文案**：删掉「健康检查：db=ok · contract=1」，`/health` 此后只用于读版本号。
- **logo 换新版**：墨 `#1B1E22` 线稿 + 草绿 `#1E7C50` 强调，去掉浅蓝；PNG 图标同步重生成
  （`favicon-32` / `apple-touch-icon` 180 / `icon-192` / `icon-512`）。
- `index.html` 的 `theme-color` 由浅蓝 `#DCEEFF` 改为暖纸 `#FAF6ED`；`manifest` 底色同步。

### 新增
- **`backend/frontend/DESIGN.md`**：视觉世界规格（令牌 / 字号尺度 / 结构语法 / 状态 / 浏览器原生面 /
  动效预算 / 禁令清单 / 触发点·覆盖路径·违规处置），一行「对后续一律适用」的条款效力说明。
- **REQ-ID `UI-006…UI-012`（`DESIGN_SPEC.md §3.5`）**：令牌与字号尺度 / 主色锁定与 accent 唯一性 /
  一屏一主行动 / 状态齐全（含 disabled 必带原因）/ 浏览器原生面主题化 / 动效预算与 reduced-motion / 禁令清单。
- 反向断言进测试：① 版本三处一致 + `index.html` 全部 `?v=` 与 app version 一致 + `sw.js` CACHE/V 含该版本；
  ② 首页无 `db=` / `contract=` 字样；③ CSS 无旧 accent `#9a6b3f`；④ CSS 无 `overflow-x:auto|scroll`。

### 说明
- **不引任何依赖/框架**（UI-004）：纯 CSS + 原生 JS，与既有实现一致。
- **后端 API 契约未动**：字段不删不改名；本次无新增展示字段，故无新增接口测试。
- 前端三件套 bump `0.5.0`（`sw.js` `CACHE` + `V`、`index.html` 全部 `?v=`）；
  `backend/app.py` 与 `backend/config.py` 同步 → `0.5.0`。

## [0.4.1] - 2026-09-27 · 解锁进度按书显示（学科级改汇总）

### 变更
- **学科级改汇总**：`/api/subjects`（及 `/api/progress`）**移除** `unlocked_upto` 单值，
  改为 `books_total` / `chapters_total` / `chapters_unlocked` / `cards_total` + `unlearned`/`due`/`mastered`/`learned`。
  例：`2 本书 · 20 章 · 已学 x / 共 237 张`。
- **书级进度逐书取值**：书列表显示**该书自身**的 `已解锁到第 N 章 / 共 M 章`（`/api/books` 的
  `unlocked_upto` / `chapters_total`），互不污染。
- 前端 `js/app.js`：新增 `subjectSummary()`；首页学科卡片与学科列表改用汇总。

### 新增
- **REQ-ID `DATA-005`（🔒 口径）**：跨书聚合字段不得冒充单值 —— 一科多书时各书进度独立，
  「解锁到第几章」是书的属性，只能逐书取值。
- **REQ-ID `UI-005`（🔒 口径）**：聚合渲染口径（触发点 / 覆盖路径〔无旁路〕/ 违规处置）。
- `tests/test_progress.py`：学科级无 `unlocked_upto` + 两书进度不同（逐书取值）+ 汇总字段。
- `tests/test_unlock.py` 追加：两本书各自解锁首章（`maybe_unlock` 行为零变化）+ 连锁仍按章序、仍受阈值约束。

### 原因
- 真实数据（psychology 下 2 本书：合成示例书3 14 章 / 合成示例书9 6 章）暴露：学科级单一
  「解锁到第 N 章」在仅首章解锁时恰好为 1，一旦各书进度分开就必然说谎。owner 2026-09-27 拍板按书显示。

### 说明
- **未改**解锁算法 / 阈值 / ingest 契约 / 复习调度；无新依赖、不换皮、不引框架。
- 前端三件套 bump `0.4.1`（`sw.js` `CACHE` + `V`、`index.html` 全部 `?v=` 含页脚版本号）；
  `backend/app.py` 与 `backend/config.py` 同步 → `0.4.1`。

## [0.4.0] - 2026-09-26 · 段⑤ 出题自测 + 轻量连胜 + 今日不再空白

### 新增
- **今日队列含新卡（段⑤A）**：`/api/today` 改为「到期优先 + 未学新卡补齐」，响应新增 `new` 分组；
  字段只增不改名（`due`/`count`/`batch_max` 保留，`count` = `due` + `new`）。
  新卡按 `章 order_no → 概念 id → 卡片 id` 排序；合计 ≤ `REVIEW_BATCH_MAX`，新卡 ≤ `NEW_CARDS_BATCH_MAX`；
  **两组都限定在已解锁章内**。修「新卡从不进队列导致首页空白」。
- `backend/services/queue.py`：`today_queue()` 单一口径（today 与 quiz 共用，禁各写一套 WHERE）。
- **出题·自测（段⑤B）**：`POST /api/quiz/session`（题干列表，**绝不含答案**）、
  `POST /api/quiz/answer`（`pass`→`good` / `fail`→`again`，**复用 `review_sched.apply_result`**）、
  `GET /api/quiz/session/<sid>`（`total/answered/passed/current_card_id`）、
  `GET /api/quiz/session/<sid>/answer/<card_id>`（答案**只在「看答案」时**返回）。
  会话存内存（重启失效可接受，会话内稳定）；**幂等**：同会话重复作答 → 删旧 `card_reviews` 行再写新行。
  不引入 LLM / RAG / 新依赖；**禁止自动判分**（不做关键词打分、不猜）。
- **轻量连胜（段⑤C）**：`GET /api/streak` → `{"days","today_done","last_at"}`；按 Asia/Hong_Kong 本地日切分
  （`config.STREAK_TZ_OFFSET_HOURS` 单点）；今天未复习 → 不计入但**不判断连**。
  仅此端点：**无推送 / 无弹窗 / 无催促文案与接口**（OPS-004）。
- **前端（段⑤D）**：`js/quiz.js`（逐题：题干 → 看答案 → 记住了/没记住 → 下一题 → 通过率 + 连续天数）；
  `js/app.js` 新增「今日」页（到期复习 / 新卡 两组纵向列表，禁横滑，不再空白）；页头常显「连续 N 天」
  （0 天置灰，不隐藏）；「复习」页队列改为 到期 + 新卡。

### 变更
- `backend/services/review_sched.py`：`apply_result` 返回值新增 `review_id`（供幂等替换），既有字段不变。
- `backend/config.py`：新增 `QUIZ_DEFAULT_SIZE/QUIZ_MAX_SIZE/STREAK_TZ_OFFSET_HOURS` 单点配置。
- 前端三件套 bump `0.4.0`（`sw.js` CACHE + V、`index.html` 全部 `?v=`、SHELL 加 `js/quiz.js`）。

### 说明
- **无配额 / 无强制轮转 / 无保底张数**（SCHED-003）；未实现任何 §1.2 非目标。
- 两条反向断言入库：① 未解锁章的卡不入今日队列与测验；② 同会话重复作答 `card_reviews` 不重复。

## [0.3.2] - 2026-09-26 · 契约放宽：`pages` 改为可选（EPUB 无真实页码）

### 变更
- 校验器 `REQUIRED` 去掉 `pages`（契约 §5 必填字段 9 → 8）；**给了就必须合法**（数组或区间字符串），
  非法类型（如 `pages=12`）仍拒收 —— 可选不等于不校验。
- 卡片 `source` 拼法：有页码 →「书/章/页」；无页码 → 退化为「书/章」，不再产生 `书/章/` 这种空尾巴。
- 契约文件格式版本 `contract_version` 仍为 **1**（向后兼容：旧文件带页码照收）。

### 原因
- 首次真实 ingest（知识库导出 **188 行 / 14 章**）dry-run 阶段 **100% 卡在「缺必填字段 pages」**：
  知识库 raw 层只到章粒度（`chapter: N` + sha256），且源是**本地 EPUB** —— 页码在链路上不可得。
- owner 2026-09-26 决策：`pages` 改可选、`source` 退到「书+章」，当天把卡片进库。

### 测试
- 新增 `tests/test_ingest.py::test_pages_optional_source_degrades`（缺 pages / 空数组都收 + source 退化 + 非法类型拒收）。
- 前端三件套 bump → `0.3.2`：`sw.js` 的 `CACHE` + `V`、`index.html` 全部 `?v=`、页头版本号；
  `backend/app.py` `version` 与 `backend/config.py` `VERSION` 同步 → `0.3.2`。

## [0.3.1] - 2026-09-26 · 品牌标识（浅蓝白图书 logo）

### 新增
- `backend/frontend/img/logo.svg`：浅蓝白图书 logo（矢量，源文件）；派生产物
  `icon-512.png` / `icon-192.png` / `apple-touch-icon.png`(180) / `favicon-32.png`
  （`qlmanage -s 512` 渲染 SVG → `sips` 缩放，尺寸已逐一核验）。
- `index.html`：页头 `.brand-logo`（28px 圆角）+ favicon(32/ svg) + `apple-touch-icon` +
  `theme-color #DCEEFF`；`manifest.webmanifest`：补 `icons`(192/512) 与浅蓝白
  `background_color #F4FAFF` / `theme_color #DCEEFF`（原先 `icons: []`，PWA 装到主屏无图标）。

### 变更
- 前端三件套 bump → `0.3.1`：`sw.js` 的 `CACHE` + `V`，`index.html` 全部 `?v=`，
  预缓存清单加入 `/img/logo.svg`、`/img/icon-192.png`、`/img/apple-touch-icon.png`。
- `backend/app.py` `version` 与 `backend/config.py` `VERSION` 同步 → `0.3.1`。

## [0.3.0] - 2026-09-26 · 段④ 复习调度 / 掌握度解锁 / 钻取式 UI

### 新增
- `backend/services/review_sched.py`（REVIEW-001）：三档结果（`again`/`hard`/`good`）推进
  `learn_count` / `status` / `next_review_at`，**唯一一套间隔表**（config 单点），写 `card_reviews` 历史。
- API（`api/{subjects,books,chapters,concepts,cards,review,progress}.py`，全部 `/api/*`）：
  - `GET /api/today`（REVIEW-002）：全学科到期混合、`next_review_at` 升序，上限 `REVIEW_BATCH_MAX`；
  - `POST /api/review/<card_id>`：三档结果 → 推进调度 + 顺带评估解锁；
  - `GET /api/progress`（DATA-004）：每科「未学 / 到期 / 已掌握 / 已解锁到第几章」+ 距上次触碰天数；
  - 钻取读取：`/api/subjects` `/api/books` `/api/chapters` `/api/concepts` `/api/cards`。
- `backend/services/unlock.py` 补齐阈值解锁与连锁评估（SCHED-001/002/005）：未解锁章返回**原因**（UI-003）。
- 前端：`js/app.js`（hash 钻取：科→书→章→概念→卡，禁横滑，锁定项置灰写原因）、
  `js/review.js`（翻卡 + 三档结果）；`index.html` 首页三块接真数据；`css/app.css` 暖纸语法扩展。
- 测试：`tests/test_unlock.py`（含 **3 条反向断言**：已学<5 / 掌握度<80% / 有到期 → 不解锁；单向性）、
  `tests/test_review_sched.py`、`tests/test_api.py`、`tests/test_frontend.py`（三件套一致性 + 禁横滑）。

### 变更
- `backend/app.py`：注册 8 个蓝图。
- 前端三件套 bump 到 `0.3.0`（`sw.js` CACHE + V、`index.html` 全部 `?v=`、SHELL 加 `app.js`/`review.js`）。

### 说明
- 未实现任何 §1.2 非目标；**无每日配额 / 强制轮转 / 保底张数**（SCHED-003）。
- 实测 `make lint test smoke` 全绿，覆盖率 **90.66%**；`/health` 复验 `version=0.3.0`。

## [0.2.0] - 2026-09-26 · 段③ 上游 ingest（app 侧）

### 新增
- `backend/scripts/ingest_kb.py`（CARD-001~004）：读 `exports/<学科>/<书>.jsonl`（契约 §5）→
  逐行校验 → 建/取 subject·book·chapter·concept·card → 去重 → 三段账
  「新增 N / 合并 M / 跳过 K / 待人工 M′」→ 写 `reports/ingest-<日期>.md` → 记 `ingest_runs`。
  支持 `--file` / `--subject` / `--book` / `--dry-run`。
- `backend/ai/cardgate.py`（适配入库）：确定性预筛 R1–R5 + 近似合并（同概念并集）/ 跨概念丢弃；
  **移除对 `ai.agents`（LLM）/ `ai.cardtext` 的依赖，零第三方依赖**，判定可复现。
- `backend/ai/cardtext.py`：考点 → 卡面文本（`front=question`，`back=answer_points` 并集）。
- `backend/services/unlock.py` + `clock.py`：掌握度解锁（SCHED-001/002/005），阈值只从 config 读；
  新书入库即解锁第 1 章；解锁单向。本段先落「首章解锁」，阈值解锁的反向断言在段④同目录补齐。
- 测试：`tests/test_ingest.py`（幂等、契约违规拒绝且库不变、contract=2 整文件拒绝、
  pages 区间串、首章解锁、dry-run、审计、CLI）、`tests/test_dedup.py`；
  夹具 `tests/fixtures/cards-contract-{1,2}.jsonl`。

### 变更
- `cards` 表补 `learn_count` / `next_review_at` 两列（§4 草案允许「以迁移脚本为准」）；
  `data/models.py::migrate()` 幂等加列，兼容既有生产库。

### 说明
- 纯后端改动，**不动前端三件套**（CLAUDE.md §5）。
- 实测 `make lint test` 全绿，覆盖率 **86.76%**；幂等自证：同夹具连跑两次 → 第二次「新增 0 / 跳过 3」。

## [0.1.0] - 2026-09-26 · 立项（spec 定稿）

### 新增
- 项目立项：`DESIGN_SPEC.md` v0.1.0 定稿，冻结 **§5 上游契约**（`exports/<学科>/<书>.jsonl`，
  `contract: 1`）——契约冻结后才允许开工 ingest。
- 交付纪律：`CLAUDE.md`（AI 行为准则，含版本号诚实规则、多 Agent 防撞车、验证清单）。

### 决策留痕（owner 2026-09-26 拍板）
- 形态：**新建独立 repo**，照 COPY_LIST 抄骨架；不与「AI 学习小组 app」共享 git 祖谱。
- 上游契约产出方：**brain** 跑 `scripts/export_cards.py` 产出（导出是机械可复现的一步）。
- 学科粒度：**一科多书，书只属一科**。
- **不设每日配额**：当天想学哪科就哪科（反向条款写入 `DESIGN_SPEC §3.4 SCHED-003`：禁止实现配额/强制轮转/保底张数）。
- 新鲜度机制只取 **掌握度解锁**（不做「一周一主打 / 开箱任务 / 每周复习日」）。

### 说明（立项阶段）
- 本项目以 `0.1.0` 起步：spec 定稿与骨架落地**同属一个版本**，`backend/app.py version = "0.1.0"`
  与本条目一致（版本号诚实规则见 `CLAUDE.md §5`）。

**段② 骨架落地（同日，服务已上线）**

### 新增
- `backend/app.py`（应用工厂 + waitress + 静态托管 PWA，`version = "0.1.0"`）、`backend/config.py`
  （含 SCHED-005 掌握度阈值单点配置）、`backend/api/health.py`、`backend/data/models.py`（DESIGN_SPEC §4 九张表）。
- 门禁：`Makefile`（lint / test / smoke / boot / deploy / backup）、`pytest.ini`、`ruff.toml`、
  `tests/test_health.py`；实测 `make lint test smoke` 全绿，覆盖率 **82.78%**。
- 前端壳：`frontend/{index.html,css/app.css,js/api.js,sw.js,manifest.webmanifest}`（暖纸 editorial；
  骨架期三块卡片按 UI-003 常显 + 置灰 + 写明原因）。
- 部署面：`deploy/{org.example.review,org.example.review,run.sh,
  review-run-port.sh,install_launchd.sh}`、`scripts/backup_icloud.sh`（LaunchAgent，无需 root）。
- 上线：Cloudflare 隧道加 ingress `example.invalid → localhost:5004` + CNAME；
  本机与公网 `/health` 均 `0.1.0`。

### 移除（**不是删除**，已移入回收站可还原）
- 抄骨架时一并带来的 8 个**尚未接入**的通用件（`ai/cardgate.py`、`ai/review_sched.py`、`ai/usage_log.py`、
  `services/push.py`、`services/notify.py`、`middleware/rate_limit.py`、`middleware/input_validation.py`、
  `auth/jwt_utils.py`）移入 `~/.Trash/review-scaffold-20260926-203451/`。
  原因：`ai/cardgate.py` 依赖本项目不存在的 `ai.agents` / `ai.cardtext`（在源项目可跑、在此处是坏死代码），
  且无用代码会把覆盖率门禁稀释到 25%（假绿）。各件将在用到它的段（③/④）**适配后再入库**，并自带测试。


## [0.15.11] - 2026-10-12
- 上传逐块隔离与默认两次重试（环境变量 `UPLOAD_BLOCK_RETRIES` 上限 3）；块失败分类记录、任务提示可见，整书仅零成功失败。
- 前端仅展示后端提供的块失败摘要；版本与资产缓存同步。
- 规范及断言证据见 `reports/S1-round12.md`。
