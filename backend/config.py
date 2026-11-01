"""配置（Development / Production）。生产环境不开调试器。

数据库路径优先 DATABASE_PATH（测试用临时库）→ DATABASE_URL → 默认 data-local/review.sqlite3。
"""
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BACKEND_DIR.parent


class BaseConfig:
    S2_OWNER_USERNAME = os.environ.get("S2_OWNER_USERNAME", "owner")
    VERSION = "0.24.0"
    APP_SECRET = os.environ.get("APP_SECRET", "")
    JWT_SECRET = os.environ.get("JWT_SECRET", "") or os.environ.get("APP_SECRET", "") or "development-only-change-me"
    JWT_TTL_HOURS = int(os.environ.get("JWT_TTL_HOURS", "720"))

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///data-local/review.sqlite3"
    )
    DATABASE_PATH = os.environ.get("DATABASE_PATH")

    # 上游契约（DESIGN_SPEC §5）
    KB_EXPORTS_DIR = os.environ.get(
        "KB_EXPORTS_DIR", str(Path.home() / "data-local" / "exports")
    )
    CONTRACT_VERSION = int(os.environ.get("CONTRACT_VERSION", "1"))

    # 学科显示名映射（DATA-006）：契约只给 slug，**显示名由 app 侧维护**（唯一来源 = 库内 subjects.name）。
    # 加学科时在这里补一行；未命中的 slug 回落为 slug 本身，并在 ingest 时记一条 warning。
    SUBJECT_LABELS = {"demo": "演示学科"}

    # 卡片四状态中文词表（MAST-003 / MAST-005，v0.6.1）：**唯一来源**，前端零映射、零拼接。
    # 卡级 `status_label`（MAST-003）与概念行 `status_counts`/`status_label`（MAST-005）都只从这里取词。
    STATUS_LABELS = {
        "new": "未学习",
        "learning": "学习中",
        "reviewing": "复习中",
        "mastered": "已掌握",
    }
    # 多态计数顺序固定：新 → 学 → 复 → 掌（MAST-005）
    STATUS_ORDER = ("new", "learning", "reviewing", "mastered")
    STATUS_UNKNOWN_LABEL = "未学习"   # 未知 status 回落标签（并记 warning，不得静默）
    STATUS_NO_CARD_LABEL = "无卡"     # 概念下无卡时的状态文案

    # 掌握度解锁（SCHED-001/005：单点配置，禁止散落硬编码）
    UNLOCK_MASTERY_RATIO = float(os.environ.get("UNLOCK_MASTERY_RATIO", "0.8"))
    UNLOCK_MIN_LEARNED = int(os.environ.get("UNLOCK_MIN_LEARNED", "5"))

    # 复习卡组上限（REVIEW-003）
    REVIEW_BATCH_MAX = int(os.environ.get("REVIEW_BATCH_MAX", "100"))
    NEW_CARDS_BATCH_MAX = int(os.environ.get("NEW_CARDS_BATCH_MAX", "30"))

    # 出题（QUIZ-001/002/003）：单次题量 + 题型配比 + LLM 接入（单点配置，禁止散落硬编码）
    QUIZ_DEFAULT_SIZE = int(os.environ.get("QUIZ_DEFAULT_SIZE", "10"))
    QUIZ_MAX_SIZE = int(os.environ.get("QUIZ_MAX_SIZE", "50"))
    QUIZ_SESSION_SIZE = int(os.environ.get("QUIZ_SESSION_SIZE", "10"))  # 一次会话默认题量
    QUIZ_CHOICE_RATIO = int(os.environ.get("QUIZ_CHOICE_RATIO", "7"))   # choice:bool = 7:3
    QUIZ_BOOL_RATIO = int(os.environ.get("QUIZ_BOOL_RATIO", "3"))
    QUIZ_LLM_TIMEOUT_SECONDS = int(os.environ.get("QUIZ_LLM_TIMEOUT_SECONDS", "30"))

    # 今日任务（TASK-001）：出题 M 题 = 今日测验目标题数（单点配置，禁止散落硬编码）
    QUIZ_TASK_TARGET = int(os.environ.get("QUIZ_TASK_TARGET", "5"))
    # 每日连胜口径（2026-10-31 owner 定）：看 5 个视频 + 复习 20 张卡 + 做 5 道题。
    VIDEO_TASK_TARGET = int(os.environ.get("VIDEO_TASK_TARGET", "5"))

    # 每日复习卡片目标（GOAL-001，v0.6.0）：单一真相，默认 30、env 可覆写；前端不得硬编码
    REVIEW_TASK_TARGET = int(os.environ.get("REVIEW_TASK_TARGET", "20"))

    # DeepSeek（QUIZ-002：出题草稿；判分绝不走此处 —— QUIZ-004）
    DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
    DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

    # S1 出卡 provider 单点；local 本版仅接口，不主动接入机器。
    UPLOAD_MONTHLY_PAGES = int(os.environ.get("UPLOAD_MONTHLY_PAGES", "600"))
    UPLOAD_WORKER_ENABLED = os.environ.get("UPLOAD_WORKER_ENABLED", "0") == "1"
    LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "proxy")
    LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
    LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
    LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
    LLM_TIMEOUT = os.environ.get("LLM_TIMEOUT", "")

    FREEZE_BASE = int(os.environ.get("FREEZE_BASE", "3"))

    # 连胜（段⑤C）：按本地日切分。Asia/Hong_Kong 全年 UTC+8、无夏令时，固定偏移等价。
    STREAK_GOAL_FROM_DATE = "2026-09-27"
    STREAK_TZ_OFFSET_HOURS = int(os.environ.get("STREAK_TZ_OFFSET_HOURS", "8"))

    # 复习调度（REVIEW-001：唯一一套间隔，SM-2 派生；learn_count 索引 1..N）
    # good 的第 k 次连击 → 间隔天数；超出表长取末档。不得另起一套算法。
    REVIEW_INTERVALS_DAYS = [1, 3, 7, 16, 35]
    AGAIN_INTERVAL_MINUTES = int(os.environ.get("AGAIN_INTERVAL_MINUTES", "10"))
    HARD_INTERVAL_HOURS = int(os.environ.get("HARD_INTERVAL_HOURS", "12"))
    # learn_count ≥ 此值且最近一次 good → status='mastered'（掌握度分子）
    MASTER_MIN_LEARN = int(os.environ.get("MASTER_MIN_LEARN", "3"))

    # Tutor（规格 v0.1 §5）：每人每日调用上限 + 检索/上下文口径；上限只走配置，禁止散落硬编码。
    TUTOR_DAILY_LIMIT = int(os.environ.get("TUTOR_DAILY_LIMIT", "40"))
    TUTOR_TOP_K = int(os.environ.get("TUTOR_TOP_K", "5"))
    TUTOR_HISTORY_ROUNDS = int(os.environ.get("TUTOR_HISTORY_ROUNDS", "6"))
    TUTOR_LLM_TIMEOUT = int(os.environ.get("TUTOR_LLM_TIMEOUT", "60"))
    # 概念表路由（规格 §9f）：这一次调用只给 8 秒，超时就静默退回 2-gram，不让用户等
    TUTOR_ROUTE_TIMEOUT = int(os.environ.get("TUTOR_ROUTE_TIMEOUT", "8"))

    # 提醒（OPS-004）
    REMIND_AT = os.environ.get("REMIND_AT", "20:00")

    JSON_AS_ASCII = False
    JSON_SORT_KEYS = False


class DevelopmentConfig(BaseConfig):
    DEBUG = False  # 生产同款进程模型，不用 Flask 调试器
    ENV = "development"


class ProductionConfig(BaseConfig):
    DEBUG = False
    ENV = "production"


def get_config(env: str | None = None) -> type[BaseConfig]:
    env = (env or os.environ.get("FLASK_ENV") or "development").lower()
    return ProductionConfig if env == "production" else DevelopmentConfig
