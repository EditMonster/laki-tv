"""Sivustotesti: site/ tarjoiltuna alipolusta (/laki-tv/) kuten GitHub Pagesissa.
Tarkistaa metatiedot, syötteiden ja kalenterin osoitteet, PWA:n (manifest, service worker, offline), .ics-latauksen ja syvälinkit."""
import http.server, json, os, socketserver, subprocess, sys, tempfile, threading, urllib.request, xml.etree.ElementTree as ET
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
fails = []
def ok(c, msg, extra=""):
    print(("OK  " if c else "FAIL") + " " + msg + (f" -> {str(extra)[:300]}" if extra and not c else ""))
    if not c: fails.append(msg)

# lähdekansio kuten päivitysajo sen työntää (sivu + feed-komennon tiedostot), sitten sivusto alipolkuun
SRC = tempfile.mkdtemp()
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools/lakitv.py"), "feed", os.path.join(ROOT, "data.json"), "--out", SRC], capture_output=True, text=True)
ok(r.returncode == 0, "feed-komento tuottaa jakelutiedostot", r.stdout + r.stderr)
import shutil; shutil.copy(os.path.join(ROOT, "laki-tv.html"), os.path.join(SRC, "laki-tv.html"))
for n in ("viikkokatsaus.html", "viikkokatsaus.pdf"):
    if os.path.exists(os.path.join(ROOT, "out", n)): shutil.copy(os.path.join(ROOT, "out", n), SRC)
r = subprocess.run([sys.executable, os.path.join(ROOT, "tools/website.py"), "--from-dir", SRC, "--out", SITE, "--base", "http://localhost:8765/laki-tv/"], capture_output=True, text=True)
ok(r.returncode == 0 and "OK:" in r.stdout, "website.py rakentaa sivuston", r.stdout + r.stderr)
www = tempfile.mkdtemp(); os.symlink(SITE, os.path.join(www, "laki-tv"))

class H(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".ics": "text/calendar", ".webmanifest": "application/manifest+json", ".md": "text/markdown"}
    def __init__(self, *a, **k): super().__init__(*a, directory=www, **k)
    def log_message(self, *a): pass
socketserver.TCPServer.allow_reuse_address = True
srv = socketserver.TCPServer(("127.0.0.1", 8765), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://localhost:8765/laki-tv/"

def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as r: return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e: return e.code, "", b""

# staattiset tiedostot
s, ct, b = get(""); html = b.decode()
ok(s == 200 and html.count("<title>") == 1 and "<title>LAKI-TV – juridinen teksti-TV</title>" in html, "index: yksi title", html.count("<title>"))
for tag in ['<meta name="description"', 'property="og:image" content="http://localhost:8765/laki-tv/og.png"', 'rel="canonical" href="http://localhost:8765/laki-tv/"', 'rel="manifest"', 'type="application/rss+xml"', '<html lang="fi">', 'name="twitter:card"']:
    ok(tag in html, f"index: {tag[:40]}")
ok("kalenteri.txt" not in html and "kalenteri.ics" in html, "index: kalenteri viittaa .ics-tiedostoon")
ok(html.lstrip().startswith("<!doctype html>") and html.rstrip().endswith("</html>"), "index: kokonainen dokumentti")
s, ct, b = get("feed.xml"); ok(s == 200 and ET.fromstring(b).find("channel/title") is not None, "feed.xml vastaa ja jäsentyy")
for f in ("feed-sv.xml", "feed-en.xml"): s, _, b = get(f); ok(s == 200 and b.startswith(b"<?xml"), f"{f} vastaa")
s, _, b = get("feed.json"); j = json.loads(b); ok(s == 200 and j.get("version", "").startswith("https://jsonfeed.org/version/1.1") and j["items"], "feed.json on JSON Feed 1.1")
s, ct, b = get("kalenteri.ics"); ok(s == 200 and b.startswith(b"BEGIN:VCALENDAR") and "text/calendar" in ct, "kalenteri.ics vastaa (text/calendar)", ct)
s, _, b = get("manifest.webmanifest"); m = json.loads(b)
ok(s == 200 and m["short_name"] == "LAKI-TV" and m["display"] == "standalone" and len(m["icons"]) == 3 and m["start_url"] == "./", "manifest kelvollinen")
for f in ("icon.svg", "icon-192.png", "icon-512.png", "og.png", "sw.js", "robots.txt", "404.html", "sitemap.xml", "lakitv.md"):
    s, _, b = get(f); ok(s == 200 and b, f"{f} vastaa")
ok(b"Sitemap: http://localhost:8765/laki-tv/sitemap.xml" in get("robots.txt")[2], "robots.txt osoittaa sitemapiin")
s, _, _ = get("kalenteri.txt"); ok(s == 404, "kalenteri.txt ei ole enää sivustolla")

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 820}, accept_downloads=True)
    pg = ctx.new_page(); errs = []; con = []
    pg.on("pageerror", lambda e: errs.append(str(e))); pg.on("console", lambda m: con.append(m.text) if m.type == "error" else None)
    pg.goto(BASE); pg.wait_for_timeout(1200)
    rows = pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')")
    ok("LAKI-TV" in rows and "KANAVAT" in rows and pg.evaluate("window.LAKITV.state.current") == 100, "sivu 100 piirtyy alipolusta", rows[:200])
    ok(pg.title().startswith("LAKI-TV"), "document.title säilyy", pg.title())
    ok(not errs and not con, "ei JS- tai konsolivirheitä", (errs + con)[:3])
    # service worker
    sw = pg.evaluate("navigator.serviceWorker.ready.then(r => r.active && r.active.scriptURL)")
    ok(sw == BASE + "sw.js", "service worker rekisteröityy sivuston juureen", sw)
    # fileUrl ja JAKELU-paneelin linkit
    ok(pg.evaluate("window.LAKITV.fileUrl('feed.xml')") == BASE + "feed.xml", "fileUrl osoittaa alipolkuun")
    pg.click("#kSub"); pg.wait_for_timeout(300)
    hrefs = pg.evaluate("[...document.querySelectorAll('#paneKal a[href]')].map(a => a.href)")
    ok(any(h == BASE + "feed.xml" for h in hrefs) and any(h == BASE + "feed.json" for h in hrefs), "JAKELU: syötelinkit sivuston osoitteeseen", hrefs[:6])
    cal = pg.evaluate("[...document.querySelectorAll('#paneKal a[href], #paneKal input, #paneKal code')].map(e => e.href || e.value || e.textContent).filter(x => /kalenteri/.test(x))")
    ok(cal and all("kalenteri.ics" in c or "kalenteri-sv.ics" in c or "kalenteri-en.ics" in c for c in cal) and any(c.startswith("webcal://localhost:8765/laki-tv/kalenteri.ics") for c in cal), "JAKELU: kalenteriosoite on webcal://…/kalenteri.ics", cal)
    # .ics-lataus ilman claude-ajoympäristöä
    btn = pg.query_selector("#paneKal button:has-text('.ics')")
    if btn:
        with pg.expect_download(timeout=5000) as dl:
            btn.click()
        d = dl.value; path = d.path(); txt = open(path, encoding="utf-8").read()
        ok(d.suggested_filename == "laki-tv.ics" and txt.startswith("BEGIN:VCALENDAR"), ".ics-nappi lataa oikean tiedoston", d.suggested_filename)
    else:
        ok(False, ".ics-nappi puuttuu (ei tulevia tapahtumia?)")
    pg.keyboard.press("Escape")
    # syvälinkit alipolussa
    pg.goto(BASE + "#p800"); pg.wait_for_timeout(400); ok(pg.evaluate("window.LAKITV.state.current") == 800, "#p800 toimii alipolussa")
    jid = pg.evaluate("(() => { const n = [...window.LAKITV.NUMS()].find(n => (window.LAKITV.itemIndexGet(n)||{}).it); return n ? window.LAKITV.itemIndexGet(n).it.id : null; })()")
    pg.goto(BASE + "#j=" + jid); pg.reload(); pg.wait_for_timeout(500)
    ok(pg.evaluate("((window.LAKITV.itemIndexGet(window.LAKITV.state.current)||{}).it||{}).id") == jid, "#j= syvälinkki avaa jutun alipolussa", jid)
    # offline: välimuisti vastaa
    pg.goto(BASE); pg.wait_for_timeout(800); pg.evaluate("navigator.serviceWorker.ready")
    pg.evaluate("fetch('feed.xml').then(r => r.text())"); pg.wait_for_timeout(500)
    ctx.set_offline(True)
    pg.reload(); pg.wait_for_timeout(1200)
    off_rows = pg.evaluate("document.querySelectorAll('#rows .row').length")
    off_feed = pg.evaluate("fetch('feed.xml').then(r => r.status).catch(() => 0)")
    ok(off_rows >= 25 and off_feed == 200, "offline: sivu ja syöte tulevat välimuistista", (off_rows, off_feed))
    ctx.set_offline(False)
    # mobiili
    m = b.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, device_scale_factor=3)
    m.goto(BASE); m.wait_for_timeout(1000)
    ok(m.evaluate("document.documentElement.scrollWidth <= innerWidth + 1") and m.evaluate("document.querySelectorAll('#rows .row').length") >= 25, "mobiili: ei vaakavieritystä, sivu piirtyy")
    ok(not errs and not con, "ei virheitä lopussa", (errs + con)[:3])
    b.close()
srv.shutdown()
print(f"{len(fails)} virhettä" if fails else "KAIKKI OK")
sys.exit(1 if fails else 0)
