"""所有 Agent 的输入输出 Schema。

Agent 之间只通过这些结构化对象通信，前端只渲染不解析自然语言。
"""

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
    """给用户的中文脚手架：这一步该说什么，以及可以照着翻译的句子。"""

    task_key: str = ""
    task_description: str = ""
    idea_zh: str = ""
    suggested_zh: str = ""
    suggested_en: str = ""


class CoachNote(BaseModel):
    """实时点评：对用户这一句的直接回应。

    与 correction 的分工：correction 指出错在哪，coach_note 用中文说明
    "这句好在哪 / 下次怎么说得更好"，让用户每轮都能拿到明确反馈。
    verdict 取值 good（没问题）/ fix（有要改的地方）/ try（可以更地道）。
    """

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


class ScenarioReplyCore(BaseModel):
    """对话回复本体。

    单独走一次调用，只为一个字段——输出 token 越少，用户越早看到 AI 说话。
    反馈（纠错、点评、提示）另开一路并行跑，不必等它。
    """

    reply: str


class ScenarioFeedback(BaseModel):
    """一轮对话结束后的学习反馈。可以比回复晚到，不阻塞对话继续。"""

    correction: CorrectionOut | None = None
    natural_expression: NaturalExpressionOut | None = None
    new_vocabulary: list[VocabularyItemOut] = Field(default_factory=list)
    hint: ScenarioHint | None = None
    coach_note: CoachNote | None = None
    completed_task_keys: list[str] = Field(default_factory=list)


class TranslationOut(BaseModel):
    """整句翻译。只有一个字段，刻意保持最小，好让往返尽量快。"""

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
    """精读里划词/划短语的实时解析：释义 + 一条可采纳的学习笔记。

    与 WordExplanation 的分工：那个是查词弹窗要的完整词条（音标、近义词、
    多条例句），这个是"划一下马上要一条笔记"，只留能直接放进批注的内容。
    """

    kind: str = "word"  # word | phrase
    text: str = ""
    lemma: str = ""
    meaning: str = ""
    part_of_speech: str = ""
    note: str = ""
    example: str = ""


class SuggestedSpan(BaseModel):
    """AI 建议标注的一段原文。

    `text` 必须能在原句里逐字找到；Agent 会再校验一次并算出字符区间，
    找不到的整条丢弃，绝不让模型改写的文本污染原文。
    """

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
    """一次模型调用分析多条句子的批量结构。

    单句分析时每句都要走一次往返，长文几十句就卡在串行模型调用上。
    批量把若干句塞进一次调用，往返次数按批数缩，配合流式按批逐句吐出，
    首句就绪时间不变、全篇就绪时间能压到原来的 1/N。
    """

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
