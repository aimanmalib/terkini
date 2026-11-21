"""Capture the real replay page (docs/) for the demo video: work/aset/*.png + kotak.json.

The page is served from this repository's docs/ folder on 127.0.0.1 (GET only, no keys, no network beyond localhost).
Desktop = Chromium at 2x pixels. Boxes are CSS px relative to each image, so the stage can place rings on real elements.
Also writes the domain list from packs/my.toml and the per-model eval counts from eval/my/results.json, so the
numbers on screen come from the same files as the README.
  python3 demo/video/tangkap.py
"""
import functools
import http.server
import json
import threading
import tomllib
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ASET = HERE / "work" / "aset"
ASET.mkdir(parents=True, exist_ok=True)
CASE = "my-03--grok-4-7"
kotak = {}


def box(pg, sel, parent=None, n=0):
    b = pg.locator(sel).nth(n).bounding_box()
    if parent:
        p = pg.locator(parent).first.bounding_box()
        return {"x": round(b["x"] - p["x"], 1), "y": round(b["y"] - p["y"], 1), "w": round(b["width"], 1), "h": round(b["height"], 1)}
    return {"x": round(b["x"], 1), "y": round(b["y"], 1), "w": round(b["width"], 1), "h": round(b["height"], 1)}


def serve():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    handler = functools.partial(Quiet, directory=str(ROOT / "docs"))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    srv = serve()
    base = f"http://127.0.0.1:{srv.server_address[1]}/"
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2, locale="en-GB")
        ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base) and r.request.method == "GET" else r.abort())
        pg = ctx.new_page()
        pg.goto(base + f"#case={CASE}", wait_until="networkidle")
        pg.locator(".claim").first.wait_for()
        pg.evaluate("document.fonts.ready.then(() => true)")
        pg.wait_for_timeout(500)
        pg.screenshot(path=str(ASET / "d-top.png"))
        kotak["d-top"] = {"hl": box(pg, ".answer .hl.outdated"), "case": box(pg, ".case[aria-current=true]"),
                          "asof": box(pg, ".asof"), "answer": box(pg, ".answer")}
        card = pg.locator(".claim").first
        card.screenshot(path=str(ASET / "d-card.png"))
        kotak["d-card"] = {"size": box(pg, ".claim"), "badge": box(pg, ".claim .badge", ".claim"),
                           "stated": box(pg, ".claim .facts .stated", ".claim"), "now": box(pg, ".claim .facts .now", ".claim"),
                           "quote": box(pg, ".claim blockquote", ".claim"), "source": box(pg, ".claim figcaption", ".claim"),
                           "score": box(pg, ".claim .score", ".claim")}
        ctx.close()
        b.close()
    srv.shutdown()

    pack = tomllib.loads((ROOT / "packs" / "my.toml").read_text())
    kotak["domains"] = [d["domain"] for d in pack["domains"]]
    res = json.loads((ROOT / "eval" / "my" / "results.json").read_text())
    kotak["eval"] = {k: res[k] for k in ("answers", "detection", "per_model", "claims")}
    # The honest-numbers scene shows the hybrid row (D-022), the figure the README leads with.
    kotak["eval"]["detection"] = next(r for r in res["baselines"]["rows"] if r["name"] == "hybrid")
    (ASET / "kotak.json").write_text(json.dumps(kotak, indent=1))
    print("captured:", sorted(x.name for x in ASET.glob("*.png")))


if __name__ == "__main__":
    main()
