import json, sys
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # varaston juuri
_FONTS = _os.path.join(_ROOT, 'fonts') if _os.path.isdir(_os.path.join(_ROOT, 'fonts')) else _os.path.join(_ROOT, '..', 'fonts')
from playwright.sync_api import sync_playwright
URL = "file://" + _ROOT + "/preview.html"
def run(throttle):
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        cdp = pg.context.new_cdp_session(pg)
        cdp.send("Emulation.setCPUThrottlingRate", {"rate": throttle})
        # estä ulkoiset fontit, jotta mitataan vain oma koodi
        pg.route("**/fonts.googleapis.com/**", lambda r: r.abort())
        pg.route("**/fonts.gstatic.com/**", lambda r: r.abort())
        res = []
        for i in range(6):
            pg.goto(URL, wait_until="load")
            pg.wait_for_timeout(300)
            m = pg.evaluate("""() => { const n = performance.getEntriesByType('navigation')[0];
              const fcp = performance.getEntriesByName('first-contentful-paint')[0];
              const s = [...performance.getEntriesByType('script')];
              return {dcl: Math.round(n.domContentLoadedEventEnd), load: Math.round(n.loadEventEnd), fcp: fcp ? Math.round(fcp.startTime) : null,
                ready: window.__ready ? Math.round(window.__ready) : null}; }""")
            res.append(m)
        # navigointinopeus: 30 sivunvaihtoa show():lla
        t = pg.evaluate("""() => { const L = window.LAKITV; const t0 = performance.now();
            for (const n of [100,101,200,201,202,300,301,260,261,700,701,720,800,801,802,850,851,852,190,199,150,180,888,110,233,555,400,401,600,601]) L.show(n,0,true);
            return Math.round((performance.now()-t0)/30*10)/10; }""")
        # suodattimen vaihto
        f = pg.evaluate("""() => { const t0 = performance.now(); for (let i=0;i<5;i++){ document.querySelector('#kTopics').click(); const c=document.querySelector("label[for='t-sote']"); c.click(); c.click(); document.getElementById('panel').close(); } return Math.round((performance.now()-t0)/10*10)/10; }""")
        b.close()
        return res, t, f
for th in [1, 4]:
    r, t, f = run(th)
    print(f"CPU x{th}: loads {r} | show() avg {t} ms | filter toggle avg {f} ms")
