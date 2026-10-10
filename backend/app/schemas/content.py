from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PhraseOut(BaseModel):
    phrase: str
    meaning: str = ""
    example: str = ""


class GrammarPointOut(BaseModel):
    point: str
    explanation: str = ""
    example: str = ""


class ArticleCardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    source: str
    url: str
    summary: str
    level: str
    category: str
    word_count: int
    read_minutes: int
    published_at: datetime


class ArticleDetailOut(ArticleCardOut):
    content: str


class ArticleAnalysisOut(BaseModel):
    summary: str = ""
    level: str = "B1"
    keywords: list[dict] = []
    phrases: list[PhraseOut] = []
    grammar_points: list[GrammarPointOut] = []
    reading_questions: list[str] = []
    speaking_questions: list[str] = []
    writing_task: str = ""


class WordSenseOut(BaseModel):
    part_of_speech: str = ""
    meaning: str = ""
    example: str = ""


class WordExplanationOut(BaseModel):
    word: str
    pronunciation: str = ""
    part_of_speech: str = ""
    core_meanings: list[str] = []
    meaning_in_context: str = ""
    collocations: list[str] = []
    example_sentences: list[str] = []
    related_words: list[str] = []
    cefr_level: str = "B1"
    senses: list[WordSenseOut] = []


class TranslateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    context: str = Field(default="", max_length=5000)
    fast: bool = False


class SentenceAnalysisRequest(BaseModel):
    sentence: str = Field(min_length=1, max_length=1000)
    context: str = ""


class UserContentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content_type: str
    status: str
    created_at: datetime
    word_count: int = 0
    preview: str = ""
