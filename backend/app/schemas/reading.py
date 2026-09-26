from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReadingWord(BaseModel):

    word: str
    lemma: str = ""
    meaning: str = ""
    phonetic: str = ""
    part_of_speech: str = ""


class ReadingPhrase(BaseModel):

    phrase: str
    meaning: str = ""
    example: str = ""


class ReadingGrammar(BaseModel):
    point: str
    explanation: str = ""
    example: str = ""


class ReadingSentence(BaseModel):

    index: int
    paragraph: int = 0
    text: str
    translation: str = ""
    main_clause: str = ""
    words: list[ReadingWord] = Field(default_factory=list)
    phrases: list[ReadingPhrase] = Field(default_factory=list)
    grammar: list[ReadingGrammar] = Field(default_factory=list)
    explanation: str = ""
    notes: list["NoteOut"] = Field(default_factory=list)


class ReadingAnalysisOut(BaseModel):
    level: str = "B1"
    sentences: list[ReadingSentence] = Field(default_factory=list)
    generated: bool = False


class NoteCreate(BaseModel):
    sentence_index: int = 0
    kind: str = Field(default="word", pattern="^(word|phrase|sentence|note)$")
    text: str = Field(min_length=1, max_length=512)
    lemma: str = Field(default="", max_length=128)
    meaning: str = ""
    note: str = ""
    color: str = Field(default="blue", pattern="^(blue|green|amber|rose|violet)$")
    start_offset: int = Field(default=0, ge=0)
    end_offset: int = Field(default=0, ge=0)


class NoteUpdate(BaseModel):
    note: str | None = None
    meaning: str | None = None
    color: str | None = Field(default=None, pattern="^(blue|green|amber|rose|violet)$")


class SuggestedSpanOut(BaseModel):

    text: str
    color: str = "blue"
    reason: str = ""
    start_offset: int = 0
    end_offset: int = 0


class SuggestRequest(BaseModel):

    sentence_indexes: list[int] = Field(default_factory=list)


class SuggestOut(BaseModel):
    by_sentence: dict[int, list[SuggestedSpanOut]] = Field(default_factory=dict)
    generated: bool = False
    fallback_count: int = 0
    sentence_count: int = 0


class SelectionAnalyzeRequest(BaseModel):

    text: str = Field(min_length=1, max_length=512)
    sentence: str = ""
    sentence_index: int = 0


class SelectionAnalysisOut(BaseModel):
    kind: str = "word"
    text: str = ""
    lemma: str = ""
    meaning: str = ""
    part_of_speech: str = ""
    note: str = ""
    example: str = ""
    generated: bool = False


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sentence_index: int
    kind: str
    text: str
    lemma: str = ""
    meaning: str
    note: str
    color: str
    start_offset: int = 0
    end_offset: int = 0
    created_at: datetime
    in_vocabulary: bool = False


class MaterialOut(BaseModel):

    id: int
    title: str
    source: str
    author_name: str = ""
    content_type: str = "text"
    level: str = "B1"
    word_count: int = 0
    read_minutes: int = 5
    is_public: bool = False
    is_mine: bool = False
    note_count: int = 0
    created_at: datetime | None = None


class MaterialDetailOut(MaterialOut):
    content: str = ""
    sentences: list[ReadingSentence] = Field(default_factory=list)


ReadingSentence.model_rebuild()
