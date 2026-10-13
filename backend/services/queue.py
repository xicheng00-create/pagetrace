"""今日队列兼容入口；卡池读取统一由 services.cards 实现。"""
from services.cards import due_query, new_query, today_queue  # noqa: F401
