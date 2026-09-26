"""萌宠服务：形象、心情、连续陪伴，以及每天一次的喂食。

心情有两层。陪伴天数来自 users.last_login_date，只有 POST /api/pet/visit
（以及喂食顺手记的到访）会推进它。GET 只投影「今天已经来过」的样子，不落库，
避免严格模式连打两次把「见面前」的心情冲掉。

喂食是另一层，压在陪伴心情上面：pet_last_fed 不是今天，mood 就是 hungry，
不管陪伴天数多高。同一天再喂是空操作，连续天数不涨。日期跟陪伴天数一样用
UTC 的日历日，两套「今天」不会错开。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.user import User

# 可选形象；前端 lib/pet.ts 的 PET_SPECIES 需要与此保持一致
PET_SPECIES: tuple[str, ...] = ("hedgehog",)
DEFAULT_SPECIES = "hedgehog"
MAX_NAME_LENGTH = 12

# 连续陪伴天数决定开心程度（今天喂过之后才用得上）
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


def fed_today(user: User) -> bool:
    return user.pet_last_fed == _day()


def record_feed(db: Session, user: User) -> bool:
    """今天第一次喂返回 True；已经喂过返回 False，连续天数不动。

    昨天喂过则连续 +1，中间断了从 1 重新计。不抛错：多点一次按钮
    只是没东西可喂，不算失败。
    """
    today = _day()
    if user.pet_last_fed == today:
        return False

    if user.pet_last_fed == _day(-1):
        user.pet_feed_streak = (user.pet_feed_streak or 0) + 1
    else:
        user.pet_feed_streak = 1

    user.pet_last_fed = today
    db.flush()
    return True


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

    # 中间断了：先难过，见到你回来立刻换表情
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
    今天还没喂时，陪伴心情让位给 hungry——喂过才露出开心的那一档。
    previous_mood 是它见到你之前的表情，供前端播过渡动画。
    """
    state = previous if previous is not None else {"previous_mood": None, "days_away": 0}
    streak = projected_streak(user)
    fed = fed_today(user)
    return {
        "species": normalize_species(user.pet_species),
        "name": user.pet_name or "",
        "mood": mood_for(streak) if fed else "hungry",
        "previous_mood": state["previous_mood"],
        "days_away": state["days_away"],
        "login_streak": streak,
        "best_login_streak": max(user.best_login_streak, streak),
        "study_streak": user.streak,
        "last_login_date": user.last_login_date,
        "fed_today": fed,
        "feed_streak": user.pet_feed_streak or 0,
        "last_fed_date": user.pet_last_fed,
    }
