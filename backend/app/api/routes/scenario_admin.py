import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_admin_user
from app.core.database import get_db
from app.models.learning import Scenario, ScenarioTask
from app.models.user import User
from app.schemas.learning import (
    ScenarioAdminOut,
    ScenarioCreate,
    ScenarioUpdate,
)
from app.services import scenarios as scenario_service

router = APIRouter(prefix="/api/admin/scenarios", tags=["admin-scenarios"])


def _admin_payload(scenario: Scenario) -> dict:
    return {
        **scenario_service.scenario_payload(scenario),
        "ai_role_prompt": scenario.ai_role_prompt,
        "is_published": bool(scenario.is_published),
    }


def _unique_slug(db: Session, raw: str, title: str, *, exclude_id: int | None = None) -> str:
    base = scenario_service.slugify(raw or title)
    if not base:
        base = "scenario"
    candidate = base
    index = 2
    while True:
        query = select(Scenario).where(Scenario.slug == candidate)
        if exclude_id is not None:
            query = query.where(Scenario.id != exclude_id)
        if not db.execute(query).scalar_one_or_none():
            return candidate
        candidate = f"{base}-{index}"
        index += 1


def _sync_tasks(db: Session, scenario: Scenario, tasks) -> None:
    scenario.tasks.clear()
    db.flush()
    for order, task in enumerate(tasks, start=1):
        scenario.tasks.append(
            ScenarioTask(
                task_order=order,
                task_key=f"task_{order}",
                description=task.description.strip(),
                required=task.required,
            )
        )


@router.get("", response_model=list[ScenarioAdminOut])
def list_scenarios(
    db: Session = Depends(get_db),
    _admin: User = Depends(get_admin_user),
) -> list[ScenarioAdminOut]:
    """管理员视角：连未发布的场景一起返回。"""
    rows = db.execute(select(Scenario).order_by(Scenario.id)).scalars().all()
    return [ScenarioAdminOut.model_validate(_admin_payload(s)) for s in rows]


@router.post("", response_model=ScenarioAdminOut, status_code=status.HTTP_201_CREATED)
def create_scenario(
    payload: ScenarioCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_admin_user),
) -> ScenarioAdminOut:
    scenario = Scenario(
        slug=_unique_slug(db, payload.slug, payload.title),
        title=payload.title.strip(),
        title_zh=payload.title_zh.strip(),
        description=payload.description.strip(),
        category=payload.category.strip() or "daily",
        icon=payload.icon or "💬",
        level=payload.level.strip() or "A2",
        difficulty=payload.difficulty,
        estimated_minutes=payload.estimated_minutes,
        ai_role=payload.ai_role.strip() or "Assistant",
        ai_role_prompt=payload.ai_role_prompt,
        opening_line=payload.opening_line,
        goal=payload.goal,
        key_phrases=json.dumps(payload.key_phrases, ensure_ascii=False),
        key_vocabulary=json.dumps(payload.key_vocabulary, ensure_ascii=False),
        is_published=payload.is_published,
    )
    db.add(scenario)
    db.flush()
    _sync_tasks(db, scenario, payload.tasks)
    db.commit()
    db.refresh(scenario)
    return ScenarioAdminOut.model_validate(_admin_payload(scenario))


@router.patch("/{scenario_id}", response_model=ScenarioAdminOut)
def update_scenario(
    scenario_id: int,
    payload: ScenarioUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_admin_user),
) -> ScenarioAdminOut:
    scenario = db.get(Scenario, scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="场景不存在")

    data = payload.model_dump(exclude_unset=True)
    if "slug" in data and data["slug"]:
        scenario.slug = _unique_slug(
            db, data["slug"], scenario.title, exclude_id=scenario.id
        )
    if "tasks" in data and data["tasks"] is not None:
        _sync_tasks(db, scenario, payload.tasks or [])

    simple = (
        "title", "title_zh", "description", "category", "icon", "level",
        "difficulty", "estimated_minutes", "ai_role", "ai_role_prompt",
        "opening_line", "goal",
    )
    for field in simple:
        if field in data and data[field] is not None:
            setattr(scenario, field, data[field])
    if "key_phrases" in data and data["key_phrases"] is not None:
        scenario.key_phrases = json.dumps(data["key_phrases"], ensure_ascii=False)
    if "key_vocabulary" in data and data["key_vocabulary"] is not None:
        scenario.key_vocabulary = json.dumps(data["key_vocabulary"], ensure_ascii=False)
    if "is_published" in data and data["is_published"] is not None:
        scenario.is_published = data["is_published"]

    db.commit()
    db.refresh(scenario)
    return ScenarioAdminOut.model_validate(_admin_payload(scenario))


@router.delete("/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scenario(
    scenario_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(get_admin_user),
) -> None:
    scenario = db.get(Scenario, scenario_id)
    if not scenario:
        raise HTTPException(status_code=404, detail="场景不存在")
    db.delete(scenario)
    db.commit()
