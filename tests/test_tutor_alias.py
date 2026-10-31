"""口语别名层：数据卫生、触发条件、不越租户、表外改写也命中。"""
import pytest
from tutor_fixtures import make_app

from ai import rag, tutor_synonyms


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "alias.sqlite3"))
    app = make_app(tmp_path / "alias.sqlite3")
    with app.app_context():
        from data.db import get_db

        yield get_db()


def test_alias_table_hygiene():
    """键 ≥2 字（单字键会满天飞误触发）；值非空且能过 2-gram 分词。"""
    assert tutor_synonyms.ALIASES, "别名表不能是空的（否则断言形同虚设）"
    for key, values in tutor_synonyms.ALIASES.items():
        assert len(key) >= 2, f"键「{key}」太短，会误触发"
        assert values, f"键「{key}」没有术语值"
        for value in values:
            assert rag._tokens(value), f"值「{value}」切不出 2-gram，等于没写（3 字以上术语常见坑）"


def test_no_colloquial_key_no_behavior_change(con):
    """没有口语键时行为与参考实现完全一致：全部 exact。"""
    hits = rag.retrieve_cards(con, "亲密伴侣暴力", user_id=1)
    assert hits and all(hit.get("via", "exact") == "exact" for hit in hits)


def test_colloquial_query_goes_through_alias_arm(con):
    hits = rag.retrieve_cards(con, "他动手了我怕他", user_id=1, top_k=3)
    assert hits[0]["via"] == "alias"
    assert hits[0]["concept_name"] == "亲密伴侣暴力"  # 库里 gold 概念


def test_held_out_paraphrase_not_in_index(con):
    """表外改写（problem-index 里没有这句）：只靠别名表也要落到 gold。"""
    hits = rag.retrieve_cards(con, "他打我了 我很怕", user_id=1, top_k=3)
    assert hits[0]["concept_name"] == "亲密伴侣暴力"


def test_alias_does_not_bypass_tenant_scope(con):
    """别名臂也只在自己可见的卡里排：户 2 的「项目管理」卡不能被口语问句捞出来。"""
    hits = rag.retrieve_cards(con, "他动手了我怕他", user_id=3, top_k=5)
    assert all(hit["card_id"] != 1 for hit in hits)
    assert hits == [] or all(hit.get("via") == "alias" for hit in hits)


def test_expand_returns_only_matched_targets():
    assert tutor_synonyms.expand("他动手了我怕他") >= {"暴力", "恐吓"}
    assert tutor_synonyms.expand("今天天气不错") == set()
    assert tutor_synonyms.expand("") == set()
