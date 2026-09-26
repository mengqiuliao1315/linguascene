"""从 ECDICT 生成四六级与雅思词表，供 `app.import_words` 导入。

ECDICT（https://github.com/skywind3000/ECDICT，MIT 协议）是开源英汉词典库，
带音标、释义以及 cet4 / cet6 / ielts 等考试标签。本脚本把这些词导出成
import_words 需要的 JSON 格式。

用法：
    python -m app.fetch_cet_words                 # 每本默认 3000 词
    python -m app.fetch_cet_words --limit 5000    # 导出更多
    python -m app.fetch_cet_words --out app/data  # 指定输出目录

注意：ECDICT 只有音标和释义，**不含例句**（ex 导出为空数组）。
"""
from __future__ import annotations

import argparse
import csv
import json
import urllib.request
from pathlib import Path

ECDICT_URL = "https://raw.githubusercontent.com/skywind3000/ECDICT/master/ecdict.csv"
DATA_DIR = Path(__file__).resolve().parent / "data"

POS_NAMES = {
    "n": "n.", "v": "v.", "adj": "adj.", "adv": "adv.", "prep": "prep.",
    "conj": "conj.", "pron": "pron.", "num": "num.", "art": "art.",
    "int": "int.", "aux": "aux.", "abbr": "abbr.", "vt": "vt.", "vi": "vi.",
    "a": "adj.",
}
# 词性标记既有缩写也有全称，长的放前面先匹配
POS_PREFIXES = (
    "adj.", "adv.", "prep.", "conj.", "pron.", "abbr.", "aux.",
    "a.", "ad.",
    "n.", "v.", "vt.", "vi.", "num.", "art.", "int.",
)
BACKSLASH_N = chr(92) + "n"
MAX_SENSES = 3
MAX_MEANING = 60


def download(dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 1_000_000:
        print(f"使用缓存 {dest}（{dest.stat().st_size / 1048576:.1f} MB）")
        return
    print("下载 ECDICT …")
    req = urllib.request.Request(ECDICT_URL, headers={"User-Agent": "linguascene/1.0"})
    with urllib.request.urlopen(req, timeout=180) as resp, dest.open("wb") as fh:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
        print(f"  完成 {done / 1048576:.1f} MB")


def split_translation(translation: str) -> list[str]:
    """ECDICT 用字面量反斜杠+n 分隔多行释义，拆成段落并丢掉领域标注行。"""
    text = (translation or "").replace(BACKSLASH_N, "\n")
    parts = []
    for chunk in text.split("\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        # 丢掉 [网络] [经] [计] 这类领域标注行
        if chunk.startswith("[") and "]" in chunk[:8]:
            continue
        parts.append(chunk)
    return parts


def parse_pos_and_zh(translation: str) -> tuple[str, str]:
    """返回 (词性, 中文释义)，都从释义文本里推断。

    ECDICT 的 pos 列大量为空，词性其实写在释义行首（如 "n. 罩；风帽"）。
    优先选第一个带词性标记的段落，让词性和释义对得上。
    """
    parts = split_translation(translation)
    if not parts:
        return "", ""

    pos, meaning = "", ""
    for part in parts:
        for prefix in POS_PREFIXES:
            if part.startswith(prefix):
                pos, meaning = prefix, part[len(prefix):].strip()
                break
        if pos:
            break
    if not meaning:
        meaning = parts[0]

    # 释义太杂就只保留前几个义项，避免卡片被塞满
    meaning = meaning.replace("；", ";")
    if ";" in meaning:
        meaning = meaning.split(";")[0]
    pieces = [p.strip() for p in meaning.replace("，", ",").split(",") if p.strip()]
    if len(pieces) > MAX_SENSES:
        pieces = pieces[:MAX_SENSES]
    meaning = ", ".join(pieces)
    return normalize_pos(pos), meaning[:MAX_MEANING]


POS_ALIASES = {
    "a.": "adj.", "ad.": "adv.", "adv": "adv.", "adj": "adj.",
    "prep": "prep.", "conj": "conj.", "pron": "pron.", "n": "n.", "v": "v.",
}


def normalize_pos(pos: str) -> str:
    """把 ECDICT 里各种词性写法统一成 n. / v. / adj. 这种形式。"""
    if not pos:
        return ""
    key = pos.strip().lower()
    if key in POS_ALIASES:
        return POS_ALIASES[key]
    if not key.endswith("."):
        key += "."
    return key


def dominant_pos(pos_field: str) -> str:
    """pos 列的兜底解析：形如 n:64/v:36，取占比最高的那个。"""
    if not pos_field:
        return ""
    best, best_ratio = "", -1.0
    for part in pos_field.split("/"):
        name, sep, ratio = part.partition(":")
        if not sep:
            continue
        try:
            value = float(ratio)
        except ValueError:
            continue
        if value > best_ratio:
            best, best_ratio = name.strip().lower(), value
    return normalize_pos(POS_NAMES.get(best, best)) if best else ""


def band(rank: int) -> str:
    if rank <= 1000:
        return "高频"
    if rank <= 2000:
        return "常考"
    return "拓展"


def collect(csv_path: Path, tag: str, limit: int, exclude: str | None = None) -> list[dict]:
    """导出带 tag 标签的词。

    exclude 用于排除更高频词书已收录的词：六级词表里 83% 的词同时带 cet4 标签，
    不排除的话「六级词书」就是四级重来一遍。ECDICT 每个 tag 的词量都远超
    考纲实际数量，所以排除后仍然够用。
    """
    rows: list[dict] = []
    with csv_path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            tags = (row.get("tag") or "").split()
            if tag not in tags:
                continue
            if exclude and exclude in tags:
                continue
            word = (row.get("word") or "").strip()
            pos, zh = parse_pos_and_zh(row.get("translation") or "")
            # 只要单个英文单词，过滤掉词组和带符号的条目
            if not word or not zh or not word.isascii() or " " in word or len(word) > 24:
                continue
            if not word.replace("-", "").isalpha():
                continue
            try:
                frq = int(row.get("frq") or 0)
            except ValueError:
                frq = 0
            phonetic = (row.get("phonetic") or "").strip()
            if tag == "ielts" and not phonetic:
                continue
            rows.append(
                {
                    "word": word,
                    "phonetic": f"/{phonetic}/" if phonetic else "",
                    "pos": pos or dominant_pos(row.get("pos") or ""),
                    "zh": zh,
                    "en": (row.get("definition") or "").strip()[:200],
                    "frq": frq,
                }
            )

    # 高频词优先，没有词频数据的排最后
    rows.sort(key=lambda r: (r["frq"] == 0, r["frq"]))
    rows = rows[:limit]

    return [
        {
            "word": item["word"],
            "uk": item["phonetic"],
            "us": item["phonetic"],
            "pos": item["pos"],
            "zh": item["zh"],
            "en": item["en"],
            "ex": [],
            "unit": band(item["frq"] or 99999),
            "tags": tag,
        }
        for item in rows
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="从 ECDICT 生成四六级与雅思词表")
    parser.add_argument("--limit", type=int, default=3000, help="每本词书最多导出多少词")
    parser.add_argument("--out", default=str(DATA_DIR), help="输出目录")
    parser.add_argument("--cache", default="ecdict.csv", help="ECDICT 缓存路径")
    parser.add_argument(
        "--books",
        default="",
        help="只导出这些词书，逗号分隔（cet4,cet6,ielts）。默认三本都导出",
    )
    args = parser.parse_args(argv)

    cache = Path(args.cache)
    download(cache)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # cet6 排除 cet4 已收录的词，只留六级新增词。
    # ielts 不排除任何词：雅思是独立词书，和四六级重叠的词两本都该能学到。
    plan = [("cet4", None), ("cet6", "cet4"), ("ielts", None)]
    wanted = {name.strip() for name in args.books.split(",") if name.strip()}
    unknown = wanted - {code for code, _ in plan}
    if unknown:
        print(f"未知词书：{', '.join(sorted(unknown))}（可选 cet4, cet6, ielts）")
        return 1
    for code, exclude in plan:
        if wanted and code not in wanted:
            continue
        words = collect(cache, code, args.limit, exclude=exclude)
        target = out_dir / f"{code}.json"
        target.write_text(json.dumps({code: words}, ensure_ascii=False), encoding="utf-8")
        note = f"（排除 {exclude}）" if exclude else ""
        print(f"{code}: {len(words)} 词{note} -> {target.name}（{target.stat().st_size / 1024:.0f} KB）")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
