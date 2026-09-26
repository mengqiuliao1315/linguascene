"""词书 / 单词卡 / 每日任务 / 排行榜 测试。

依赖 conftest 里 session 级的 seed()，它会导入内置词书数据。
"""
from app.core.database import SessionLocal
from app.models.user import User
from app.services import wordbook_service


def _cards(client, book="cet4", limit=3):
    resp = client.get(f"/api/wordbook/cards?book={book}&limit={limit}")
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def test_list_books(auth_client):
    resp = auth_client.get("/api/wordbook/wordbooks")
    assert resp.status_code == 200, resp.text
    codes = {b["code"] for b in resp.json()["items"]}
    assert {"cet4", "cet6", "nce3", "ielts"} <= codes


def test_word_card_has_phonetic_and_examples(auth_client):
    word = _cards(auth_client, limit=1)[0]
    assert word["word"]
    assert word["phonetic_us"]
    assert word["meaning_zh"]
    assert isinstance(word["examples"], list)
    assert len(word["examples"]) >= 1


def test_book_words_endpoint(auth_client):
    resp = auth_client.get("/api/wordbook/wordbooks/cet4/words?limit=5")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 5
    assert len(body["items"]) == 5


def test_ielts_book_words_endpoint(auth_client):
    resp = auth_client.get("/api/wordbook/wordbooks/ielts/words?limit=5")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 4700
    assert len(body["items"]) == 5
    assert all("ielts" in word["books"] for word in body["items"])


def test_favorite_endpoints_removed(auth_client):
    """收藏功能已下线，接口不再存在。"""
    word = _cards(auth_client, limit=1)[0]
    wid = word["id"]
    assert auth_client.get("/api/wordbook/favorites").status_code == 404
    assert (
        auth_client.post(f"/api/wordbook/word/{wid}/favorite", json={"favorite": True}).status_code
        == 404
    )


def test_collect_awards_xp(auth_client):
    word = _cards(auth_client, limit=1)[0]
    before = auth_client.get("/api/users/me").json()["xp"]
    resp = auth_client.post(f"/api/wordbook/word/{word['id']}/collect")
    assert resp.status_code == 200, resp.text
    assert resp.json()["in_vocabulary"] is True
    after = auth_client.get("/api/users/me").json()["xp"]
    assert after > before


def test_review_updates_state_and_xp(auth_client):
    word = _cards(auth_client, limit=1)[0]
    resp = auth_client.post(
        f"/api/wordbook/word/{word['id']}/review", json={"correct": True}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["review_count"] == 1
    assert body["xp_gained"] > 0
    assert body["mastery"] > 0

    task = auth_client.get("/api/wordbook/daily-task").json()
    assert task["done"]["words"] >= 1


def test_unknown_word_returns_404(auth_client):
    resp = auth_client.post("/api/wordbook/word/999999/review", json={"correct": True})
    assert resp.status_code == 404


def test_daily_task_defaults_and_settings(auth_client):
    task = auth_client.get("/api/wordbook/daily-task").json()
    assert task["targets"]["words"] > 0
    assert task["is_complete"] is False

    updated = auth_client.put(
        "/api/wordbook/daily-task",
        json={"target_words": 5, "target_scenarios": 0, "target_articles": 0},
    ).json()
    assert updated["targets"]["words"] == 5


def test_daily_task_completion_and_overachievement_bonus(auth_client):
    auth_client.put(
        "/api/wordbook/daily-task",
        json={"target_words": 2, "target_scenarios": 0, "target_articles": 0},
    )
    words = _cards(auth_client, limit=8)
    assert len(words) >= 8

    for word in words[:2]:
        auth_client.post(f"/api/wordbook/word/{word['id']}/review", json={"correct": True})

    task = auth_client.get("/api/wordbook/daily-task").json()
    assert task["is_complete"] is True
    # 背单词子项完成各发 10 XP
    assert task["xp_earned"] == 10
    assert task["awarded"]["words"] is True
    assert task["awarded"]["scenarios"] is False

    for word in words[2:8]:
        auth_client.post(f"/api/wordbook/word/{word['id']}/review", json={"correct": True})

    task = auth_client.get("/api/wordbook/daily-task").json()
    assert task["bonus_xp"] > 0, "超额完成应发放额外经验"

    # 重复读取不该重复发子项经验
    again = auth_client.get("/api/wordbook/daily-task").json()
    assert again["xp_earned"] == task["xp_earned"]


def test_daily_task_progress_is_average_not_min(auth_client):
    """进度条取三项平均：某项为 0 时不该把整条压成 0%，否则看起来像坏了。

    完成判定仍然用最短板（见 is_complete），两者是不同口径。
    """
    auth_client.put(
        "/api/wordbook/daily-task",
        json={"target_words": 2, "target_scenarios": 1, "target_articles": 0},
    )
    words = _cards(auth_client, limit=2)
    auth_client.post(
        f"/api/wordbook/word/{words[0]['id']}/review", json={"correct": True}
    )

    task = auth_client.get("/api/wordbook/daily-task").json()
    assert task["done"]["words"] == 1
    # 背单词 0.5、场景 0.0 → 平均 0.25；若退回 min 会是 0.0
    assert task["progress"] == 0.25
    assert task["is_complete"] is False


def test_each_daily_task_item_awards_ten_xp_once(auth_client):
    """三个子项各自完成时各 +10 XP，且只发一次。"""
    auth_client.put(
        "/api/wordbook/daily-task",
        json={"target_words": 1, "target_scenarios": 1, "target_articles": 0},
    )
    words = _cards(auth_client, limit=2)
    auth_client.post(
        f"/api/wordbook/word/{words[0]['id']}/review", json={"correct": True}
    )

    task = auth_client.get("/api/wordbook/daily-task").json()
    assert task["awarded"]["words"] is True
    assert task["xp_earned"] == 10

    # 场景子项的目标是 1，完成一个场景后应再 +10
    scenario = next(
        s for s in auth_client.get("/api/scenarios").json() if s["slug"] == "restaurant"
    )
    conversation_id = auth_client.post(
        f"/api/scenarios/{scenario['id']}/start"
    ).json()["id"]
    auth_client.post(f"/api/conversations/{conversation_id}/finish")

    task = auth_client.get("/api/wordbook/daily-task").json()
    assert task["done"]["scenarios"] >= 1
    assert task["awarded"]["scenarios"] is True
    assert task["xp_earned"] == 20


def test_leaderboard_three_kinds(auth_client):
    for kind in ("xp", "streak", "contribution"):
        resp = auth_client.get(f"/api/wordbook/leaderboard?type={kind}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["kind"] == kind
        assert body["me"] is not None
        assert body["me"]["rank"] >= 1
        assert isinstance(body["entries"], list)


def test_contribution_leaderboard_reflects_records(auth_client):
    me = auth_client.get("/api/users/me").json()
    db = SessionLocal()
    try:
        user = db.get(User, me["id"])
        wordbook_service.award_contribution(db, user, 40, "publish_article")
        db.commit()
    finally:
        db.close()

    body = auth_client.get("/api/wordbook/leaderboard?type=contribution").json()
    assert body["me"]["score"] >= 40


def test_stats_leaderboard_contribution_metric(auth_client):
    """原有 /api/stats/leaderboard 现在也支持 contribution。"""
    resp = auth_client.get("/api/stats/leaderboard?metric=contribution")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "bars" in body and "entries" in body


def test_stats_leaderboard_rejects_unknown_metric(auth_client):
    resp = auth_client.get("/api/stats/leaderboard?metric=bogus")
    assert resp.status_code == 400


def test_import_words_rejects_unknown_book(tmp_path):
    """导入脚本遇到未定义的词书 code 应当拒绝，而不是写脏数据。"""
    import json

    from app import import_words

    path = tmp_path / "words.json"
    path.write_text(
        json.dumps({"not_a_book": [{"word": "x", "zh": "y"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    assert import_words.main(["import_words", str(path)]) == 1


def test_import_words_requires_existing_file(tmp_path):
    from app import import_words

    assert import_words.main(["import_words", str(tmp_path / "missing.json")]) == 1


def test_word_belongs_to_multiple_books_without_duplicating(auth_client):
    """同一个单词可以同时属于多本词书，但库里只能有一行。

    这条是回归测试：种子脚本早期按「每本词书各插一次」写入，
    accumulate 这类跨词书的词会撞上 vocabulary.word 的唯一约束。
    """
    from sqlalchemy import func, select

    from app.core.database import SessionLocal
    from app.models.learning import Vocabulary

    db = SessionLocal()
    try:
        total, distinct = db.execute(
            select(func.count(Vocabulary.id), func.count(func.distinct(Vocabulary.word)))
        ).one()
        assert total == distinct, "vocabulary 表存在重复单词"

        multi = db.scalar(
            select(Vocabulary).where(Vocabulary.books.like("%,%"))
        )
        assert multi is not None, "应当有单词同时属于多本词书"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 背单词流程：新学 / 复习 / 已掌握
# ---------------------------------------------------------------------------


def _queue(client, mode, book="cet4", limit=5):
    resp = client.get(f"/api/wordbook/study/queue?mode={mode}&book={book}&limit={limit}")
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def test_study_summary_shape(auth_client):
    body = auth_client.get("/api/wordbook/study/summary?book=cet4").json()
    assert body["new"]["target"] >= 1
    assert body["review"]["target"] >= 1
    assert body["new"]["available"] > 0
    assert body["mastered"] == 0


def test_study_queue_new_returns_cards(auth_client):
    words = _queue(auth_client, "new")
    assert words
    assert words[0]["word"]
    assert words[0]["status"] == "new"


def test_remember_moves_word_to_review_not_due_today(auth_client):
    word = _queue(auth_client, "new", limit=1)[0]
    result = auth_client.post(
        f"/api/wordbook/word/{word['id']}/study",
        json={"action": "remember", "mode": "new", "book": "cet4"},
    ).json()
    assert result["action"] == "remember"
    assert result["status"] == "review"
    assert result["due_date"] > result["task"]["date"], "记住了应排到明天及以后"
    assert result["xp_gained"] > 0

    # 不再出现在新学队列里
    assert all(w["id"] != word["id"] for w in _queue(auth_client, "new", limit=50))
    # 今天也不该到期复习
    assert all(w["id"] != word["id"] for w in _queue(auth_client, "review", limit=50))


def test_forget_puts_word_back_into_review_today(auth_client):
    word = _queue(auth_client, "new", limit=1)[0]
    result = auth_client.post(
        f"/api/wordbook/word/{word['id']}/study",
        json={"action": "forget", "mode": "new", "book": "cet4"},
    ).json()
    assert result["status"] == "learning"
    assert result["due_date"] == result["task"]["date"]

    due = _queue(auth_client, "review", limit=50)
    assert any(w["id"] == word["id"] for w in due)


def test_mastered_word_never_appears_again(auth_client):
    word = _queue(auth_client, "new", limit=1)[0]
    auth_client.post(
        f"/api/wordbook/word/{word['id']}/study",
        json={"action": "mastered", "mode": "new", "book": "cet4"},
    )

    summary = auth_client.get("/api/wordbook/study/summary?book=cet4").json()
    assert summary["mastered"] >= 1
    assert all(w["id"] != word["id"] for w in _queue(auth_client, "new", limit=100))
    assert all(w["id"] != word["id"] for w in _queue(auth_client, "review", limit=100))


def test_study_progress_tracks_new_and_review_separately(auth_client):
    auth_client.put(
        "/api/wordbook/daily-task",
        json={"target_new_words": 2, "target_review_words": 1},
    )
    before = auth_client.get("/api/wordbook/study/summary").json()
    assert before["new"]["target"] == 2
    assert before["review"]["target"] == 1

    word = _queue(auth_client, "new", limit=1)[0]
    auth_client.post(
        f"/api/wordbook/word/{word['id']}/study",
        json={"action": "forget", "mode": "new", "book": "cet4"},
    )

    after = auth_client.get("/api/wordbook/study/summary").json()
    assert after["new"]["done"] == 1
    assert after["review"]["done"] == 0

    # 同一天复习它一次
    auth_client.post(
        f"/api/wordbook/word/{word['id']}/study",
        json={"action": "remember", "mode": "review", "book": "cet4"},
    )
    final = auth_client.get("/api/wordbook/study/summary").json()
    assert final["new"]["done"] == 1
    assert final["review"]["done"] == 1

    task = auth_client.get("/api/wordbook/daily-task").json()
    assert task["done"]["new_words"] == 1
    assert task["done"]["review_words"] == 1
    # 总目标随新学/复习目标一起更新
    assert task["targets"]["words"] == 3


def test_study_answer_rejects_unknown_word(auth_client):
    resp = auth_client.post(
        "/api/wordbook/word/999999/study",
        json={"action": "remember", "mode": "new"},
    )
    assert resp.status_code == 404


def test_study_answer_rejects_bad_action(auth_client):
    word = _queue(auth_client, "new", limit=1)[0]
    resp = auth_client.post(
        f"/api/wordbook/word/{word['id']}/study",
        json={"action": "whatever", "mode": "new"},
    )
    assert resp.status_code == 422


def _collect(client, words):
    for word in words:
        resp = client.post(f"/api/wordbook/word/{word['id']}/collect")
        assert resp.status_code == 200, resp.text


def _start_quiz(client, count=2, mode="fresh"):
    resp = client.post("/api/wordbook/quiz", json={"count": count, "mode": mode})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _correct_text(question):
    word = question["word"]
    return word["meaning_zh"] or word["meaning"]


def _answer(client, question, choice):
    resp = client.post(
        "/api/wordbook/quiz/answer",
        json={"word_id": question["word"]["id"], "choice": choice},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_quiz_starts_with_four_choice_options(auth_client):
    _collect(auth_client, _cards(auth_client, limit=3))

    body = _start_quiz(auth_client, count=2)
    assert body["active"] is True
    assert body["total"] == 2
    assert body["remaining"] == 2
    assert body["finished"] is False

    question = body["question"]
    assert question is not None
    assert len(question["options"]) == 4
    assert len(set(question["options"])) == 4
    # 正确释义一定在选项里，且只出现一次
    correct = _correct_text(question)
    assert correct
    assert question["options"].count(correct) == 1


def test_quiz_caps_count_at_wordbook_total(auth_client):
    _collect(auth_client, _cards(auth_client, limit=2))

    body = _start_quiz(auth_client, count=50)
    assert body["total"] == 2
    assert body["remaining"] == 2


def test_quiz_answering_all_correct_finishes(auth_client):
    _collect(auth_client, _cards(auth_client, limit=2))

    body = _start_quiz(auth_client, count=2)
    guard = 0
    while body["active"]:
        guard += 1
        assert guard <= 10, "答对不该让题目反复出现"
        question = body["question"]
        result = _answer(auth_client, question, _correct_text(question))
        assert result["correct"] is True
        body = result["session"]

    assert body["finished"] is True
    assert body["remaining"] == 0
    assert body["correct_count"] == 2
    assert body["wrong_count"] == 0
    assert body["question"] is None


def test_quiz_wrong_answer_requeues_word(auth_client):
    _collect(auth_client, _cards(auth_client, limit=1))

    body = _start_quiz(auth_client, count=1)
    question = body["question"]
    correct = _correct_text(question)
    wrong = next(option for option in question["options"] if option != correct)

    result = _answer(auth_client, question, wrong)
    assert result["correct"] is False
    assert result["answer"] == correct

    session = result["session"]
    # 答错后同一个词仍在队列里，稍后还会再考
    assert session["finished"] is False
    assert session["remaining"] == 1
    assert session["wrong_count"] == 1
    assert session["question"]["word"]["id"] == question["word"]["id"]


def test_quiz_can_resume_and_restart(auth_client):
    _collect(auth_client, _cards(auth_client, limit=2))

    body = _start_quiz(auth_client, count=2)
    result = _answer(auth_client, body["question"], _correct_text(body["question"]))
    remaining = result["session"]["remaining"]
    assert remaining == 1

    # resume 接着上次，还剩同一道题
    resumed = _start_quiz(auth_client, count=2, mode="resume")
    assert resumed["remaining"] == remaining
    assert resumed["total"] == 2

    # fresh 重新抽题，恢复成完整的一轮
    fresh = _start_quiz(auth_client, count=2, mode="fresh")
    assert fresh["remaining"] == 2
    assert fresh["wrong_count"] == 0


def test_quiz_state_and_reset(auth_client):
    _collect(auth_client, _cards(auth_client, limit=2))

    state = auth_client.get("/api/wordbook/quiz").json()
    assert state["active"] is False

    _start_quiz(auth_client, count=2)
    state = auth_client.get("/api/wordbook/quiz").json()
    assert state["active"] is True
    assert state["question"] is not None

    assert auth_client.delete("/api/wordbook/quiz").status_code == 200
    state = auth_client.get("/api/wordbook/quiz").json()
    assert state["active"] is False
    assert state["question"] is None


def test_quiz_on_empty_wordbook_starts_nothing(auth_client):
    body = _start_quiz(auth_client, count=5)
    assert body["active"] is False
    assert body["total"] == 0
    assert body["question"] is None


def test_quiz_rejects_invalid_count(auth_client):
    assert (
        auth_client.post("/api/wordbook/quiz", json={"count": 0, "mode": "fresh"}).status_code
        == 422
    )
    assert (
        auth_client.post("/api/wordbook/quiz", json={"count": 101, "mode": "fresh"}).status_code
        == 422
    )


def test_remove_my_word_clears_it_from_wordbook(auth_client):
    word = _cards(auth_client, limit=1)[0]
    wid = word["id"]
    auth_client.post(f"/api/wordbook/word/{wid}/collect")

    mine = auth_client.get("/api/wordbook/cards?only_my=true").json()["items"]
    assert any(item["id"] == wid for item in mine)

    resp = auth_client.delete(f"/api/wordbook/my/word/{wid}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["in_vocabulary"] is False

    mine = auth_client.get("/api/wordbook/cards?only_my=true").json()["items"]
    assert not any(item["id"] == wid for item in mine)


def test_remove_unknown_word_returns_404(auth_client):
    assert auth_client.delete("/api/wordbook/my/word/999999").status_code == 404


def test_remove_keeps_learning_record_on_recollect(auth_client):
    """删除只清收藏标记，学习进度还在，所以重新收藏不会重复发新词经验。"""
    word = _cards(auth_client, limit=1)[0]
    wid = word["id"]
    auth_client.post(f"/api/wordbook/word/{wid}/collect")
    auth_client.delete(f"/api/wordbook/my/word/{wid}")

    before = auth_client.get("/api/users/me").json()["xp"]
    resp = auth_client.post(f"/api/wordbook/word/{wid}/collect")
    assert resp.status_code == 200, resp.text
    assert resp.json()["in_vocabulary"] is True
    assert auth_client.get("/api/users/me").json()["xp"] == before
