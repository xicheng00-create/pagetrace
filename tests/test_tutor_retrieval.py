"""检索层：2-gram 口径、两表覆盖、范围收窄、跨租户隔离、定序可复现。"""
import pytest
from tutor_fixtures import BACKEND, make_app  # noqa: F401  (BACKEND 用于 sys.path)

from ai import rag


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "retrieval.sqlite3"))
    app = make_app(tmp_path / "retrieval.sqlite3")
    with app.app_context():
        from data.db import get_db

        yield get_db()


def test_tokens_are_reference_2gram():
    """口径锚点：分词结果必须与参考实现逐字一致（中文 2-gram，单字丢弃）。"""
    assert rag._tokens("亲密伴侣暴力") == {"亲密", "密伴", "伴侣", "侣暴", "暴力"}
    assert rag._tokens("ABCD 12") == {"abcd", "12"}
    assert rag._tokens("") == set()


def test_score_is_query_coverage(con):
    hits = rag.retrieve_cards(con, "亲密伴侣暴力", user_id=1)
    assert hits and hits[0]["card_id"] == 1
    # 主分 = 命中的 query 词数 / query 词数（参考实现口径），不是 Jaccard
    assert hits[0]["score"] == 1.0


def test_concept_name_is_part_of_card_unit(con):
    """卡片问句里没有「项目管理」也得被查到 —— 靠概念名进检索单元。"""
    hits = rag.retrieve_cards(con, "项目管理", user_id=3)
    assert [hit["card_id"] for hit in hits] == [3]


def test_concepts_are_retrievable_on_their_own(con):
    hits = rag.retrieve_concepts(con, "性满足", user_id=1, top_k=2)
    assert hits and hits[0]["name"] == "性满足"


def test_empty_query_returns_nothing(con):
    assert rag.retrieve_cards(con, "", user_id=1) == []
    assert rag.retrieve_concepts(con, "   ", user_id=1) == []


def test_scope_by_subject_and_chapter(con):
    by_subject = rag.retrieve_cards(con, "关系", user_id=1, subject_id=1)
    assert by_subject and all(hit["chapter_id"] == 1 for hit in by_subject)
    by_chapter = rag.retrieve_cards(con, "关系", user_id=1, chapter_id=2)
    assert by_chapter == []  # 第 2 章只有项目管理卡，不含 query 词


def test_cross_household_is_invisible(con):
    """户 1 看不到户 2 的书；户 2 也看不到户 1 的。"""
    assert [hit["card_id"] for hit in rag.retrieve_cards(con, "亲密伴侣暴力", user_id=1)] == [1]
    assert rag.retrieve_cards(con, "亲密伴侣暴力", user_id=3) == []
    assert [hit["card_id"] for hit in rag.retrieve_cards(con, "项目管理", user_id=3)] == [3]


def test_locked_chapter_cards_are_still_retrievable(con):
    """解锁是学习流进度，不是访问边界：未解锁章的内容同样要能被问到。

    反证理由：本库 1576 张卡有 1130 张在未解锁章（含「第12章 · 权力和暴力」），
    若按 unlocked_at 过滤，tutor 会对七成藏书画地为牢。
    """
    con.execute("UPDATE chapters SET unlocked_at=NULL WHERE id=1")
    con.commit()
    assert [hit["card_id"] for hit in rag.retrieve_cards(con, "亲密伴侣暴力", user_id=1)] == [1]
    assert rag.card_by_id(con, 1, user_id=1)["concept_name"] == "亲密伴侣暴力"


def test_card_by_id_scope(con):
    assert rag.card_by_id(con, 1, user_id=1)["front"].startswith("亲密伴侣暴力")
    with pytest.raises(rag.CardNotFound):
        rag.card_by_id(con, 3, user_id=1)


def test_rarity_breaks_score_ties(con):
    """同分时按命中词稀有度定序（不是按卡片 id），否则 top-k 不可复现。"""
    con.execute(
        "INSERT INTO concepts(concept_uid,chapter_id,name,tags) VALUES('u4',1,'性的双重标准','[]')")
    common = con.execute(
        "INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,created_at)"
        " VALUES(4,1,'高频词卡','我们我们我们','src','h4',datetime('now'))").lastrowid
    con.execute("INSERT INTO concepts(concept_uid,chapter_id,name,tags) VALUES('u5',1,'性沟通','[]')")
    rare = con.execute(
        "INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,created_at)"
        " VALUES(5,1,'稀有词卡','床上','src','h5',datetime('now'))").lastrowid
    # 让「我们」变成高频词（df 提高 → idf 降低），稀有度比较才有意义
    for index in range(2):
        con.execute(
            "INSERT INTO cards(concept_id,subject_id,front,back,source,content_hash,created_at)"
            " VALUES(4,1,'填充卡','我们再看一眼','src',?,datetime('now'))", (f"h6{index}",))
    con.commit()
    hits = rag.retrieve_cards(con, "我们床上", user_id=1, top_k=10)
    by_id = {hit["card_id"]: hit for hit in hits}
    assert by_id[common]["score"] == by_id[rare]["score"]  # 主分同为 1/5
    order = [hit["card_id"] for hit in hits]
    assert order.index(rare) < order.index(common)  # 稀有词先，尽管 id 更大
    assert rag.retrieve_cards(con, "我们床上", user_id=1, top_k=10) == hits  # 两次结果一致
