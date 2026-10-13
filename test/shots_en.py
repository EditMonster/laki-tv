import sys
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # varaston juuri
_FONTS = _os.path.join(_ROOT, 'fonts') if _os.path.isdir(_os.path.join(_ROOT, 'fonts')) else _os.path.join(_ROOT, '..', 'fonts')
from playwright.sync_api import sync_playwright
U = "file://" + _ROOT + "/laki-tv.html"
pages = [int(x) for x in sys.argv[1].split(",")] if len(sys.argv) > 1 else [100, 101, 190, 199, 200, 201, 720, 800, 850, 106, 198]
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1280, "height": 820})
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(U); pg.wait_for_timeout(600)
    pg.evaluate("window.LAKITV.setLang('en')"); pg.wait_for_timeout(300)
    for n in pages:
        pg.evaluate(f"window.LAKITV.go({n})"); pg.wait_for_timeout(350); pg.screenshot(path=f"test/en_{n}.png")
    print("errors", errs); b.close()
