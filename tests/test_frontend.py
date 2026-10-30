"""前端三件套一致性 + 视觉世界规格反向断言（OPS-002 / UI-006…UI-012 / CLAUDE.md §5）。

这些断言是**反向**的：不只检查「该有的在」，更检查「不该有的不在」——
旧 accent、横向滚动容器、首页技术文案、版本漂移，出现即失败。
"""

import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

FRONTEND = BACKEND / "frontend"
ROOT = BACKEND.parent


def _frontend(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


def _css() -> str:
    return _frontend("css/app.css")


def _app_version() -> str:
    return re.search(r'^version = "([^"]+)"', (BACKEND / "app.py").read_text(encoding="utf-8"), re.M).group(1)


def test_three_piece_versions_match():
    sw = _frontend("sw.js")
    idx = _frontend("index.html")
    v = re.search(r"const V = '([^']+)'", sw).group(1)
    cache = re.search(r"const CACHE = '([^']+)'", sw).group(1)
    assert cache.endswith(v)
    versions = set(re.findall(r"\?v=([0-9.]+)", idx))
    assert versions == {v}, versions
    # SW 预缓存列表也必须带同一版本串
    shell_versions = set(re.findall(r"'/(?:css|js)/[^']+?\?v=' \+ V", sw))
    assert shell_versions  # 资产用 V 拼接，天然同版本


def _changelog_versions() -> set[str]:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    return set(re.findall(r"^## \[([0-9.]+)\]", text, re.M))


def test_frontend_asset_version_is_real_and_consistent():
    """反向断言①：前端资产版本必须**自洽**且**真实存在**，且 == app version。

    口径修正（0.9.1，推翻 0.5.1）：0.5.1 曾因「纯后端不 bump 前端」把「?v= == app version」放宽为
    「三件套内部一致 + 版本号真实」，允许前端落后于后端 —— 这直接导致 v0.9.0/0.9.1 前端资产
    （quiz.js/app.css）改了却没 bump 三件套，CF 缓存旧壳吞掉修复。
    现改回硬口径：**前端三件套版本必须 == app version**（与 `make smoke` 的「每个 ?v= == /health version」一致）。
    """
    sw = _frontend("sw.js")
    idx = _frontend("index.html")
    v = re.search(r"const V = '([^']+)'", sw).group(1)
    cache = re.search(r"const CACHE = '([^']+)'", sw).group(1)
    assert cache == f"review-v{v}"
    versions = set(re.findall(r"\?v=([0-9.]+)", idx))
    assert versions == {v}, versions  # 三件套自洽
    assert v in _changelog_versions(), v  # 不是拍脑袋写的版本
    # 前端版本必须 == app version（前端落后 = 旧壳吞修复；领先 = 漏 app 侧 bump）
    app = _app_version()
    assert v == app, (v, app)


def test_version_three_places_consistent():
    """版本三处（诚实规则）：backend/app.py == CHANGELOG 段号 == DESIGN_SPEC §12 段号。"""
    v = _app_version()
    assert f'VERSION = "{v}"' in (BACKEND / "config.py").read_text(encoding="utf-8")
    assert f"## [{v}]" in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"### [{v}]" in (ROOT / "DESIGN_SPEC.md").read_text(encoding="utf-8")
    # 封面版本也从这里管住（2026-10-11 实测漂移：正文到 0.15.6、封面还停 0.15.5）
    cover = (ROOT / "DESIGN_SPEC.md").read_text(encoding="utf-8").splitlines()[0]
    assert re.search(r"\bv([0-9]+\.[0-9]+\.[0-9]+)\b", cover).group(1) == v, (
        f"DESIGN_SPEC 封面版本未同步：{cover}"
    )


def test_pagefoot_version_matches_shell():
    """OPS-002 / CLAUDE.md §5：`index.html` 静态页脚版本串必须 == 前端三件套版本（`sw.js` 的 `const V`）== app version。

    反证（v0.8.0 实况）：页脚曾停在 `v0.6.1`，0.7.0 / 0.8.0 两次 bump 均漏改，
    而项目内当时**零断言**（ui-audit / tests 都没有）→ 只有日审脚本兜住，属「版本诚实」铁律的证伪缺口。
    口径：页脚属**前端版本面**，随 `sw.js` 的 `V` 走；运行时 `/health` 回填**不构成豁免**（已安装客户端会长期吃旧壳）。
    0.9.1 起前端版本面必须 == app version（`make smoke` 每个 ?v= == /health version），页脚同样不得漂移。
    """
    sw = _frontend("sw.js")
    idx = _frontend("index.html")
    v = re.search(r"const V = '([^']+)'", sw).group(1)
    m = re.search(r'<span class="ver" id="ver">v([0-9.]+)</span>', idx)
    assert m, "页脚 #ver 静态版本串不得缺失"
    assert m.group(1) == v, (m.group(1), v)
    assert v in _changelog_versions(), v  # 不是拍脑袋写的版本
    app = _app_version()
    assert v == app, (v, app)


def test_accent_locked_to_green():
    """反向断言③：accent 锁定草绿 —— 旧暗棕 #9a6b3f 不得再出现（大小写皆禁）。"""
    css = _css()
    low = css.lower()
    assert "#9a6b3f" not in low
    assert "#1e7c50" in low and "#14613c" in low  # 草绿主色 + 深色变体
    assert "--orange" in low  # 陶橙只作警示槽存在
    assert "#dceeff" not in low  # 旧浅蓝主题色已弃


def test_tokens_present():
    """UI-006：四语义槽与字号尺度必须写进 :root。"""
    css = _css()
    for token in (
        "--paper",
        "--paper-2",
        "--card",
        "--ink",
        "--ink-2",
        "--muted",
        "--hair",
        "--green",
        "--green-deep",
        "--green-tint",
        "--orange",
        "--disp",
        "--body",
    ):
        assert token in css, token
    assert "17.5px" in css and "tabular-nums" in css
    assert "prefers-reduced-motion" in css
    assert "::selection" in css and ":focus-visible" in css


def test_no_health_jargon_on_home():
    """反向断言②：首页不得出现 db= / contract= 字样（健康检查文案已删，/health 只读版本号）。"""
    for name in ("index.html", "js/app.js"):
        text = _frontend(name)
        assert "db=" not in text, name
        assert "contract=" not in text, name


def test_no_horizontal_carousel():
    """UI-001：禁横向滑动 —— 不得出现 overflow-x:auto/scroll 或 carousel 字样（反向断言④）。"""
    css = _css()
    compact = css.replace(" ", "").lower()
    assert "overflow-x:auto" not in compact
    assert "overflow-x:scroll" not in compact
    assert "carousel" not in css.lower()


def test_new_assets_registered_in_shell():
    """新增前端资产必须同时出现在 index.html 与 sw.js 预缓存（否则线上卡旧壳）。"""
    sw = _frontend("sw.js")
    idx = _frontend("index.html")
    for asset in (
        "js/app.js",
        "js/review.js",
        "js/quiz.js",
        "js/flashcard.js",
        "js/wrong.js",
        "js/plan.js",
        "js/weak.js",
        "js/report.js",
    ):
        assert asset in idx and asset in sw, asset


def test_adjacent_interactive_block_gap():
    """UI-013：相邻可交互块必须有真实间隙 —— 行式入口独立块化（卡底 + hairline 边 + 圆角）+ gap:12px。"""
    css = _css()
    compact = css.replace(" ", "")
    # 列表容器靠 gap 撑开（不再单靠 hairline 分隔）
    assert "gap:12px" in compact
    # 行 / 章 summary / 进度行都做成独立块（暖纸卡底 + hairline 边 + 圆角）
    for sel in (".row{", ".chap>summary{", ".progline{"):
        assert sel in compact, sel
    assert "border:1pxsolidvar(--hair)" in compact
    assert "border-radius:var(--r-btn)" in compact
    assert "background:var(--card)" in compact


def test_flashcard_gesture_hooks():
    """UI-014：前端源码必须含手势钩子（touch/mouse + 飞出/入场/跟手类名 + 阈值 70 + 提示文案）。"""
    js = "\n".join(_frontend(f"js/{n}") for n in ("flashcard.js", "review.js"))
    for hook in ("touchstart", "touchmove", "touchend", "mousedown"):
        assert hook in js, hook
    for cls in ("out-r", "out-l", "kc-in", "dragging"):
        assert cls in js, cls
    assert "THRESHOLD = 70" in js  # 阈值 70px 不许漂移
    css = _css()
    for cls in (".kc-card.dragging", ".kc-card.out-r", ".kc-card.out-l", ".kc-card.kc-in"):
        assert cls in css, cls
    assert "拖动卡片" in js  # 卡片下方提示行
    assert "backface-visibility" in css  # 3D 翻转
    # reduced-motion 下动画全关（全局过渡/动画预算）
    assert "prefers-reduced-motion" in css


def test_quiz_no_longer_swipes():
    """UI-014 修订（v0.5.4）：测验页改为客观题 → **不再**左右滑切卡（手势只属复习卡）。"""
    quiz = _frontend("js/quiz.js")
    for banned in ("Flashcard", "拖动卡片", "kc-scene", "kc-card"):
        assert banned not in quiz, banned
    assert "touchstart" not in quiz and "mousedown" not in quiz


def test_flashcard_direction_not_reversed():
    """UI-014：右滑 = 记得（dx>0），左滑 = 忘了 —— 方向不许反（复习卡）。"""
    js = _frontend("js/flashcard.js")
    # 超阈值时以 dx>0（右滑）为「记住」判据
    assert "decide(p.dx > 0)" in js
    review = _frontend("js/review.js")
    assert "右滑 = 记得 · 左滑 = 忘了" in review
    assert "'good' : 'again'" in review  # 复习卡：记得 → good / 忘了 → again
    # UI-014（v0.5.7 补漏）：**按钮顺序必须与手势方向一致** —— 左「忘了」/ 右「记得」
    block = review.split('class="actions', 1)[1].split("</div>", 1)[0]
    assert block.index('id="k-again"') < block.index('id="k-good"'), (
        "闪卡自评按钮顺序反了：应左「忘了」(k-again) 右「记得」(k-good)"
    )
    assert 'class="btn" id="k-again"' in block  # 忘了：hairline，不做主行动
    assert 'class="btn solid" id="k-good"' in block  # 记得：accent 实心，主行动在右
    # 视觉顺序不得被 CSS 反转（否则 DOM 顺序失去意义）
    act = re.search(r"\.actions\s*\{[^}]*\}", _css())
    assert act, "app.css 缺 .actions 规则"
    assert not re.search(r"row-reverse|direction:\s*rtl", act.group(0)), ".actions 反转了视觉顺序"


def test_quiz_micro_label_uses_book_not_stem():
    """微标签：quiz.js 出处用 书 · 章（会话响应带 book/chapter），不得把「题干」当出处。"""
    quiz = _frontend("js/quiz.js")
    assert "题干 · " not in quiz
    assert "esc(it.source_label)" in quiz
    assert "esc(it.book)" not in quiz and "esc(it.chapter)" not in quiz


def test_header_streak_always_present():
    """段⑤C/D：页头连胜常显（0 天也显示，不按条件隐藏）。"""
    idx = _frontend("index.html")
    assert 'id="streak"' in idx and 'class="clover"' in idx and "连胜" in idx
    assert "连续" not in idx


def test_no_nagging_copy():
    """段⑤C / TASK-001：禁止催促类文案（「不催」这类反向声明不算催促）。"""
    bad_phrases = (
        "快来",
        "打卡",
        "提醒我",
        "该复习了",
        "别断更",
        "你已落后",
        "今天必须",
        "坚持打卡",
        "别落下",
        "落后了",
    )
    for name in ("index.html", "js/app.js", "js/quiz.js", "js/review.js", "js/wrong.js"):
        text = _frontend(name)
        for bad in bad_phrases:
            assert bad not in text, f"{name} 含催促类文案 {bad}"


def test_home_daily_quote_and_task_hooks():
    """HOME-001 / TASK-001：首页格言走 /api/quote（回落「今日复习」），任务清单有「今日复习 / 出题」两子项。"""
    appjs = _frontend("js/app.js")
    assert "/api/quote" in appjs and "今日复习" in appjs  # 格言数据源 + 空回落
    assert "/api/task" in appjs
    assert "今日任务" in appjs and "今日复习" in appjs and "出题" in appjs
    assert "开始复习" in appjs
    # 格言不编造作者：前端不出现「—— 某某」式署名拼接
    assert "author" not in appjs and "作者" not in appjs


def test_home_quiz_entry_copy_updated():
    """缺陷修复：首页出题自测行不得再写「看答案后自评，不判分」（已是客观题 + 自动判分）。"""
    appjs = _frontend("js/app.js")
    assert "不判分" not in appjs
    assert "看答案后自评" not in appjs
    assert "自动判分" in appjs and "选择题 / 是非题" in appjs


def test_mastery_bar_and_percent_four_levels():
    """MAST-002 / MAST-004：四级均有进度条 + 百分比 + 分子分母；卡级四态标签来自后端（前端零映射）。"""
    appjs = _frontend("js/app.js")
    assert 'class="bar"' in appjs and "mLab(" in appjs  # 进度条 + 百分比文案单点
    assert "掌握度 —" in appjs
    assert "state_label" in appjs
    assert "掌握度 ${m.m}%" in appjs
    assert "覆盖率 ${o.coverage}%" in appjs and "已学 ${o.learned} / 共 ${o.cards_total}" in appjs
    assert (
        "num ||" not in appjs
        and "den ||" not in appjs
        and "mastery.pct" not in appjs
        and "started" not in appjs
    )
    css = _css()
    assert ".cm.on" in css and ".meter" in css


def test_wrong_book_page_hooks():
    """WRONG-001：错题本页（#/wrong）—— 路由可达、空态有话说、可展开对照、可一键重刷。"""
    appjs = _frontend("js/app.js")
    assert "name === 'wrong'" in appjs and "WrongView" in appjs
    assert 'href="#/wrong"' in appjs  # 首页入口
    wrong = _frontend("js/wrong.js")
    assert "/api/wrong" in wrong and "/api/wrong/retry" in wrong
    assert "还没有错题" in wrong  # 空态有话说（不得空白）
    assert "正确答案" in wrong and "我的答案" in wrong  # 可展开对照
    assert "重刷" in wrong  # 一键重刷
    assert "去出题自测" in wrong  # 指路
    # 重刷复用测验作答 UI（不另写一套判分/作答逻辑）
    assert "QuizView.run" in wrong


def test_quiz_page_polish_hooks():
    """第 4 节：测验页进度（第 x / N 题）+ 选项三态（选中 / 判对 / 判错）+ 结果页得分。"""
    quiz = _frontend("js/quiz.js")
    assert "第 " in quiz and "题" in quiz  # 进度文案
    assert "opt.sel" not in quiz or "sel" in quiz  # 选中态类
    assert "sel" in quiz
    assert "q-next" in quiz
    assert "q-submit" not in quiz
    assert "提交" not in quiz
    assert "得分" in quiz and "答对" in quiz
    css = _css()
    assert ".opt.sel" in css and ".opt.correct" in css and ".opt.wrong" in css
    assert "tabular-nums" in css


# —— M2-B3（PLAN-001 / WEAK-001 / RPT-001）三页反向断言 ——
def test_plan_page_hooks():
    """PLAN-001：路由可达、间隔文案**来自后端字段**（前端零计算、不写死）、空态有话说。"""
    appjs = _frontend("js/app.js")
    assert "name === 'plan'" in appjs and "PlanView" in appjs
    assert 'href="#/plan"' in appjs  # 首页入口
    plan = _frontend("js/plan.js")
    assert "/api/plan" in plan
    assert "when_label" in plan  # 间隔读数后端字段
    # 前端不得自行拼/写死间隔：不得出现 '天后' / '小时后' 字符串字面量（注释里的示例不算）
    assert "'天后'" not in plan and '"天后"' not in plan
    assert "'小时后'" not in plan and '"小时后"' not in plan
    assert "还没有" in plan  # 空态有话说
    assert "#/review" in plan  # 已到期 → 直接作答（复用复习卡路径）


def test_weak_page_hooks():
    """WEAK-001：路由可达、**按章聚合**、空态有话说、点章可展开。"""
    appjs = _frontend("js/app.js")
    assert "name === 'weak'" in appjs and "WeakView" in appjs
    assert 'href="#/weak"' in appjs
    weak = _frontend("js/weak.js")
    assert "/api/weak" in weak
    assert "错" in weak and "张卡" in weak  # 错次 · 涉及卡数
    assert "details" in weak and "chap" in weak  # 点章可展开
    assert "还没有" in weak  # 空态有话说


def test_report_page_and_no_client_side_accuracy():
    """RPT-001：正确率**必须来自后端字段**；0 作答显示 —；前端 JS 不得自算正确率。"""
    appjs = _frontend("js/app.js")
    assert "name === 'report'" in appjs and "ReportView" in appjs
    assert 'href="#/report"' in appjs
    assert "/api/report" in appjs  # 首页一行摘要复用同一接口字段
    rep = _frontend("js/report.js")
    assert "/api/report" in rep and "accuracy" in rep
    assert "'—'" in rep  # 0 作答 → —（不得显示 0%）
    assert "还没有" in rep  # 空态有话说
    # 反断言：前端任何 JS 不得出现 Math.round(...correct...) 式自算正确率
    all_js = "\n".join(
        _frontend(f"js/{n}")
        for n in ("app.js", "review.js", "quiz.js", "wrong.js", "plan.js", "weak.js", "report.js")
    )
    assert not re.search(r"Math\.round\([^)]*correct", all_js), "前端不得自算正确率"


def test_home_quick_entries_grid():
    """首页「快捷入口」为网格（两列 gap 12px，不横滑），且含三个新入口。"""
    appjs = _frontend("js/app.js")
    assert "rowlist grid" in appjs
    for entry in ("#/plan", "#/weak", "#/report"):
        assert f'href="{entry}"' in appjs, entry
    css = _css()
    compact = css.replace(" ", "")
    assert ".rowlist.grid{display:grid" in compact
    assert "grid-template-columns:repeat(2,1fr)" in compact


def test_backend_files_under_300_lines():
    """CLAUDE.md §3 / DESIGN_SPEC §8：**后端 Python** 单文件 < 300 行（前端 JS 不在此限）。

    扫 `backend/**/*.py`，排除 `backend/scripts/`（一次性/运维脚本）；超限即 fail（超则拆模块）。
    """
    offenders = []
    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND).as_posix()
        if rel.startswith("scripts/"):
            continue
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > 300:
            offenders.append(f"{rel} = {lines} 行")
    assert not offenders, "后端 Python 单文件必须 < 300 行（超则拆模块）：\n  " + "\n  ".join(offenders)


# —— v0.6.0 前端信息架构（UI-015/016、TASK-002、GOAL-001、MAST-003）反向断言 ——
def _cut(src: str, start: str, end: str) -> str:
    """粗切一段源码（从 start 到下一个 end 之间），供源码级反向断言。"""
    assert start in src, f"未找到锚点：{start}"
    return src.split(start, 1)[1].split(end, 1)[0]


def test_subject_page_lists_books_only():
    """UI-015：`#/subject/<id>` 只渲染书列表（有 h1、无章行）；点书才进 `#/book/<id>`。"""
    appjs = _frontend("js/app.js")
    # 反断言：删掉 v0.6.0 前的扁平写法与「另一本书」小节
    assert "另一本书" not in appjs
    assert "books[0]" not in appjs
    assert "siblings" not in appjs
    subj = _cut(appjs, "async function subject(id)", "\n  // 书级深链")
    assert "<h1" in subj and 'class="display"' in subj  # 学科页必须有 h1
    assert "books.map(bookRow)" in subj  # 只渲染「书的按钮」列表
    assert "details.chap" not in subj  # 学科页不得出现章行
    row = _cut(appjs, "function bookRow(b)", "\n\n  // 已解锁章展开")
    assert 'href="#/book/' in row  # 每本书可点进书页
    assert (
        'class="bar"' in row and "mCount(" in row
    )  # 书级进度条 + 百分比（mCount = 已学/共 + 状态，环星已表达双数）


def test_knowledge_cards_naming():
    """UI-016：全前端不得出现「挑新卡」；`#/subjects` 的 h1 == 「知识卡片」。"""
    exts = {".js", ".css", ".html", ".md", ".webmanifest"}
    for p in sorted(FRONTEND.rglob("*")):
        if p.is_file() and p.suffix in exts:
            assert "挑新卡" not in p.read_text(encoding="utf-8"), f"{p} 仍残留「挑新卡」"
    appjs = _frontend("js/app.js")
    assert "知识卡片" in appjs
    body = _cut(appjs, "async function subjectList()", "\n  // 章行")
    assert '<h1 class="display">知识卡片</h1>' in body


def test_task_row_actions():
    """TASK-002：未完成 → 「去完成」；完成 → 绿勾 + 「再来一组」；阈值一律后端下发。"""
    appjs = _frontend("js/app.js")
    row = _cut(appjs, "function taskRow(", "\n  // —— 首页")
    assert "去完成" in row and "再来一组" in row
    assert "tick" in row and "complete" in row  # 完成态绿勾（.tick.on）
    assert "t.target" in row and "reason" in row  # 目标/原因来自后端
    assert re.search(r"\b30\b", row) is None  # 不硬编码字面阈值
    assert "disabled" in row  # 退化态常显 + 置灰（UI-003）
    home = _cut(appjs, "async function home()", "\n  // —— 今日清单")
    assert "#/review?extra=1" in home  # 复习完成态 → 再来一组（额外组）


def test_no_hardcoded_goal():
    """GOAL-001：首页主行动数字来自后端 `review.target`，前端不得写死 30（反向断言）。"""
    appjs = _frontend("js/app.js")
    assert "REVIEW_TASK_TARGET" not in appjs
    assert re.search(r"开始复习\s*30", appjs) is None
    home = _cut(appjs, "async function home()", "\n  // —— 今日清单")
    assert "task.review.target" in home
    assert re.search(r"开始复习 \$\{goal\}", home)  # 数字来自变量，非字面量


MASTERY_NOTE = "掌握度 = 已学卡掌握度平均（卡级 = 50% 状态分 + 50% 作答正确率）；覆盖率 = 已学卡 ÷ 全部卡"


def test_card_status_labels_from_backend():
    """MAST-003：前端只读后端 `status_label`；不得出现 status→中文 映射表（四态零映射）。"""
    for n in ("app.js", "review.js", "wrong.js", "plan.js"):
        assert "status_label" in _frontend(f"js/{n}"), n
    alljs = "\n".join(
        _frontend(f"js/{n}")
        for n in (
            "app.js",
            "review.js",
            "quiz.js",
            "wrong.js",
            "plan.js",
            "weak.js",
            "report.js",
            "flashcard.js",
        )
    )
    for pat in (
        r"['\"]new['\"]\s*:\s*['\"]未学习",
        r"['\"]learning['\"]\s*:\s*['\"]学习中",
        r"['\"]review['\"]\s*:\s*['\"]复习中",
        r"['\"]mastered['\"]\s*:\s*['\"]已掌握",
        r"status\s*===?\s*['\"]\w+['\"][^\n;]*['\"](未学习|学习中|复习中|已掌握)['\"]",
    ):
        assert not re.search(pat, alljs), pat
    # 旧两态（已掌握/未掌握）与四态中文一律不得在前端出现 —— 唯一例外是 MAST-004 的掌握度公式文案
    # `已掌握 {num} / 已学 {den}`（数值只读后端）与口径说明句原文；把这两处扣掉后必须零残留。
    rest = re.sub(
        r"已掌握\s*<span[^>]*>\$\{[^}]*\}</span>\s*/\s*已学\s*<span[^>]*>\$\{[^}]*\}</span>", "", alljs
    ).replace(MASTERY_NOTE, "")
    for lab in ("已掌握", "未掌握", "未学习", "学习中"):
        assert lab not in rest, lab


# —— v0.6.0 CSS 工艺与可读性（UI-017 / A11Y-001）——
def _hex_rgb(h: str):
    h = h.strip().lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _lin(c: float) -> float:
    c = c / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _lum(rgb) -> float:
    r, g, b = (_lin(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(fg, bg) -> float:
    a, b = sorted((_lum(fg), _lum(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def test_muted_contrast_aa():
    """A11Y-001：`:root` 的 `--muted` 对暖纸底 `--paper` 的 WCAG 对比度 ≥4.5:1（现算）。"""
    css = _css()
    muted = re.search(r"--muted:\s*(#[0-9A-Fa-f]{6})", css).group(1)
    paper = re.search(r"--paper:\s*(#[0-9A-Fa-f]{6})", css).group(1)
    ratio = _contrast(_hex_rgb(muted), _hex_rgb(paper))
    assert muted.lower() != "#8c8371"  # 旧值（3.5:1）不得回归
    assert ratio >= 4.5, f"--muted {muted} vs --paper {paper} = {ratio:.2f}:1 < 4.5"


def test_motion_craft_floor():
    """UI-017：① 缓动不得过冲（贝塞尔 y 控制点 ≤1）；② 进度条填充禁 `transition: width`。"""
    css = _css()
    beziers = re.findall(
        r"cubic-bezier\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)", css
    )
    assert beziers, "未找到 cubic-bezier（动效预算应有一条作者化曲线）"
    for x1, y1, x2, y2 in beziers:
        assert float(y1) <= 1 and float(y2) <= 1, f"贝塞尔过冲：cubic-bezier({x1},{y1},{x2},{y2})"
    assert "bounce" not in css.lower() and "elastic" not in css.lower()
    # 任何 transition 声明不得含 width（禁 layout thrash）
    for decl in re.findall(r"transition\s*:[^;}]+", css):
        assert "width" not in decl, f"transition 含 width：{decl.strip()}"
    bar = re.search(r"\.bar i\s*\{[^}]*\}", css).group(0)
    assert "scaleX(" in bar and "transform-origin: left" in bar
    assert re.search(r"style=\"width:", _frontend("js/app.js")) is None  # JS 不再写 width


# —— v0.6.1 掌握度口径可见（MAST-004）+ 概念行状态（MAST-005）——
def test_mastery_formula_visible():
    """MAST-004：每一级掌握度都带 `已掌握 {num} / 已学 {den}`（数值只读后端 `mastery.num/den`，前端零计算）；
    学科页与书页常显口径说明句原文；反断言：总卡数不得混进掌握度（旧 `已学 2/237` 不得回归）。

    MAST-004（v0.10.1 修订）：渲染了环星的层级，文字行只留「已学 x / 共 y · 状态」
    （双数只出现一次：环心写覆盖率、星旁写掌握度）；未渲染环星的层级文字行保留双数。
    """
    appjs = _frontend("js/app.js")
    assert "function mText(m)" in appjs and "o.cards_total" in appjs
    assert ".m !== null" in appjs
    # 口径说明句（原文固定，不得改写、不得省略）：学科列表 / 学科页（两分支）/ 书页常显
    assert MASTERY_NOTE in appjs
    assert appjs.count("${masteryNote()}") >= 4, appjs.count("${masteryNote()}")
    # 反断言：总卡数只能另写「共 N 张」，不得与掌握度同括号
    assert "共 <span" in appjs
    assert "已学 x/y" not in appjs, "旧混写不得回归"
    assert re.search(r"已学\s*\d+\s*/\s*\d+", appjs) is None, "旧「已学 x/y」混写"

    # —— MAST-004（v0.10.1 修订）数值去重：环星层级短文案、非环星层级保留双数 ——
    assert "function mCount(m)" in appjs
    assert "已学 ${o.learned} / 共 ${o.cards_total} · ${o.state_label}" in appjs
    # 渲染环星的三个层级（首页学科块 / 学科页书行两分支 / 书页 .meter）用 mCount
    assert "mCount(s.mastery)" in appjs
    assert appjs.count("mCount(m)") >= 2  # bookRow 解锁/未解锁两分支
    assert "mCount(bm)" in appjs
    # 未渲染环星的层级（学科列表 / 章行）仍用 mText（保留双数）
    assert "mText(s.mastery)" in appjs  # 学科列表 .row.prog
    assert "mText(c.mastery)" in appjs  # 章行 .chap summary
    # mCount 模板自身不得包含掌握度/覆盖率（只留已学/共 + 状态）
    mcount = _cut(appjs, "function mCount(m)", "\n  // UI-018")
    assert "掌握度" not in mcount and "覆盖率" not in mcount


def test_concept_row_status_from_backend():
    """MAST-005：概念行状态一律读后端 `status_label`（前端零映射、零计数、零拼接）。"""
    appjs = _frontend("js/app.js")
    assert appjs.count("c.status_label") >= 2  # 章展开 + `#/chapter/<id>` 两个渲染点
    # 反断言①：计数与多态文案由后端拼好 → 前端不碰 `status_counts`、不自行统计
    assert "status_counts" not in appjs
    assert re.search(r"filter\([^)]*status[^)]*\)\.length", appjs) is None
    assert re.search(r"\.status\s*\+\+", appjs) is None
    # 反断言②：四态中文与「无卡」只来自后端（扣掉 MAST-004 公式与口径说明句后必须零残留）
    rest = re.sub(
        r"已掌握\s*<span[^>]*>\$\{[^}]*\}</span>\s*/\s*已学\s*<span[^>]*>\$\{[^}]*\}</span>", "", appjs
    ).replace(MASTERY_NOTE, "")
    for lab in ("未学习", "学习中", "复习中", "已掌握"):
        assert lab not in rest, lab
    # 「无卡」要按**整串字面量**判（正文里「今日无卡可复习」是任务文案，不是状态标签）
    assert not re.search(r"['\"]无卡['\"]", rest), "「无卡」不得前端硬编码（由后端 status_label 下发）"
    # 概念行行内必须同时有状态与张数
    row = _cut(appjs, "async function chapter(id)", "\n  // 卡级状态标签")
    assert "status_label" in row and "张卡" in row


# —— v0.10.0 UI-018 覆盖率环形图 / MAST-008 掌握度五星（源码级反向断言）——
def test_coverage_ring_hooks():
    """UI-018：覆盖率环形图用 inline SVG + `stroke-dasharray`（禁外链库/emoji/图表库）；
    底环 `--hair`、进度环 `--green`；三处渲染点都在（首页学科块 / 学科页书行 / 书页）。"""
    appjs = _frontend("js/app.js")
    assert "stroke-dasharray" in appjs and "coverageRing" in appjs
    assert 'role="img"' in appjs and 'aria-label="覆盖率' in appjs
    # 三处渲染点（与 UI-018 覆盖路径一致）：首页学科块 / 学科页书行（bookRow 两分支）/ 书页
    assert "masteryGauges(s.mastery)" in appjs  # 首页学科块 .progline
    assert "masteryGauges(m)" in appjs  # 学科页书行 bookRow（解锁/未解锁两分支）
    assert "masteryGauges(bm)" in appjs  # 书页 .meter
    # 环心文本含 %（数字只读后端 coverage，前端零自算）
    assert 'class="ring-num"' in appjs and ">${c}%</text>" in appjs
    css = _css()
    assert ".ring-bg" in css and ".ring-fg" in css and ".ring-num" in css
    # 底环 = --hair / 进度环 = --green（禁新颜色）
    assert re.search(r"\.ring-bg\s*\{[^}]*--hair", css)
    assert re.search(r"\.ring-fg\s*\{[^}]*--green", css)
    # 进度用 dasharray，非 width 动画（UI-017 工艺禁动 width）
    assert "width" not in (re.search(r"\.ring-fg\s*\{[^}]*\}", css).group(0))


def test_mastery_stars_hooks():
    """MAST-008：五星用 inline SVG + `<clipPath>` 遮罩表达小数（不用圆点）；空星 `--hair` / 实星 `--green`；
    `stars = round(m/20, 1)` 单点；「★」用 SVG（非字符/emoji）。"""
    appjs = _frontend("js/app.js")
    assert "starsOf" in appjs and "Math.round((m.m / 20) * 10) / 10" in appjs
    assert "clipPath" in appjs and "clip-path" in appjs  # 遮罩裁剪，非圆点近似
    assert "starsFilledWidth" in appjs
    # m 缺失 → 「—」；常显一行「掌握度 86% · 4.3★」（★ = 内联 SVG）
    assert 'class="stars none"' in appjs and "掌握度 —" in appjs
    assert 'class="star-ico"' in appjs
    assert "★" not in appjs  # 字符星禁止（只用 SVG）
    css = _css()
    assert ".stars-bg" in css and ".stars-fg" in css
    assert re.search(r"\.stars-bg path\s*\{[^}]*--hair", css)  # 空星浅色
    assert re.search(r"\.stars-fg path\s*\{[^}]*--green", css)  # 实星 accent 绿


def test_scope_hooks():
    """SCOPE-001~004：首页「图书」入口 + `#/scope` 独立钻取页；勾选框复用 `.tick`
    （禁系统 checkbox 原生样式）；先草稿后确认（确认按钮 .primary + 「至少选择一本书」+
    「尚未确认」）；范围文案只读后端 label。"""
    scopejs = _frontend("js/scope.js")
    # 禁原生 checkbox（勾选视觉只用 .tick 纯 CSS）
    assert 'type="checkbox"' not in scopejs
    assert "<input" not in scopejs
    assert ".tick" in scopejs
    # 草稿 + 确认 + 空草稿拦截 + 未确认标记
    assert "至少选择一本书" in scopejs
    assert "尚未确认" in scopejs
    assert "全选" in scopejs and "清空" in scopejs and "确认" in scopejs
    assert 'id="scope-confirm"' in scopejs
    assert 'id="scope-all"' in scopejs and 'id="scope-clear"' in scopejs
    assert 'class="primary"' in scopejs
    assert 'role="alert"' in scopejs and "scope-error" in scopejs
    assert 'id="scope-error"' in scopejs
    # 范围文案只读后端 label（前端零自算）
    assert "d.label" in scopejs and "d.selected_ids" in scopejs
    # 草稿只改本地、确认才 PUT
    assert "api.put('/api/scope'" in scopejs

    # 首页入口 + 路由注册
    appjs = _frontend("js/app.js")
    assert 'href="#/scope"' in appjs
    assert "name === 'scope'" in appjs
    assert "window.ScopeView.render()" in appjs
    assert "api.get('/api/scope')" in appjs

    # 三件套：index.html 注册 + sw.js 预缓存 scope.js
    idx = _frontend("index.html")
    sw = _frontend("sw.js")
    assert "/js/scope.js?v=" in idx
    assert "/js/scope.js?v=' + V" in sw

    css = _css()
    assert ".scope-book" in css and ".scope-error" in css
    # 选中行 accent 绿（唯一主色，禁新颜色）
    assert re.search(r"\.scope-book\.on\s*\{[^}]*--green", css)


def test_quiz_session_does_not_override_backend_size():
    quiz = _frontend("js/quiz.js")
    assert "const SIZE" not in quiz and "size: 10" not in quiz
    assert "api.post('/api/quiz/session')" in quiz


def test_freeze_chip_and_overlay_are_present():
    page = _frontend("index.html")
    assert 'id="freezeChip"' in page and 'id="freezeCount"' in page and 'id="freezeAnim"' in page


def test_freeze_chip_reads_freezes_off_response_object():
    """FREEZE-001 回归：chip 数字只能来自 /api/streak 的 data.freezes。

    曾经写成 `const d = r.data.days || 0; … const f = d.freezes || {}` —— 从数字上取属性恒为
    undefined → 接口 available=4 而 chip 恒显示 0、还写「冰冻已用完」（2026-10-09 公网实测）。
    """
    app = _frontend("js/app.js")
    assert "const data = r.data" in app, "app.js 须保留响应对象再取字段"
    assert "data.freezes" in app, "freezes 必须从响应对象上取"
    assert "d.freezes" not in app, "不得从 days 数字上取 freezes（恒 undefined → chip 恒为 0）"
    assert "available" in app, "chip 数字须用后端下发的 available（前端零计算）"


def test_freeze_icon_matches_streak_source():
    """UI-020 源码级反断言：冰冻符号与数字必须与连胜那组同尺寸同风格。

    CC 首版：chip `font: inherit`（13px）+ emoji ❄ 文本节点 → 公网实测
    连胜数字 17px / 冰冻数字 13px、四叶草 18×18 / ❄ 字形 13.3px（owner 2026-10-09 追问）。
    屏幕实测值由 `make ui-audit` ⑯c 断言，这里只钉源码，两处一起才防复发。
    """
    html = _frontend("index.html")
    css = _frontend("css/app.css")
    assert 'class="flake"' in html, "冰冻符号必须是内联 SVG（svg.flake，与 svg.clover 同款）"
    assert 'id="freezeCount" class="n tnum"' in html, "冰冻数字须与连胜数字同 class（.n.tnum）"
    assert ">❄ " not in html and "❄ <span" not in html, "冰冻 chip 内不得再用 emoji 字形 ❄"
    assert ".freeze-chip .flake" in css and "width: 18px; height: 18px" in css, "flake 必须与四叶草同为 18×18"
    assert ".freeze-chip .n" in css and "font-size: 17px" in css, "冰冻数字字号必须与 .streak .n 一致（17px）"


def test_upload_notice_text():
    root = Path(__file__).resolve().parents[1] / "backend/frontend"
    html = (root / "index.html").read_text()
    js = (root / "js/upload.js").read_text()
    assert 'id="uploadNotice"' in html
    assert "上传的文本会发送给模型服务商，用于生成知识卡片。" in html
    assert ".hidden" not in js and "display: none" not in js and "不会外传" not in js


def test_upload_drafts_backend_fields():
    root = Path(__file__).resolve().parents[1] / "backend/frontend"
    upload = (root / "js/upload.js").read_text()
    drafts = (root / "js/drafts.js").read_text()
    assert "d.label" in upload and "d.progress" in upload and "d.stage" in upload
    assert "600" not in upload and 'type="checkbox"' not in upload + drafts
    assert 'id="draftConfirm"' in drafts and 'class="primary"' in drafts


def test_cover_version_rejects_prefixes():
    for cover in ("# v0.15.6", "# v0.15.70"):
        assert re.search(r"\bv([0-9]+\.[0-9]+\.[0-9]+)\b", cover).group(1) != "0.15.7"


def test_video_frontend_contracts():
    js = _frontend("js/app.js") + _frontend("js/review.js")
    review = _frontend("js/review.js")
    assert "已加入生成队列，完成后可在此播放" in js
    assert "讲解视频" in js and "视频讲解" in js and "还没有讲解视频" in js
    assert "split(' · ')" not in js
    assert "removeAttribute('src')" in js and "playsinline" in js
    assert "#/videos/${video.video_id}" in js and "videoDetail(id)" in js
    assert "requested_at" in js and "已等待 ${seconds} 秒" in review
    assert review.index("class=\"kc-scene\"") < review.index("class=\"btn video-review\"")
    worker = (ROOT / "backend" / "video_worker.py").read_text()
    assert "JSON.stringify" not in worker
    assert "--neighbours" in worker and "、" in worker
