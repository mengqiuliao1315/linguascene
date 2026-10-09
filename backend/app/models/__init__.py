from app.models.ai_config import (
    AiProviderConfig,
    AiShare,
    AiShareAdoption,
    AiShareDismissal,
)
from app.models.content import (
    Article,
    ArticleAnalysis,
    ReadingHiddenSentence,
    ReadingNote,
    UserContent,
)
from app.models.gamification import Achievement, UserAchievement, XpRecord
from app.models.learning import (
    Conversation,
    Correction,
    Message,
    Phrase,
    Scenario,
    ScenarioTask,
    UserVocabulary,
    Vocabulary,
)
from app.models.social import (
    ChatMessage,
    CustomQuest,
    ForumComment,
    ForumLike,
    ForumPost,
    Friendship,
    QuestCheck,
)
from app.models.user import User
from app.models.wordbook import (
    ContributionRecord,
    DailyTask,
    WordAudio,
    WordQuizSession,
    Wordbook,
    WordStudyLog,
)

__all__ = [
    "User",
    "AiProviderConfig",
    "AiShare",
    "AiShareAdoption",
    "AiShareDismissal",
    "CustomQuest",
    "QuestCheck",
    "Friendship",
    "ChatMessage",
    "ForumPost",
    "ForumComment",
    "ForumLike",
    "Scenario",
    "ScenarioTask",
    "Conversation",
    "Message",
    "Correction",
    "Vocabulary",
    "UserVocabulary",
    "Phrase",
    "Article",
    "ArticleAnalysis",
    "UserContent",
    "ReadingNote",
    "ReadingHiddenSentence",
    "Achievement",
    "UserAchievement",
    "XpRecord",
    "WordStudyLog",
    "WordQuizSession",
]
