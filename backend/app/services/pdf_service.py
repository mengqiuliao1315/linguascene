import io
import os
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


INK = "#0f172a"
BODY = "#1e293b"
MUTED = "#64748b"
FAINT = "#94a3b8"
RULE = "#e2e8f0"
SOFT_RULE = "#f1f5f9"
BRAND = "#2563eb"
BRAND_SOFT = "#eff6ff"
PANEL = "#f8fafc"

HIGHLIGHT_COLORS = {
    "blue": "#dbeafe",
    "green": "#dcfce7",
    "amber": "#fef3c7",
    "rose": "#ffe4e6",
    "violet": "#ede9fe",
}

HIGHLIGHT_RADIUS = 3

HIGHLIGHT_HEIGHT_RATIO = 1.25
HIGHLIGHT_DROP_RATIO = 0.25

ANNO_ROW_PAD = 1.5

ANNO_ROW_GAP = 1


PAGE_W, PAGE_H = A4
MARGIN_X = 15 * mm
MARGIN_TOP = 13 * mm
MARGIN_BOTTOM = 15 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X

COL_NUM = 9 * mm
COL_ANNO = 60 * mm
COL_BODY = CONTENT_W - COL_NUM - COL_ANNO

ANNO_GAP = 5
ANNO_CARD_W = COL_ANNO - ANNO_GAP

FS_TITLE = 18
FS_BODY = 11.5
FS_TRANS = 9.5
FS_TERM = 8.8
FS_MEAN = 8.2
FS_USER = 7.8
FS_META = 8.2
FS_HEAD = 7.4
FS_FOOT = 7.2

LEAD_BODY = 1.52
LEAD_ANNO = 11

_FONT_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc"),
    ("C:/Windows/Fonts/Deng.ttf", "C:/Windows/Fonts/Dengb.ttf"),
    ("C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simhei.ttf"),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
     "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
     "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
     "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/PingFang.ttc"),
)


def _register_ttf_pair(
    candidates: tuple[tuple[str, str], ...],
    prefix: str,
    env_regular: str,
    env_bold: str,
) -> tuple[str, str] | None:
    items: list[tuple[str, str]] = []
    if env_regular:
        items.append((env_regular, env_bold or env_regular))
    items.extend(candidates)

    for index, (regular, bold) in enumerate(items):
        if not regular or not Path(regular).exists():
            continue
        regular_name = f"{prefix}{index}"
        bold_name = f"{prefix}{index}Bold"
        try:
            pdfmetrics.registerFont(TTFont(regular_name, regular, subfontIndex=0))
        except Exception:  # noqa: BLE001 - 换下一个候选
            continue
        if bold and bold != regular and Path(bold).exists():
            try:
                pdfmetrics.registerFont(TTFont(bold_name, bold, subfontIndex=0))
            except Exception:  # noqa: BLE001 - 没有粗体就用常规代替
                bold_name = regular_name
        else:
            bold_name = regular_name
        pdfmetrics.registerFontFamily(
            regular_name, normal=regular_name, bold=bold_name,
            italic=regular_name, boldItalic=bold_name,
        )
        return regular_name, bold_name
    return None


def _register_fonts() -> tuple[str, str]:
    pair = _register_ttf_pair(
        _FONT_CANDIDATES,
        "ReadingCJK",
        os.environ.get("READING_PDF_FONT", "").strip(),
        os.environ.get("READING_PDF_FONT_BOLD", "").strip(),
    )
    if pair:
        return pair

    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    except Exception:  # noqa: BLE001 - 字体不可用时退回内置字体
        return "Helvetica", "Helvetica"
    return "STSong-Light", "STSong-Light"


def _escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


class _NumberBadge(Flowable):

    def __init__(
        self,
        number: int,
        font_name: str,
        diameter: float = 5.4 * mm,
        font_size: float = 7.6,
        fill: str = BRAND_SOFT,
        stroke: str = "#dbeafe",
        text_color: str = BRAND,
    ) -> None:
        super().__init__()
        self.number = number
        self.font_name = font_name
        self.font_size = font_size
        self.fill = fill
        self.stroke = stroke
        self.text_color = text_color
        self.width = diameter
        self.height = diameter

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:
        return self.width, self.height

    def draw(self) -> None:
        radius = self.width / 2.0
        canvas = self.canv
        canvas.saveState()
        canvas.setFillColor(colors.HexColor(self.fill))
        canvas.setStrokeColor(colors.HexColor(self.stroke))
        canvas.setLineWidth(0.4)
        canvas.circle(radius, radius, radius - 0.25, stroke=1, fill=1)
        canvas.setFillColor(colors.HexColor(self.text_color))
        canvas.setFont(self.font_name, self.font_size)
        canvas.drawCentredString(
            radius, radius - self.font_size * 0.34, str(self.number)
        )
        canvas.restoreState()


class _AnnotationCards(Table):

    def __init__(self, data: list[list], col_widths: list[float], text: str) -> None:
        super().__init__(data, colWidths=col_widths)
        self._text = text

    @property
    def text(self) -> str:
        return self._text


def _rounded_rect_replacer(
    canvas, original_rect, *, font_size: float, leading: float
):

    def rect(x, y, width, height, stroke=1, fill=0, **kwargs):  # noqa: ANN001
        if stroke == 0 and fill == 1:
            baseline = y + height - font_size
            box_height = font_size * HIGHLIGHT_HEIGHT_RATIO
            box_bottom = baseline - font_size * HIGHLIGHT_DROP_RATIO
            radius = min(HIGHLIGHT_RADIUS, width / 2, box_height / 2)
            canvas.roundRect(
                x, box_bottom, width, box_height, radius, stroke=0, fill=1
            )
            return None
        return original_rect(x, y, width, height, stroke=stroke, fill=fill, **kwargs)

    return rect


class _RoundedHighlightParagraph(Paragraph):

    def draw(self) -> None:
        canvas = self.canv
        original_rect = canvas.rect
        canvas.rect = _rounded_rect_replacer(
            canvas,
            original_rect,
            font_size=self.style.fontSize,
            leading=self.style.leading,
        )
        try:
            super().draw()
        finally:
            canvas.rect = original_rect


def _note_spans(sentence: str, notes: list[dict]) -> list[tuple[int, int, str, int]]:
    spans: list[tuple[int, int, str, int]] = []
    for order, note in enumerate(notes):
        color = note.get("color") or "blue"
        start = note.get("start_offset") or 0
        end = note.get("end_offset") or 0
        if 0 <= start < end <= len(sentence):
            spans.append((start, end, color, order))
            continue

        text = (note.get("text") or "").strip()
        if note.get("kind") not in ("word", "phrase") or not text:
            continue
        pattern = re.compile(
            r"(?<![A-Za-z])" + re.escape(text) + r"(?![A-Za-z])", re.IGNORECASE
        )
        for match in pattern.finditer(sentence):
            spans.append((match.start(), match.end(), color, order))
    return spans


def _highlight_sentence(sentence: str, notes: list[dict]) -> str:
    spans = _note_spans(sentence, notes)
    if not spans:
        return _escape(sentence)

    boundaries = {0, len(sentence)}
    for start, end, _, _ in spans:
        boundaries.add(start)
        boundaries.add(end)
    ordered = sorted(boundaries)

    html: list[str] = []
    for left, right in zip(ordered, ordered[1:]):
        if right <= left:
            continue
        covering = [s for s in spans if s[0] <= left and s[1] >= right]
        color = max(covering, key=lambda s: (s[0], s[3]))[2] if covering else None
        chunk = _escape(sentence[left:right])
        if color:
            hex_color = HIGHLIGHT_COLORS.get(color, HIGHLIGHT_COLORS["blue"])
            html.append(f'<font backColor="{hex_color}">{chunk}</font>')
        else:
            html.append(chunk)
    return "".join(html)


def _annotation_cell(
    notes: list[dict],
    body_style: ParagraphStyle,
    width: float = ANNO_CARD_W,
):
    if not notes:
        return Paragraph("", body_style)

    rows: list[list] = []
    card_rows: list[int] = []
    texts: list[str] = []

    for note in notes:
        text = (note.get("text") or "").strip()
        meaning = (note.get("meaning") or "").strip()
        body = (note.get("note") or "").strip()
        if not text and not meaning and not body:
            continue

        line = ""
        if text:
            line += f'<font size="{FS_TERM}" color="{INK}"><b>{_escape(text)}</b></font>'
        if meaning:
            line += ("&#160;&#160;" if line else "") + (
                f'<font size="{FS_MEAN}" color="#475569">{_escape(meaning)}</font>'
            )
        if body:
            line += ("<br/>" if line else "") + (
                f'<font size="{FS_USER}" color="{MUTED}">{_escape(body)}</font>'
            )

        if rows:
            rows.append([Spacer(1, ANNO_ROW_GAP)])
        card_rows.append(len(rows))
        rows.append([Paragraph(line, body_style)])
        texts.append(" ".join(p for p in (text, meaning, body) if p))

    if not rows:
        return Paragraph("", body_style)

    cards = _AnnotationCards(rows, [width], "\n".join(texts))
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]
    for row_index in card_rows:
        style += [
            ("TOPPADDING", (0, row_index), (0, row_index), ANNO_ROW_PAD),
            ("BOTTOMPADDING", (0, row_index), (0, row_index), ANNO_ROW_PAD),
        ]
    cards.setStyle(TableStyle(style))
    return cards


def _make_footer(font_name: str):

    def draw(canvas, doc) -> None:  # noqa: ANN001 - reportlab 回调签名
        canvas.saveState()
        baseline = 9 * mm
        canvas.setStrokeColor(colors.HexColor(RULE))
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN_X, baseline + 4 * mm, PAGE_W - MARGIN_X, baseline + 4 * mm)
        canvas.setFont(font_name, FS_FOOT)
        canvas.setFillColor(colors.HexColor(FAINT))
        canvas.drawRightString(PAGE_W - MARGIN_X, baseline, str(doc.page))
        canvas.restoreState()

    return draw


def build_reading_pdf(
    *,
    title: str,
    author: str,
    level: str,
    sentences: list[dict],
) -> bytes:
    font, bold_font = _register_fonts()
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=title,
        author=author,
        subject="精读导出",
        creator="LinguaScene",
    )

    eyebrow_style = ParagraphStyle(
        "eyebrow", fontName=font, fontSize=FS_FOOT, leading=10,
        textColor=colors.HexColor(BRAND),
    )
    title_style = ParagraphStyle(
        "title", fontName=bold_font, fontSize=FS_TITLE, leading=FS_TITLE * 1.3,
        textColor=colors.HexColor(INK),
    )
    meta_style = ParagraphStyle(
        "meta", fontName=font, fontSize=FS_META, leading=12,
        textColor=colors.HexColor(MUTED),
    )
    head_style = ParagraphStyle(
        "head", fontName=font, fontSize=FS_HEAD, leading=11,
        textColor=colors.HexColor(MUTED),
    )
    body_style = ParagraphStyle(
        "body", fontName=font, fontSize=FS_BODY, leading=FS_BODY * LEAD_BODY,
        alignment=TA_LEFT, textColor=colors.HexColor(BODY),
    )
    trans_style = ParagraphStyle(
        "trans", fontName=font, fontSize=FS_TRANS, leading=FS_TRANS * 1.5,
        textColor=colors.HexColor(MUTED),
    )
    anno_style = ParagraphStyle(
        "anno", fontName=font, fontSize=FS_MEAN, leading=LEAD_ANNO,
        textColor=colors.HexColor(BODY),
    )

    note_total = sum(len(s.get("notes") or []) for s in sentences)
    meta_bits = [_escape(author)]
    if level:
        meta_bits.append(
            f'<font backColor="{BRAND_SOFT}" color="{BRAND}">&#160;{_escape(level)}&#160;</font>'
        )
    meta_bits.append(f"{len(sentences)} 句")
    if note_total:
        meta_bits.append(f"{note_total} 条批注")

    header = Table(
        [[[
            Paragraph("LINGUASCENE 精读", eyebrow_style),
            Spacer(1, 3),
            Paragraph(_escape(title), title_style),
            Spacer(1, 5),
            Paragraph("　·　".join(meta_bits), meta_style),
        ]]],
        colWidths=[CONTENT_W],
    )
    header.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(PANEL)),
                ("LINEBEFORE", (0, 0), (0, 0), 3, colors.HexColor(BRAND)),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )

    story: list = [header, Spacer(1, 4 * mm)]

    show_anno = note_total > 0
    rows: list[list] = [
        [
            Paragraph("", head_style),
            Paragraph("原文", head_style),
            Paragraph("批注" if show_anno else "", head_style),
        ]
    ]
    for sentence in sentences:
        notes = sentence.get("notes") or []
        source = sentence.get("text", "") or ""

        cell: list = [
            _RoundedHighlightParagraph(_highlight_sentence(source, notes), body_style)
        ]
        if sentence.get("translation"):
            cell.append(Spacer(1, 1.4 * mm))
            cell.append(Paragraph(_escape(sentence["translation"]), trans_style))

        rows.append(
            [
                _NumberBadge(sentence.get("index", 0) + 1, bold_font),
                cell,
                _annotation_cell(notes, anno_style),
            ]
        )

    if len(rows) == 1:
        rows.append(
            [
                Paragraph("", head_style),
                Paragraph("", body_style),
                Paragraph("", anno_style),
            ]
        )

    table = Table(rows, colWidths=[COL_NUM, COL_BODY, COL_ANNO], repeatRows=1)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, 0), 0),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, -1), 5),
        ("LEFTPADDING", (1, 0), (1, -1), 4),
        ("RIGHTPADDING", (1, 0), (1, -1), 8),
        ("LEFTPADDING", (2, 0), (2, -1), ANNO_GAP),
        ("RIGHTPADDING", (2, 0), (2, -1), 0),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor(RULE)),
    ]
    if show_anno:
        style.append(("LINEBEFORE", (2, 1), (2, -1), 0.5, colors.HexColor(RULE)))
    for row_index in range(1, len(rows) - 1):
        style.append(
            ("LINEBELOW", (1, row_index), (1, row_index), 0.4, colors.HexColor(SOFT_RULE))
        )
    table.setStyle(TableStyle(style))
    story.append(table)

    footer = _make_footer(font)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
