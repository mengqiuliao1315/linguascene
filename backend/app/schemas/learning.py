from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ScenarioTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_key: str
    task_order: int
    description: str
    required: bool


class ScenarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    title: str
    title_zh: str
    description: str
    category: str
    icon: str
    level: str
    difficulty: int
    estimated_minutes: int
    ai_role: str
    opening_line: str
    goal: str
    key_phrases: list[str] = []
    key_vocabulary: list[str] = []
    tasks: list[ScenarioTaskOut] = []


class ScenarioTaskInput(BaseModel):

    description: str = Field(min_length=1, max_length=500)
    required: bool = True


class ScenarioCreate(BaseModel):

    slug: str = Field(default="", max_length=64)
    title: str = Field(min_length=1, max_length=128)
    title_zh: str = Field(default="", max_length=128)
    description: str = Field(default="", max_length=2000)
    category: str = Field(default="daily", max_length=32)
    icon: str = Field(default="💬", max_length=16)
    level: str = Field(default="A2", max_length=4)
    difficulty: int = Field(default=2, ge=1, le=5)
    estimated_minutes: int = Field(default=8, ge=1, le=120)
    ai_role: str = Field(default="Assistant", max_length=64)
    ai_role_prompt: str = Field(default="", max_length=4000)
    opening_line: str = Field(default="Hello!", max_length=1000)
    goal: str = Field(default="", max_length=2000)
    key_phrases: list[str] = []
    key_vocabulary: list[str] = []
    tasks: list[ScenarioTaskInput] = []
    is_published: bool = True


class ScenarioUpdate(BaseModel):

    slug: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=128)
    title_zh: str | None = Field(default=None, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    category: str | None = Field(default=None, max_length=32)
    icon: str | None = Field(default=None, max_length=16)
    level: str | None = Field(default=None, max_length=4)
    difficulty: int | None = Field(default=None, ge=1, le=5)
    estimated_minutes: int | None = Field(default=None, ge=1, le=120)
    ai_role: str | None = Field(default=None, max_length=64)
    ai_role_prompt: str | None = Field(default=None, max_length=4000)
    opening_line: str | None = Field(default=None, max_length=1000)
    goal: str | None = Field(default=None, max_length=2000)
    key_phrases: list[str] | None = None
    key_vocabulary: list[str] | None = None
    tasks: list[ScenarioTaskInput] | None = None
    is_published: bool | None = None


class ScenarioAdminOut(ScenarioOut):

    ai_role_prompt: str = ""
    is_published: bool = True


class CorrectionOut(BaseModel):
    original: str
    corrected: str
    explanation: str
    correction_type: str
    severity: int


class NaturalExpressionOut(BaseModel):
    expression: str
    meaning: str
    example: str = ""


class VocabularyItemOut(BaseModel):
    word: str
    meaning: str
    phonetic: str = ""
    example: str = ""
    is_new: bool = False


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    created_at: datetime
    feedback: dict | None = None


class ScenarioHintOut(BaseModel):
    task_key: str = ""
    task_description: str = ""
    idea_zh: str = ""
    suggested_zh: str = ""
    suggested_en: str = ""


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    mode: str
    scenario_id: int | None
    task_progress: int
    is_completed: bool
    xp_earned: int
    started_at: datetime
    finished_at: datetime | None = None
    scenario: ScenarioOut | None = None


class StartConversationRequest(BaseModel):
    scenario_id: int


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class CoachNoteOut(BaseModel):
    verdict: str = "good"
    message_zh: str = ""
    tip_en: str = ""


class ChatResponse(BaseModel):
    user_message: MessageOut
    ai_message: MessageOut
    correction: CorrectionOut | None = None
    natural_expression: NaturalExpressionOut | None = None
    new_vocabulary: list[VocabularyItemOut] = []
    hint: ScenarioHintOut | None = None
    coach_note: CoachNoteOut | None = None
    task_progress: int
    task_completed: bool
    completed_tasks: list[str] = []


class ScoreOut(BaseModel):
    grammar: int
    vocabulary: int
    naturalness: int
    communication: int


class ReportOut(BaseModel):
    conversation_id: int
    scenario_title: str
    summary: str
    task_progress: int
    scores: ScoreOut
    new_words: list[str] = []
    key_phrases: list[str] = []
    corrections_count: int
    xp_earned: int
    streak: int
