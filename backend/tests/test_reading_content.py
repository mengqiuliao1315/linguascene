"""内置逐句讲解的数据校验。

平台文章要「没配模型也能精读」，靠的是 app/data/reading_content.py 里
人工写好的讲解。这份数据一旦和正文错位、或者挑了原文里根本没有的词，
用户看到的讲解就是错的，而且不会有任何报错——所以在这里逐句卡一遍。
"""

import re

from app.data.reading_content import READING_CONTENT, build_sentences
from app.seed import ARTICLES
from app.services.reading_service import lemma_for, lemmatize, split_sentences


def _letters_only(text: str) -> str:
    return re.sub(r"[^a-z ]", "", text.lower())


def _builtin(article: dict) -> list[dict]:
    segments = split_sentences(article["content"])
    sentences = build_sentences(article["title"], segments)
    assert sentences is not None, f"{article['title']} 缺少内置讲解"
    return sentences


def test_every_platform_article_has_builtin_analysis():
    """六篇平台文章都必须有内置讲解，否则断网时精读页是空的。"""
    for article in ARTICLES:
        segments = split_sentences(article["content"])
        sentences = build_sentences(article["title"], segments)
        assert sentences is not None, f"{article['title']} 缺少内置讲解"
        assert len(sentences) == len(segments)


def test_builtin_words_actually_appear_in_the_sentence():
    """重点单词必须是这句里真实出现的写法，不能挂到别的句子或写错形式。"""
    for article in ARTICLES:
        segments = split_sentences(article["content"])
        for sentence, (_, text) in zip(_builtin(article), segments):
            haystack = _letters_only(text)
            for word in sentence["words"]:
                assert word["word"], "重点单词不能为空"
                assert word["lemma"], "重点单词必须带原型"
                assert _letters_only(word["word"]) in haystack, (
                    f"{article['title']} 第 {sentence['index'] + 1} 句里的 "
                    f"{word['word']!r} 不在原句中"
                )


def test_builtin_sentences_carry_translation():
    """每句都要有中文翻译，否则「逐句讲解」名不副实。"""
    for article in ARTICLES:
        for sentence in _builtin(article):
            assert sentence["translation"].strip(), (
                f"{article['title']} 第 {sentence['index'] + 1} 句缺翻译"
            )


def test_content_rows_have_no_leftover_articles():
    """READING_CONTENT 不应残留已被删掉的文章。"""
    titles = {article["title"] for article in ARTICLES}
    assert set(READING_CONTENT) <= titles


# ------------------------------------------------------ 词形还原


def test_lemmatize_keeps_multiword_terms_apart():
    """artificial intelligence 是两个词，不能被拼成 artificialintelligence。"""
    assert lemmatize("artificial intelligence") == "artificial intelligence"
    assert lemma_for("artificial intelligence") == "artificial intelligence"
    assert lemmatize("  The   Way  ") == "the way"


def test_lemmatize_does_not_strip_ly_adverbs():
    """significantly 的原型就是它自己，不是 significant。"""
    assert lemmatize("significantly") == "significantly"
    assert lemmatize("effectively") == "effectively"


def test_lemma_for_prefers_words_already_in_the_dictionary():
    """本身就是词典条目时不再砍词尾：meeting 不必还原成 meet。"""
    known = {"meeting", "meet", "change", "study"}
    assert lemma_for("meeting", known) == "meeting"
    assert lemma_for("changed", known) == "change"
    assert lemma_for("studies", known) == "study"
