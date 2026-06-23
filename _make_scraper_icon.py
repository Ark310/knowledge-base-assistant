# _make_scraper_icon.py
"""One-off: draw a clean ice-scraper app mark (Contoso blue tile + white scraper glyph)
and save a multi-size .ico. Run: scraper\\venv\\Scripts\\python.exe _make_scraper_icon.py"""
from pathlib import Path
from PIL import Image, ImageDraw

BRAND = (81, 99, 158, 255)      # #51639e
WHITE = (255, 255, 255, 255)
S = 1024                         # supersample, then downscale

def draw() -> Image.Image:
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # rounded-square brand tile
    pad = S // 10
    d.rounded_rectangle([pad, pad, S - pad, S - pad], radius=S // 7, fill=BRAND)
    # ice-scraper: angled flat blade + handle (white)
    cx = S // 2
    # blade (a wide trapezoid near the lower-left, angled)
    d.polygon([(cx - 300, cx + 70), (cx + 120, cx + 70), (cx + 60, cx + 200), (cx - 240, cx + 200)], fill=WHITE)
    # blade lip
    d.rounded_rectangle([cx - 300, cx + 40, cx + 120, cx + 78], radius=18, fill=WHITE)
    # handle (rounded bar rising to upper-right)
    d.line([(cx + 20, cx + 120), (cx + 230, cx - 230)], fill=WHITE, width=70)
    d.ellipse([cx + 195, cx - 270, cx + 285, cx - 180], fill=WHITE)  # grip knob
    return im

def main() -> None:
    out = Path(__file__).parent / "assets" / "scraper_icon.ico"
    out.parent.mkdir(parents=True, exist_ok=True)
    big = draw()
    icon = big.resize((256, 256), Image.LANCZOS)
    icon.save(out, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"wrote {out}")

if __name__ == "__main__":
    main()
