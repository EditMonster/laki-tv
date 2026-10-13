from playwright.sync_api import sync_playwright
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # varaston juuri
_FONTS = _os.path.join(_ROOT, 'fonts') if _os.path.isdir(_os.path.join(_ROOT, 'fonts')) else _os.path.join(_ROOT, '..', 'fonts')
U = "file://" + _ROOT + "/laki-tv.html"
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1280, "height": 820})
    pg.goto(U); pg.wait_for_timeout(700)
    for n, f in [(100, "v6_100"), (102, "v6_102"), (103, "v6_103")]:
        pg.evaluate(f"window.LAKITV.go({n})"); pg.wait_for_timeout(500); pg.screenshot(path=f"test/{f}.png")
    pg.evaluate("window.LAKITV.go(103)"); pg.wait_for_timeout(300)
    pg.evaluate("window.LAKITV.show(103, 1)"); pg.wait_for_timeout(300); pg.screenshot(path="test/v6_103b.png")
    pg.evaluate("window.LAKITV.go(104, false, {day: new Date(Date.now()-864e5).toISOString().slice(0,10)})"); pg.wait_for_timeout(500); pg.screenshot(path="test/v6_104.png")
    pg.click("#kSv"); pg.wait_for_timeout(300)
    pg.evaluate("window.LAKITV.go(100)"); pg.wait_for_timeout(500); pg.screenshot(path="test/v6_100sv.png")
    pg.evaluate("window.LAKITV.go(201)"); pg.wait_for_timeout(500); pg.screenshot(path="test/v6_201sv.png")
    pg.click("#kFi")
    m = b.new_page(viewport={"width": 390, "height": 844}); m.goto(U); m.wait_for_timeout(600)
    m.click("#kSub"); m.wait_for_timeout(600); m.screenshot(path="test/v6_sub_mob.png")
    b.close()
