"""社交功能：每日计划、打卡热力图、排行榜、好友、私信、论坛。

需要两个用户互相操作，所以不用 conftest 里那个共享 headers 的 auth_client，
而是每个用户一个独立的 TestClient。
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import levels

PASSWORD = "tester12345"


@pytest.fixture
def make_user():
    """返回一个工厂：每次调用造一个独立登录的用户。"""
    clients: list[TestClient] = []

    def _make(prefix: str = "u"):
        client = TestClient(app)
        client.__enter__()
        clients.append(client)

        suffix = uuid.uuid4().hex[:8]
        username = f"{prefix}{suffix}"
        response = client.post(
            "/api/auth/register",
            json={
                "username": username,
                "email": f"{username}@example.com",
                "password": PASSWORD,
            },
        )
        assert response.status_code == 201, response.text
        client.headers.update(
            {"Authorization": f"Bearer {response.json()['access_token']}"}
        )
        user_id = client.get("/api/users/me").json()["id"]
        return client, user_id, username

    yield _make

    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def make_admin(make_user):
    """管理员客户端，用于置顶这类需要权限的操作。"""

    def _make():
        client = TestClient(app)
        client.__enter__()
        response = client.post(
            "/api/auth/login",
            json={
                "email": settings.admin_email,
                "password": settings.admin_password,
            },
        )
        assert response.status_code == 200, response.text
        client.headers.update(
            {"Authorization": f"Bearer {response.json()['access_token']}"}
        )
        return client

    yield _make


# ------------------------------------------------------------------ 每日计划


def test_default_quests_are_seeded_once(make_user):
    """新用户第一次拉列表会拿到四条默认计划，且只播一次。"""
    client, _, _ = make_user()
    quests = client.get("/api/quests").json()

    assert len(quests) == len(levels.DAILY_QUESTS)
    # 默认计划也是用户自己的，可以改可以删，所以都带 id
    assert all(q["custom"] is True and q["id"] for q in quests)
    assert all(q["key"] and q["icon"] and q["label"] for q in quests)
    # 进度不能超过目标，否则前端进度条会溢出
    assert all(0 <= q["progress"] <= q["target"] for q in quests)
    # 默认计划的 XP 由「今日任务」发放，这里不挂
    assert all(q["xp"] == 0 for q in quests)
    # 没打勾之前一律未完成，不看统计进度
    assert all(q["completed"] is False for q in quests)

    again = client.get("/api/quests").json()
    assert [q["id"] for q in again] == [q["id"] for q in quests]


def test_deleted_default_quests_do_not_come_back(make_user):
    """删光默认计划后不会再自动长出来。"""
    client, _, _ = make_user()
    for quest in client.get("/api/quests").json():
        assert client.delete(f"/api/quests/{quest['id']}").status_code == 204

    assert client.get("/api/quests").json() == []


def test_quest_completion_is_manual(make_user):
    """完成与否由用户打勾决定，不看站内统计进度。"""
    client, _, _ = make_user()
    quest = client.get("/api/quests").json()[0]
    assert quest["completed"] is False

    checked = client.post(f"/api/quests/{quest['id']}/check", json={"completed": True})
    assert checked.status_code == 200, checked.text
    body = checked.json()
    assert body["completed"] is True
    # 新用户没有任何站内学习记录，进度是 0，但用户说完成了就是完成了
    assert body["progress"] == 0

    listed = {q["id"]: q for q in client.get("/api/quests").json()}
    assert listed[quest["id"]]["completed"] is True

    unchecked = client.post(f"/api/quests/{quest['id']}/check", json={"completed": False})
    assert unchecked.status_code == 200
    assert unchecked.json()["completed"] is False


def test_quest_check_counts_as_activity(make_user):
    """手动打勾算当天一次学习活动：热力图有记录，连续天数起来。"""
    client, _, _ = make_user()
    quest = client.get("/api/quests").json()[0]

    before = client.get("/api/stats/heatmap?days=30").json()
    assert before["cells"][-1]["count"] == 0
    assert before["current_streak"] == 0

    client.post(f"/api/quests/{quest['id']}/check", json={"completed": True})

    after = client.get("/api/stats/heatmap?days=30").json()
    assert after["cells"][-1]["count"] == 1
    assert after["current_streak"] == 1


def test_quest_check_is_idempotent(make_user):
    """重复打勾只记一条活动，不会把热力图刷爆。"""
    client, _, _ = make_user()
    quest = client.get("/api/quests").json()[0]

    for _ in range(3):
        assert (
            client.post(
                f"/api/quests/{quest['id']}/check", json={"completed": True}
            ).status_code
            == 200
        )

    heat = client.get("/api/stats/heatmap?days=30").json()
    assert heat["cells"][-1]["count"] == 1


def test_deleting_a_checked_quest_keeps_that_days_activity(make_user):
    """删掉打过勾的计划，当天的活动不该跟着消失。"""
    client, _, _ = make_user()
    quest = client.get("/api/quests").json()[0]
    client.post(f"/api/quests/{quest['id']}/check", json={"completed": True})

    assert client.delete(f"/api/quests/{quest['id']}").status_code == 204

    heat = client.get("/api/stats/heatmap?days=30").json()
    assert heat["cells"][-1]["count"] == 1


def test_cannot_check_another_users_quest(make_user):
    owner, _, _ = make_user("own")
    other, _, _ = make_user("oth")
    quest_id = owner.get("/api/quests").json()[0]["id"]

    assert other.post(
        f"/api/quests/{quest_id}/check", json={"completed": True}
    ).status_code in (403, 404)
    assert owner.get("/api/quests").json()[0]["completed"] is False


def test_quest_metrics_match_daily_stats_keys(make_user):
    """计划的可选口径必须和 daily_stats 的返回键一致，否则进度永远是 0。"""
    client, _, _ = make_user()
    metrics = client.get("/api/quests/metrics").json()

    assert {m["key"] for m in metrics} == {
        "words",
        "articles",
        "scenarios",
        "reviews",
        "chat_minutes",
        "forum_posts",
    }
    assert all(m["label"] and m["unit"] for m in metrics)


def test_user_can_manage_custom_quest(make_user):
    client, _, _ = make_user()

    created = client.post(
        "/api/quests",
        json={
            "label": "每天背 20 个单词",
            "metric": "words",
            "target": 20,
            "xp": 15,
            "icon": "📚",
        },
    )
    assert created.status_code == 201, created.text
    quest = created.json()
    assert quest["custom"] is True
    assert quest["label"] == "每天背 20 个单词"
    quest_id = quest["id"]

    updated = client.patch(
        f"/api/quests/{quest_id}",
        json={"label": "每天背 30 个单词", "target": 30},
    )
    assert updated.status_code == 200
    assert updated.json()["target"] == 30
    assert updated.json()["label"] == "每天背 30 个单词"

    listed = client.get("/api/quests").json()
    assert any(q["id"] == quest_id and q["custom"] for q in listed)

    assert client.delete(f"/api/quests/{quest_id}").status_code == 204
    assert all(q["id"] != quest_id for q in client.get("/api/quests").json())


def test_cannot_touch_another_users_quest(make_user):
    owner, _, _ = make_user("own")
    other, _, _ = make_user("oth")

    quest_id = owner.post(
        "/api/quests",
        json={"label": "私人计划", "metric": "words", "target": 5, "xp": 10, "icon": "🎯"},
    ).json()["id"]

    assert other.patch(
        f"/api/quests/{quest_id}", json={"target": 99}
    ).status_code in (403, 404)
    assert other.delete(f"/api/quests/{quest_id}").status_code in (403, 404)
    # 原主人还能看到
    assert any(q["id"] == quest_id for q in owner.get("/api/quests").json())


# ------------------------------------------------------------------ 打卡与排行


def test_heatmap_returns_contiguous_days(make_user):
    client, _, _ = make_user()
    heat = client.get("/api/stats/heatmap?days=120").json()

    assert len(heat["cells"]) == 120
    assert len({c["date"] for c in heat["cells"]}) == 120
    assert all(0 <= c["level"] <= 4 for c in heat["cells"])
    assert all(c["count"] >= 0 for c in heat["cells"])
    assert heat["current_streak"] >= 0
    assert heat["longest_streak"] >= heat["current_streak"]


def test_heatmap_of_other_user_and_unknown(make_user):
    client, _, _ = make_user("me")
    peer, peer_id, _ = make_user("pe")

    assert client.get(f"/api/stats/heatmap/{peer_id}").status_code == 200
    assert client.get("/api/stats/heatmap/999999").status_code == 404


def test_leaderboard_chart_and_list_share_data(make_user):
    client, user_id, _ = make_user()
    board = client.get("/api/stats/leaderboard?metric=xp").json()

    assert len(board["bars"]) == len(board["entries"])
    # 服务层返回前 limit 名，如果自己不在其中会额外补一条，所以上限是 limit + 1
    assert 0 < len(board["bars"]) <= 21
    assert len({b["user_id"] for b in board["bars"]}) == len(board["bars"])
    assert [e["rank"] for e in board["entries"]] == list(
        range(1, len(board["entries"]) + 1)
    )
    values = [b["value"] for b in board["bars"]]
    assert values == sorted(values, reverse=True)
    assert all("level" in e and "streak" in e for e in board["entries"])
    # 自己必须被标出来，前端靠它高亮
    assert sum(1 for e in board["entries"] if e["is_me"]) == 1
    assert any(e["user_id"] == user_id for e in board["entries"])


def test_leaderboard_supports_streak_and_rejects_unknown_metric(make_user):
    client, _, _ = make_user()

    assert client.get("/api/stats/leaderboard?metric=streak").status_code == 200
    assert client.get("/api/stats/leaderboard?metric=nope").status_code == 400


def test_user_stats_expose_profile_fields(make_user):
    client, _, _ = make_user("me")
    peer, peer_id, peer_name = make_user("pe")

    stats = client.get(f"/api/stats/users/{peer_id}").json()

    assert stats["user_id"] == peer_id
    assert stats["username"] == peer_name
    for field in (
        "contribution",
        "published_articles",
        "forum_posts",
        "forum_comments",
        "likes_received",
        "words_today",
        "articles_today",
        "words_total",
        "scenarios_done",
        "active_days",
    ):
        assert field in stats, field

    assert client.get("/api/stats/users/999999").status_code == 404


# ------------------------------------------------------------------ 好友


def test_friend_request_and_accept_flow(make_user):
    me, my_id, _ = make_user("me")
    peer, peer_id, _ = make_user("pe")

    assert me.get(f"/api/friends/status/{my_id}").json()["state"] == "self"
    assert me.get(f"/api/friends/status/{peer_id}").json()["state"] == "none"

    requested = me.post(f"/api/friends/{peer_id}")
    assert requested.status_code in (200, 201)
    assert requested.json()["state"] == "outgoing"
    assert me.get(f"/api/friends/status/{peer_id}").json()["state"] == "outgoing"
    assert peer.get(f"/api/friends/status/{my_id}").json()["state"] == "incoming"

    incoming = peer.get("/api/friends/requests").json()["incoming"]
    assert len(incoming) == 1
    assert incoming[0]["user_id"] == my_id
    friendship_id = incoming[0]["friendship_id"]

    assert me.get("/api/friends/requests").json()["outgoing"][0][
        "user_id"
    ] == peer_id

    accepted = peer.post(f"/api/friends/requests/{friendship_id}/accept")
    assert accepted.status_code == 204
    assert me.get(f"/api/friends/status/{peer_id}").json()["state"] == "friends"
    assert peer.get(f"/api/friends/status/{my_id}").json()["state"] == "friends"

    my_friends = me.get("/api/friends").json()
    peer_friends = peer.get("/api/friends").json()
    assert [f["user_id"] for f in my_friends] == [peer_id]
    assert [f["user_id"] for f in peer_friends] == [my_id]
    # 自己的列表里绝不能出现自己
    assert all(f["user_id"] != my_id for f in my_friends)


def test_friend_request_can_be_declined(make_user):
    me, my_id, _ = make_user("me")
    peer, peer_id, _ = make_user("pe")

    me.post(f"/api/friends/{peer_id}")
    friendship_id = peer.get("/api/friends/requests").json()["incoming"][0][
        "friendship_id"
    ]

    assert peer.post(
        f"/api/friends/requests/{friendship_id}/decline"
    ).status_code == 204
    assert me.get(f"/api/friends/status/{peer_id}").json()["state"] == "none"
    assert peer.get("/api/friends").json() == []


def test_unfriend_blocks_chat(make_user):
    me, _, _ = make_user("me")
    peer, peer_id, _ = make_user("pe")

    me.post(f"/api/friends/{peer_id}")
    friendship_id = peer.get("/api/friends/requests").json()["incoming"][0][
        "friendship_id"
    ]
    peer.post(f"/api/friends/requests/{friendship_id}/accept")

    me.post(f"/api/chat/{peer_id}", json={"content": "你好"})
    assert me.get(f"/api/chat/{peer_id}").status_code == 200

    assert me.delete(f"/api/friends/{peer_id}").status_code == 204
    assert me.get(f"/api/friends/status/{peer_id}").json()["state"] == "none"
    assert me.get(f"/api/chat/{peer_id}").status_code == 403


# ------------------------------------------------------------------ 私信


def _become_friends(a, b, b_id):
    """a 向 b 发申请，b 通过。"""
    a.post(f"/api/friends/{b_id}")
    friendship_id = b.get("/api/friends/requests").json()["incoming"][0][
        "friendship_id"
    ]
    b.post(f"/api/friends/requests/{friendship_id}/accept")


def test_friends_can_exchange_messages(make_user):
    me, my_id, _ = make_user("me")
    peer, peer_id, _ = make_user("pe")
    _become_friends(me, peer, peer_id)

    sent = me.post(f"/api/chat/{peer_id}", json={"content": "一起练口语吗？"})
    assert sent.status_code in (200, 201)
    assert sent.json()["mine"] is True
    assert sent.json()["content"] == "一起练口语吗？"

    peer.post(f"/api/chat/{my_id}", json={"content": "好啊，明天开始"})

    conversation = me.get(f"/api/chat/{peer_id}").json()
    assert len(conversation) == 2
    assert [m["mine"] for m in conversation] == [True, False]
    assert conversation[0]["created_at"] <= conversation[1]["created_at"]

    threads = peer.get("/api/chat/threads").json()
    assert len(threads) == 1
    assert threads[0]["user_id"] == my_id
    # 会话列表显示的是最新一条，不是第一条
    assert threads[0]["last_message"] == "好啊，明天开始"
    assert isinstance(peer.get("/api/chat/unread").json()["unread"], int)


def test_strangers_cannot_chat(make_user):
    me, my_id, _ = make_user("me")
    stranger, _, _ = make_user("st")

    assert stranger.post(
        f"/api/chat/{my_id}", json={"content": "hi"}
    ).status_code == 403
    assert stranger.get(f"/api/chat/{my_id}").status_code == 403
    assert stranger.get("/api/chat/threads").json() == []


def test_blank_message_is_rejected(make_user):
    """只有空白的消息不该存进库，也不能算一条聊天记录。"""
    me, _, _ = make_user("me")
    peer, peer_id, _ = make_user("pe")
    _become_friends(me, peer, peer_id)

    assert me.post(f"/api/chat/{peer_id}", json={"content": "   "}).status_code == 422
    assert me.post(f"/api/chat/{peer_id}", json={"content": ""}).status_code == 422
    assert me.get(f"/api/chat/{peer_id}").json() == []


def test_blank_post_and_comment_are_rejected(make_user):
    client, _, _ = make_user()

    assert client.post(
        "/api/forum/posts", json={"title": "  ", "content": "正文", "tags": []}
    ).status_code == 422
    assert client.post(
        "/api/forum/posts", json={"title": "标题", "content": "  ", "tags": []}
    ).status_code == 422

    post_id = client.post(
        "/api/forum/posts", json={"title": "标题", "content": "正文", "tags": []}
    ).json()["id"]
    assert client.post(
        f"/api/forum/posts/{post_id}/comments", json={"content": "   "}
    ).status_code == 422


# ------------------------------------------------------------------ 论坛


def test_post_lifecycle_and_owner_permissions(make_user):
    author, _, _ = make_user("au")
    other, _, _ = make_user("ot")

    body = (
        "# 我的方法\n\n每天 **30 分钟**：\n\n- 一个场景对话\n\n"
        "参考 [资源](https://example.com)\n\n> 坚持最重要\n"
    )
    created = author.post(
        "/api/forum/posts",
        json={"title": "三个月从 A2 到 B1", "content": body, "tags": ["经验", "口语"]},
    )
    assert created.status_code == 201, created.text
    post = created.json()
    post_id = post["id"]
    assert post["tags"] == ["经验", "口语"]
    assert post["is_mine"] is True
    assert "# 我的方法" in post["content"]
    # 列表摘要要去掉 markdown 记号，避免卡片里出现 ** 和裸链接
    assert "**" not in post["summary"]
    assert "https" not in post["summary"]

    assert author.get("/api/forum/posts").json()
    listed = author.get("/api/forum/posts").json()
    assert any(p["id"] == post_id for p in listed["items"])
    # 列表是分页响应，total 用于「加载更多」
    assert listed["total"] >= 1
    assert listed["offset"] == 0
    assert isinstance(listed["has_more"], bool)

    # 别人不能改、不能删
    assert other.patch(
        f"/api/forum/posts/{post_id}", json={"title": "改个名"}
    ).status_code == 403
    assert other.delete(f"/api/forum/posts/{post_id}").status_code == 403

    updated = author.patch(f"/api/forum/posts/{post_id}", json={"title": "改名了"})
    assert updated.status_code == 200
    assert author.get(f"/api/forum/posts/{post_id}").json()["title"] == "改名了"

    assert author.delete(f"/api/forum/posts/{post_id}").status_code == 204
    assert author.get(f"/api/forum/posts/{post_id}").status_code == 404


def test_like_and_comment_counts(make_user):
    author, _, _ = make_user("au")
    reader, _, _ = make_user("rd")

    post_id = author.post(
        "/api/forum/posts",
        json={"title": "精读心得", "content": "正文", "tags": []},
    ).json()["id"]

    liked = reader.post(f"/api/forum/posts/{post_id}/like").json()
    assert liked == {"liked": True, "like_count": 1}
    unliked = reader.post(f"/api/forum/posts/{post_id}/like").json()
    assert unliked == {"liked": False, "like_count": 0}
    reader.post(f"/api/forum/posts/{post_id}/like")

    comment = reader.post(
        f"/api/forum/posts/{post_id}/comments", json={"content": "很有帮助"}
    )
    assert comment.status_code == 201
    assert comment.json()["is_mine"] is True

    detail = author.get(f"/api/forum/posts/{post_id}").json()
    assert detail["like_count"] == 1
    assert detail["comment_count"] == 1
    # 作者看自己的帖子不计阅读量，避免刷数据
    assert detail["view_count"] == 0
    # 别人打开才算一次阅读
    reader.get(f"/api/forum/posts/{post_id}")
    assert author.get(f"/api/forum/posts/{post_id}").json()["view_count"] == 1
    # 作者看别人的评论，is_mine 应为 False
    assert author.get(f"/api/forum/posts/{post_id}/comments").json()[0][
        "is_mine"
    ] is False
    # 点赞者自己看，liked 应为 True
    assert reader.get(f"/api/forum/posts/{post_id}").json()["liked"] is True


def test_forum_search_and_tag_filter(make_user):
    client, _, _ = make_user()
    post_id = client.post(
        "/api/forum/posts",
        json={"title": "雅思口语 7 分经验", "content": "正文", "tags": ["雅思"]},
    ).json()["id"]

    def ids(query: str) -> list[int]:
        return [p["id"] for p in client.get(f"/api/forum/posts{query}").json()["items"]]

    assert post_id in ids("?q=雅思")
    assert post_id in ids("?tag=雅思")
    assert post_id not in ids("?q=zzzzzz")
    # 标签是精确匹配，"雅思" 不该命中 "雅思口语"
    assert post_id not in ids("?tag=雅思口语")


def test_only_admin_can_pin(make_user, make_admin):
    author, _, _ = make_user("au")
    admin = make_admin()

    post_id = author.post(
        "/api/forum/posts",
        json={"title": "置顶测试", "content": "正文", "tags": []},
    ).json()["id"]

    assert author.post(f"/api/forum/posts/{post_id}/pin").status_code == 403
    assert admin.post(f"/api/forum/posts/{post_id}/pin").status_code == 200

    ordered = admin.get("/api/forum/posts").json()["items"]
    index = next(i for i, p in enumerate(ordered) if p["id"] == post_id)
    # 它前面只能有别置顶帖，不能夹着普通帖
    assert all(p["is_pinned"] for p in ordered[:index])


def test_forum_activity_raises_contribution(make_user):
    author, author_id, _ = make_user("au")
    reader, _, _ = make_user("rd")

    before = author.get(f"/api/stats/users/{author_id}").json()

    post_id = author.post(
        "/api/forum/posts",
        json={"title": "贡献值测试", "content": "正文", "tags": []},
    ).json()["id"]
    reader.post(f"/api/forum/posts/{post_id}/like")
    reader.post(f"/api/forum/posts/{post_id}/comments", json={"content": "赞"})

    after = author.get(f"/api/stats/users/{author_id}").json()

    assert after["forum_posts"] == before["forum_posts"] + 1
    assert after["likes_received"] == before["likes_received"] + 1
    assert after["forum_comments"] == before["forum_comments"]
    assert after["contribution"] > before["contribution"]


def test_unknown_post_and_comment_return_404(make_user):
    client, _, _ = make_user()

    assert client.get("/api/forum/posts/999999").status_code == 404
    assert client.delete("/api/forum/comments/999999").status_code == 404


def test_forum_list_paginates_and_reports_total(make_user):
    client, _, _ = make_user()
    for index in range(3):
        client.post(
            "/api/forum/posts",
            json={"title": f"分页帖 {index}", "content": "正文", "tags": ["分页"]},
        )

    first = client.get("/api/forum/posts?tag=分页&limit=2&offset=0").json()
    assert len(first["items"]) == 2
    assert first["total"] == 3
    assert first["has_more"] is True

    second = client.get("/api/forum/posts?tag=分页&limit=2&offset=2").json()
    assert len(second["items"]) == 1
    assert second["has_more"] is False
    # 两页不重叠
    first_ids = {p["id"] for p in first["items"]}
    second_ids = {p["id"] for p in second["items"]}
    assert first_ids.isdisjoint(second_ids)


def test_forum_list_supports_sort_modes(make_user):
    client, _, _ = make_user("me")
    reader, _, _ = make_user("rd")

    quiet = client.post(
        "/api/forum/posts", json={"title": "无人问津", "content": "正文", "tags": []}
    ).json()["id"]
    hot = client.post(
        "/api/forum/posts", json={"title": "很受欢迎", "content": "正文", "tags": []}
    ).json()["id"]
    discussed = client.post(
        "/api/forum/posts", json={"title": "讨论热烈", "content": "正文", "tags": []}
    ).json()["id"]

    # 点赞是开关，同一个人点两次会取消，所以要两个不同的人各点一次
    reader.post(f"/api/forum/posts/{hot}/like")
    other, _, _ = make_user("ot")
    other.post(f"/api/forum/posts/{hot}/like")
    for _ in range(2):
        reader.post(f"/api/forum/posts/{discussed}/comments", json={"content": "顶"})

    def ids(sort: str) -> list[int]:
        return [
            p["id"]
            for p in client.get(f"/api/forum/posts?sort={sort}&limit=50").json()["items"]
        ]

    # 测试库是 session 级共享的，别的用例也留了帖子，所以只比较这三篇的相对顺序，
    # 不能断言它们一定排在全站第一。
    hot_order = ids("hot")
    assert hot_order.index(hot) < hot_order.index(quiet)

    active_order = ids("active")
    assert active_order.index(discussed) < active_order.index(quiet)

    # 最新排序按创建时间倒序，最后发的排最前
    new_order = ids("new")
    assert new_order.index(discussed) < new_order.index(quiet)
    assert quiet in new_order
    # 非法 sort 回退到最新，不应该报错
    assert client.get("/api/forum/posts?sort=nonsense").status_code == 200


def test_popular_tags_endpoint(make_user):
    client, _, _ = make_user()
    for _ in range(2):
        client.post(
            "/api/forum/posts",
            json={"title": "标签帖", "content": "正文", "tags": ["口语", "备考"]},
        )

    tags = client.get("/api/forum/tags").json()
    counts = {row["tag"]: row["count"] for row in tags}
    assert counts["口语"] == 2
    assert counts["备考"] == 2


def test_comment_awards_contribution_to_commenter(make_user):
    author, _, _ = make_user("au")
    reader, reader_id, _ = make_user("rd")

    before = reader.get(f"/api/stats/users/{reader_id}").json()

    post_id = author.post(
        "/api/forum/posts", json={"title": "正文", "content": "正文", "tags": []}
    ).json()["id"]
    assert reader.post(
        f"/api/forum/posts/{post_id}/comments", json={"content": "有用"}
    ).status_code == 201

    after = reader.get(f"/api/stats/users/{reader_id}").json()
    assert after["forum_comments"] == before["forum_comments"] + 1
    assert after["contribution"] > before["contribution"]


def test_forum_posts_expose_updated_at_and_level_name(make_user):
    client, _, _ = make_user()
    post_id = client.post(
        "/api/forum/posts", json={"title": "元数据", "content": "正文", "tags": []}
    ).json()["id"]

    card = next(
        p for p in client.get("/api/forum/posts").json()["items"] if p["id"] == post_id
    )
    assert card["updated_at"] is not None
    assert card["author"]["level_name"]
