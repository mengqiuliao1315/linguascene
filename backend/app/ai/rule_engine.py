import re
from dataclasses import dataclass, field

from app.data.scenario_content import (
    FIXED_ZH,
    OPENING_ZH,
    SCENARIO_EXPRESSIONS,
    TASKS,
)


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
    hint = TASK_HINTS.get(task_key)
    if not hint:
        return None
    return {"task_key": task_key, **hint}


SENTENCE_ZH: dict[str, str] = {
    **OPENING_ZH,
    **{item["question_en"]: item["question_zh"] for item in TASKS.values()},
    **FIXED_ZH,
}


def translate_sentence(sentence: str) -> str:
    cleaned = sentence.strip()
    if cleaned in SENTENCE_ZH:
        return SENTENCE_ZH[cleaned]
    stripped = re.sub(r"^Got it\.\s*", "", cleaned)
    return SENTENCE_ZH.get(stripped, "")


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
    stripped = text.strip()
    if not stripped:
        return None

    for rule in GRAMMAR_RULES:
        match = rule.pattern.search(stripped)
        if not match:
            continue

        if rule.explanation.startswith("描述过去"):
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


def extract_vocabulary(text: str, level: str, limit: int = 3) -> list[dict]:
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


_NUMBER_WORDS: dict[str, str] = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "fifteen": "15",
    "twenty": "20", "thirty": "30", "forty": "40", "fifty": "50",
    "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90",
}

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


def build_report_stats(
    messages: list[dict], corrections: list[dict], task_progress: int
) -> dict:
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
