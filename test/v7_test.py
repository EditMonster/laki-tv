# Testit avaavat näppäimistön (kaukosäätimen) sivupaneelin heti sivun latauduttua, jotta sen näppäimiä voi painaa.
"""v7: seuraa asiaa (108), kalenteri (paneeli, .ics, Google/Outlook-linkit), jakelu (109, feed/kalenteri/viikkokatsaus), ei alasivukiertoa."""
import json, subprocess, os, re
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # varaston juuri
_FONTS = _os.path.join(_ROOT, 'fonts') if _os.path.isdir(_os.path.join(_ROOT, 'fonts')) else _os.path.join(_ROOT, '..', 'fonts')
from playwright.sync_api import sync_playwright
import datetime as _dt, zoneinfo as _zi
_FIXED = _dt.datetime.combine(_dt.datetime.now(_zi.ZoneInfo("Europe/Helsinki")).date(), _dt.time(21, 0), tzinfo=_zi.ZoneInfo("Europe/Helsinki"))   # testikello: tänään klo 21 Helsinki
BASE = _ROOT + "/"
ok = []
def check(name, cond, info=""):
    ok.append(bool(cond)); print(("OK   " if cond else "FAIL ") + name + ("" if cond else f"  -> {info}"))
rows = lambda pg: pg.evaluate("[...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n')")
allrows = lambda pg, n: pg.evaluate("""(n) => { const L = window.LAKITV; let t = ''; const p = L.getPage(n); for (let s = 0; s < p.subs.length; s++) { L.show(n, s); t += [...document.querySelectorAll('#rows .row')].map(r => r.textContent).join('\\n'); } return t; }""", n)
d = json.load(open(BASE + "test/fixture_data.json", encoding="utf-8"))
laus = d["kanavat"]["lausunnot"][0]
with sync_playwright() as p:
    b = p.chromium.launch()
    # 1) selain ilman claude-kykyjä: seuranta localStorageen, kalenteri data-URL:llä
    pg = b.new_page(viewport={"width": 1440, "height": 900}); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.clock.set_fixed_time(_FIXED)
    pg.goto("file://" + BASE + "test/fixture.html"); pg.wait_for_timeout(500); pg.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg.wait_for_timeout(300)
    check("kHold poistettu", pg.evaluate("!document.getElementById('kHold') && !!document.getElementById('kFollow')"))
    t = allrows(pg, 199)
    check("ohje: ei HOLD-riviä", "PYSÄYTÄ ALASIVUJEN" not in t.upper() and "HOLD" not in t)
    pg.evaluate("window.LAKITV.go(741)"); pg.wait_for_timeout(300)
    pg.evaluate("window.LAKITV.show(741, window.LAKITV.getPage(741).subs.length - 1)"); pg.wait_for_timeout(200)
    t = rows(pg)
    check("juttusivu: SEURAA ASIAA ja KALENTERIIN", "SEURAA ASIAA" in t and "KALENTERIIN" in t, t[-300:])
    pg.click("a[data-act='seuraa']"); pg.wait_for_timeout(400)
    fl = pg.evaluate("window.LAKITV.followList()")
    check("seuraa: tallentuu ja näkyy", len(fl) == 1 and fl[0]["id"] == laus["id"] and fl[0]["tila"] == "dl:" + laus["maaraaika"] and "SEURANNASSA · LOPETA" in rows(pg), fl)
    pg.evaluate("window.LAKITV.go(108)"); pg.wait_for_timeout(300)
    t = rows(pg)
    check("108: seurattu juttu, ei muutoksia", "EI MUUTOKSIA" in t and laus["otsikko"] in t and "DL " in t, t[:400])
    # muutos: simuloi vanha tilannekuva -> MUUTTUNUT ja kuittaus
    pg.evaluate("(function(){ const l = window.LAKITV.followList(); l[0].tila = 'dl:2026-01-01'; localStorage.setItem('lakitv:seuranta', JSON.stringify(l)); window.LAKITV.buildAll(); window.LAKITV.go(108); })()"); pg.wait_for_timeout(300)
    t = rows(pg)
    check("108: muutos näkyy ja kuittaus tarjolla", "MUUTTUNUT" in t and "▶" in t and "MERKITSE NÄHDYIKSI" in t, t[:400])
    pg.evaluate("window.LAKITV.go(107)"); pg.wait_for_timeout(300)
    t = allrows(pg, 107)
    check("107: seurannassa-osio muutoksesta", "SEURANNASSA · MUUTTUNUT" in t, t[:300])
    pg.evaluate("window.LAKITV.go(108)"); pg.wait_for_timeout(200)
    pg.click("a[data-act='seuraa-ok']"); pg.wait_for_timeout(400)
    check("kuittaus päivittää tilannekuvan", pg.evaluate("window.LAKITV.followList()[0].tila") == "dl:" + laus["maaraaika"] and "EI MUUTOKSIA" in rows(pg))
    pg.reload(); pg.wait_for_timeout(500)
    check("seuranta säilyy latauksen yli", pg.evaluate("window.LAKITV.followList().length") == 1)
    pg.evaluate("window.LAKITV.go(741)"); pg.wait_for_timeout(200)
    pg.evaluate("window.LAKITV.show(741, window.LAKITV.getPage(741).subs.length - 1)"); pg.wait_for_timeout(200)
    pg.click("a[data-act='seuraa']"); pg.wait_for_timeout(300)
    check("lopeta seuranta", pg.evaluate("window.LAKITV.followList().length") == 0 and "SEURAA ASIAA" in rows(pg))
    # kalenteri
    pg.click("a[data-act='kal']"); pg.wait_for_timeout(500)
    kt = pg.evaluate("document.getElementById('paneKal').textContent")
    check("kalenteripaneeli aukeaa valitulla tapahtumalla", pg.is_visible("#paneKal") and "Lausuntoaika päättyy" in kt and "Seuraavat 30 päivää" in kt, kt[:200])
    g = pg.get_attribute("#paneKal .kal-ev a.pn-btn", "href")
    check("Google-linkki oikein", g and g.startswith("https://calendar.google.com/calendar/render?action=TEMPLATE") and laus["maaraaika"].replace("-", "") in g, g)
    o = pg.evaluate("[...document.querySelectorAll('#paneKal .kal-ev a.pn-btn')][1].href")
    check("Outlook-linkki oikein", "outlook.office.com" in o and f"startdt={laus['maaraaika']}" in o, o)
    ics = pg.evaluate("window.LAKITV.icsText([window.LAKITV.KAL.get('dl:' + %s)])" % json.dumps(laus["id"]))
    check("ics: VEVENT päivämäärällä", "BEGIN:VEVENT" in ics and f"DTSTART;VALUE=DATE:{laus['maaraaika'].replace('-', '')}" in ics and "SUMMARY:Lausuntoaika päättyy" in ics, ics[:300])
    with pg.expect_download() as dl:
        pg.click("#paneKal .kal-ev button:has-text('.ics')")
    check("ics-lataus (ilman claude-kykyä data-URL)", dl.value.suggested_filename == "laki-tv.ics")
    up = pg.evaluate("window.LAKITV.kalEventsUpcoming(30).map(e => e.id)")
    check("tulevat tapahtumat: lausunto + voimaantulopäivä", any(x.startswith("dl-") for x in up) and any(x.startswith("vt-") for x in up), up)
    pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    pg.evaluate("window.LAKITV.go(800)"); pg.wait_for_timeout(300)
    check("800: KAL-linkki päivärivillä", pg.evaluate("!!document.querySelector('#rows a[data-act=kal][data-arg^=\"vt:\"]')"))
    pg.evaluate("window.LAKITV.go(109)"); pg.wait_for_timeout(300)
    t = allrows(pg, 109)
    hrefs = pg.evaluate("window.LAKITV.go(109); [...document.querySelectorAll('#rows a[target=_blank]')].map(a => a.getAttribute('href'))")
    check("109: syötelinkit", "RSS FI" in t and any(h.endswith("feed.xml") for h in hrefs) and any(h.endswith("kalenteri.txt") for h in hrefs) and any(h.endswith("viikkokatsaus.pdf") for h in hrefs), hrefs[:5])
    check("fileUrl: claude.ai/artifact/<id> -> /<id>/tiedosto", pg.evaluate("(function(){ const o = location.href; try { history.replaceState(null, '', o); } catch(e){} return window.LAKITV.fileUrl('feed.xml'); })()").endswith("feed.xml"))
    # kierto: alasivu ei vaihdu 2 sekunnissa
    pg.evaluate("window.LAKITV.go(802)"); pg.wait_for_timeout(2300)
    check("ei automaattikiertoa", pg.evaluate("window.LAKITV.state.sub") == 0)
    # 2) kirjautunut: seuranta synkronoituu tilaukseen, downloads-kyky, ylläpitäjän webhookit
    pg2 = b.new_page(viewport={"width": 1280, "height": 820})
    pg2.clock.set_fixed_time(_FIXED)
    pg2.add_init_script("""
      window.__docs = {}; window.__saves = [];
      const mkdoc = p => ({get: async () => ({exists: p in window.__docs, data: () => window.__docs[p]}), set: async v => { window.__docs[p] = v; }, update: async v => { Object.assign(window.__docs[p], v); }, delete: async () => { delete window.__docs[p]; }});
      window.claude = { use: async n => n === 'db' ? {doc: mkdoc, collection: c => ({add: async v => ({id:'x'})})} : n === 'user' ? {id: async () => 'u_test123', isOwner: async () => true} : n === 'downloads' ? {save: async r => { window.__saves.push(r); return {status:'saved'}; }} : null };
    """)
    e2 = []; pg2.on("pageerror", lambda e: e2.append(str(e)))
    pg2.goto("file://" + BASE + "test/fixture.html"); pg2.wait_for_timeout(500); pg2.evaluate("window.LAKITV && window.LAKITV.setKbd && window.LAKITV.setKbd(true, false)"); pg2.wait_for_timeout(300)
    pg2.evaluate("window.LAKITV.go(741)"); pg2.wait_for_timeout(200)
    pg2.evaluate("window.LAKITV.show(741, window.LAKITV.getPage(741).subs.length - 1)"); pg2.wait_for_timeout(200)
    pg2.click("a[data-act='seuraa']"); pg2.wait_for_timeout(600)
    docs = pg2.evaluate("window.__docs")
    check("seuranta ei kirjoita tietokantaan", not any(k.startswith("tilaukset") for k in docs), docs)
    pg2.click("#kSub"); pg2.wait_for_timeout(800)
    check("ylläpitäjän webhook-lomake näkyy", pg2.is_visible("#jakeluAdmin") and pg2.is_visible("#whSlack"))
    pg2.fill("#whSlack", "https://hooks.slack.com/services/T/B/x"); pg2.click("#jakeluAdmin button"); pg2.wait_for_timeout(400)
    docs = pg2.evaluate("window.__docs")
    check("webhook tallentuu asetukset/jakelu", docs.get("asetukset/jakelu", {}).get("slack_webhook", "").startswith("https://hooks.slack.com"), docs.get("asetukset/jakelu"))
    check("JAKELU avaa kalenteri- ja syötenäkymän", pg2.get_attribute("#tabKal", "aria-selected") == "true" and pg2.locator("#paneKal a.pn-btn", has_text="RSS FI").count() == 1)
    pg2.click("#paneKal .kal-ev button:has-text('.ics')"); pg2.wait_for_timeout(400)
    saves = pg2.evaluate("window.__saves")
    check("downloads-kyky: save({filename:'laki-tv.ics'})", saves and saves[0]["filename"] == "laki-tv.ics" and "BEGIN:VCALENDAR" in saves[0]["data"], saves and saves[0]["filename"])
    # 3) työkalu: feed, kalenteri, viikkokatsaus, digest seurannalla, slack/teams
    os.makedirs("/tmp/t_out", exist_ok=True)
    r = subprocess.run(["python3", BASE + "tools/lakitv.py", "feed", BASE + "test/fixture_data.json", "--out", "/tmp/t_out"], capture_output=True, text=True)
    fx = open("/tmp/t_out/feed.xml", encoding="utf-8").read(); fj = json.load(open("/tmp/t_out/feed.json", encoding="utf-8")); md = open("/tmp/t_out/lakitv.md", encoding="utf-8").read(); ics = open("/tmp/t_out/kalenteri.txt", encoding="utf-8").read()
    check("feed.xml: RSS, jutut ja linkit", fx.startswith('<?xml') and fx.count("<item>") >= 50 and "#j=" in fx and "<pubDate>" in fx, r.stdout)
    check("feed.json: JSON Feed 1.1 kolmella kielellä", fj["version"].endswith("1.1") and len(fj["items"]) >= 100 and fj["items"][0]["_lakitv"].get("otsikko_en") and fj["items"][0]["_lakitv"].get("otsikko_sv"))
    check("lakitv.md: markdown kanavittain", md.startswith("---") and "## Korkein oikeus" in md and "<details><summary>English</summary>" in md)
    check("kalenteri.txt: määräaika + voimaantulopäivä", "SUMMARY:Lausuntoaika päättyy" in ics and "UID:vt-" in ics and ics.count("BEGIN:VEVENT") >= 3)
    r = subprocess.run(["python3", BASE + "tools/lakitv.py", "viikkokatsaus", BASE + "test/fixture_data.json", "--out", "/tmp/t_out/vk"], capture_output=True, text=True)
    check("viikkokatsaus: html + pdf", os.path.exists("/tmp/t_out/vk.html") and os.path.exists("/tmp/t_out/vk.pdf") and os.path.getsize("/tmp/t_out/vk.pdf") > 20000, r.stdout)
    json.dump({"a": {"email": "x@example.com", "sisalto": ["paiva"], "kieli": "fi", "suostumus": True,
                     "seuranta": [{"id": laus["id"], "tunnus": laus["tunnus"], "otsikko": laus["otsikko"], "k": "lausunnot", "tila": "dl:2026-01-01", "pvm": "2026-09-30"},
                                  {"id": "poistunut-juttu", "tunnus": "X", "otsikko": "VANHA JUTTU", "k": "kko", "tila": "pvm:2026-01-01", "pvm": "2026-09-30"}]}},
              open("/tmp/t_til.json", "w"))
    r = subprocess.run(["python3", BASE + "tools/lakitv.py", "digest", BASE + "test/fixture_data.json", "--laji", "aamu", "--tilaukset", "/tmp/t_til.json", "--out", "/tmp/t_msgs.json"], capture_output=True, text=True)
    msgs = json.load(open("/tmp/t_msgs.json"))
    txt = msgs[0]["text"] if msgs else ""
    check("digest: SEURANNASSA-osio muutoksesta ja poistuneesta", "SEURANNASSA" in txt and f"DL 1.1. → DL {int(laus['maaraaika'][8:10])}.{int(laus['maaraaika'][5:7])}." in txt and "Poistunut LAKI-TV:stä" in txt and "108" in msgs[0]["html"], txt[:600])
    r = subprocess.run(["python3", BASE + "tools/lakitv.py", "digest", BASE + "test/fixture_data.json", "--muoto", "slack", "--out", "/tmp/t_out/slack.json"], capture_output=True, text=True)
    sl = json.load(open("/tmp/t_out/slack.json"))
    check("slack-kuorma: text + mrkdwn-linkit", "text" in sl and "*LAKI-TV aamukooste" in sl["text"] and "<https://" in sl["text"])
    r = subprocess.run(["python3", BASE + "tools/lakitv.py", "digest", BASE + "test/fixture_data.json", "--muoto", "teams", "--out", "/tmp/t_out/teams.json"], capture_output=True, text=True)
    tm = json.load(open("/tmp/t_out/teams.json"))
    check("teams-kuorma: Adaptive Card", tm["type"] == "message" and tm["attachments"][0]["content"]["type"] == "AdaptiveCard" and len(tm["attachments"][0]["content"]["body"]) >= 3)
    check("ei JS-virheitä", not errs and not e2, errs + e2)
    b.close()
print(f"{sum(ok)} / {len(ok)} OK")
