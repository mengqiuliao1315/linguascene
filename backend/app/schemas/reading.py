"""精读功能的输入输出 Schema。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReadingWord(BaseModel):
    """句子里的重点单词。lemma 是原型，用户背单词时看这个。"""

    word: str
    lemma: str = ""
    meaning: str = ""
    phonetic: str = ""
    part_of_speech: str = ""


class ReadingPhrase(BaseModel):
    """固定搭配。"""

    phrase: str
    meaning: str = ""
    example: str = ""


class ReadingGrammar(BaseModel):
    point: str
    explanation: str = ""
    example: str = ""


class ReadingSentence(BaseModel):
    """一句原文 + AI 讲解。前端按 index 对齐原文渲染。"""

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
    # 单词原型；留空则由服务端还原
    lemma: str = Field(default="", max_length=128)
    meaning: str = ""
    note: str = ""
    color: str = Field(default="blue", pattern="^(blue|green|amber|rose|violet)$")
    # 选中文字在句内的字符区间，用于精确染色；0/0 表示按文本匹配的老笔记
    start_offset: int = Field(default=0, ge=0)
    end_offset: int = Field(default=0, ge=0)


class NoteUpdate(BaseModel):
    # None 表示本次不改这个字段。只改颜色时必须留空，
    # 否则会把已有的笔记正文清掉。
    note: str | None = None
    # 模型给的释义/翻译不一定准，允许用户就地改。空串是合法值（表示清空）。
    meaning: str | None = None
    color: str | None = Field(default=None, pattern="^(blue|green|amber|rose|violet)$")


class SuggestedSpanOut(BaseModel):
    """一条建议标注，区间已由服务端按原文算好。"""

    text: str
    color: str = "blue"
    reason: str = ""
    start_offset: int = 0
    end_offset: int = 0


class SuggestRequest(BaseModel):
    """请求某几句的建议。留空表示整篇。"""

    sentence_indexes: list[int] = Field(default_factory=list)


class SuggestOut(BaseModel):
    # {sentence_index: [span, ...]}
    by_sentence: dict[int, list[SuggestedSpanOut]] = Field(default_factory=dict)
    # 全部句子都由模型产出才算 True
    generated: bool = False
    # 有多少句退化成了离线词表。>0 时前端按「部分兜底」提示，
    # 不能笼统说"模型没调通"——多数建议可能仍然来自模型。
    fallback_count: int = 0
    sentence_count: int = 0


class SelectionAnalyzeRequest(BaseModel):
    """划词解析请求。sentence 留空时服务端按 sentence_index 从缓存里取。"""

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
    # False 表示模型没调通、这是离线兜底，前端应提示
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
    # 这个词是否已经在个人词库里，前端据此显示"已加入"
    in_vocabulary: bool = False


class MaterialOut(BaseModel):
    """阅读库列表项。source 区分平台材料 / 我的上传 / 他人公开。"""

    id: int
    title: str
    source: str  # platform | mine | shared
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
