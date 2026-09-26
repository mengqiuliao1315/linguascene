"""精读导出：正文在左，批注在右。

用 platypus 的两列表格排版，每行一句原文，右列放这句的全部用户批注。
批注过的词在原文里用底色标出。

排版约定（改样式时请一并遵守，别只改一处）：

* 英文正文用衬线体（Georgia 一类），中文释义/批注用无衬线黑体。
  中英混排时衬线管拉丁、黑体管汉字，是阅读材料最常见的一组搭配；
  单用一种字体的话，英文要么太方，要么中文发虚。
* 字号阶梯固定为 18 / 10.8 / 8.8 / 8.2 / 7.8 / 7.4，行距 ≥ 字号的 1.5 倍。
  正文行距不能再压，压到 1.4 以下长句会连成一片。
* 颜色只用 slate 灰阶 + 一个品牌蓝（#2563eb，与前端 brand-600 同值）。
  彩色只出现在正文里：被批注过的词按分类上色（HIGHLIGHT_COLORS），颜色即分类轴
  （生词/好句/语法/疑问/待复习），不能随手换。
* 右栏批注**只有黑白文字**：不印分类文字、不铺底色、不画分类色竖条。
  一条批注就是一行「词 + 释义 + 笔记」，导出是拿去打印的——省墨、省纸，
  也让整栏一眼能扫完。分类看正文高亮的颜色就够了，右栏再刷一遍颜色
  只是把一栏铺成噪声。

批注栏的字段必须和前端「本页批注」逐条对齐：用户划词写下的笔记，
text 是锚定的原文、note 才是正文，两个都要留——只留正文的话导出后
只剩一句"显著地"，读者根本不知道说的是哪个词。

字体优先嵌入系统里的中文 TrueType 字体（有真正的粗体），找不到才退回
reportlab 自带的 STSong-Light。STSong-Light 是 CID 字体，PDF 阅读器要
自己去拼字形，导出的正文看着发虚、粗细也不分，所以只当兜底。
"""

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

# ------------------------------------------------------------------ 调色板

INK = "#0f172a"          # 标题
BODY = "#1e293b"         # 正文
MUTED = "#64748b"        # 次级说明
FAINT = "#94a3b8"        # 译文、页码
RULE = "#e2e8f0"         # 分隔线
SOFT_RULE = "#f1f5f9"    # 句间细分隔线
BRAND = "#2563eb"        # 品牌蓝 = 前端 brand-600
BRAND_SOFT = "#eff6ff"   # 品牌蓝浅底
PANEL = "#f8fafc"        # 页眉卡片底

# 高亮色与前端保持一致，导出后一眼能对上
HIGHLIGHT_COLORS = {
    "blue": "#dbeafe",
    "green": "#dcfce7",
    "amber": "#fef3c7",
    "rose": "#ffe4e6",
    "violet": "#ede9fe",
}

# 高亮块的圆角半径（pt）。正文 10.8pt、色块高约 12.5pt，3pt 的圆角刚好把方角
# 磨掉，又不会啃到词首词尾；太大会把短词（如 has）压成胶囊形。
HIGHLIGHT_RADIUS = 3

# 色块高度 = 字号 × 这个比例，底边落在基线下 0.25em。
#
# reportlab 的 <font backColor> 是拿「行距」当色块高的（1.52em），上下各空出
# 好几个点，看着像糊了一块膏药。前端的高亮是浏览器按字体自身的升部/降部
# 撑出来的盒子，量下来约 1.25em、底边在基线下 0.25em，这里照抄这个比例，
# 所以导出后的观感和页面一致。改这两个值就能整体调高矮 / 调上下位置。
HIGHLIGHT_HEIGHT_RATIO = 1.25
HIGHLIGHT_DROP_RATIO = 0.25

# 批注条目上下留白（pt）。条目之间靠这点留白和行距分开就够了，
# 3.5 那种厚 padding 只会把右栏撑高、把整行逼高，白费纸。
ANNO_ROW_PAD = 1.5

# 批注条目之间插入的空隙（pt）。整栏都是同一种黑字，不隔开的话几条会粘成
# 一段，看不出哪里是一条批注的结尾；留 1pt 就够分段，又不明显占高。
ANNO_ROW_GAP = 1

# ------------------------------------------------------------------ 版面度量

PAGE_W, PAGE_H = A4
MARGIN_X = 15 * mm
MARGIN_TOP = 13 * mm
MARGIN_BOTTOM = 15 * mm
CONTENT_W = PAGE_W - 2 * MARGIN_X

COL_NUM = 9 * mm                    # 句号圆标
COL_ANNO = 60 * mm                  # 批注栏
COL_BODY = CONTENT_W - COL_NUM - COL_ANNO

ANNO_GAP = 5                        # 分隔线到批注卡片的留白（pt）
ANNO_CARD_W = COL_ANNO - ANNO_GAP   # 卡片可用宽度

# 字号阶梯，改这里就够，别在各处散着写
FS_TITLE = 18
FS_BODY = 10.8
FS_TRANS = 8.6
FS_TERM = 8.8
FS_MEAN = 8.2
FS_USER = 7.8
FS_META = 8.2
FS_HEAD = 7.4
FS_FOOT = 7.2

# 行距倍数：正文最松，批注最紧——批注是速查，不是用来连读的
LEAD_BODY = 1.52
LEAD_ANNO = 11

# 中文正文字体候选：(常规, 粗体)。按顺序取第一对能注册成功的。
# 环境变量 READING_PDF_FONT / READING_PDF_FONT_BOLD 可覆盖，方便部署时
# 指定字体文件；没有粗体时用常规字体代替。
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

# 拉丁正文用的衬线体候选。英文长句用衬线读起来比黑体省力，
# 也是阅读材料该有的样子。环境变量 READING_PDF_SERIF 可覆盖。
_LATIN_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("C:/Windows/Fonts/georgia.ttf", "C:/Windows/Fonts/georgiab.ttf"),
    ("C:/Windows/Fonts/cambria.ttc", "C:/Windows/Fonts/cambriab.ttf"),
    ("C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/timesbd.ttf"),
    ("/System/Library/Fonts/Supplemental/Georgia.ttf",
     "/System/Library/Fonts/Supplemental/Georgia Bold.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"),
)

# 句子正文里出现这些区间的字符就得换回中文字体，衬线体没有汉字字形
_CJK_RE = re.compile(r"[\u2e80-\u9fff\uf900-\ufaff\ufe30-\ufe4f\uff00-\uffef]")


def _register_ttf_pair(
    candidates: tuple[tuple[str, str], ...],
    prefix: str,
    env_regular: str,
    env_bold: str,
) -> tuple[str, str] | None:
    """按候选顺序注册一组 TTF，返回 (常规名, 粗体名)；全都不行返回 None。

    .ttc 是字体集合，统一取第 0 个子字体；注册失败就换下一个候选。
    """
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
    """注册中文字体，返回 (常规, 粗体) 字体名。"""
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


def _register_latin(cjk: tuple[str, str]) -> tuple[str, str]:
    """注册拉丁衬线体，返回 (常规, 粗体)；没有可用的就退回中文字体。"""
    pair = _register_ttf_pair(
        _LATIN_CANDIDATES,
        "ReadingLatin",
        os.environ.get("READING_PDF_SERIF", "").strip(),
        os.environ.get("READING_PDF_SERIF_BOLD", "").strip(),
    )
    return pair or cjk


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def _escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


class _NumberBadge(Flowable):
    """句号圆标。

    一个圆 + 一个数字，替掉原来那列裸数字：把序号收进圆里，右侧正文
    就有了明确的起点，翻页时也更容易找回上一句读到哪。
    """

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
    """批注条目容器。

    继承 Table 只是为了补一个 .text —— 测试靠它检查批注字段有没有在
    改版里漏掉，普通 Table 没有。
    """

    def __init__(self, data: list[list], col_widths: list[float], text: str) -> None:
        super().__init__(data, colWidths=col_widths)
        self._text = text

    @property
    def text(self) -> str:
        return self._text


def _rounded_rect_replacer(
    canvas, original_rect, *, font_size: float, leading: float
):
    """造一个顶替 canvas.rect 的函数：高亮那一笔改画圆角，其余原样透传。

    判据是「实心 + 无描边」——paragraph.py 里只有高亮是这么画的。
    单独拎出来是为了能直接单测，不必真去跑一遍版面。

    传进来的 y / height 是 reportlab 的原值（下沿 + 行距），这里按字号
    重算成贴着字形的高矮，顺便算出基线：reportlab 把色块上沿放在
    「基线 + 字号」处，所以 基线 = 下沿 + 行距 - 字号。
    """

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
    """把 <font backColor> 的直角高亮画成圆角。

    reportlab 的高亮是在 _do_post_text() 里直接 canvas.rect(...) 画的，
    Paragraph 没留样式钩子；而这一笔又发生在 canvas.drawText(tx) 之前、
    且处于「已经 translate 到本行原点」的坐标系里，所以在 draw() 外面
    补画是补不到正确位置的。

    于是这里在 draw() 期间临时接管画布实例上的 rect。改的是实例属性，
    不动 reportlab 全局，两个导出并发也不会互相串。
    """

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
    """把批注换算成句内的字符区间，附带批注序号用于同区间时定序。

    优先用笔记自己存的 [start_offset, end_offset)：同一句话里同一个词
    出现多次时，只有区间才能指回用户当时选中的那一处，按文本匹配会
    全指到第一处。老笔记这两列是 0，才退回按文本匹配。
    """
    spans: list[tuple[int, int, str, int]] = []
    for order, note in enumerate(notes):
        color = note.get("color") or "blue"
        start = note.get("start_offset") or 0
        end = note.get("end_offset") or 0
        if 0 <= start < end <= len(sentence):
            spans.append((start, end, color, order))
            continue

        # 没有区间：只有词/搭配能按文本回退匹配。kind="note" 的 text 是
        # 笔记正文（整句笔记时）或锚定原文（划词笔记时），都可能不在原文里，
        # 硬匹配会把"给这句加的笔记"误染到正文上，所以不参与。
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
    """在原文里给批注过的词/搭配加底色。

    先按所有区间端点把句子切段，每段取覆盖它的最内层那条上色——和前端
    buildPieces 的规则一致（短语套生词时以生词的颜色为准，起点相同则
    后加的那条赢），导出后看到的颜色与页面上完全对得上。
    """
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
    """右列：这句的全部批注。

    字段与前端「本页批注」逐条对应——词条原文、释义、用户自己写的笔记，
    一个都不能省。之前按 kind 分支渲染，划词写的笔记只剩正文，原文
    （text）和分类（color）都丢了，导出的 PDF 看着就像批注缺了一半。

    一条批注只占一行（有用户笔记时才两行）：不印「生词/好句」这类分类文字，
    也不铺底色、不画分类色竖条，整栏就是纯黑文字。导出是拿去打印的，
    这些东西除了多占地方、多耗墨，并不比正文高亮的颜色多说什么。
    """
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

        # 词条加粗、释义跟在同一行，读起来是「词 → 义」一个整体
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

        # 条目之间留一线空隙，几条批注才不会粘成一段
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
    """页脚：一条细线 + 页码。多页导出时不会翻着翻着迷路。

    只留页码，不再写「本文档由 LinguaScene 生成 · 左栏原文，右栏……」
    这类说明：版式一眼能看懂，说明文字只是噪音。
    """

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
    """生成带批注栏的 PDF，返回字节。"""
    font, bold_font = _register_fonts()
    serif, serif_bold = _register_latin((font, bold_font))
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
        "title", fontName=serif_bold, fontSize=FS_TITLE, leading=FS_TITLE * 1.3,
        textColor=colors.HexColor(INK),
    )
    meta_style = ParagraphStyle(
        "meta", fontName=font, fontSize=FS_META, leading=12,
        textColor=colors.HexColor(MUTED),
    )
    head_style = ParagraphStyle(
        "head", fontName=font, fontSize=FS_HEAD, leading=11,
        textColor=colors.HexColor(FAINT),
    )
    body_serif_style = ParagraphStyle(
        "bodySerif", fontName=serif, fontSize=FS_BODY, leading=FS_BODY * LEAD_BODY,
        alignment=TA_LEFT, textColor=colors.HexColor(BODY),
    )
    body_cjk_style = ParagraphStyle(
        "bodyCjk", fontName=font, fontSize=FS_BODY, leading=FS_BODY * LEAD_BODY,
        alignment=TA_LEFT, textColor=colors.HexColor(BODY),
    )
    trans_style = ParagraphStyle(
        "trans", fontName=font, fontSize=FS_TRANS, leading=FS_TRANS * 1.5,
        textColor=colors.HexColor(FAINT),
    )
    anno_style = ParagraphStyle(
        "anno", fontName=font, fontSize=FS_MEAN, leading=LEAD_ANNO,
        textColor=colors.HexColor(BODY),
    )

    note_total = sum(len(s.get("notes") or []) for s in sentences)
    meta_bits = [_escape(author)]
    if level:
        # 等级做成小色片：B1/B2 是读者最先要找的信息，不该和来源混在一行灰字里
        meta_bits.append(
            f'<font backColor="{BRAND_SOFT}" color="{BRAND}">&#160;{_escape(level)}&#160;</font>'
        )
    meta_bits.append(f"{len(sentences)} 句")
    if note_total:
        meta_bits.append(f"{note_total} 条批注")

    # 页眉做成一张浅底卡片：左边一条品牌色竖条，把标题、来源、统计收在一起，
    # 比原来「标题 + 一行灰字 + 一条通栏线」更像一份正式材料。
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

    # 整篇一条批注都没有时，右栏就是纯留白：留着「批注」表头和竖线反而
    # 像排版没做完，所以这两个装饰只在真有批注时才画。
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
        body_style = body_cjk_style if _has_cjk(source) else body_serif_style

        # 正文用带圆角高亮的段落：批注底色不再是方块，和前端的高亮观感一致
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
        # 一句都没有（空文章）也要给一行，否则表格没法构建
        rows.append(
            [
                Paragraph("", head_style),
                Paragraph("", body_serif_style),
                Paragraph("", anno_style),
            ]
        )

    table = Table(rows, colWidths=[COL_NUM, COL_BODY, COL_ANNO], repeatRows=1)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        # 表头行贴住页眉卡片，正文行留足上下气口
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
        # 表头下的一条实线，加右列的分隔竖线
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor(RULE)),
    ]
    if show_anno:
        style.append(("LINEBEFORE", (2, 1), (2, -1), 0.5, colors.HexColor(RULE)))
    # 句与句之间只用一条极淡的线，且只画在正文列——批注列是卡片，不该被切
    for row_index in range(1, len(rows) - 1):
        style.append(
            ("LINEBELOW", (1, row_index), (1, row_index), 0.4, colors.HexColor(SOFT_RULE))
        )
    table.setStyle(TableStyle(style))
    story.append(table)

    footer = _make_footer(font)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
