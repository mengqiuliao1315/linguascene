"""从刺猬底图上裁出开心 / 委屈的眼睛贴片。

贴片盖住瞳孔的一半：开心盖下半（眯成笑眼），委屈盖上半（眼皮耷下来）。
填充色取瞳孔正上方的脸颊像素，不取贴片自己的边缘——边缘常常已经是深色眼线。

外圈 BORDER 像素最后从底图逐像素还原，叠回去不会露边。
坐标按 frontend/public/pet/hedgehog.png 的 400×521 量出，
换素材后重跑，并把打印出的框同步到 Pet.tsx 的 FACE_PATCHES。
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "public" / "pet" / "hedgehog.png"
OUT = ROOT / "public" / "pet"
BORDER = 3

# (name, left, top, width, height, skin_x, skin_y)
# 皮肤采样点在瞳孔正上方的脸颊上，亮度必须是浅色。
EYES = (
    ("left", 108, 206, 40, 34, 127, 178),
    ("right", 260, 192, 40, 34, 280, 170),
)


def _patch(base: Image.Image, box: tuple[int, int, int, int], skin: tuple, mood: str) -> Image.Image:
    left, top, width, height = box
    crop = base.crop((left, top, left + width, top + height)).convert("RGBA")
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    mask = Image.new("L", (width, height), 0)
    mask_draw = ImageDraw.Draw(mask)
    if mood == "happy":
        # 下半盖住，留下上沿那条弯眼
        draw.pieslice((-4, -2, width + 3, int(height * 1.45)), 200, 340, fill=skin)
        mask_draw.pieslice((1, int(height * 0.28), width - 2, int(height * 1.2)), 205, 335, fill=255)
    else:
        # 上半盖住，眼皮沉下来
        draw.pieslice((-4, int(-height * 0.55), width + 3, int(height * 0.72)), 20, 160, fill=skin)
        mask_draw.pieslice((1, int(-height * 0.35), width - 2, int(height * 0.55)), 20, 160, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(0.8))
    mp = mask.load()
    for y in range(height):
        for x in range(width):
            if x < BORDER or y < BORDER or x >= width - BORDER or y >= height - BORDER:
                mp[x, y] = 0
    out = Image.composite(overlay, crop, mask)
    op, cp = out.load(), crop.load()
    changed = bad = 0
    for y in range(height):
        for x in range(width):
            edge = x < BORDER or y < BORDER or x >= width - BORDER or y >= height - BORDER
            if edge:
                if op[x, y] != cp[x, y]:
                    bad += 1
                op[x, y] = cp[x, y]
            elif op[x, y] != cp[x, y]:
                changed += 1
    if bad:
        raise SystemExit(f"border pixels differ: {bad}")
    return out, changed


def main() -> None:
    base = Image.open(SRC).convert("RGBA")
    print("base", base.size)
    for name, left, top, width, height, sx, sy in EYES:
        skin = base.getpixel((sx, sy))
        if sum(skin[:3]) / 3 < 200:
            raise SystemExit(f"{name} skin sample is not cheek color: {skin}")
        for mood in ("happy", "sad"):
            out, changed = _patch(base, (left, top, width, height), skin, mood)
            path = OUT / f"{mood}-{name}.png"
            out.save(path)
            print(
                f"{mood}-{name} box=({left},{top},{width},{height}) "
                f"changed={changed} skin={skin[:3]}"
            )


if __name__ == "__main__":
    main()
