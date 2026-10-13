"""Tuoreuslogiikka eri katsomishetkillä (kello lukitaan)."""
import datetime as dt
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # varaston juuri
_FONTS = _os.path.join(_ROOT, 'fonts') if _os.path.isdir(_os.path.join(_ROOT, 'fonts')) else _os.path.join(_ROOT, '..', 'fonts')
from playwright.sync_api import sync_playwright
URL = "file://" + _ROOT + "/preview.html"
def screen(pg): return pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r=>r.textContent).join('\\n')")
def allsubs(pg, n):
    out = []
    k = pg.evaluate(f"window.LAKITV.getPage({n}).subs.length")
    for s in range(k):
        pg.evaluate(f"window.LAKITV.show({n},{s},true)"); out.append(screen(pg))
    return "\n".join(out)
with sync_playwright() as p:
    b = p.chromium.launch()
    for when in ["2026-09-29T10:30:00+03:00", "2026-09-30T08:00:00+03:00", "2026-10-01T12:00:00+03:00", "2026-10-20T09:00:00+03:00"]:
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.clock.install(time=dt.datetime.fromisoformat(when))
        pg.goto(URL); pg.wait_for_timeout(300)
        print("=" * 20, when)
        print("\n".join(screen(pg).split("\n")[5:16]))
        print("--- 101")
        print(allsubs(pg, 101))
        pg.close()
    b.close()
