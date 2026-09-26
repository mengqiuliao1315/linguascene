"""场景序列化与 slug 生成，供普通路由与管理员路由共用。"""

import hashlib
import json
import re

from app.models.learning import Scenario


def scenario_payload(scenario: Scenario) -> dict:
    """把 ORM 对象转成前端要的形状（JSON 字段解包、任务排序）。"""
    return {
        "id": scenario.id,
        "slug": scenario.slug,
        "title": scenario.title,
        "title_zh": scenario.title_zh,
        "description": scenario.description,
        "category": scenario.category,
        "icon": scenario.icon,
        "level": scenario.level,
        "difficulty": scenario.difficulty,
        "estimated_minutes": scenario.estimated_minutes,
        "ai_role": scenario.ai_role,
        "opening_line": scenario.opening_line,
        "goal": scenario.goal,
        "key_phrases": json.loads(scenario.key_phrases or "[]"),
        "key_vocabulary": json.loads(scenario.key_vocabulary or "[]"),
        "tasks": [
            {
                "id": t.id,
                "task_key": t.task_key,
                "task_order": t.task_order,
                "description": t.description,
                "required": t.required,
            }
            for t in scenario.tasks
        ],
    }


def slugify(raw: str) -> str:
    """把标题压成 URL 友好的 slug。

    保留字母数字与连字符；中文标题转不出可用字符时，退回标题哈希，
    保证同一标题稳定生成同一个 slug（冲突再由调用方加序号）。
    """
    text = (raw or "").strip().lower()
    ascii_part = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if ascii_part:
        return ascii_part[:64]
    if not text:
        return ""
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"scenario-{digest}"
