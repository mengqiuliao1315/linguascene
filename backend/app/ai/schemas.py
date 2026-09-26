from pydantic import BaseModel, Field


class CorrectionOut(BaseModel):
    has_error: bool = False
    original: str = ""
    corrected: str = ""
    explanation: str = ""
    correction_type: str = "grammar"
    severity: int = Field(default=0, ge=0, le=3)


class NaturalExpressionOut(BaseModel):
    expression: str = ""
    meaning: str = ""
    example: str = ""


class VocabularyItemOut(BaseModel):
    word: str
    meaning: str = ""
    phonetic: str = ""
    part_of_speech: str = ""
    example: str = ""


class ScenarioHint(BaseModel):

    task_key: str = ""
    task_description: str = ""
    idea_zh: str = ""
    suggested_zh: str = ""
    suggested_en: str = ""


class CoachNote(BaseModel):

    verdict: str = "good"
    message_zh: str = ""
    tip_en: str = ""


class ScenarioReply(BaseModel):
    reply: str
    correction: CorrectionOut | None = None
    natural_expression: NaturalExpressionOut | None = None
    new_vocabulary: list[VocabularyItemOut] = Field(default_factory=list)
    hint: ScenarioHint | None = None
    coach_note: CoachNote | None = None
    completed_task_keys: list[str] = Field(default_factory=list)
    task_progress: int = Field(default=0, ge=0, le=100)
    task_completed: bool = False


class ScenarioFeedback(BaseModel):

    correction: CorrectionOut | None = None
    natural_expression: NaturalExpressionOut | None = None
    new_vocabulary: list[VocabularyItemOut] = Field(default_factory=list)
    hint: ScenarioHint | None = None
    coach_note: CoachNote | None = None
    completed_task_keys: list[str] = Field(default_factory=list)


class TranslationOut(BaseModel):

    translation: str = ""


class WordExplanation(BaseModel):
    word: str
    pronunciation: str = ""
    part_of_speech: str = ""
    core_meanings: list[str] = Field(default_factory=list)
    meaning_in_context: str = ""
    collocations: list[str] = Field(default_factory=list)
    example_sentences: list[str] = Field(default_factory=list)
    related_words: list[str] = Field(default_factory=list)
    cefr_level: str = "B1"


class PhraseItem(BaseModel):
    phrase: str
    meaning: str = ""
    example: str = ""


class WordPhraseAnalysis(BaseModel):

    kind: str = "word"
    text: str = ""
    lemma: str = ""
    meaning: str = ""
    part_of_speech: str = ""
    note: str = ""
    example: str = ""


class SuggestedSpan(BaseModel):

    text: str = ""
    color: str = "blue"
    reason: str = ""


class AnnotationSuggestions(BaseModel):
    spans: list[SuggestedSpan] = Field(default_factory=list)


class GrammarPoint(BaseModel):
    point: str
    explanation: str = ""
    example: str = ""


class SentenceAnalysis(BaseModel):
    sentence: str
    chinese_meaning: str = ""
    main_clause: str = ""
    structure: str = ""
    vocabulary: list[VocabularyItemOut] = Field(default_factory=list)
    collocations: list[PhraseItem] = Field(default_factory=list)
    grammar_points: list[GrammarPoint] = Field(default_factory=list)
    natural_alternative: str = ""
    cefr_level: str = "B1"


class SentenceBatch(BaseModel):

    sentences: list[SentenceAnalysis] = Field(default_factory=list)


class ArticleAnalysisOut(BaseModel):
    summary: str = ""
    level: str = "B1"
    keywords: list[VocabularyItemOut] = Field(default_factory=list)
    phrases: list[PhraseItem] = Field(default_factory=list)
    grammar_points: list[GrammarPoint] = Field(default_factory=list)
    reading_questions: list[str] = Field(default_factory=list)
    speaking_questions: list[str] = Field(default_factory=list)
    writing_task: str = ""


class ConversationReport(BaseModel):
    summary: str = ""
    task_progress: int = Field(default=0, ge=0, le=100)
    grammar_score: int = Field(default=3, ge=1, le=5)
    vocabulary_score: int = Field(default=3, ge=1, le=5)
    naturalness_score: int = Field(default=3, ge=1, le=5)
    communication_score: int = Field(default=3, ge=1, le=5)
    new_words: list[str] = Field(default_factory=list)
    key_phrases: list[str] = Field(default_factory=list)
    corrections_count: int = 0
    xp_earned: int = 0
