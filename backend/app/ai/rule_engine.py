"""规则引擎（离线模式）。

当 AI Provider 不可用（未配置 Key / 调用失败）时，由这里提供确定性的分析结果。
它只做规则能可靠判断的事：
- 高置信度的语法错误（时态、冠词、主谓一致、大小写等）
- 场景高频表达替换（I want → I'd like）
- 任务完成判定（关键词 + 意图匹配）
- 词汇提取（词频 + 分级词表）

规则判定不了的语义问题一律不猜，交给在线模型。
"""

import re
from dataclasses import dataclass, field

from app.data.scenario_content import (
    FIXED_ZH,
    OPENING_ZH,
    SCENARIO_EXPRESSIONS,
    TASKS,
)

# ---------------------------------------------------------------- 语法规则

# 每条规则：(正则, 修正回调, 说明, 严重级别, 类型)
# 严重级别：1 严重语法错误 / 2 语法正确但不自然 / 3 表达优化


@dataclass
class Rule:
    pattern: re.Pattern[str]
    replacement: str
    explanation: str
    severity: int
    correction_type: str = "grammar"


GRAMMAR_RULES: list[Rule] = [
    Rule(
        re.compile(r"\bI\s+want\s+(a|an|some|the)\b", re.IGNORECASE),
        "I'd like \\1",
        "点单或请求时用 I'd like 比 I want 更礼貌自然。",
        2,
        "naturalness",
    ),
    Rule(
        re.compile(r"\bI\s+want\s+to\s+buy\b", re.IGNORECASE),
        "I'd like to get",
        "I'd like to get 在购物场景中更自然。",
        2,
        "naturalness",
    ),
    Rule(
        re.compile(r"\b(?:yesterday|last night|last week|last year)\b.*\b(go|eat|see|meet|take|buy|come)\b", re.IGNORECASE),
        "",
        "描述过去发生的事情要用过去式（went / ate / saw / met / took / bought / came）。",
        1,
        "tense",
    ),
    Rule(
        re.compile(r"\bI\s+am\s+agree\b", re.IGNORECASE),
        "I agree",
        "agree 是动词，直接用 I agree，不需要 be 动词。",
        1,
        "grammar",
    ),
    Rule(
        re.compile(r"\bhow\s+much\s+(?:is\s+)?(?:the\s+)?(?:price)\s+of\b", re.IGNORECASE),
        "how much is",
        "询问价格用 how much is + 物品，不用 price of。",
        2,
        "naturalness",
    ),
    Rule(
        re.compile(r"\bI\s+very\s+like\b", re.IGNORECASE),
        "I really like",
        "英语中不说 I very like，用 I really like 或 I like ... very much。",
        1,
        "word_order",
    ),
    Rule(
        re.compile(r"\bI\s+look\s+forward\s+to\s+(meet|see|hear)\b", re.IGNORECASE),
        "I look forward to meeting",
        "look forward to 后面接动名词形式（-ing）。",
        1,
        "grammar",
    ),
    Rule(
        re.compile(r"\bcan\s+you\s+give\s+me\s+(?:the\s+)?bill\b", re.IGNORECASE),
        "Could I get the bill",
        "结账时 Could I get the bill, please? 更地道。",
        2,
        "naturalness",
    ),
    Rule(
        re.compile(r"\bwhat\s+is\s+your\s+name\s+again\b", re.IGNORECASE),
        "Sorry, what was your name again?",
        "回忆对方姓名时用过去式 what was your name again 更自然。",
        3,
        "naturalness",
    ),
    Rule(
        re.compile(r"\bI\s+have\s+been\s+to\s+there\s+since\s+\d+\s+years\b", re.IGNORECASE),
        "I have been there for ... years",
        "for 接一段时间，since 接时间点。",
        1,
        "grammar",
    ),
]

# 单词级别的补充检查：句中孤立出现的动词原形配过去时间状语
PAST_TIME_MARKERS = {"yesterday", "ago", "last night", "last week", "last year"}
IRREGULAR_PAST = {
    "go": "went",
    "eat": "ate",
    "see": "saw",
    "meet": "met",
    "take": "took",
    "buy": "bought",
    "come": "came",
    "drink": "drank",
    "give": "gave",
    "get": "got",
    "make": "made",
    "fly": "flew",
    "leave": "left",
}

# 场景高频表达直接复用内容模块，避免两处维护同一份表达库。
# 下面几个映射统一由 TASKS 派生：模型不可用时也能给出提问、中文句与任务判定。

TASK_HINTS: dict[str, dict[str, str]] = {
    key: {
        "idea_zh": item["idea_zh"],
        "suggested_zh": item["suggested_zh"],
        "suggested_en": item["suggested_en"],
    }
    for key, item in TASKS.items()
}

TASK_QUESTIONS: dict[str, str] = {
    key: item["question_en"] for key, item in TASKS.items()
}

TASK_INTENT_PATTERNS: dict[str, list[str]] = {
    key: item["intents"] for key, item in TASKS.items()
}


def task_hint(task_key: str) -> dict | None:
    """取某个任务的离线提示。未知任务键返回 None，由前端隐藏提示卡。"""
    hint = TASK_HINTS.get(task_key)
    if not hint:
        return None
    return {"task_key": task_key, **hint}


# --------------------------------------- 离线整句翻译（对话常用句 → 中文）

# 只覆盖系统自己会说的固定句子（开场白、任务提问、收尾语），
# 用户自由输入或模型自由生成的内容不在这里猜。
SENTENCE_ZH: dict[str, str] = {
    **OPENING_ZH,
    **{item["question_en"]: item["question_zh"] for item in TASKS.values()},
    **FIXED_ZH,
}


def translate_sentence(sentence: str) -> str:
    """离线整句翻译。命中内置句库才返回中文，否则返回空串（不猜）。"""
    cleaned = sentence.strip()
    if cleaned in SENTENCE_ZH:
        return SENTENCE_ZH[cleaned]
    # 离线回复会在任务提问前加 "Got it. " 作为承接，这里还原后再查
    stripped = re.sub(r"^Got it\.\s*", "", cleaned)
    return SENTENCE_ZH.get(stripped, "")


# ------------------------------------------------------------ 词汇分级

# 高频但值得学习的词（按 CEFR 粗分），用于从对话/文章中挑词
VOCAB_BY_LEVEL: dict[str, dict[str, str]] = {
    "A2": {
        "coffee": "咖啡", "menu": "菜单", "bill": "账单", "order": "点单",
        "size": "尺寸", "price": "价格", "ticket": "票", "seat": "座位",
    },
    "B1": {
        "reservation": "预订", "luggage": "行李", "departure": "出发",
        "available": "可用的", "recommend": "推荐", "include": "包含",
        "experience": "经验", "responsibility": "职责", "improve": "改进",
        "significant": "显著的", "approach": "方法", "benefit": "好处",
    },
    "B2": {
        "adaptive": "适应性的", "personalized": "个性化的", "accessibility": "可及性",
        "transform": "改变；转变", "efficient": "高效的", "sustainable": "可持续的",
        "perspective": "视角", "framework": "框架", "implement": "实施",
        "collaborate": "协作", "leverage": "利用", "infrastructure": "基础设施",
    },
    "C1": {
        "nuanced": "细致入微的", "pragmatic": "务实的", "ambiguous": "模棱两可的",
        "underpin": "支撑", "paradigm": "范式", "resilience": "韧性",
    },
}

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "of", "to", "in", "on", "at", "for",
    "with", "is", "are", "was", "were", "be", "been", "am", "do", "does", "did",
    "have", "has", "had", "i", "you", "he", "she", "it", "we", "they", "me", "him",
    "her", "us", "them", "my", "your", "his", "its", "our", "their", "this", "that",
    "these", "those", "so", "very", "just", "can", "could", "will", "would", "shall",
    "should", "may", "might", "must", "not", "no", "yes", "ok", "okay", "hi", "hello",
    "thanks", "thank", "please", "there", "here", "what", "when", "where", "who",
    "how", "why", "as", "by", "from", "up", "out", "about", "into", "than", "then",
}


def detect_correction(text: str) -> dict | None:
    """返回最高优先级的一处修正；没有可靠命中就返回 None（不硬凑）。"""
    stripped = text.strip()
    if not stripped:
        return None

    for rule in GRAMMAR_RULES:
        match = rule.pattern.search(stripped)
        if not match:
            continue

        if rule.explanation.startswith("描述过去"):
            # 逐词修正过去式，避免整句替换丢失信息
            corrected = stripped
            for base, past in IRREGULAR_PAST.items():
                corrected = re.sub(
                    rf"\b{base}\b", past, corrected, count=1, flags=re.IGNORECASE
                )
            return {
                "has_error": True,
                "original": stripped,
                "corrected": corrected,
                "explanation": rule.explanation,
                "correction_type": rule.correction_type,
                "severity": rule.severity,
            }

        if rule.replacement:
            corrected = rule.pattern.sub(rule.replacement, stripped, count=1)
        else:
            continue

        if corrected == stripped:
            continue

        return {
            "has_error": True,
            "original": stripped,
            "corrected": corrected,
            "explanation": rule.explanation,
            "correction_type": rule.correction_type,
            "severity": rule.severity,
        }

    # 句首小写（明确的书写错误）
    if stripped[0].islower() and stripped[0].isalpha():
        return {
            "has_error": True,
            "original": stripped,
            "corrected": stripped[0].upper() + stripped[1:],
            "explanation": "句首字母需要大写。",
            "correction_type": "mechanics",
            "severity": 1,
        }

    return None


def pick_natural_expression(
    scenario_slug: str | None,
    text: str,
    already_suggested: set[str] | None = None,
) -> dict | None:
    """根据场景给一条地道表达。

    跳过用户已经用过的，以及本对话已经推荐过的，避免每轮重复同一条。
    """
    if not scenario_slug:
        scenario_slug = "free-talk"
    pool = SCENARIO_EXPRESSIONS.get(scenario_slug, SCENARIO_EXPRESSIONS["free-talk"])
    lowered = text.lower()
    suggested = {s.lower() for s in (already_suggested or set())}

    for expression, meaning, example in pool:
        if expression.lower() in suggested:
            continue  # 本对话已经推过
        head = expression.split("...")[0].split(",")[0].strip().lower()
        if head and head in lowered:
            continue  # 用户已经用过了
        return {"expression": expression, "meaning": meaning, "example": example}
    return None


def extract_vocabulary(text: str, level: str, limit: int = 3) -> list[dict]:
    """按用户等级从文本中提取值得学的词。命中分级词表才算，不硬凑。"""
    levels_order = ["A2", "B1", "B2", "C1"]
    try:
        start = levels_order.index(level)
    except ValueError:
        start = 1
    candidate_levels = levels_order[start:] + levels_order[:start]

    words = re.findall(r"[A-Za-z][A-Za-z'-]{2,}", text)
    seen: set[str] = set()
    result: list[dict] = []

    for word in words:
        lower = word.lower()
        if lower in seen or lower in STOPWORDS:
            continue
        for lvl in candidate_levels:
            lexicon = VOCAB_BY_LEVEL.get(lvl, {})
            if lower in lexicon:
                seen.add(lower)
                result.append({"word": lower, "meaning": lexicon[lower], "level": lvl})
                break
        if len(result) >= limit:
            break
    return result


# ------------------------------------------------------- 任务完成判定

# 触发意图在 TASKS 里与任务提示放在一起，这里只消费。


# 数字词 → 阿拉伯数字。意图规则里写的是 \d+ years，而用户会写 "three
# years"；不归一化就永远判不出完成，提示卡会一直停在同一步不动。
_NUMBER_WORDS: dict[str, str] = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "fifteen": "15",
    "twenty": "20", "thirty": "30", "forty": "40", "fifty": "50",
    "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90",
}

# 缩写展开。只用于额外匹配一遍，不替换原文，免得打断依赖缩写的意图规则。
_CONTRACTIONS: dict[str, str] = {
    "i'd": "i would", "i'm": "i am", "i've": "i have", "i'll": "i will",
    "you're": "you are", "you've": "you have", "you'd": "you would",
    "you'll": "you will", "it's": "it is", "that's": "that is",
    "what's": "what is", "there's": "there is", "let's": "let us",
    "we're": "we are", "we've": "we have", "we'll": "we will",
    "they're": "they are", "don't": "do not", "doesn't": "does not",
    "didn't": "did not", "can't": "cannot", "couldn't": "could not",
    "won't": "will not", "isn't": "is not", "aren't": "are not",
    "wasn't": "was not", "weren't": "were not",
}


def _normalize(text: str) -> str:
    """把数字词换成阿拉伯数字、展开常见缩写，让意图规则容忍自然写法。"""
    lowered = text.lower().replace("\u2019", "'")
    for contraction, expanded in _CONTRACTIONS.items():
        lowered = re.sub(rf"\b{re.escape(contraction)}\b", expanded, lowered)
    return re.sub(
        r"\b[a-z]+\b",
        lambda match: _NUMBER_WORDS.get(match.group(0), match.group(0)),
        lowered,
    )


def detect_completed_tasks(
    text: str, pending_keys: list[str], already_done: set[str]
) -> list[str]:
    """只判定尚未完成的任务，且必须真正命中意图，不凭空标记完成。

    原文与归一化文本各匹配一遍：前者保住依赖缩写的意图规则，后者让
    "three years" 这类写法也能命中 \\d+ 规则。取并集，只会更宽容。
    """
    candidates = (text.lower(), _normalize(text))
    completed: list[str] = []
    for key in pending_keys:
        if key in already_done:
            continue
        patterns = TASK_INTENT_PATTERNS.get(key)
        if not patterns:
            continue
        if any(re.search(p, c) for p in patterns for c in candidates):
            completed.append(key)
    return completed


# ----------------------------------------------------------- 实时点评

def coach_note(
    text: str,
    *,
    correction: dict | None,
    completed_keys: list[str],
    natural: dict | None,
) -> dict:
    """对用户刚说的这一句给出中文即时点评。

    只根据已有信号说话（纠错结果、任务完成、地道表达建议），不臆测语义。
    模型在线时由 ScenarioAgent 覆盖这里的结果；离线时保证每轮都有回应。
    """
    words = text.split()

    if correction and correction.get("severity") == 1:
        return {
            "verdict": "fix",
            "message_zh": f"这句有一处要改：{correction['explanation']}",
            "tip_en": correction["corrected"],
        }

    if correction:
        return {
            "verdict": "try",
            "message_zh": "语法没问题，不过换个说法会更自然。",
            "tip_en": correction["corrected"],
        }

    if completed_keys:
        key = completed_keys[-1]
        item = TASKS.get(key, {})
        hint = item.get("suggested_en", "")
        message = "意思表达清楚了，这一步完成了。"
        if len(words) <= 3 and hint:
            message += f"想更充分一点，可以试试：{hint}"
        return {"verdict": "good", "message_zh": message, "tip_en": ""}

    if len(words) <= 1:
        return {
            "verdict": "try",
            "message_zh": "回答有点短，多说一句能让对话更自然。",
            "tip_en": "",
        }

    if natural:
        return {
            "verdict": "try",
            "message_zh": "句子没问题，可以顺便学一个更地道的说法。",
            "tip_en": natural["example"],
        }

    return {
        "verdict": "good",
        "message_zh": "表达清楚，继续保持这个节奏。",
        "tip_en": "",
    }


# ----------------------------------------------------------- 报告生成

def build_report_stats(
    messages: list[dict], corrections: list[dict], task_progress: int
) -> dict:
    """从真实对话统计里算分数，不编造。"""
    user_messages = [m for m in messages if m.get("role") == "user"]
    total_words = sum(len(m.get("content", "").split()) for m in user_messages)
    turns = len(user_messages)

    severity_counts = {1: 0, 2: 0, 3: 0}
    for c in corrections:
        severity_counts[int(c.get("severity", 1))] = (
            severity_counts.get(int(c.get("severity", 1)), 0) + 1
        )

    serious = severity_counts.get(1, 0)
    minor = severity_counts.get(2, 0) + severity_counts.get(3, 0)

    grammar = _clamp(5 - serious, 1, 5)
    naturalness = _clamp(5 - minor, 1, 5)
    vocabulary = _clamp(2 + min(3, total_words // 40), 1, 5)
    communication = _clamp(
        2 + min(3, turns // 3) + (1 if task_progress >= 80 else 0), 1, 5
    )

    return {
        "grammar_score": grammar,
        "vocabulary_score": vocabulary,
        "naturalness_score": naturalness,
        "communication_score": communication,
        "corrections_count": len(corrections),
        "user_turns": turns,
        "user_words": total_words,
    }


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))
