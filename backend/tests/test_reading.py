import io
import json
import time
import uuid

import pytest
from reportlab.lib.styles import ParagraphStyle

from app.services import pdf_service, reading_service
from app.services.reading_service import lemmatize, split_sentences


def _article_payload() -> dict:
    return {
        "username": f"reader{uuid.uuid4().hex[:8]}",
        "email": f"reader{uuid.uuid4().hex[:8]}@example.com",
        "password": "reader12345",
    }


def test_split_sentences_basic():
    text = "First sentence here. Second one follows! Third?"
    parts = split_sentences(text)
    assert [s for _, s in parts] == [
        "First sentence here.",
        "Second one follows!",
        "Third?",
    ]
    assert all(p == 0 for p, _ in parts)


def test_split_sentences_keeps_abbreviations_together():
    text = "Dr. Smith arrived at 9 a.m. He was early."
    sentences = [s for _, s in split_sentences(text)]
    assert sentences[0].startswith("Dr. Smith")
    assert len(sentences) == 2


def test_split_sentences_separates_paragraphs():
    text = "One. Two.\n\nThree. Four."
    parts = split_sentences(text)
    assert parts[0][0] == 0 and parts[-1][0] == 1


def test_split_sentences_handles_missing_space_after_punctuation():
    text = (
        "What does self-discipline look like at work?Sometimes it is the ability "
        "to resist temptation.Other times it is the ability to persist."
    )
    assert [s for _, s in split_sentences(text)] == [
        "What does self-discipline look like at work?",
        "Sometimes it is the ability to resist temptation.",
        "Other times it is the ability to persist.",
    ]


def test_iter_analyses_emits_in_sentence_order(monkeypatch):
    segments = [(0, f"First sentence {i}.") for i in range(6)]

    class _Agent:
        def analyze_batch_with_status(self, texts, level, context=None):
            if texts[0] == "First sentence 0.":
                time.sleep(0.3)
            return [(object(), True) for _ in texts]

    class _Tuner:
        def current(self):
            return 2, 2

    monkeypatch.setattr(reading_service, "get_batch_tuner", lambda: _Tuner())

    got = [
        index
        for index, _, _ in reading_service._iter_analyses(
            _Agent(), segments, "CET6", "Order"
        )
    ]
    assert got == list(range(6))


def test_chunk_indexes_runs_first_sentence_alone():
    assert reading_service._chunk_indexes(5, 4) == [[0], [1, 2, 3, 4]]
    assert reading_service._chunk_indexes(22, 4) == [
        [0], [1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12],
        [13, 14, 15, 16], [17, 18, 19, 20], [21],
    ]
    assert reading_service._chunk_indexes(3, 4) == [[0], [1, 2]]
    assert reading_service._chunk_indexes(4, 4) == [[0], [1, 2, 3]]


def test_split_sentences_drops_non_english_lines():
    text = "2026 年 6 月英语六级真题\n\nEnglish only here. Second one follows."
    assert [s for _, s in split_sentences(text)] == [
        "English only here.",
        "Second one follows.",
    ]


def test_split_sentences_drops_paragraph_markers():
    text = "A.\n\nFive hundred years ago, forests covered the land. B.\n\nBut that soon changed."
    assert [s for _, s in split_sentences(text)] == [
        "Five hundred years ago, forests covered the land.",
        "But that soon changed.",
    ]
    assert [(p, s) for p, s in split_sentences("C. Only this sentence stays.")] == [
        (0, "Only this sentence stays.")
    ]
    assert split_sentences("(A)") == []
    assert [s for _, s in split_sentences("II. Third section text.")] == [
        "Third section text."
    ]


def test_upload_drops_chinese_lines_but_keeps_inline_gloss(auth_client):
    text = (
        "中文标题\n\n"
        "Schools are a microcosm (缩影) of society.\n\n"
        "中文译文段落。"
    )
    upload = auth_client.post(
        "/api/reading/materials/upload",
        files={"file": ("bilingual.txt", text.encode("utf-8"), "text/plain")},
        data={"title": "Bilingual"},
    )
    assert upload.status_code == 201
    assert upload.json()["content"] == "Schools are a microcosm (缩影) of society."


def test_open_material_ignores_cache_from_old_splitting(auth_client):
    text = "First one here. Second one follows! Third?"
    content_id = auth_client.post(
        "/api/reading/materials/upload",
        files={"file": ("stale.txt", text.encode("utf-8"), "text/plain")},
        data={"title": "Stale"},
    ).json()["id"]

    from app.core.database import SessionLocal
    from app.models.content import UserContent

    db = SessionLocal()
    try:
        stale = json.dumps(
            [{"index": 0, "paragraph": 0, "text": text, "translation": ""}],
            ensure_ascii=False,
        )
        db.get(UserContent, content_id).sentences_json = stale
        db.commit()
    finally:
        db.close()

    detail = auth_client.get(f"/api/reading/materials/content/{content_id}").json()
    assert detail["sentences"] == []

    analyzed = auth_client.post(
        f"/api/reading/materials/content/{content_id}/analyze"
    ).json()
    assert [s["text"] for s in analyzed["sentences"]] == [
        "First one here.",
        "Second one follows!",
        "Third?",
    ]


def test_lemmatize_irregular_and_suffixes():
    assert lemmatize("went") == "go"
    assert lemmatize("children") == "child"
    assert lemmatize("changed") == "change"
    assert lemmatize("studies") == "study"
    assert lemmatize("running") == "run"
    assert lemmatize("business") == "business"
    assert lemmatize("class") == "class"


def test_analyze_article_returns_sentences_with_words_and_phrases(auth_client):
    response = auth_client.post("/api/reading/materials/article/1/analyze")
    assert response.status_code == 200

    data = response.json()
    sentences = data["sentences"]
    assert len(sentences) > 1

    first = sentences[0]
    assert first["text"]
    assert first["index"] == 0
    assert any("Present Perfect" == g["point"] for g in first["grammar"]) or first["grammar"]
    assert first["phrases"], "应能识别出固定搭配"
    assert first["words"], "应能挑出重点单词"

    for word in first["words"]:
        assert word["lemma"]


def test_analyze_is_cached(auth_client):
    first = auth_client.post("/api/reading/materials/article/1/analyze").json()
    second = auth_client.post("/api/reading/materials/article/1/analyze").json()
    assert len(first["sentences"]) == len(second["sentences"])


def test_materials_list_covers_platform_and_shared(auth_client):
    rows = auth_client.get("/api/reading/materials?source=platform").json()
    assert rows and all(r["source"] == "platform" for r in rows)


def test_upload_then_read_and_notes(auth_client):
    text = (
        "Learning a language takes time. "
        "You should adapt to new tools and pay attention to feedback."
    )
    upload = auth_client.post(
        "/api/reading/materials/upload",
        files={"file": ("note.txt", text.encode("utf-8"), "text/plain")},
        data={"title": "My Reading"},
    )
    assert upload.status_code == 201
    material = upload.json()
    assert material["is_mine"] is True
    content_id = material["id"]

    analyzed = auth_client.post(
        f"/api/reading/materials/content/{content_id}/analyze"
    ).json()
    assert len(analyzed["sentences"]) == 2

    note = auth_client.post(
        f"/api/reading/materials/content/{content_id}/notes",
        json={
            "sentence_index": 1,
            "kind": "phrase",
            "text": "adapt to",
            "meaning": "适应",
            "color": "green",
        },
    )
    assert note.status_code == 201
    note_id = note.json()["id"]
    assert note.json()["in_vocabulary"] is False

    detail = auth_client.get(f"/api/reading/materials/content/{content_id}").json()
    assert detail["note_count"] == 1
    second = detail["sentences"][1]
    assert any(n["text"] == "adapt to" for n in second["notes"])

    promoted = auth_client.post(f"/api/reading/notes/{note_id}/to-vocabulary")
    assert promoted.status_code == 200
    assert promoted.json()["in_vocabulary"] is True

    assert auth_client.delete(f"/api/reading/notes/{note_id}").status_code == 204
    assert auth_client.get(f"/api/reading/materials/content/{content_id}").json()["note_count"] == 0


def test_unpublished_content_is_private_until_shared(auth_client, client):
    text = "This sentence is private. Only the owner can read it."

    upload = auth_client.post(
        "/api/reading/materials/upload",
        files={"file": ("private.txt", text.encode("utf-8"), "text/plain")},
        data={"title": "Private"},
    ).json()
    content_id = upload["id"]

    other = client.post("/api/auth/register", json=_article_payload()).json()
    headers = {"Authorization": f"Bearer {other['access_token']}"}
    assert (
        client.get(f"/api/reading/materials/content/{content_id}", headers=headers).status_code
        == 403
    )

    assert auth_client.post(
        f"/api/reading/materials/content/{content_id}/publish?is_public=true"
    ).status_code == 200

    shared = client.get(f"/api/reading/materials/content/{content_id}", headers=headers)
    assert shared.status_code == 200
    assert shared.json()["source"] == "shared"

    client.post(
        f"/api/reading/materials/content/{content_id}/analyze", headers=headers
    )
    mine = client.post(
        f"/api/reading/materials/content/{content_id}/notes",
        headers=headers,
        json={"sentence_index": 0, "kind": "word", "text": "private", "color": "rose"},
    )
    assert mine.status_code == 201

    owner_detail = auth_client.get(
        f"/api/reading/materials/content/{content_id}"
    ).json()
    assert owner_detail["note_count"] == 0

    auth_client.post(f"/api/reading/materials/content/{content_id}/publish?is_public=false")
    assert (
        client.get(f"/api/reading/materials/content/{content_id}", headers=headers).status_code
        == 403
    )


def test_export_pdf_returns_pdf_bytes(auth_client):
    response = auth_client.get("/api/reading/materials/article/1/export.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    assert len(response.content) > 1000


def test_annotation_cell_keeps_anchor_and_body():
    cell = pdf_service._annotation_cell(
        [
            {
                "kind": "note",
                "text": "significantly",
                "meaning": "",
                "note": "副词，修饰 changed",
                "color": "amber",
            }
        ],
        ParagraphStyle("anno"),
    )
    assert "significantly" in cell.text
    assert "副词，修饰 changed" in cell.text


def test_annotation_cell_keeps_every_field_and_drops_category_text():
    cell = pdf_service._annotation_cell(
        [
            {
                "kind": "word",
                "text": "development",
                "meaning": "发展；进展",
                "note": "名词",
                "color": "blue",
            }
        ],
        ParagraphStyle("anno"),
    )
    assert "development" in cell.text
    assert "发展；进展" in cell.text
    assert "名词" in cell.text
    assert "生词" not in cell.text


def test_annotation_cell_skips_empty_notes():
    cell = pdf_service._annotation_cell(
        [{"kind": "word", "text": "", "meaning": "", "note": "", "color": "blue"}],
        ParagraphStyle("anno"),
    )
    assert cell.text == ""


def test_highlight_prefers_stored_offsets():
    sentence = "The bank raised rates, then the bank cut them."
    start = sentence.rindex("bank")
    assert start == 32
    html = pdf_service._highlight_sentence(
        sentence,
        [
            {
                "kind": "word",
                "text": "bank",
                "color": "blue",
                "start_offset": start,
                "end_offset": start + 4,
            }
        ],
    )
    assert html.startswith("The bank raised rates, then the ")
    assert html.count("backColor") == 1
    assert html.endswith('<font backColor="#dbeafe">bank</font> cut them.')


def test_highlight_falls_back_to_text_for_legacy_notes():
    html = pdf_service._highlight_sentence(
        "The rapid development of AI.",
        [
            {
                "kind": "word",
                "text": "development",
                "color": "blue",
                "start_offset": 0,
                "end_offset": 0,
            }
        ],
    )
    assert '<font backColor="#dbeafe">development</font>' in html


def test_highlight_covers_note_kind_with_offsets():
    sentence = "The rapid development of AI."
    html = pdf_service._highlight_sentence(
        sentence,
        [
            {
                "kind": "note",
                "text": "development",
                "color": "rose",
                "start_offset": 10,
                "end_offset": 21,
            }
        ],
    )
    assert '<font backColor="#ffe4e6">development</font>' in html


def test_highlight_does_not_paint_sentence_note_body():
    sentence = "The rapid development of AI."
    html = pdf_service._highlight_sentence(
        sentence,
        [
            {
                "kind": "note",
                "text": "这句是总起",
                "color": "violet",
                "start_offset": 0,
                "end_offset": 0,
            }
        ],
    )
    assert html == sentence
    assert "backColor" not in html


def test_highlight_ignores_out_of_range_offsets():
    html = pdf_service._highlight_sentence(
        "Hello world.",
        [
            {
                "kind": "word",
                "text": "Hello",
                "color": "blue",
                "start_offset": 0,
                "end_offset": 999,
            }
        ],
    )
    assert '<font backColor="#dbeafe">Hello</font>' in html


def test_export_pdf_contains_user_annotations(auth_client):
    from pypdf import PdfReader

    content_id = _upload_and_analyze(
        auth_client, "The rapid development of AI is significant."
    )
    created = auth_client.post(
        f"/api/reading/materials/content/{content_id}/notes",
        json={
            "sentence_index": 0,
            "kind": "note",
            "text": "development",
            "note": "名词，发展",
            "color": "violet",
            "start_offset": 10,
            "end_offset": 21,
        },
    )
    assert created.status_code == 201

    response = auth_client.get(f"/api/reading/materials/content/{content_id}/export.pdf")
    assert response.status_code == 200

    reader = PdfReader(io.BytesIO(response.content))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "development" in text
    assert "名词，发展" in text
    assert "批注" in text


def test_unknown_material_returns_404(auth_client):
    assert auth_client.get("/api/reading/materials/article/999999").status_code == 404
    assert auth_client.get("/api/reading/materials/content/999999").status_code == 404


def _upload_and_analyze(client, text: str) -> int:
    upload = client.post(
        "/api/reading/materials/upload",
        files={"file": ("offsets.txt", text.encode("utf-8"), "text/plain")},
        data={"title": "Offsets"},
    ).json()
    content_id = upload["id"]
    client.post(f"/api/reading/materials/content/{content_id}/analyze")
    return content_id


def test_note_offsets_round_trip(auth_client):
    content_id = _upload_and_analyze(
        auth_client, "The bank raised rates. I sat by the bank."
    )

    created = auth_client.post(
        f"/api/reading/materials/content/{content_id}/notes",
        json={
            "sentence_index": 1,
            "kind": "word",
            "text": "bank",
            "meaning": "河岸",
            "color": "blue",
            "start_offset": 15,
            "end_offset": 19,
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert (body["start_offset"], body["end_offset"]) == (15, 19)

    detail = auth_client.get(f"/api/reading/materials/content/{content_id}").json()
    note = detail["sentences"][1]["notes"][0]
    assert (note["start_offset"], note["end_offset"]) == (15, 19)

    legacy = auth_client.post(
        f"/api/reading/materials/content/{content_id}/notes",
        json={"sentence_index": 0, "kind": "word", "text": "bank"},
    ).json()
    assert (legacy["start_offset"], legacy["end_offset"]) == (0, 0)


def test_suggest_returns_offsets_matching_sentence(auth_client):
    content_id = _upload_and_analyze(
        auth_client, "These systems analyse mistakes and adjust the difficulty."
    )
    response = auth_client.post(
        f"/api/reading/materials/content/{content_id}/suggest",
        json={"sentence_indexes": [0]},
    )
    assert response.status_code == 200
    body = response.json()

    detail = auth_client.get(f"/api/reading/materials/content/{content_id}").json()
    sentence = detail["sentences"][0]["text"]

    for index, spans in body["by_sentence"].items():
        assert int(index) == 0
        for span in spans:
            start, end = span["start_offset"], span["end_offset"]
            assert 0 <= start < end <= len(sentence)
            assert sentence[start:end] == span["text"]
            assert span["color"] in {"blue", "green", "amber", "rose", "violet"}


def test_suggest_stream_sends_one_event_per_sentence(auth_client):
    content_id = _upload_and_analyze(
        auth_client,
        "These systems analyse mistakes and adjust the difficulty. "
        "Learners then revise what went wrong.",
    )
    with auth_client.stream(
        "GET", f"/api/reading/materials/content/{content_id}/suggest/stream"
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    events = _parse_sse(body)
    name, start = events[0]
    assert name == "start"
    assert start["total"] == 2

    assert events[-1][0] == "done"
    assert events[-1][1]["sentence_count"] == 2

    streamed = [data for event, data in events if event == "sentence"]
    assert sorted(item["index"] for item in streamed) == [0, 1]

    detail = auth_client.get(f"/api/reading/materials/content/{content_id}").json()
    for item in streamed:
        text = detail["sentences"][item["index"]]["text"]
        for span in item["spans"]:
            assert text[span["start_offset"] : span["end_offset"]] == span["text"]


def test_suggest_stream_requires_login(client):
    assert (
        client.get("/api/reading/materials/article/1/suggest/stream").status_code == 401
    )


def test_suggest_drops_spans_not_in_sentence():
    from app.ai.agents.annotation_agent import AnnotationAgent
    from app.ai.schemas import AnnotationSuggestions, SuggestedSpan

    agent = AnnotationAgent.__new__(AnnotationAgent)
    sentence = "The learner can't adapt to new tools easily."

    cleaned = agent._validate(
        AnnotationSuggestions(
            spans=[
                SuggestedSpan(text="cannot adapt", color="blue"),
                SuggestedSpan(text="ADAPT TO", color="green"),
                SuggestedSpan(text="a phrase that is not here", color="blue"),
                SuggestedSpan(text=sentence, color="amber"),
                SuggestedSpan(text="new tools", color="chartreuse"),
            ]
        ),
        sentence,
    )

    assert [s.text for s in cleaned.spans] == ["adapt to", "new tools"]
    assert cleaned.spans[0].color == "green"
    assert cleaned.spans[1].color == "blue"


def test_build_suggestions_offsets_repeated_words():
    from app.services.reading_service import build_suggestions

    sentence = "The bank raised rates and the bank stayed open."
    spans = build_suggestions(
        sentence,
        [
            type("S", (), {"text": "bank", "color": "blue", "reason": ""})(),
            type("S", (), {"text": "bank", "color": "blue", "reason": ""})(),
        ],
    )
    assert len(spans) == 2
    assert spans[0]["start_offset"] == 4
    assert spans[1]["start_offset"] == 30
    for span in spans:
        assert sentence[span["start_offset"] : span["end_offset"]] == "bank"


def test_update_note_color_keeps_body(auth_client):
    content_id = _upload_and_analyze(auth_client, "One sentence only here.")

    note = auth_client.post(
        f"/api/reading/materials/content/{content_id}/notes",
        json={
            "sentence_index": 0,
            "kind": "note",
            "text": "One sentence",
            "note": "这句是总起",
            "color": "blue",
        },
    ).json()

    recolored = auth_client.patch(
        f"/api/reading/notes/{note['id']}", json={"color": "rose"}
    )
    assert recolored.status_code == 200
    assert recolored.json()["color"] == "rose"
    assert recolored.json()["note"] == "这句是总起"

    updated = auth_client.patch(
        f"/api/reading/notes/{note['id']}", json={"note": "换个说法"}
    ).json()
    assert updated["note"] == "换个说法"
    assert updated["color"] == "rose"


def test_update_note_meaning_can_be_fixed(auth_client):
    content_id = _upload_and_analyze(auth_client, "One sentence only here.")

    note = auth_client.post(
        f"/api/reading/materials/content/{content_id}/notes",
        json={
            "sentence_index": 0,
            "kind": "word",
            "text": "here",
            "meaning": "这里",
            "color": "amber",
        },
    ).json()

    fixed = auth_client.patch(
        f"/api/reading/notes/{note['id']}", json={"meaning": "在这里（强调地点）"}
    )
    assert fixed.status_code == 200
    assert fixed.json()["meaning"] == "在这里（强调地点）"
    assert fixed.json()["text"] == "here"
    assert fixed.json()["color"] == "amber"

    cleared = auth_client.patch(
        f"/api/reading/notes/{note['id']}", json={"meaning": ""}
    ).json()
    assert cleared["meaning"] == ""
    assert cleared["text"] == "here"


def test_highlight_rect_is_rounded():
    calls: list[tuple] = []

    class FakeCanvas:
        def roundRect(self, *args, **kwargs):
            calls.append(("roundRect", args, kwargs))

    def original_rect(*args, **kwargs):
        calls.append(("rect", args, kwargs))

    font_size, leading = 10.8, 16.42
    replace = pdf_service._rounded_rect_replacer(
        FakeCanvas(), original_rect, font_size=font_size, leading=leading
    )

    replace(10, 20, 40, leading, stroke=0, fill=1)
    name, args, kwargs = calls[-1]
    assert name == "roundRect"
    x, y, width, height, radius = args
    assert (x, width) == (10, 40)
    assert radius == pdf_service.HIGHLIGHT_RADIUS
    assert kwargs == {"stroke": 0, "fill": 1}

    baseline = 20 + leading - font_size
    assert height == pytest.approx(font_size * pdf_service.HIGHLIGHT_HEIGHT_RATIO)
    assert y == pytest.approx(baseline - font_size * pdf_service.HIGHLIGHT_DROP_RATIO)
    assert height < leading

    replace(0, 0, 100, 30, stroke=0, fill=0)
    assert calls[-1][0] == "rect"
    replace(0, 0, 100, 30, stroke=1, fill=1)
    assert calls[-1][0] == "rect"


def test_highlight_box_is_shorter_than_the_line_height():
    font_size, leading = pdf_service.FS_BODY, pdf_service.FS_BODY * pdf_service.LEAD_BODY
    assert font_size * pdf_service.HIGHLIGHT_HEIGHT_RATIO < leading


def test_highlight_radius_is_clamped_to_narrow_boxes():
    calls: list[tuple] = []

    class FakeCanvas:
        def roundRect(self, *args, **kwargs):
            calls.append(args)

    replace = pdf_service._rounded_rect_replacer(
        FakeCanvas(), lambda *a, **k: None, font_size=10.8, leading=16.42
    )
    replace(0, 0, 4, 16.42, stroke=0, fill=1)
    assert calls[-1][4] == 2


def test_same_word_is_only_noted_once(auth_client):
    text = "Learning a language takes time. You should adapt to new tools and adapt fast."
    upload = auth_client.post(
        "/api/reading/materials/upload",
        files={"file": ("dupe.txt", text.encode("utf-8"), "text/plain")},
        data={"title": "Dupe Reading"},
    )
    assert upload.status_code == 201
    content_id = upload.json()["id"]
    auth_client.post(f"/api/reading/materials/content/{content_id}/analyze")

    url = f"/api/reading/materials/content/{content_id}/notes"

    def add(**payload):
        return auth_client.post(url, json={"sentence_index": 1, **payload})

    first = add(kind="word", text="adapt", meaning="适应", color="blue")
    assert first.status_code == 201

    again = add(kind="word", text="adapt", meaning="适应", color="blue")
    assert again.status_code == 201
    assert again.json()["id"] == first.json()["id"]

    assert add(kind="word", text="Adapt").json()["id"] == first.json()["id"]

    phrase = add(kind="phrase", text="pay attention to", color="green")
    assert phrase.json()["id"] != first.json()["id"]

    span_a = add(kind="word", text="adapt", start_offset=11, end_offset=16)
    span_b = add(kind="word", text="adapt", start_offset=33, end_offset=38)
    assert span_a.json()["id"] != span_b.json()["id"]
    assert span_a.json()["id"] != first.json()["id"]

    free = add(kind="note", text="adapt", note="这里可以换成 adjust")
    assert free.status_code == 201

    detail = auth_client.get(f"/api/reading/materials/content/{content_id}").json()
    assert detail["note_count"] == 5

    assert add(kind="word", text="adapt", sentence_index=0).status_code == 201
    assert (
        auth_client.get(f"/api/reading/materials/content/{content_id}").json()["note_count"]
        == 6
    )


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in body.split("\n\n"):
        name = ""
        payload = ""
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                payload = line[len("data: ") :]
        if name and payload:
            events.append((name, json.loads(payload)))
    return events


def test_analyze_stream_sends_skeleton_then_one_event_per_sentence(auth_client):
    with auth_client.stream(
        "GET", "/api/reading/materials/article/1/analyze/stream"
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    events = _parse_sse(body)
    assert events, "至少要有 start 和 done"

    name, start = events[0]
    assert name == "start"
    assert start["total"] > 1
    assert [item["index"] for item in start["sentences"]] == list(range(start["total"]))
    assert start["sentences"][0]["text"]

    assert events[-1][0] == "done"
    assert events[-1][1]["generated"] is True

    streamed = [data["sentence"] for event, data in events if event == "sentence"]
    assert len(streamed) == start["total"]
    assert [item["index"] for item in streamed] == list(range(start["total"]))
    assert all(item["notes"] == [] for item in streamed)
    assert all(item["text"] for item in streamed)


def test_analyze_stream_persists_result_for_next_open(auth_client):
    text = "Learning a language takes time. You should adapt to new tools."
    content_id = auth_client.post(
        "/api/reading/materials/upload",
        files={"file": ("stream.txt", text.encode("utf-8"), "text/plain")},
        data={"title": "Stream me"},
    ).json()["id"]

    with auth_client.stream(
        "GET", f"/api/reading/materials/content/{content_id}/analyze/stream"
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert [name for name, _ in _parse_sse(body)][-1] == "done"

    detail = auth_client.get(f"/api/reading/materials/content/{content_id}").json()
    assert len(detail["sentences"]) == 2
    assert detail["sentences"][0]["text"].startswith("Learning")


def test_reopen_keeps_saved_analysis_without_calling_model(auth_client, monkeypatch):
    text = "Learning a language takes time. You should adapt to new tools."
    content_id = auth_client.post(
        "/api/reading/materials/upload",
        files={"file": ("remember.txt", text.encode("utf-8"), "text/plain")},
        data={"title": "Remember me"},
    ).json()["id"]

    first = auth_client.post(f"/api/reading/materials/content/{content_id}/analyze")
    assert first.status_code == 200
    remembered = first.json()["sentences"][0]["translation"]

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("再次打开不该再分析")

    monkeypatch.setattr(reading_service, "SentenceAgent", fail_if_called)

    detail = auth_client.get(f"/api/reading/materials/content/{content_id}").json()
    assert detail["sentences"][0]["translation"] == remembered

    again = auth_client.post(f"/api/reading/materials/content/{content_id}/analyze")
    assert again.status_code == 200
    assert again.json()["sentences"][0]["translation"] == remembered


def test_stream_keeps_analysis_when_client_drops_before_done(auth_client, monkeypatch):
    real_store = reading_service._store_sentences

    def store_then_drop(db, document, blob):
        real_store(db, document, blob)
        db.commit()
        raise RuntimeError("客户端已断开")

    monkeypatch.setattr(reading_service, "_store_sentences", store_then_drop)

    text = "Learning a language takes time. You should adapt to new tools."
    content_id = auth_client.post(
        "/api/reading/materials/upload",
        files={"file": ("drop.txt", text.encode("utf-8"), "text/plain")},
        data={"title": "Dropped"},
    ).json()["id"]

    with auth_client.stream(
        "GET", f"/api/reading/materials/content/{content_id}/analyze/stream"
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    events = _parse_sse(body)
    assert any(name == "sentence" for name, _ in events)
    assert events[-1] == ("error", {"detail": "生成失败：客户端已断开"})

    detail = auth_client.get(f"/api/reading/materials/content/{content_id}").json()
    assert [item["text"] for item in detail["sentences"]] == [
        "Learning a language takes time.",
        "You should adapt to new tools.",
    ]


def test_failed_model_result_is_not_remembered(auth_client, monkeypatch):
    from app.ai.provider import AIProviderError

    text = "Learning a language takes time."
    content_id = auth_client.post(
        "/api/reading/materials/upload",
        files={"file": ("fail.txt", text.encode("utf-8"), "text/plain")},
        data={"title": "Failed"},
    ).json()["id"]

    class _Down:
        is_mock = False
        signature = "down"

        def complete_json(self, *_args, **_kwargs):
            raise AIProviderError("模型调用失败：timed out")

        def complete_json_fast(self, *_args, **_kwargs):
            raise AIProviderError("模型调用失败：timed out")

    monkeypatch.setattr(
        "app.services.ai_config_service.get_provider_for",
        lambda *_args, **_kwargs: _Down(),
    )

    analyzed = auth_client.post(f"/api/reading/materials/content/{content_id}/analyze")
    assert analyzed.status_code == 200
    assert analyzed.json()["generated"] is False

    detail = auth_client.get(f"/api/reading/materials/content/{content_id}").json()
    assert detail["sentences"] == []


def test_analyze_stream_requires_login(client):
    assert (
        client.get("/api/reading/materials/article/1/analyze/stream").status_code == 401
    )


def test_analyze_stream_404_for_missing_material(auth_client):
    assert (
        auth_client.get("/api/reading/materials/article/9999/analyze/stream").status_code
        == 404
    )


def test_suggest_keeps_using_the_users_provider(auth_client, monkeypatch):
    """标注建议这条链路必须把用户配置的模型透传给逐句讲解。

    漏传 provider 时会回退到全局 mock，离线规则引擎的结果还会被写进
    sentences_json，让用户之后一直看不到真实译文。
    """
    from app.ai.schemas import AnnotationSuggestions, SentenceAnalysis

    text = "Learning a language takes time."
    content_id = auth_client.post(
        "/api/reading/materials/upload",
        files={"file": ("stub.txt", text.encode("utf-8"), "text/plain")},
        data={"title": "StubMaterial"},
    ).json()["id"]

    class _Stub:
        is_mock = False
        signature = "stub"
        max_tokens = 1500

        def complete_json(self, _system, _user, schema, max_tokens=None):
            if schema is AnnotationSuggestions:
                return {"spans": []}
            assert schema is SentenceAnalysis
            return {"sentence": text, "chinese_meaning": "标记译文"}

        def complete_json_fast(self, system, user, schema, max_tokens=None):
            return self.complete_json(system, user, schema, max_tokens)

    monkeypatch.setattr(
        "app.services.ai_config_service.get_provider_for",
        lambda *_args, **_kwargs: _Stub(),
    )

    suggested = auth_client.post(
        f"/api/reading/materials/content/{content_id}/suggest",
        json={"sentence_indexes": [0]},
    )
    assert suggested.status_code == 200

    detail = auth_client.get(f"/api/reading/materials/content/{content_id}").json()
    assert detail["sentences"][0]["translation"] == "标记译文"
