"""萌宠服务：形象、心情与连续陪伴天数。

心情的唯一数据来源是 users.last_login_date，而且只有 /api/pet 会推进它。
这样「打开首页」这一个动作能同时完成两件事：读到见面之前的心情快照、
再记录今天来过——前端据此播一段「旧心情 -> 新心情」的过渡动画。

形象只剩一个：刺猬「墩墩」。早期版本的犬种（萨摩耶 / 柴犬 / 边牧）和喂食
功能都已下线，normalize_species 会把库里残留的旧值统一归到刺猬。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.user import User

# 可选形象；前端 lib/pet.ts 的 PET_SPECIES 需要与此保持一致
PET_SPECIES: tuple[str, ...] = ("hedgehog",)
DEFAULT_SPECIES = "hedgehog"
MAX_NAME_LENGTH = 12

# 连续陪伴天数决定开心程度
DELIGHTED_DAYS = 2
EXCITED_DAYS = 7


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _day(offset: int = 0) -> str:
    return (_now() + timedelta(days=offset)).strftime("%Y-%m-%d")


def _days_between(start: str, end: str) -> int:
    try:
        first = datetime.strptime(start, "%Y-%m-%d").date()
        second = datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError:
        return 0
    return max((second - first).days, 0)


def normalize_species(value: str | None) -> str:
    """未知形象一律回落到默认，避免前端传坏值后画不出来。

    旧版本的 samoyed / shiba / border_collie 已经下线，
    历史用户的 pet_species 会在这里自动归到刺猬。
    """
    return value if value in PET_SPECIES else DEFAULT_SPECIES


def record_visit(db: Session, user: User) -> None:
    """记录今天来看过宠物；跨天连续则 +1，中断则重置为 1。

    幂等：同一天重复调用不会累加，所以前端即便因严格模式重复请求也安全。
    """
    today = _day()
    if user.last_login_date == today:
        return

    if user.last_login_date == _day(-1):
        user.login_streak += 1
    else:
        user.login_streak = 1

    user.last_login_date = today
    user.best_login_streak = max(user.best_login_streak, user.login_streak)
    db.flush()


def mood_for(streak: int) -> str:
    if streak >= EXCITED_DAYS:
        return "excited"
    if streak >= DELIGHTED_DAYS:
        return "delighted"
    return "happy"


def snapshot(user: User) -> dict:
    """见面前的「旧心情」：还没记录今天到访时它是什么状态。

    只读，不修改 user——这样 GET /api/pet 可以安全地被重复请求
    （React 严格模式下 effect 会跑两次），不会把难过的状态覆盖掉。
    """
    today = _day()
    previous = user.last_login_date

    if not previous or previous == today:
        return {"previous_mood": None, "days_away": 0}

    away = _days_between(previous, today)
    if away <= 1:
        # 昨天刚见过，只是今天还没来：期待里带一点小委屈
        return {"previous_mood": "waiting", "days_away": 0}

    # 中间断了：先难过，见到你回来立刻开心
    return {"previous_mood": "sad", "days_away": max(away - 1, 1)}


def projected_streak(user: User) -> int:
    """今天记录到访之后，连续陪伴天数会变成多少。

    GET 不能改库，但界面需要立刻显示「见到你之后」的样子，
    所以这里按 record_visit 同样的规则把结果算出来。
    """
    today = _day()
    if user.last_login_date == today:
        return user.login_streak
    if user.last_login_date == _day(-1):
        return user.login_streak + 1
    return 1


def payload(user: User, previous: dict | None = None) -> dict:
    """对外状态。

    mood / login_streak 用「记录今天到访之后」的值：GET 是只读的，
    但打开首页就等于来过，界面要直接呈现它见到你之后的样子。
    previous_mood 是它见到你之前的表情，供前端播过渡动画。
    """
    state = previous if previous is not None else {"previous_mood": None, "days_away": 0}
    streak = projected_streak(user)
    return {
        "species": normalize_species(user.pet_species),
        "name": user.pet_name or "",
        "mood": mood_for(streak),
        "previous_mood": state["previous_mood"],
        "days_away": state["days_away"],
        "login_streak": streak,
        "best_login_streak": max(user.best_login_streak, streak),
        "study_streak": user.streak,
        "last_login_date": user.last_login_date,
    }
