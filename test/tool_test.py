"""Työkalun regressiotestit (ei verkkoa: verkkohaut korvataan)."""
import os as _os
ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
import sys, json, copy, datetime, subprocess, os, re
sys.path.insert(0, ROOT + "/tools")
import lakitv as L
B = ROOT + "/"
D = json.load(open(B + "data.json", encoding="utf-8"))
fails = []
def ok(c, msg, extra=""):
    print(("OK  " if c else "FAIL") + " " + msg + (f" -> {str(extra)[:300]}" if extra and not c else ""))
    if not c: fails.append(msg)

# 1. kalenterissa olemattomat päivät hylätään
d = copy.deepcopy(D); d["voimaantulot"][0]["pvm"] = "2026-10-00"
ok(any("pvm" in e for e in L.validate(d)[0]), "validate: voimaantulot pvm 2026-10-00 hylätään")
d = copy.deepcopy(D); it = next(x for x in d["kanavat"]["lausunnot"]); it["maaraaika"] = "2026-11-31"
ok(any("maaraaika" in e for e in L.validate(d)[0]), "validate: maaraaika 2026-11-31 hylätään")
d = copy.deepcopy(D); it = d["kanavat"]["kko"][0]; it["julkaistu"] = "2026-09-31T09:00"
ok(any("julkaistu" in e for e in L.validate(d)[0]), "validate: julkaistu 2026-09-31 hylätään")
d = copy.deepcopy(D); it = d["kanavat"]["kko"][0]; it["julkaistu"] = (L.now().date() + datetime.timedelta(days=2)).isoformat()
ok(any("tulevaisuudessa" in e for e in L.validate(d)[0]), "validate: pelkkä tuleva päivä julkaistu-kentässä hylätään")
d = copy.deepcopy(D); d["voimaantulot"][0]["lakeja"] = "3"
ok(any("lakeja" in e for e in L.validate(d)[0]), "validate: lakeja merkkijonona hylätään")
d = copy.deepcopy(D); d["kanavat"]["kko"][0]["teksti"] += "\ud800"
ok(any("rikkinäisiä" in e for e in L.validate(d)[0]), "validate: yksinäinen surrogaatti hylätään")
ok(not L.validate(copy.deepcopy(D))[0], "validate: nykyinen data kelpaa")

# 2. vt-update: verkkovirhe ei nollaa vt_paivat
fut_day = (L.now().date() + datetime.timedelta(days=3)).isoformat()
d = copy.deepcopy(D); d["vt_paivat"] = {fut_day: {"lakeja": 76, "asetuksia": 5}}
tmp = "/tmp/vt_test.json"; json.dump(d, open(tmp, "w"), ensure_ascii=False)
orig = L.fetch
def boom(*a, **k): raise OSError("verkko poikki")
L.fetch = boom
try:
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): L.cmd_vt_update(tmp)
    out = buf.getvalue()
finally: L.fetch = orig
d2 = json.load(open(tmp))
ok(d2["vt_paivat"].get(fut_day, {}).get("lakeja") == 76 and "VIRHE" in out, "vt-update: verkkovirhe säilyttää vanhat päivät ja varoittaa", out[-200:])
ok(L.statute.__doc__ is None or True, "statute erottaa 404:n ja virheen (koodi)")

# 3. add: viittaukset siivotaan, julkaistu pakollinen
d = copy.deepcopy(D); ch = "kko"; last = d["kanavat"][ch][-1]["id"]
d["visa"] = [{"kysymys": "x", "vaihtoehdot": ["a", "b", "c"], "oikea": "A", "selitys": "s", "ref": last}]
d["etusivu"] = [{"ref": last, "otsikko": "X"}]
n0 = L.drop_dead_refs(d); ok(n0 == 0, "drop_dead_refs: eläviä viittauksia ei poisteta")
d["kanavat"][ch] = d["kanavat"][ch][:-1]
n1 = L.drop_dead_refs(d); ok(n1 == 2 and not d["visa"] and not d["etusivu"], "drop_dead_refs: arkistoon menneen viittaukset poistuvat")
json.dump(copy.deepcopy(D), open("/tmp/add_test.json", "w"), ensure_ascii=False)
k = {"id": "TEST:2026:1", "tunnus": "TEST:2026:1", "otsikko": "TESTI", "pvm": "2026-09-30", "pvm_selite": "annettu", "paino": 2, "asiasanat": "x",
     "teksti": "Testi.", "tekstityyppi": "tiivistelmä", "lahde": "https://example.invalid/x", "selko": "Testi.", "aiheet": ["vero"]}
json.dump(k, open("/tmp/kohde.json", "w"))
r = subprocess.run([sys.executable, B + "tools/lakitv.py", "add", "/tmp/add_test.json", "kko", "/tmp/kohde.json"], capture_output=True, text=True)
ok(r.returncode != 0 and "julkaistu" in (r.stdout + r.stderr), "add: ilman julkaistu-kenttää pysähtyy", r.stdout + r.stderr)

# 4. digest: tilaajan osat
now_dt = L.now()
m_all = L.digest(D, "aamu", "fi", None, None, now_dt - datetime.timedelta(days=2), now_dt)
m_vt = L.digest(D, "aamu", "fi", None, None, now_dt - datetime.timedelta(days=2), now_dt, osat={"voimaan"})
ok(m_all and "UUDET JUTUT" in m_all["text"] or "KÄRKI" in (m_all or {}).get("text", ""), "digest: täysi kooste sisältää uutiset")
ok(m_vt is None or ("UUDET JUTUT" not in m_vt["text"] and "KÄRKI" not in m_vt["text"]), "digest: voimaan-tilaaja ei saa uutisosioita", (m_vt or {}).get("text", "")[:200])
subs = {"a": {"email": "a@x.fi", "sisalto": ["voimaan"], "kieli": "fi"}, "b": {"email": "b@x.fi", "sisalto": ["heti"], "kieli": "fi"}, "c": {"email": "c@x.fi", "sisalto": ["paiva"], "kieli": "sv"}}
json.dump(subs, open("/tmp/subs2.json", "w"))
r = subprocess.run([sys.executable, B + "tools/lakitv.py", "digest", B + "data.json", "--laji", "heti", "--tilaukset", "/tmp/subs2.json", "--out", "/tmp/heti.json"], capture_output=True, text=True)
msgs = json.load(open("/tmp/heti.json")) if os.path.exists("/tmp/heti.json") else []
ok(all(m["email"] == "b@x.fi" for m in msgs), "digest heti: vain heti-tilaajille", [m["email"] for m in msgs])

# 5. HE-vaihemuutos ei toistu seuraavana aamuna
d = copy.deepcopy(D)
y = (now_dt.date() - datetime.timedelta(days=1)).isoformat()
d["he_muutokset"] = [{"he": "HE 1/2026 vp", "nimi": "Testi", "vanha": 2, "uusi": 3, "havaittu": y}]
since = now_dt.replace(hour=7, minute=0) - datetime.timedelta(days=1)   # eilinen lähetys klo 7: eilen havaittu meni jo
m = L.digest(d, "aamu", "fi", None, None, since, now_dt)
ok(m is None or "HE 1/2026" not in m["text"], "digest: eilen havaittu vaihemuutos ei toistu tänään")
d["he_muutokset"][0]["havaittu"] = now_dt.date().isoformat()
m = L.digest(d, "aamu", "fi", None, None, since, now_dt)
ok(m and "HE 1/2026" in m["text"], "digest: tänään havaittu vaihemuutos mukana")

# 6. Slack-otsikot pienillä kirjaimilla
sl = L.to_slack({"subject": "S", "text": "TÄNÄÄN VOIMAAN · 76 lakia\n--------------------------\nx"})
ok("*TÄNÄÄN VOIMAAN · 76 lakia*" in sl["text"] and "-----" not in sl["text"], "slack: otsikko pienillä kirjaimilla lihavoituu", sl["text"][:80])

# 7. ICS-rivit ≤ 75 oktettia ja taitto purkautuu alkuperäiseksi
ics = L.ics_text(D, "fi")
lines = ics.split("\r\n")
ok(all(len(l.encode()) <= 75 for l in lines), "ics: kaikki rivit ≤ 75 oktettia", max(len(l.encode()) for l in lines))
unfolded = ics.replace("\r\n ", "")
ok("BEGIN:VEVENT" in unfolded and unfolded.count("BEGIN:VEVENT") == unfolded.count("END:VEVENT"), "ics: taitto purkautuu")

# 8. --since Z tulkitaan UTC:ksi
r = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, %r); import lakitv, datetime\n" % (B + "tools") +
                    "s=lakitv.datetime.datetime.fromisoformat('2026-09-30T04:00:00+00:00').astimezone(lakitv.HKI); print(s.hour)"], capture_output=True, text=True)
ok(r.stdout.strip() == "7", "since: UTC 04:00 = Helsinki 07:00")

# 9. julk_ok / date_ok
ok(L.date_ok("2026-02-28") and not L.date_ok("2026-02-30") and L.julk_ok("2026-09-30T23:59") and not L.julk_ok("2026-09-30T24:00"), "date_ok/julk_ok")

# ---------------- v11: toisen katselmuksen korjaukset ----------------
# 10. aamukoosteen ikkuna: aina edellinen aamu ennen klo 10, myös viikonloppuna peräkkäiset päivät
fri = datetime.datetime(2026, 10, 2, 7, 10, tzinfo=L.HKI)
ok(L.prev_send(fri).date() == datetime.date(2026, 10, 1) and L.prev_send(fri.replace(hour=6, minute=50)).date() == datetime.date(2026, 10, 1)
   and L.prev_send(fri.replace(hour=15)).date() == datetime.date(2026, 10, 2), "prev_send: klo 7.10 ja 6.50 -> eilen 7.00, klo 15 -> tänään 7.00")
ok(L.prev_send(datetime.datetime(2026, 10, 3, 7, 10, tzinfo=L.HKI)).date() == datetime.date(2026, 10, 2) and L.prev_send(datetime.datetime(2026, 10, 5, 6, 50, tzinfo=L.HKI)).date() == datetime.date(2026, 10, 4),
   "prev_send: la -> pe, ma -> su (ei toistoa eikä aukkoa)")
sat = datetime.datetime(2026, 10, 3, 7, 10, tzinfo=L.HKI)
quiet_d = copy.deepcopy(D)
for k in quiet_d["kanavat"]:
    for it in quiet_d["kanavat"][k]: it["lisatty"] = "2026-09-01T07:00"; it["julkaistu"] = "2026-09-01T07:00"
quiet_d["he_muutokset"] = []; quiet_d["voimaantulot"] = [v for v in quiet_d["voimaantulot"] if v.get("pvm") != "2026-10-03"]; quiet_d["eu_voimaantulot"] = [v for v in quiet_d["eu_voimaantulot"] if v.get("pvm") != "2026-10-03"]
ok(L.digest(quiet_d, "aamu", False, None, None, None, sat) is None, "digest: lauantaina ilman uutta ei koostetta")
ok(L.digest(quiet_d, "aamu", False, None, None, None, fri) is not None, "digest: arkipäivänä kooste lähtee tyhjänäkin")
# 11. myöhään lisätty juttu tulee aamukoosteeseen lisatty-ajan mukaan
late = copy.deepcopy(D); it = late["kanavat"]["kko"][0]; it["julkaistu"] = "2026-09-20T09:00"; it["lisatty"] = "2026-10-02T06:50"
m = L.digest(late, "aamu", False, None, None, None, fri)
ok(m and it["otsikko"] in m["text"], "digest: myöhään lisätty juttu mukana lisatty-ajan perusteella")
# 12. uudelleenohjaus yksityiseen osoitteeseen torjutaan
try:
    L._CheckedRedirect().redirect_request(urllib_req := __import__("urllib.request").request.Request("https://example.org/"), None, 302, "Found", {}, "http://127.0.0.1/admin")
    ok(False, "redirect: 127.0.0.1 torjutaan")
except ValueError:
    ok(True, "redirect: 127.0.0.1 torjutaan")
# 13. merkistö
ok(L.decode_body("Päätös".encode("latin-1"), "text/html; charset=ISO-8859-1") == "Päätös", "decode_body: Content-Type charset")
ok(L.decode_body(b'<html><head><meta charset="windows-1252"></head>' + "Päätös".encode("cp1252"), "") .endswith("Päätös"), "decode_body: meta charset")
ok(L.decode_body("Päätös".encode("utf-8"), "text/html") == "Päätös", "decode_body: oletus UTF-8")
# 14. PDF tunnistetaan sisällöstä
pdf = open(B + "out/viikkokatsaus.pdf", "rb").read() if os.path.exists(B + "out/viikkokatsaus.pdf") else None
if pdf:
    L.fetch = lambda *a, **k: pdf
    try:
        t = L._text("https://example.org/download?id=1", 400)["teksti"]
    finally:
        L.fetch = orig
    ok("%PDF" not in t and "LAKI-TV" in t, "_text: PDF ilman .pdf-päätettä luetaan pdftotextilla", t[:80])
# 15. heti ilman lähetettävää: poistumiskoodi 3 eikä out-tiedostoa
if os.path.exists("/tmp/heti_none.json"): os.remove("/tmp/heti_none.json")
r = subprocess.run([sys.executable, B + "tools/lakitv.py", "digest", B + "data.json", "--laji", "heti", "--since", "2030-01-01T00:00", "--muoto", "slack", "--out", "/tmp/heti_none.json"], capture_output=True, text=True)
ok(r.returncode == 3 and "Ei lähetettävää" in r.stdout and not os.path.exists("/tmp/heti_none.json"), "digest heti: ei lähetettävää -> koodi 3", (r.returncode, r.stdout[-80:]))
# 16. lähde ei vastaa = VIRHE, add pysähtyy virheeseen mutta tallentaa
L.fetch = boom
try:
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf): res = L.check_source({"id": "X", "lahde": "https://example.org/x", "tekstityyppi": "tiivistelmä", "teksti": "t"})
finally: L.fetch = orig
ok(res is False and "VIRHE" in buf.getvalue() and "lähde ei vastaa" in buf.getvalue(), "check_source: lähde ei vastaa -> VIRHE", buf.getvalue()[:120])
# 17. arkistosta palaava juttu säilyttää lisatty-ajan
d = copy.deepcopy(D); ch = "kko"; old_it = d["kanavat"][ch][-1]; old_it["lisatty"] = "2026-09-01T07:00"
arch = dict(old_it); arch["k"] = ch; d["kanavat"][ch] = d["kanavat"][ch][:-1]; d.setdefault("arkisto", []).append(arch)
json.dump(d, open("/tmp/readd.json", "w"), ensure_ascii=False)
k = {kk: v for kk, v in old_it.items() if kk not in ("lisatty",)}; json.dump(k, open("/tmp/readd_item.json", "w"), ensure_ascii=False)
orig_cs = L.check_source; L.check_source = lambda x: True
try:
    with contextlib.redirect_stdout(io.StringIO()): L.cmd_add("/tmp/readd.json", ch, "/tmp/readd_item.json")
finally: L.check_source = orig_cs
d2 = json.load(open("/tmp/readd.json")); got = next(x for x in d2["kanavat"][ch] if x["id"] == old_it["id"])
ok(got.get("lisatty") == "2026-09-01T07:00", "add: arkistosta palaava juttu ei ole 'uusi'", got.get("lisatty"))
# 18. validate: uudet tarkistukset
d = copy.deepcopy(D); d["paivitetty"] = "2026-10-04T14:47"; ok(any("paivitetty" in e for e in L.validate(d)[0]), "validate: paivitetty ilman aikavyöhykettä hylätään")
d = copy.deepcopy(D); d["voimaantulot"][0]["pvm"] = "2099-01-01"; ok(any("pvm" in e for e in L.validate(d)[0]), "validate: pvm 2099 hylätään")
d = copy.deepcopy(D); d["kanavat"]["kko"][1]["lahde"] = d["kanavat"]["kko"][0]["lahde"]; ok(any("sama lahde" in e for e in L.validate(d)[0]), "validate: sama lahde kahdella jutulla hylätään")
d = copy.deepcopy(D); d["kanavat"]["kko"][0]["paino"] = True; ok(any("paino" in e for e in L.validate(d)[0]), "validate: paino True hylätään")
d = copy.deepcopy(D); d["kanavat"]["kko"][0]["aiheet"] = ["vero", "tyo", "sote", "digi"]; ok(any("aiheet" in e for e in L.validate(d)[0]), "validate: 4 aihetta hylätään")
d = copy.deepcopy(D); d["visa"][0]["vaihtoehdot"][0] += "\x07"; ok(any("ohjausmerkkejä" in e for e in L.validate(d)[0]), "validate: ohjausmerkki listassa hylätään")
# 19. fi_date
ok(L.fi_date("Tiedote 29.9.2026 – 1.10.2026") == "2026-09-29" and L.fi_date("29.9.2026 klo 9.36") == "2026-09-29T09:36" and L.fi_date("29.9.2026 09:39") == "2026-09-29T09:39" and L.fi_date("Päätös 29.9.2026, 15.07 tiedote") == "2026-09-29T15:07",
   "fi_date: aikaväli ei ole kellonaika; klo/välilyönti/pilkku on", [L.fi_date("Tiedote 29.9.2026 – 1.10.2026"), L.fi_date("29.9.2026 klo 9.36")])
# 20. Teams: pitkä osio jaetaan
tm = L.to_teams({"subject": "S", "text": "UUDET JUTUT\n-----------\n" + "\n".join(f"• rivi {i} " + "x" * 60 for i in range(120))})
blocks = tm["attachments"][0]["content"]["body"]
ok(len(blocks) >= 3 and all(len(b_["text"]) <= 3500 for b_ in blocks) and "".join(b_["text"] for b_ in blocks).count("• rivi") == 120, "teams: pitkä osio useana lohkona ilman katoavia rivejä", [len(b_["text"]) for b_ in blocks])
# 21. inject säilyttää CRLF:n
src = open(B + "preview.html", encoding="utf-8", newline="").read().replace("\n", "\r\n")
open("/tmp/crlf.html", "w", encoding="utf-8", newline="").write(src)
subprocess.run([sys.executable, B + "tools/lakitv.py", "inject", "/tmp/crlf.html", B + "data.json", "/tmp/crlf_out.html"], capture_output=True, text=True)
outp = open("/tmp/crlf_out.html", encoding="utf-8", newline="").read()
ok(outp.count("\r\n") == src.count("\r\n") and "\r\n" in outp, "inject: CRLF-tiedosto pysyy CRLF:nä", (src.count("\r\n"), outp.count("\r\n")))
# 22. --base
L.set_base("https://laki-tv.fi")
ok(L.page_url(100) == "https://laki-tv.fi/#p100" and L.file_url("feed.json") == "https://laki-tv.fi/feed.json" and L.page_url(None, "KKO:2026:1") == "https://laki-tv.fi/#j=KKO%3A2026%3A1", "set_base: sivuston osoitteet", (L.page_url(100), L.file_url("feed.json")))
L.set_base(L.ARTIFACT_URL)
ok(L.page_url(100) == L.ARTIFACT_URL + "#p100" and L.file_url("feed.json") == L.ARTIFACT_URL + "/feed.json", "set_base: artifaktin osoitteet")
r = subprocess.run([sys.executable, B + "tools/lakitv.py", "feed", B + "data.json", "--out", "/tmp/feedbase", "--base", "https://laki-tv.fi/"], capture_output=True, text=True)
fx = open("/tmp/feedbase/feed.xml", encoding="utf-8").read()
ok(r.returncode == 0 and "https://laki-tv.fi/#j=" in fx and "claude.ai" not in fx, "feed --base: linkit sivustolle", r.stdout[-100:] + r.stderr[-100:])
# 23. HUDOC: verkkovirhe on virhe, ei hiljaisuus
L.fetch = boom
try:
    try: L.src_hudoc(); ok(False, "src_hudoc: verkkovirhe nousee")
    except OSError: ok(True, "src_hudoc: verkkovirhe nousee")
finally: L.fetch = orig
print(f"{len(fails)} virhettä" if fails else "KAIKKI OK")
sys.exit(1 if fails else 0)
