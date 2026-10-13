from playwright.sync_api import sync_playwright
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # varaston juuri
_FONTS = _os.path.join(_ROOT, 'fonts') if _os.path.isdir(_os.path.join(_ROOT, 'fonts')) else _os.path.join(_ROOT, '..', 'fonts')
URL = "file://" + _ROOT + "/preview.html"
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.goto(URL); pg.wait_for_timeout(600)
    for n in [100, 800, 801, 850, 260, 233, 190, 204]:
        pg.evaluate(f"window.LAKITV.show({n},0,true)"); pg.wait_for_timeout(150)
        pg.locator("#tv").screenshot(path=f"d{n}.png")
    pg.screenshot(path="desk-full.png")
    m = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True)
    m.goto(URL); m.wait_for_timeout(600)
    m.screenshot(path="m100.png", full_page=True)
    m.click("#kTopics"); m.wait_for_timeout(300); m.click("label[for='t-sote']"); m.wait_for_timeout(200)
    m.screenshot(path="m-panel.png")
    b.close()
