"""等级、XP 与成就的规则定义。所有数值集中在此，便于调整。"""

LEVELS: list[tuple[int, str, int]] = [
    # (等级, 名称, 该等级起始 XP)
    (1, "Beginner", 0),
    (2, "Explorer", 100),
    (3, "Speaker", 250),
    (4, "Traveler", 500),
    (5, "Communicator", 900),
    (6, "Fluent", 1500),
    (7, "Articulate", 2300),
    (8, "Eloquent", 3300),
    (9, "Native-like", 4600),
    (10, "Master", 6200),
]

XP_REWARDS = {
    "scenario": 30,
    "free_talk": 10,
    "article": 20,
    "new_word": 5,
    "review": 5,
}

DAILY_GOAL_MINUTES = 10

# 经验统一由「今日任务」的三个子项发放，这里只做进度展示，不再挂 XP。
# metric / icon 用于给新用户播种默认计划（见 social_service.ensure_default_quests），
# metric 的取值必须与 social_service.daily_stats 的返回键一致。
DAILY_QUESTS: list[dict] = [
    {
        "key": "complete_scenario",
        "label": "完成一个场景",
        "target": 1,
        "xp": 0,
        "metric": "scenarios",
        "icon": "🎭",
    },
    {
        "key": "learn_words",
        "label": "学习 10 个单词",
        "target": 10,
        "xp": 0,
        "metric": "words",
        "icon": "📚",
    },
    {
        "key": "read_article",
        "label": "阅读一篇文章",
        "target": 1,
        "xp": 0,
        "metric": "articles",
        "icon": "📖",
    },
    {
        "key": "chat_minutes",
        "label": "与 AI 聊天 5 分钟",
        "target": 5,
        "xp": 0,
        "metric": "chat_minutes",
        "icon": "💬",
    },
]

# 自建计划可选的口径。key 必须与 social_service.daily_stats 的返回键一致，
# 否则进度永远为 0。
QUEST_METRICS: list[dict] = [
    {"key": "words", "label": "学习单词", "unit": "个"},
    {"key": "articles", "label": "阅读文章", "unit": "篇"},
    {"key": "scenarios", "label": "完成场景", "unit": "个"},
    {"key": "reviews", "label": "复习单词", "unit": "个"},
    {"key": "chat_minutes", "label": "与 AI 聊天", "unit": "分钟"},
    {"key": "forum_posts", "label": "发布帖子", "unit": "篇"},
]

ACHIEVEMENTS: list[dict] = [
    {"code": "first_scenario", "name": "初次登场", "description": "完成第一个场景", "icon": "🎬", "condition_type": "scenarios", "condition_value": 1},
    {"code": "scenario_5", "name": "场景达人", "description": "完成 5 个场景", "icon": "🎭", "condition_type": "scenarios", "condition_value": 5},
    {"code": "scenario_20", "name": "生活体验家", "description": "完成 20 个场景", "icon": "🌍", "condition_type": "scenarios", "condition_value": 20},
    {"code": "streak_7", "name": "七日不断", "description": "连续学习 7 天", "icon": "🔥", "condition_type": "streak", "condition_value": 7},
    {"code": "streak_30", "name": "月度坚持", "description": "连续学习 30 天", "icon": "🏔️", "condition_type": "streak", "condition_value": 30},
    {"code": "words_50", "name": "词汇积累", "description": "词库积累 50 个单词", "icon": "📚", "condition_type": "words", "condition_value": 50},
    {"code": "words_200", "name": "词汇富翁", "description": "词库积累 200 个单词", "icon": "💎", "condition_type": "words", "condition_value": 200},
    {"code": "xp_1000", "name": "千分经验", "description": "累计获得 1000 XP", "icon": "⭐", "condition_type": "xp", "condition_value": 1000},
    {"code": "articles_10", "name": "阅读习惯", "description": "分析 10 篇文章", "icon": "📰", "condition_type": "articles", "condition_value": 10},
]

# 皮肤全部免费，任何用户都能直接切换，不再有解锁或金币门槛。
THEMES: list[dict] = [
    {"code": "ocean", "name": "Ocean", "colors": ["#2563eb", "#dbeafe"]},
    {"code": "sky", "name": "Sky", "colors": ["#0ea5e9", "#e0f2fe"]},
    {"code": "night", "name": "Night", "colors": ["#1e3a8a", "#c7d2fe"]},
    {"code": "coffee", "name": "Coffee", "colors": ["#0369a1", "#fef3c7"]},
    {"code": "forest", "name": "Forest", "colors": ["#0d9488", "#ccfbf1"]},
    {"code": "sakura", "name": "Sakura", "colors": ["#4f46e5", "#fce7f3"]},
]


def level_for_xp(xp: int) -> tuple[int, str]:
    current = LEVELS[0]
    for level, name, threshold in LEVELS:
        if xp >= threshold:
            current = (level, name, threshold)
        else:
            break
    return current[0], current[1]


def level_bounds(xp: int) -> tuple[int, int, int]:
    """返回 (当前等级起始 XP, 下一等级起始 XP, 当前等级)。"""
    level, _ = level_for_xp(xp)
    start = next(t for lv, _, t in LEVELS if lv == level)
    nxt = next((t for lv, _, t in LEVELS if lv == level + 1), None)
    if nxt is None:
        return start, start, level
    return start, nxt, level


def level_progress(xp: int) -> int:
    start, nxt, _ = level_bounds(xp)
    if nxt <= start:
        return 100
    return int((xp - start) / (nxt - start) * 100)


def xp_to_next(xp: int) -> int:
    _, nxt, _ = level_bounds(xp)
    return max(0, nxt - xp)
