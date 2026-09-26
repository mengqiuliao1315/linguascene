import hashlib
import json
import re

from app.models.learning import Scenario


def scenario_payload(scenario: Scenario) -> dict:
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
    text = (raw or "").strip().lower()
    ascii_part = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if ascii_part:
        return ascii_part[:64]
    if not text:
        return ""
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"scenario-{digest}"
