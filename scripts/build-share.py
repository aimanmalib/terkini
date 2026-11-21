# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright==1.48.0", "pillow==11.0.0"]
# ///
"""Write the page's icons and share card into docs/ (config/share.toml, D-028).

Icons: favicon.svg, favicon.ico (16 + 32), apple-touch-icon.png (180), icon-192.png, icon-512.png, site.webmanifest.
Share card: og.png (1200 x 630), drawn from a real recorded run (docs/cases/<case>.json) and the English strings in
i18n/en.json, with the page's own fonts. Run after changing the case, the strings or config/share.toml:
  uv run scripts/build-share.py      (needs a Playwright Chromium: uv run --with playwright==1.48.0 playwright install chromium)
"""

from __future__ import annotations

import html
import io
import json
import tempfile
import tomllib
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
CFG = tomllib.loads((ROOT / "config" / "share.toml").read_text(encoding="utf-8"))
C = CFG["colors"]


def mark_svg(size: int, radius: float) -> str:
    """The three dots from the page header (fresh, not settled, stale) on an ink square."""
    r = size * 0.105
    cy = size / 2
    xs = [size * 0.25, size * 0.5, size * 0.75]
    dots = "".join(f'<circle cx="{x:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="{c}"/>'
                   for x, c in zip(xs, (C["fresh_hi"], C["unsure_hi"], C["stale_hi"])))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
            f'<rect width="{size}" height="{size}" rx="{size * radius:.2f}" fill="{C["ink"]}"/>{dots}</svg>')


def card_html(strings: dict, case: dict) -> str:
    res = next(r for r in case["report"]["results"] if r["verdict"] == "outdated")
    host = res["source_url"].split("/")[2].removeprefix("www.")
    e = html.escape
    font = (DOCS / "fonts").as_uri()
    title = strings["title"].split(":", 1)[-1].strip()
    title = title[0].upper() + title[1:]
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@font-face {{ font-family: B; src: url("{font}/barlow-400.woff2"); font-weight: 400; }}
@font-face {{ font-family: B; src: url("{font}/barlow-600.woff2"); font-weight: 600; }}
@font-face {{ font-family: B; src: url("{font}/barlow-800.woff2"); font-weight: 800; }}
@font-face {{ font-family: M; src: url("{font}/plex-mono-400.woff2"); font-weight: 400; }}
* {{ box-sizing: border-box; margin: 0; }}
body {{ width: 1200px; height: 630px; background: {C["ink"]}; color: {C["paper"]}; font-family: B; overflow: hidden;
  background-image: radial-gradient(900px 500px at 0% 0%, #22325a 0%, transparent 70%); }}
.wrap {{ padding: 64px 72px; height: 100%; display: flex; flex-direction: column; }}
.brand {{ display: flex; align-items: center; gap: 16px; font-weight: 800; font-size: 40px; letter-spacing: -.01em; }}
h1 {{ margin-top: 40px; font-weight: 800; font-size: 64px; line-height: 1.04; letter-spacing: -.02em; max-width: 1000px; }}
.q {{ margin-top: 36px; font-size: 26px; color: rgba(251,250,246,.75); }}
.card {{ margin-top: 14px; display: flex; align-items: center; gap: 28px; background: rgba(251,250,246,.06);
  border: 2px solid rgba(251,250,246,.14); border-radius: 18px; padding: 22px 28px; width: fit-content; }}
.badge {{ font-weight: 800; font-size: 22px; letter-spacing: .06em; text-transform: uppercase; color: {C["ink"]};
  background: {C["stale_hi"]}; border-radius: 999px; padding: 6px 16px; }}
.was {{ font-size: 40px; font-weight: 600; text-decoration: line-through; text-decoration-color: {C["stale_hi"]};
  text-decoration-thickness: 4px; color: rgba(251,250,246,.7); }}
.arrow {{ font-size: 36px; color: rgba(251,250,246,.5); }}
.now {{ font-size: 40px; font-weight: 800; color: {C["fresh_hi"]}; }}
.src {{ font-family: M; font-size: 22px; color: rgba(251,250,246,.65); }}
.foot {{ margin-top: auto; display: flex; justify-content: space-between; font-family: M; font-size: 22px;
  color: rgba(251,250,246,.7); }}
</style></head><body><div class="wrap">
<div class="brand"><svg width="78" height="26" viewBox="0 0 34 12"><circle cx="6" cy="6" r="5" fill="{C["fresh_hi"]}"/>
<circle cx="17" cy="6" r="5" fill="{C["unsure_hi"]}"/><circle cx="28" cy="6" r="5" fill="{C["stale_hi"]}"/></svg>Terkini</div>
<h1>{e(title)}</h1>
<p class="q">{e(case["question"])} &middot; {e(case["model"]["name"])}</p>
<div class="card"><span class="badge">{e(strings["verdict_outdated"])}</span>
<span class="was">{e(res["claim"]["value"])}</span><span class="arrow">&rarr;</span><span class="now">{e(res["current_value"])}</span>
<span class="src">{e(host)}</span></div>
<div class="foot"><span>{e(CFG["card"]["footer_left"])}</span><span>{e(CFG["card"]["footer_right"])}</span></div>
</div></body></html>"""


def main() -> None:
    strings = json.loads((ROOT / "i18n" / "en.json").read_text(encoding="utf-8"))
    case = json.loads((DOCS / "cases" / f"{CFG['card']['case']}.json").read_text(encoding="utf-8"))
    (DOCS / "favicon.svg").write_text(mark_svg(64, 0.22), encoding="utf-8")
    pngs: dict[int, bytes] = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        for size in (16, 32, 180, 192, 512):
            pg = b.new_page(viewport={"width": size, "height": size})
            # apple-touch-icon is masked by iOS, so it gets square corners
            pg.set_content(f'<body style="margin:0">{mark_svg(size, 0 if size == 180 else 0.22)}</body>')
            pngs[size] = pg.screenshot(omit_background=True)
            pg.close()
        pg = b.new_page(viewport={"width": 1200, "height": 630})
        # A file:// page so the page's own woff2 files load (set_content runs on about:blank, which cannot read them).
        with tempfile.TemporaryDirectory() as tmp:
            card = Path(tmp) / "card.html"
            card.write_text(card_html(strings, case), encoding="utf-8")
            pg.goto(card.as_uri(), wait_until="networkidle")
            pg.evaluate("document.fonts.ready")
            missing = pg.evaluate("[...document.fonts].filter(f => f.status !== 'loaded').length")
            if missing:
                raise SystemExit(f"{missing} fonts did not load for the share card")
        og = pg.screenshot(type="png")
        b.close()
    (DOCS / "apple-touch-icon.png").write_bytes(pngs[180])
    (DOCS / "icon-192.png").write_bytes(pngs[192])
    (DOCS / "icon-512.png").write_bytes(pngs[512])
    Image.open(io.BytesIO(pngs[32])).save(DOCS / "favicon.ico", sizes=[(16, 16), (32, 32)])
    img = Image.open(io.BytesIO(og)).convert("RGB")
    img.save(DOCS / "og.png", optimize=True)
    manifest = {"name": "Terkini", "short_name": "Terkini", "description": strings["meta_description"],
                "start_url": "./", "display": "browser", "background_color": C["paper"], "theme_color": C["ink"],
                "icons": [{"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
                          {"src": "icon-512.png", "sizes": "512x512", "type": "image/png"}]}
    (DOCS / "site.webmanifest").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    for f in ("favicon.svg", "favicon.ico", "apple-touch-icon.png", "icon-192.png", "icon-512.png", "og.png",
              "site.webmanifest"):
        print(f"docs/{f}", (DOCS / f).stat().st_size, "bytes")


if __name__ == "__main__":
    main()
