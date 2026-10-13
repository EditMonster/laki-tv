from playwright.sync_api import sync_playwright
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # varaston juuri
_FONTS = _os.path.join(_ROOT, 'fonts') if _os.path.isdir(_os.path.join(_ROOT, 'fonts')) else _os.path.join(_ROOT, '..', 'fonts')
U = "file://" + _ROOT + "/laki-tv.html"
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1280, "height": 820})
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(U); pg.wait_for_timeout(600)
    pg.evaluate("window.LAKITV.go(107)"); pg.wait_for_timeout(500); pg.screenshot(path="test/v7_107.png")
    pg.evaluate("window.LAKITV.show(107, 1)"); pg.wait_for_timeout(300); pg.screenshot(path="test/v7_107b.png")
    pg.click("#kSv"); pg.wait_for_timeout(400); pg.screenshot(path="test/v7_107sv.png")
    pg.evaluate("window.LAKITV.go(106)"); pg.wait_for_timeout(400); pg.screenshot(path="test/v7_106sv.png")
    pg.click("#kFi")
    m = b.new_page(viewport={"width": 390, "height": 844}); m.goto(U); m.wait_for_timeout(600); m.screenshot(path="test/v7_m100.png", full_page=True)
    print("errors", errs); b.close()
