"""AI 模型配置解析。

每个用户可以添加多个供应商（AiProviderConfig），每个供应商各含多个模型；
也可以采纳别的用户分享出来的供应商（AiShare）。实际用哪个模型，按下面决定：
1. 用户当前选中的那条（自己的供应商 ai_active_config_id，或采纳的分享 ai_active_share_id）
2. 没选过时：自己的第一条 → 采纳的分享 → 站点环境变量兜底（或离线规则引擎）

全站没有"平台免费模型"这种东西，所有可用模型都来自某个用户的配置或分享。
每条配置都带 api_format，决定请求发到哪个端点、响应怎么解析，
因此 OpenAI / Anthropic / Gemini 及各类兼容服务都能接。
前端拿到的是"有哪些可选、当前实际用哪个"，凭据本身永不回传。
"""

import json
import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.provider import (
    API_FORMATS,
    DEFAULT_API_FORMAT,
    AIProvider,
    AIProviderError,
    HttpAIProvider,
    assert_public_http_url,
    chat_first_models,
    get_provider,
    list_models,
    normalize_base_url,
)
from app.core.crypto import decrypt_secret, encrypt_secret, secret_fingerprint
from app.models.ai_config import (
    AiProviderConfig,
    AiShare,
    AiShareAdoption,
    AiShareDismissal,
)
from app.models.user import User

# 实际生效来源标签
SOURCE_OWN = "user"
SOURCE_SHARE = "share"

logger = logging.getLogger(__name__)


def safe_format(value: str | None) -> str:
    """老数据可能没有 api_format，统一回落成 openai。"""
    return value if value in API_FORMATS else DEFAULT_API_FORMAT


def load_models(raw: str | None) -> list[str]:
    """把库里的模型列表（JSON 字符串）解析成 list，坏数据一律当空。"""
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    return [str(m) for m in value if str(m).strip()]


def dump_models(models: list[str]) -> str:
    """去重、去空白后存成 JSON 字符串。"""
    seen: list[str] = []
    for model in models:
        name = str(model).strip()
        if name and name not in seen:
            seen.append(name)
    return json.dumps(seen, ensure_ascii=False)


def _pick_active(model: str, models: list[str]) -> str:
    """保证 active_model 落在 models 里：优先原值，其次第一个，最后空。"""
    if model and model in models:
        return model
    return models[0] if models else ""


# --------------------------------------------------------------- 用户自己的供应商


def list_configs(db: Session, user: User) -> list[AiProviderConfig]:
    return list(
        db.execute(
            select(AiProviderConfig)
            .where(AiProviderConfig.user_id == user.id)
            .order_by(AiProviderConfig.created_at.asc(), AiProviderConfig.id.asc())
        ).scalars()
    )


def get_config(db: Session, user: User, config_id: int) -> AiProviderConfig | None:
    return db.execute(
        select(AiProviderConfig).where(
            AiProviderConfig.id == config_id,
            AiProviderConfig.user_id == user.id,
        )
    ).scalar_one_or_none()


def create_config(
    db: Session,
    user: User,
    *,
    name: str,
    base_url: str,
    api_key: str,
    api_format: str = DEFAULT_API_FORMAT,
    models: list[str],
    active_model: str = "",
) -> AiProviderConfig:
    config = AiProviderConfig(
        user_id=user.id,
        name=name.strip(),
        base_url=base_url.rstrip("/"),
        api_key_encrypted=encrypt_secret(api_key),
        api_format=safe_format(api_format),
        models=dump_models(models),
        active_model=_pick_active(active_model, models),
    )
    db.add(config)
    db.flush()
    return config


def update_config(
    db: Session,
    config: AiProviderConfig,
    *,
    name: str,
    base_url: str,
    api_key: str,
    api_format: str,
    models: list[str],
    active_model: str,
) -> AiProviderConfig:
    """api_key 传空字符串表示保留原 Key 不变。"""
    config.name = name.strip()
    config.base_url = base_url.rstrip("/")
    config.api_format = safe_format(api_format)
    config.models = dump_models(models)
    config.active_model = _pick_active(active_model, models)
    if api_key:
        config.api_key_encrypted = encrypt_secret(api_key)
    db.flush()
    return config


def delete_config(db: Session, config: AiProviderConfig) -> None:
    db.delete(config)
    db.flush()


def config_provider(config: AiProviderConfig | None) -> HttpAIProvider | None:
    if config is None:
        return None
    api_key = decrypt_secret(config.api_key_encrypted)
    model = config.active_model
    if not api_key or not config.base_url or not model:
        return None
    try:
        return HttpAIProvider(
            base_url=config.base_url,
            api_key=api_key,
            model=model,
            api_format=safe_format(config.api_format),
            # name 里带上配置 id，保证不同供应商的缓存互不串用
            name=f"config:{config.id}",
            label=config.name or model,
        )
    except AIProviderError as exc:
        # 地址填坏（缺域名、有空格、方括号没配对…）只让这一条不可用：
        # 直接抛出去会让这条配置把全站 AI 请求都变成 500，而不是回落到下一条
        # 或站点兜底——一条坏配置不该拖垮整个链路。
        logger.warning("供应商配置 %s 不可用（%s）：%s", config.id, config.base_url, exc)
        return None


def build_provider(
    *,
    base_url: str,
    api_key: str,
    model: str,
    api_format: str = DEFAULT_API_FORMAT,
    label: str = "",
) -> HttpAIProvider:
    """用一组明文凭据临时构造 provider，供"测试连接"使用。"""
    return HttpAIProvider(
        base_url=base_url,
        api_key=api_key,
        model=model,
        api_format=safe_format(api_format),
        name="test",
        label=label,
    )


def decrypt_config_key(config: AiProviderConfig) -> str | None:
    return decrypt_secret(config.api_key_encrypted)


def validate_base_url(base_url: str, api_format: str = DEFAULT_API_FORMAT) -> None:
    """保存前先把地址归一化一遍，坏地址当场报错。

    以前坏地址能存进库，表现是「配置看着好好的，但 AI 永远不工作」——
    错误要等到真正调用时才以 500 的形式冒出来。这里提前拦，
    消息里直接写清缺域名 / 有空格 / 格式不对。
    """
    try:
        normalized = normalize_base_url(base_url, safe_format(api_format))
        assert_public_http_url(normalized, resolve=False)
    except AIProviderError as exc:
        raise ValueError(str(exc)) from exc


def list_provider_models(
    *, base_url: str, api_key: str, api_format: str = DEFAULT_API_FORMAT
) -> list[str]:
    """代理到 provider 的模型列表接口，把异常统一成 AIProviderError 文案。

    对话模型排前面：服务商的原始顺序多是字母序，向量/重排/语音模型挤在最前面，
    而用户拉这个列表就是为了挑一个能聊天的模型。
    """
    return chat_first_models(
        list_models(
            base_url=base_url, api_key=api_key, api_format=safe_format(api_format)
        )
    )


# ----------------------------------------------------- 别人的分享（采纳后可用）


def _share_owner(db: Session, owner_id: int) -> User | None:
    return db.get(User, owner_id)


def share_provider(db: Session, share: AiShare | None) -> HttpAIProvider | None:
    """把一条分享变成可调用的 provider。需分享仍在启用状态。"""
    if share is None or not share.is_active:
        return None
    api_key = decrypt_secret(share.api_key_encrypted)
    model = share.active_model
    if not api_key or not share.base_url or not model:
        return None
    owner = _share_owner(db, share.owner_id)
    owner_name = owner.username if owner else "匿名用户"
    label = share.title or f"{owner_name} 分享的 {model}"
    try:
        return HttpAIProvider(
            base_url=share.base_url,
            api_key=api_key,
            model=model,
            api_format=safe_format(share.api_format),
            # name 里带上 share id，保证不同分享的缓存互不串用
            name=f"share:{share.id}",
            label=label,
        )
    except AIProviderError as exc:
        # 同 config_provider：分享者的地址填坏了，只让这条分享不可用
        logger.warning("分享 %s 不可用（%s）：%s", share.id, share.base_url, exc)
        return None


def get_adoption(db: Session, user: User) -> AiShareAdoption | None:
    return db.execute(
        select(AiShareAdoption).where(AiShareAdoption.user_id == user.id)
    ).scalar_one_or_none()


def adopted_share(db: Session, user: User) -> AiShare | None:
    """我当前采纳的分享，无论是否还有效（无效时用于提示"已失效"）。"""
    adoption = get_adoption(db, user)
    if adoption is None:
        return None
    return db.get(AiShare, adoption.share_id)


# --------------------------------------------------------------- 解析实际 provider


@dataclass
class ResolvedProvider:
    provider: AIProvider
    source: str  # user | share | env | mock


def resolve_provider(db: Session, user: User | None) -> ResolvedProvider:
    """选出实际 provider：当前选中 → 自己的第一条 → 采纳的分享 → 兜底。"""
    if user is not None:
        # 1. 明确选中的分享（有效才用）
        if user.ai_active_share_id:
            share = db.get(AiShare, user.ai_active_share_id)
            provider = share_provider(db, share)
            if provider is not None:
                return ResolvedProvider(provider=provider, source=SOURCE_SHARE)

        # 2. 明确选中的自己的供应商
        if user.ai_active_config_id:
            config = get_config(db, user, user.ai_active_config_id)
            provider = config_provider(config)
            if provider is not None:
                return ResolvedProvider(provider=provider, source=SOURCE_OWN)

        # 3. 没选过：自己的第一条
        for config in list_configs(db, user):
            provider = config_provider(config)
            if provider is not None:
                return ResolvedProvider(provider=provider, source=SOURCE_OWN)

        # 4. 再看采纳的分享（比如选中的配置被删了）
        adopted = adopted_share(db, user)
        provider = share_provider(db, adopted)
        if provider is not None:
            return ResolvedProvider(provider=provider, source=SOURCE_SHARE)

    fallback = get_provider()
    return ResolvedProvider(
        provider=fallback, source="mock" if fallback.is_mock else "env"
    )


def get_provider_for(db: Session, user: User | None) -> AIProvider:
    return resolve_provider(db, user).provider


# --------------------------------------------------------------- 状态序列化


def _config_out(config: AiProviderConfig, active: bool) -> dict:
    return {
        "id": config.id,
        "name": config.name or config.active_model,
        "base_url": config.base_url,
        "api_format": safe_format(config.api_format),
        "models": load_models(config.models),
        "active_model": config.active_model,
        "key_hint": f"••••{secret_fingerprint(config.api_key_encrypted)[-4:]}",
        "is_active": active,
        "updated_at": config.updated_at,
    }


# --------------------------------------------------------------- 分享的增删改查


def _owner_name(db: Session, owner_id: int) -> str:
    owner = _share_owner(db, owner_id)
    return owner.username if owner else "已注销用户"


def share_out(db: Session, share: AiShare, viewer: User, adoption_count: int = 0) -> dict:
    return {
        "id": share.id,
        "owner_id": share.owner_id,
        "owner_name": _owner_name(db, share.owner_id),
        "title": share.title or share.active_model,
        "base_url": share.base_url,
        "api_format": safe_format(share.api_format),
        "models": load_models(share.models),
        "active_model": share.active_model,
        "note": share.note,
        "is_active": bool(share.is_active),
        "is_mine": share.owner_id == viewer.id,
        "adoption_count": adoption_count,
        "key_hint": f"••••{secret_fingerprint(share.api_key_encrypted)[-4:]}",
        "created_at": share.created_at,
        "updated_at": share.updated_at,
    }


def adoption_counts(db: Session, share_ids: list[int]) -> dict[int, int]:
    if not share_ids:
        return {}
    rows = db.execute(
        select(AiShareAdoption.share_id, func.count(AiShareAdoption.id))
        .where(AiShareAdoption.share_id.in_(share_ids))
        .group_by(AiShareAdoption.share_id)
    ).all()
    return {share_id: count for share_id, count in rows}


def create_share(
    db: Session,
    user: User,
    *,
    title: str,
    base_url: str,
    api_key: str,
    api_format: str = DEFAULT_API_FORMAT,
    models: list[str],
    active_model: str = "",
    note: str = "",
) -> AiShare:
    """分享一份供应商配置。api_key 留空则复用该供应商已保存的那把。"""
    if not api_key:
        raise ValueError("没有可分享的 API Key")

    share = AiShare(
        owner_id=user.id,
        title=title.strip() or active_model or "分享的模型",
        base_url=base_url.rstrip("/"),
        api_key_encrypted=encrypt_secret(api_key),
        api_format=safe_format(api_format),
        models=dump_models(models),
        active_model=_pick_active(active_model, models),
        note=note.strip(),
        is_active=True,
    )
    db.add(share)
    db.flush()
    return share


def get_share(db: Session, share_id: int) -> AiShare | None:
    return db.get(AiShare, share_id)


def set_share_active(db: Session, share: AiShare, is_active: bool) -> AiShare:
    share.is_active = is_active
    db.flush()
    return share


def delete_share(db: Session, share: AiShare) -> None:
    """删除分享：采纳记录与关闭记录由外键级联清掉，其他人立即看不到。"""
    db.delete(share)
    db.flush()


def my_shares(db: Session, user: User) -> list[AiShare]:
    return list(
        db.execute(
            select(AiShare)
            .where(AiShare.owner_id == user.id)
            .order_by(AiShare.created_at.desc())
        ).scalars()
    )


def available_shares(db: Session, user: User) -> list[AiShare]:
    """别人正在分享、且我尚未关闭其弹窗的可用分享。自己的分享不算在内。"""
    dismissed = select(AiShareDismissal.share_id).where(
        AiShareDismissal.user_id == user.id
    )
    return list(
        db.execute(
            select(AiShare)
            .where(
                AiShare.is_active.is_(True),
                AiShare.owner_id != user.id,
                AiShare.id.not_in(dismissed),
            )
            .order_by(AiShare.updated_at.desc())
        ).scalars()
    )


def my_shares_out(db: Session, user: User) -> list[dict]:
    shares = my_shares(db, user)
    counts = adoption_counts(db, [s.id for s in shares])
    return [share_out(db, s, user, counts.get(s.id, 0)) for s in shares]


def available_shares_out(db: Session, user: User) -> list[dict]:
    shares = available_shares(db, user)
    counts = adoption_counts(db, [s.id for s in shares])
    return [share_out(db, s, user, counts.get(s.id, 0)) for s in shares]


def adopt_share(db: Session, user: User, share: AiShare) -> None:
    """采纳一条分享，并把当前选择切到它。一人只保留一条采纳记录。"""
    if not share.is_active:
        raise ValueError("这条分享已停止分享")
    if share.owner_id == user.id:
        raise ValueError("不能采纳自己分享的模型")

    adoption = get_adoption(db, user)
    if adoption is None:
        adoption = AiShareAdoption(user_id=user.id, share_id=share.id)
        db.add(adoption)
    else:
        adoption.share_id = share.id
    user.ai_active_share_id = share.id
    user.ai_active_config_id = None
    db.flush()


def dismiss_share(db: Session, user: User, share: AiShare) -> None:
    """关掉某条分享的登录弹窗，之后不再推送给这个人。"""
    exists = db.execute(
        select(AiShareDismissal).where(
            AiShareDismissal.user_id == user.id,
            AiShareDismissal.share_id == share.id,
        )
    ).scalar_one_or_none()
    if exists is None:
        db.add(AiShareDismissal(user_id=user.id, share_id=share.id))
        db.flush()


def set_active_config(db: Session, user: User, config: AiProviderConfig) -> None:
    """把当前使用的模型切到自己的某条供应商配置。"""
    user.ai_active_config_id = config.id
    user.ai_active_share_id = None
    db.flush()


def share_prompt(db: Session, user: User) -> dict:
    """登录后弹窗内容。

    只在"还没有自己的供应商、也没采纳过别人的分享"时才推，避免打扰
    已经配置好的人。关闭过的分享不再弹。
    """
    if list_configs(db, user):
        return {"available": False, "share": None, "reason": "已有自己的模型"}
    if get_adoption(db, user) is not None:
        return {"available": False, "share": None, "reason": "已采纳分享"}

    candidates = [
        s
        for s in available_shares(db, user)
        if s.is_active and s.owner_id != user.id
    ]
    if not candidates:
        return {"available": False, "share": None, "reason": "暂无可用分享"}

    share = candidates[0]
    return {
        "available": True,
        "share": share_out(db, share, user, 0),
        "reason": "",
    }


def user_ai_status(db: Session, user: User) -> dict:
    """给用户看的设置页状态：自己的供应商 + 可用分享 + 当前生效来源。"""
    configs = list_configs(db, user)
    adopted = adopted_share(db, user)
    adopted_out = None
    if adopted is not None:
        counts = adoption_counts(db, [adopted.id])
        adopted_out = share_out(db, adopted, user, counts.get(adopted.id, 0))

    resolved = resolve_provider(db, user)
    # 哪条自己的配置在生效：resolved 的 label 带不出 id，这里按选中/回落实算一次
    active_config_id: int | None = None
    if resolved.source == SOURCE_OWN:
        chosen = get_config(db, user, user.ai_active_config_id) if user.ai_active_config_id else None
        if chosen is None or config_provider(chosen) is None:
            chosen = next((c for c in configs if config_provider(c) is not None), None)
        active_config_id = chosen.id if chosen is not None else None

    return {
        "configs": [_config_out(c, c.id == active_config_id) for c in configs],
        "active_source": resolved.source,
        "active_label": resolved.provider.label,
        "active_config_id": active_config_id,
        "active_share_id": user.ai_active_share_id if resolved.source == SOURCE_SHARE else None,
        # 自己的分享也带出来（前端要管理）；available 列表只含别人的
        "shares": my_shares_out(db, user) + available_shares_out(db, user),
        "adopted_share": adopted_out,
    }
