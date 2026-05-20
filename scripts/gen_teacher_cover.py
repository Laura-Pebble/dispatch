"""Generate a Pebble AI Teacher podcast cover from scratch with PIL.

Two variants are produced so Laura can pick:
  A. "in_family" — exact Pebble palette (navy + lime + white). Same look as
     Dispatch; differs only by wordmark and icons.
  B. "academic"  — same navy background, but warm amber/cream accent. Reads
     scholarly; clearer visual distinction from Dispatch on app tiles.

Run: python scripts/gen_teacher_cover.py
Outputs: /tmp/teacher-cover-{in_family,academic}.png at 1400x1400.

Drop the chosen one at static/teacher-cover.png and commit.
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

DISPATCH_COVER = Path("static/cover.png")
OUT_DIR = Path("/tmp")
SIZE = 1400  # Apple Podcasts square spec floor


def sample_dispatch_palette() -> dict:
    """Sample the background, wordmark, and icon colors from the existing
    Dispatch cover so the new one stays exactly in-family."""
    img = Image.open(DISPATCH_COVER).convert("RGB")
    w, h = img.size
    return {
        "background": img.getpixel((20, 20)),          # corner
        "wordmark":   img.getpixel((w // 2, h // 2)),  # middle of "Dispatch"
        "accent":     img.getpixel((int(w * 0.18), h // 2)),  # left broadcast icon
        "subline":    img.getpixel((w // 2, int(h * 0.70))),  # "by Pebble Marketing"
    }


def load_font(size: int, *, bold: bool = True) -> ImageFont.FreeTypeFont:
    path = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    )
    return ImageFont.truetype(path, size)


def draw_book_stack(draw: ImageDraw.ImageDraw, cx: int, cy: int, accent: tuple, scale: float = 1.0):
    """A stack of 3 books viewed from the side. Each book is a chunky
    horizontal rectangle. A short vertical tick on the right edge suggests
    the page block; a small spine detail on the left distinguishes the
    cover from the pages."""
    book_w = int(170 * scale)
    book_h = int(60 * scale)
    spacing = int(10 * scale)
    line_w = max(5, int(6 * scale))
    page_inset = max(6, int(10 * scale))

    # 3 books, gently fanning left/right so the stack reads as hand-stacked
    offsets = [-12, 6, -4]
    total_h = 3 * book_h + 2 * spacing
    top_y = cy - total_h // 2

    for i, ox in enumerate(offsets):
        x0 = cx + ox - book_w // 2
        y0 = top_y + i * (book_h + spacing)
        x1 = x0 + book_w
        y1 = y0 + book_h
        # Book outline
        draw.rectangle((x0, y0, x1, y1), outline=accent, width=line_w)
        # Spine band on the left — solid bar that visually separates "cover"
        # from "pages"
        spine_x = x0 + int(book_w * 0.18)
        draw.line((spine_x, y0 + line_w, spine_x, y1 - line_w), fill=accent, width=line_w)
        # Page-block tick on the right — single short vertical line, inset
        # from the edge, so the book reads as having pages
        page_x = x1 - page_inset
        draw.line((page_x, y0 + line_w + 2, page_x, y1 - line_w - 2), fill=accent, width=max(3, line_w // 2))


def render_cover(*, background, wordmark, accent, subline, out_path: Path):
    img = Image.new("RGB", (SIZE, SIZE), color=background)
    draw = ImageDraw.Draw(img)

    # ── Wordmark "AI Teacher" — sized so [icon][gap][word][gap][icon]
    #    composition fits cleanly on 1400px canvas. 140pt → ~780px wide,
    #    leaving room for ~200px icons on each side with 60px gaps.
    word_font = load_font(140, bold=True)
    word_text = "AI Teacher"
    wb = draw.textbbox((0, 0), word_text, font=word_font)
    word_w = wb[2] - wb[0]
    word_h = wb[3] - wb[1]
    word_x = (SIZE - word_w) // 2
    word_y = (SIZE - word_h) // 2 - 40
    draw.text((word_x, word_y), word_text, font=word_font, fill=wordmark)

    # ── Subline "by Pebble Marketing" ────────────────────────────────────
    sub_font = load_font(52, bold=False)
    sub_text = "by Pebble Marketing"
    sb = draw.textbbox((0, 0), sub_text, font=sub_font)
    sub_w = sb[2] - sb[0]
    sub_x = (SIZE - sub_w) // 2
    sub_y = word_y + word_h + 40
    draw.text((sub_x, sub_y), sub_text, font=sub_font, fill=subline)

    # ── Book-stack icons flanking the wordmark ───────────────────────────
    icon_scale = 1.05
    icon_w = int(170 * icon_scale)  # widest book's width
    gap = 60                          # padding between wordmark edge and icon edge
    icon_cx_left = word_x - gap - icon_w // 2
    icon_cx_right = word_x + word_w + gap + icon_w // 2
    icon_cy = word_y + word_h // 2
    draw_book_stack(draw, icon_cx_left, icon_cy, accent, scale=icon_scale)
    draw_book_stack(draw, icon_cx_right, icon_cy, accent, scale=icon_scale)

    img.save(out_path, "PNG", optimize=True)
    print(f"  wrote {out_path}")


def main():
    # Pebble palette read from the Dispatch cover. Background sampled
    # programmatically; wordmark/accent/subline use the visually-evident
    # Pebble values (sampling on antialiased edges gives garbage).
    bg = sample_dispatch_palette()["background"]
    print(f"Sampled background: {bg}")

    pebble = {
        "background": bg,                # deep navy from Dispatch (~#081F33)
        "wordmark":   (255, 255, 255),   # pure white
        "accent":     (164, 216, 56),    # Pebble lime (~#A4D838)
        "subline":    (139, 156, 173),   # muted gray-blue (~#8B9CAD)
    }

    # Variant A — in-family: exactly Pebble's existing palette
    render_cover(
        **pebble,
        out_path=OUT_DIR / "teacher-cover-in_family.png",
    )

    # Variant B — academic: same navy bg, but cream wordmark + warm amber
    # accent + dusty rose subline. Stays in Pebble's universe (deep navy
    # base) while reading visually distinct from Dispatch on tiles.
    render_cover(
        background=pebble["background"],
        wordmark=(245, 235, 216),   # warm cream
        accent=(224, 181, 71),       # warm amber/gold
        subline=(167, 139, 184),     # muted lavender
        out_path=OUT_DIR / "teacher-cover-academic.png",
    )


if __name__ == "__main__":
    main()
