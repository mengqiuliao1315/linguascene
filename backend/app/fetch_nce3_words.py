"""生成新概念英语第三册词表，供 `app.import_words` 导入。

数据来源：
- 课文生词表：GitHub `Lovecanon/nce`（新概念英语 1-4 册课文 Markdown），
  每课都有教材原版的「New words and expressions 生词和短语」段落。
- 音标 / 英文释义：本地 ECDICT 缓存（见 `app/fetch_cet_words.py`），
  课文词表的音标是 OCR 文本，质量差，所以只取「词 + 中文释义 + 课文例句」。

用法：
    python -m app.fetch_nce3_words            # 用缓存，缺哪课补哪课
    python -m app.fetch_nce3_words --refresh  # 强制重新下载全部课文

输出 `app/data/nce3.json`，格式同其他词书：{book_code: [单词对象, ...]}。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

REPO = "Lovecanon/nce"
BRANCH = "master"
LESSON_DIR = "3"
API_TREE = f"https://api.github.com/repos/{REPO}/git/trees/HEAD?recursive=1"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/"

DATA_DIR = Path(__file__).resolve().parent / "data"
STORAGE_DIR = Path(__file__).resolve().parents[1] / "storage"
CACHE_DIR = STORAGE_DIR / "nce3"
ECDICT_PATH = STORAGE_DIR / "ecdict.csv"
OUT_PATH = DATA_DIR / "nce3.json"

POS_RE = re.compile(r"\b(?:n|v|vt|vi|adj|adv|prep|conj|pron|num|art|int|aux|abbr|a)\.")
BACKSLASH_N = chr(92) + "n"

# 课文词表里的 OCR / 排版错词
WORD_FIX = {
    "lawn mowe": "lawn mower",
    "listeia": "listeria",
    "staten": "Staten Island",
}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "linguascene/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def lesson_files(refresh: bool) -> list[tuple[int, str]]:
    """返回 [(课号, 缓存文件名), ...]，缓存缺失或 refresh 时下载。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = {p.stem: p for p in CACHE_DIR.glob("L*.md")}
    if len(cached) >= 60 and not refresh:
        return sorted((int(p.stem[1:]), p.name) for p in cached.values())

    tree = json.loads(fetch(API_TREE))
    paths = [
        t["path"]
        for t in tree.get("tree", [])
        if t["path"].startswith(f"{LESSON_DIR}/") and t["path"].endswith(".md")
    ]
    plan: list[tuple[int, str]] = []
    for path in paths:
        m = re.match(rf"{LESSON_DIR}/[Ll]esson-(\d+)-", path)
        if not m:
            continue
        num = int(m.group(1))
        name = f"L{num:02d}.md"
        dest = CACHE_DIR / name
        if refresh or not dest.exists() or dest.stat().st_size == 0:
            dest.write_bytes(fetch(RAW_BASE + urllib.parse.quote(path)))
        plan.append((num, name))
    return sorted(plan)


def parse_section(text: str) -> str:
    m = re.search(r"##\s*New words and [Ee]xpressions.*?(?=\n##|\Z)", text, re.S)
    return m.group(0) if m else ""


def parse_line(line: str) -> tuple[str, str] | None:
    """把「word（1. 2)/音标/词性. 释义」拆成 (word, 剩余文本)。"""
    s = re.sub(r"^[\*\-•\s]+", "", line.strip())
    if not s or not re.match(r"^[A-Za-z]", s):
        return None
    idx = len(s)
    for ch in ("(", "（", "/"):
        i = s.find(ch)
        if i != -1:
            idx = min(idx, i)
    m = POS_RE.search(s)
    if m:
        idx = min(idx, m.start())
    word = s[:idx].strip().strip(".,;:")
    rest = s[idx:].strip()
    if not word or not re.fullmatch(r"[A-Za-z][A-Za-z'’\-\.]*(?: [A-Za-z][A-Za-z'’\-\.]*)*", word):
        return None
    return word, rest


def extract_pos_zh(rest: str) -> tuple[str, str]:
    s = re.sub(r"^[（(][^)）]*[)）]", "", rest).strip()
    s = re.sub(r"/[^/\n]*/", " ", s)  # 去掉 OCR 音标
    s = re.sub(r"[（(][^)）]*[)）]", " ", s)
    s = s.replace("．", ".").replace("。", ".")
    s = re.sub(r"\s+", " ", s).strip(" .,;:")
    m = POS_RE.search(s)
    if m:
        return m.group(0), s[m.end():].strip(" .,;:")
    return "", s


def find_example(body: str, sentences: list[str], word: str) -> str:
    stem = word.lower().split()[0][:5]
    for sent in sentences:
        if re.search(r"\b" + re.escape(stem), sent, re.I) and 15 < len(sent) < 240:
            return sent.strip()
    return ""


def load_ecdict(words: set[str]) -> dict[str, dict]:
    if not ECDICT_PATH.exists():
        print(f"缺少 ECDICT 缓存 {ECDICT_PATH}，将只写课文释义")
        return {}
    out: dict[str, dict] = {}
    with ECDICT_PATH.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            key = (row.get("word") or "").lower()
            if key in words and key not in out:
                out[key] = row
    return out


def clean_en(definition: str) -> str:
    if not definition:
        return ""
    parts = [p.strip() for p in re.split(re.escape(BACKSLASH_N) + r"|\n", definition) if p.strip()]
    text = "; ".join(parts[:3])
    return re.sub(r"^r\.\s", "adv. ", text)[:200]


def collect(refresh: bool) -> list[dict]:
    raw: list[dict] = []
    for num, name in lesson_files(refresh):
        text = (CACHE_DIR / name).read_text(encoding="utf-8")
        body = re.sub(r"^#.*$", "", text.split("## New words")[0], count=1, flags=re.M)
        sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", body))
        for line in parse_section(text).split("\n")[1:]:
            parsed = parse_line(line)
            if not parsed:
                continue
            word, rest = parsed
            word = WORD_FIX.get(word.lower(), word)
            pos, zh = extract_pos_zh(rest)
            raw.append(
                {
                    "lesson": num,
                    "word": word,
                    "pos": pos,
                    "zh": zh,
                    "ex": find_example(body, sentences, word),
                }
            )
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成新概念英语第三册词表")
    parser.add_argument("--refresh", action="store_true", help="强制重新下载全部课文")
    args = parser.parse_args(argv)

    raw = collect(args.refresh)
    # 同一个词可能出现在多课，保留首次出现的位置
    seen: dict[str, dict] = {}
    order: list[str] = []
    for entry in raw:
        key = entry["word"].lower()
        if key not in seen:
            seen[key] = entry
            order.append(key)

    ecdict = load_ecdict(set(seen))
    words: list[dict] = []
    for key in order:
        entry = seen[key]
        row = ecdict.get(key)
        phonetic = (row.get("phonetic") or "").strip() if row else ""
        phonetic = f"/{phonetic}/" if phonetic else ""
        words.append(
            {
                "word": entry["word"],
                "uk": phonetic,
                "us": phonetic,
                "pos": entry["pos"],
                "zh": entry["zh"],
                "en": clean_en(row.get("definition") or "") if row else "",
                "ex": ([{"en": entry["ex"], "zh": ""}] if entry["ex"] else []),
                "unit": f"Lesson {entry['lesson']}",
                "tags": "nce3",
            }
        )
    words.sort(key=lambda w: int(w["unit"].split()[1]))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps({"nce3": words}, ensure_ascii=False, indent=0), encoding="utf-8"
    )
    lessons = len({int(w["unit"].split()[1]) for w in words})
    print(
        f"nce3: {len(words)} 词，覆盖 {lessons} 课 -> {OUT_PATH.name}"
        f"（{OUT_PATH.stat().st_size / 1024:.0f} KB）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
