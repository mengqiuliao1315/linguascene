from datetime import datetime

from pydantic import BaseModel, ConfigDict


class VocabularyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    word: str
    phonetic: str
    meaning: str
    example: str
    level: str
    mastery: float = 0.0
    review_count: int = 0
    source: str = "scenario"
    next_review: datetime | None = None


class SaveVocabularyRequest(BaseModel):
    word: str
    meaning: str = ""
    phonetic: str = ""
    example: str = ""
    level: str = "B1"
    source: str = "reading"


class ReviewRequest(BaseModel):
    quality: int  # 0 忘记 / 1 模糊 / 2 记得
