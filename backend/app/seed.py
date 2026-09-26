import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal, engine
from app.core.schema_sync import apply_schema
from app.core.security import apply_password
from app.data.reading_content import build_sentences
from app.data.scenarios import SCENARIOS
from app.models.content import Article, ArticleAnalysis
from app.models.gamification import Achievement
from app.models.learning import Scenario, ScenarioTask, Vocabulary
from app.models.user import User
from app.services import levels, wordbook_seed
from app.services.reading_service import split_sentences

ARTICLES: list[dict] = [
    {
        "title": "AI Is Changing How Students Learn",
        "source": "LinguaScene Original",
        "url": "",
        "summary": "Adaptive tools are reshaping the classroom, but the biggest change may be how students practise on their own.",
        "category": "Technology",
        "level": "B1",
        "content": (
            "The rapid development of artificial intelligence has significantly changed "
            "the way students learn. Instead of working through the same exercises as "
            "everyone else, learners can now practise with tools that adapt to their level. "
            "These systems analyse mistakes and adjust the difficulty of the next task. "
            "As a result, students spend more time on the material they actually need. "
            "However, researchers warn that adaptive tools cannot replace conversation. "
            "Language learners still need to speak with real people to build confidence. "
            "The most effective approach combines personalised practice with live interaction."
        ),
    },
    {
        "title": "Why Remote Teams Still Struggle to Communicate",
        "source": "LinguaScene Original",
        "url": "",
        "summary": "Distributed teams have the tools, but habits and time zones remain the hard part.",
        "category": "Business",
        "level": "B2",
        "content": (
            "Remote work promised flexibility, yet many distributed teams still struggle "
            "to communicate effectively. The problem is rarely the software. It is the "
            "absence of informal conversation that used to happen between meetings. "
            "Teams that write clearly and document decisions tend to perform better. "
            "Managers play an important role in setting these norms. Without deliberate "
            "effort, information stays in private chats and new members are left behind."
        ),
    },
    {
        "title": "The Quiet Rise of Urban Gardening",
        "source": "LinguaScene Original",
        "url": "",
        "summary": "City residents are turning rooftops and balconies into small farms.",
        "category": "Lifestyle",
        "level": "B1",
        "content": (
            "Urban gardening has become increasingly popular in large cities. Residents "
            "grow vegetables on rooftops, balconies, and in shared community plots. "
            "Supporters say the practice improves mental health and reduces food costs. "
            "It also brings neighbours together. Critics point out that the impact on "
            "the environment is limited, but participants say the social benefits matter "
            "just as much as the harvest."
        ),
    },
    {
        "title": "What Makes a Habit Stick",
        "source": "LinguaScene Original",
        "url": "",
        "summary": "Research suggests that consistency matters more than intensity.",
        "category": "Science",
        "level": "B1",
        "content": (
            "People often try to change too much at once. Research on habit formation "
            "suggests that small, repeated actions are more likely to last. A short daily "
            "session is more effective than an intense weekly one. The key is to make the "
            "behaviour easy to start and hard to skip. Over time, the action becomes "
            "automatic and requires less effort to maintain."
        ),
    },
    {
        "title": "How Cities Are Rethinking Public Space",
        "source": "LinguaScene Original",
        "url": "",
        "summary": "From wider pavements to pocket parks, urban design is shifting toward people.",
        "category": "World",
        "level": "B2",
        "content": (
            "Cities around the world are rethinking how public space is used. Some have "
            "converted car lanes into bike paths and pedestrian zones. Others are creating "
            "small parks on unused land. Planners argue that these changes improve safety "
            "and support local businesses. The transition is not always smooth, and some "
            "residents worry about traffic and parking. Still, the direction of travel "
            "is clear: streets designed for people rather than cars."
        ),
    },
    {
        "title": "The Art of Asking Better Questions",
        "source": "LinguaScene Original",
        "url": "",
        "summary": "Good questions open doors; vague ones waste everyone's time.",
        "category": "Culture",
        "level": "B1",
        "content": (
            "Asking a good question is a skill that can be learned. Open questions invite "
            "explanation, while closed questions confirm facts. Skilled communicators pay "
            "attention to the order of their questions and listen carefully to the answers. "
            "In interviews and meetings, the quality of a question often reveals more than "
            "the answer itself. Practising this skill improves both conversation and "
            "critical thinking."
        ),
    },
]

VOCABULARY: list[dict] = [
    {"word": "significantly", "phonetic": "/sɪɡˈnɪfɪkəntli/", "part_of_speech": "adv.", "meaning": "显著地；明显地", "example": "The results have improved significantly.", "level": "B1"},
    {"word": "adaptive", "phonetic": "/əˈdæptɪv/", "part_of_speech": "adj.", "meaning": "适应性的", "example": "Adaptive tools adjust to each learner.", "level": "B2"},
    {"word": "personalized", "phonetic": "/ˈpɜːsənəlaɪzd/", "part_of_speech": "adj.", "meaning": "个性化的", "example": "The course offers personalized practice.", "level": "B2"},
    {"word": "reservation", "phonetic": "/ˌrezəˈveɪʃn/", "part_of_speech": "n.", "meaning": "预订", "example": "I have a reservation under Chen.", "level": "B1"},
    {"word": "luggage", "phonetic": "/ˈlʌɡɪdʒ/", "part_of_speech": "n.", "meaning": "行李", "example": "How many bags are you checking?", "level": "B1"},
    {"word": "proficient", "phonetic": "/prəˈfɪʃnt/", "part_of_speech": "adj.", "meaning": "熟练的", "example": "I'm proficient in Python.", "level": "B2"},
    {"word": "leverage", "phonetic": "/ˈliːvərɪdʒ/", "part_of_speech": "v.", "meaning": "利用", "example": "We leverage data to improve the product.", "level": "B2"},
    {"word": "sustainable", "phonetic": "/səˈsteɪnəbl/", "part_of_speech": "adj.", "meaning": "可持续的", "example": "The city adopted a sustainable transport plan.", "level": "B2"},
    {"word": "collaborate", "phonetic": "/kəˈlæbəreɪt/", "part_of_speech": "v.", "meaning": "协作", "example": "Teams collaborate across time zones.", "level": "B2"},
    {"word": "approach", "phonetic": "/əˈprəʊtʃ/", "part_of_speech": "n.", "meaning": "方法", "example": "The most effective approach combines practice and feedback.", "level": "B1"},
]


def seed() -> None:
    apply_schema(engine)
    db = SessionLocal()
    try:
        _seed_scenarios(db)
        _seed_articles(db)
        _seed_vocabulary(db)
        _seed_achievements(db)
        _seed_demo_user(db)
        db.commit()
    finally:
        db.close()

    wordbook_result = wordbook_seed.seed_wordbooks()
    print("词书导入：", wordbook_result)
    print("种子数据写入完成。")

def _seed_scenarios(db) -> None:
    for item in SCENARIOS:
        scenario = db.execute(
            select(Scenario).where(Scenario.slug == item["slug"])
        ).scalar_one_or_none()

        if scenario is None:
            scenario = Scenario(slug=item["slug"])
            db.add(scenario)

        scenario.title = item["title"]
        scenario.title_zh = item["title_zh"]
        scenario.description = item["description"]
        scenario.category = item["category"]
        scenario.icon = item["icon"]
        scenario.level = item["level"]
        scenario.difficulty = item["difficulty"]
        scenario.estimated_minutes = item["estimated_minutes"]
        scenario.ai_role = item["ai_role"]
        scenario.ai_role_prompt = item["ai_role_prompt"]
        scenario.opening_line = item["opening_line"]
        scenario.goal = item["goal"]
        scenario.key_phrases = json.dumps(item["key_phrases"], ensure_ascii=False)
        scenario.key_vocabulary = json.dumps(item["key_vocabulary"], ensure_ascii=False)
        db.flush()

        _sync_tasks(db, scenario, item["tasks"])


def _sync_tasks(db, scenario: Scenario, tasks: list[tuple]) -> None:
    existing = {t.task_key: t for t in scenario.tasks}
    wanted = {key for key, _, _ in tasks}

    for task in scenario.tasks:
        if task.task_key not in wanted:
            db.delete(task)

    for key, description, order in tasks:
        task = existing.get(key)
        if task is None:
            db.add(
                ScenarioTask(
                    scenario_id=scenario.id,
                    task_key=key,
                    task_order=order,
                    description=description,
                    required=True,
                )
            )
            continue
        task.task_order = order
        task.description = description
        task.required = True


def _seed_articles(db) -> None:
    now = datetime.now(timezone.utc)
    for index, item in enumerate(ARTICLES):
        existing = db.execute(
            select(Article).where(Article.title == item["title"])
        ).scalar_one_or_none()
        if existing:
            article = existing
            article.content = item["content"]
            article.level = item["level"]
            article.category = item["category"]
            article.summary = item["summary"]
            words = len(item["content"].split())
            article.word_count = words
            article.read_minutes = max(1, round(words / 200))
        else:
            words = len(item["content"].split())
            article = Article(
                title=item["title"],
                source=item["source"],
                url=item["url"],
                summary=item["summary"],
                content=item["content"],
                level=item["level"],
                category=item["category"],
                word_count=words,
                read_minutes=max(1, round(words / 200)),
                published_at=now - timedelta(days=index),
                is_builtin=1,
            )
            db.add(article)
        db.flush()
        _seed_article_analysis(db, article)

    db.flush()


_BUILTIN_READING_QUESTIONS = [
    "What is the main idea of this text?",
    "Which detail best supports the main idea?",
    "What is the author's attitude toward the topic?",
]


def _seed_article_analysis(db, article: Article) -> None:
    segments = split_sentences(article.content)
    sentences = build_sentences(article.title, segments)
    if not sentences:
        return

    if article.analysis is None:
        article.analysis = ArticleAnalysis(
            article_id=article.id,
            level=article.level,
            summary=article.summary,
            questions_json=json.dumps(
                _BUILTIN_READING_QUESTIONS, ensure_ascii=False
            ),
        )
        db.add(article.analysis)
        db.flush()
    elif not json.loads(article.analysis.questions_json or "[]"):
        article.analysis.questions_json = json.dumps(
            _BUILTIN_READING_QUESTIONS, ensure_ascii=False
        )
    article.analysis.sentences_json = json.dumps(sentences, ensure_ascii=False)


def _seed_vocabulary(db) -> None:
    for item in VOCABULARY:
        existing = db.execute(
            select(Vocabulary).where(Vocabulary.word == item["word"])
        ).scalar_one_or_none()
        if existing:
            continue
        db.add(Vocabulary(**item))


def _seed_achievements(db) -> None:
    for item in levels.ACHIEVEMENTS:
        existing = db.execute(
            select(Achievement).where(Achievement.code == item["code"])
        ).scalar_one_or_none()
        if existing:
            continue
        db.add(Achievement(**item))


def _seed_demo_user(db) -> None:
    email = settings.admin_email
    existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing:
        return

    user = User(
        username=settings.admin_username,
        email=email,
        role="ADMIN",
        cefr_level="B1",
        interests="Travel,Workplace,Technology",
    )
    apply_password(user, settings.admin_password)
    db.add(user)


if __name__ == "__main__":
    seed()
