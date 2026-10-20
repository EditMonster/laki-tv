"""Uusien skannerilähteiden (10/2026) jäsennystestit tallennetuilla sivuilla: ei verkkoa.
Yrityskaupat (KKV, komissio), PeVL, EU-asetukset, KVL, lautakunnat (YVTltk, KRIL), komission kilpailutiedotteet."""
import datetime, sys, json, re, os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
sys.path.insert(0, _ROOT + "/tools")
import lakitv as L
F = _ROOT + "/test/fixtures/"
fails = []
def ok(c, msg, extra=""):
    print(("OK  " if c else "FAIL") + " " + msg + (f" -> {str(extra)[:300]}" if extra and not c else ""))
    if not c: fails.append(msg)

def rd(name): return open(F + name, encoding="utf-8").read()

# verkko korvataan: osoite -> tallennettu sivu
PAGES = {
    "https://www.kkv.fi/paatokset/kilpailuasiat/yrityskauppavalvonta/": rd("kkv_yrityskaupat.html"),
    "https://www.kkv.fi/paatokset/vireilla-olevat-yrityskaupat/": rd("kkv_vireilla.html"),
    "https://www.yvtltk.fi/feed/rss-feed?post_type=tapausseloste": rd("yvtltk_rss.xml"),
    "https://www.kuluttajariita.fi/feed/rss-feed?post_type=paatos": rd("kril_rss.xml"),
    "https://www.vero.fi/syventavat-vero-ohjeet/ennakkoratkaisut/377073/kvl0222026/": rd("kvl_2026_22.html"),
    "https://www.vero.fi/sitemap.xml": ('<?xml version="1.0"?><urlset><url><loc>https://www.vero.fi/syventavat-vero-ohjeet/ennakkoratkaisut/377073/kvl0222026/</loc>'
                                         f'<lastmod>{L.now().date().isoformat()}T10:00:00+03:00</lastmod></url><url><loc>https://www.vero.fi/harmaa-talous/</loc><lastmod>2026-10-19T14:00:10+03:00</lastmod></url>'
                                         '<url><loc>https://www.vero.fi/syventavat-vero-ohjeet/ennakkoratkaisut/1/kvl0012020/</loc><lastmod>2020-01-01T10:00:00+03:00</lastmod></url></urlset>'),
}
def fake_get_text(url, **k):
    for u, body in PAGES.items():
        if url == u or url.startswith(u):
            return body
    if "kuluttajariita.fi/paatokset/" in url: return rd("kril_paatos.html")
    if "yvtltk.fi/tapausselosteet/" in url: return rd("yvtltk_seloste.html")
    if "presscorner/api/search" in url: return rd("presscorner.json")
    raise OSError("ei verkkoa testissä: " + url)
L.get_text = fake_get_text
L.SCAN_CTX["data"] = {"kanavat": {k: [] for k in L.CH_KEYS}, "arkisto": [], "_nahty": []}

# 1. KKV: päätökset ja vireillä olevat
r = L.src_kkv_yrityskaupat()
dec = [x for x in r if x["vaihe"] == "päätös"]; pend = [x for x in r if x["vaihe"] == "vireillä"]
ok(len(dec) >= 3 and dec[0]["otsikko"] == "Nimlas Finland Oy / Tammelan Talotekniikka Oy" and dec[0]["julkaistu"] == "2026-10-15"
   and dec[0]["laji"] == "Yrityskaupan hyväksyminen sellaisenaan" and dec[0]["tunnus"] == "KKV/1410/14.00.10/2026", "KKV-YK: päätöslista (otsikko, pvm, laji, tunnus)", dec[:1])
ok(len(pend) == 3 and pend[0]["kuuleminen"] == "2026-10-23" and "(kuuleminen" not in pend[0]["otsikko"] and pend[0]["valmis"], "KKV-YK: vireillä olevat (kuulemisen määräaika)", pend[:1])

# 2. Komission yrityskauppavalvonta: suomalainen osapuoli tunnistetaan ilmoituksen tekstistä; muut jätetään pois; päätös tunnetusta asiasta mukaan
L._sparql = lambda q, timeout=90: [
    {"celex": {"value": "52026M12540"}, "pub": {"value": "2026-10-20"}, "title": {"value": "Ennakkoilmoitus yrityskeskittymästä (Asia M.12540 – AP EJENDOMME / CAPMAN AIFM / HOTEL) – Yksinkertaistettuun menettelyyn mahdollisesti soveltuva asia"}},
    {"celex": {"value": "52026M12661"}, "pub": {"value": "2026-10-20"}, "title": {"value": "Ennakkoilmoitus yrityskeskittymästä (Asia M.12661 – VERITAS / BODYCOTE)"}},
    {"celex": {"value": "52026M12516(01)"}, "pub": {"value": "2026-10-19"}, "title": {"value": "Ilmoitetun keskittymän vastustamatta jättäminen (Asia M.12516 – KESKO / DAHL)"}},
    {"celex": {"value": "52026M12000(01)"}, "pub": {"value": "2026-10-19"}, "title": {"value": "Ilmoitetun keskittymän vastustamatta jättäminen (Asia M.12000 – A / B)"}}]
TEXTS = {"52026M12540": "Ennakkoilmoitus\n1.\nKomissio vastaanotti ilmoituksen.\nIlmoitus koskee seuraavia yrityksiä:\n— AP Ejendomme A/S (AP, Tanska)\n— CapMan AIFM Oy (CapMan, Suomi)\n2.\nKyseisten yritysten liiketoiminnan sisältö on seuraava:\n— AP on kiinteistösijoitusyhtiö.\n— CapMan hallinnoi rahastoja.\n3.\nKomissio katsoo.",
         "52026M12661": "Ennakkoilmoitus\n1.\nIlmoitus koskee seuraavia yrityksiä:\n— Veritas Capital (Veritas, Yhdysvallat)\n— Bodycote plc (Bodycote, Yhdistynyt kuningaskunta)\n2.\nKyseisten yritysten liiketoiminnan sisältö on seuraava:\n— Veritas on sijoitusyhtiö.\n3.\nKomissio katsoo."}
L.cellar_text = lambda celex, url, maxc, lang="FI": {"teksti": TEXTS[celex]}
L.SCAN_CTX["data"]["kanavat"]["yrityskaupat"] = [{"id": "eu-m-12516", "lahde": "https://eur-lex.europa.eu/legal-content/FI/TXT/?uri=CELEX:52026M12516"}]
r = L.src_eu_yrityskaupat()
ok([x["tunnus"] for x in r] == ["M.12540", "M.12516"] and r[0]["maat"] == ["Tanska", "Suomi"] and r[0]["id_ehdotus"] == "eu-m-12540" and "CapMan hallinnoi" in r[0]["kuvaus"],
   "EU-YK: Suomi-osapuoli mukaan, ulkomainen pois, tunnetun asian päätös mukaan", [(x["tunnus"], x.get("maat")) for x in r])
ok(r[1]["paivitys"] and r[1]["laji"].startswith("komissio hyväksyi"), "EU-YK: vastustamatta jättäminen merkitään päivitykseksi", r[1])

# 3. EU-asetukset: täytäntöönpanoasetukset pois, EP+neuvosto, neuvosto ja delegoidut mukaan; muut kielet
def sparql_reg(q, timeout=90):
    if "VALUES ?celex" in q:
        lang = "SWE" if "/SWE>" in q else "ENG"
        return [{"celex": {"value": "32026R2269"}, "title": {"value": "Europaparlamentets och rådets förordning (EU) 2026/2269" if lang == "SWE" else "Regulation (EU) 2026/2269 of the European Parliament and of the Council"}}]
    return [{"celex": {"value": "32026R2269"}, "date": {"value": "2026-10-07"}, "pub": {"value": "2026-10-09"}, "eif": {"value": "2026-10-10"}, "trans": {"value": "2027-01-01"},
             "title": {"value": "Euroopan parlamentin ja neuvoston asetus (EU) 2026/2269, annettu 7 päivänä lokakuuta 2026, testistä"}},
            {"celex": {"value": "32026R2311"}, "date": {"value": "2026-10-19"}, "pub": {"value": "2026-10-20"}, "title": {"value": "Komission täytäntöönpanoasetus (EU) 2026/2311, annettu 19 päivänä lokakuuta 2026, lopullisen polkumyyntitullin käyttöön ottamisesta"}},
            {"celex": {"value": "32026R1536"}, "date": {"value": "2026-07-06"}, "pub": {"value": "2026-10-14"}, "eif": {"value": "2026-12-07"}, "title": {"value": "Komission delegoitu asetus (EU) 2026/1536, annettu 6 päivänä heinäkuuta 2026, testistä"}}]
L._sparql = sparql_reg
r = L.src_eu_asetukset()
ok([x["tunnus"] for x in r] == ["Asetus (EU) 2026/2269", "Asetus (EU) 2026/1536"] and r[0]["laatija"] == "EP ja neuvosto" and r[1]["laatija"] == "komissio (delegoitu)"
   and r[0]["otsikko_sv"].startswith("Europaparlamentets") and r[0]["otsikko_en"].startswith("Regulation") and "sovelletaan 1.1.2027" in r[0]["kuvaus"] and r[0]["eli"] == "http://data.europa.eu/eli/reg/2026/2269/oj",
   "EU-ASETUS: täytäntöönpanoasetus pois, nimikkeet sv/en, soveltamispäivä, ELI", [(x["tunnus"], x["laatija"], x["kuvaus"]) for x in r])

# 4. PeVL eduskunnan avoimesta datasta
d = json.load(open(F + "pevl_30_2026.json")); row = dict(zip(d["columnNames"], d["rowData"][0]))
ok(L._is_pevl_doc(row) and not L._is_he_doc(row), "PeVL: asiakirja tunnistetaan (ei HE)")
x = L.pevl_item(row, re.match(r"PeVL (\d+)/(\d{4}) vp$", row["Eduskuntatunnus"]))
ok(x["kanava"] == "he" and x["tunnus"] == "PeVL 30/2026 vp" and x["he"] == "HE 52/2026 vp" and x["vastaanottaja"] == "Hallintovaliokunnalle"
   and x["paatosesitys"].startswith("Perustuslakivaliokunta esittää") and x["url"].endswith("PeVL+30/2026") and x["otsikko"].startswith("PeVL: Hallituksen esitys"),
   "PeVL: kohde-HE, vastaanottaja, päätösesitys, osoite", x)
ok(L.api_url_for("https://www.eduskunta.fi/valtiopaivaasiakirjat/PeVL+30/2026") == ("pevl", 30, 2026), "PeVL: osoite ohjataan rajapintaan (text)")

# 5. KVL vero.fi:n sivukartasta ja ratkaisusivulta
r = L.src_kvl()
ok(len(r) == 1 and r[0]["tunnus"] == "KVL:2026/22" and r[0]["annettu"] == "2026-08-21" and r[0]["lainvoimainen"] == "Lainvoimainen"
   and r[0]["asiasanat"].startswith("Arvonlisävero, Hammasproteesi") and r[0]["kuvaus"].startswith("A Oy valmisti ja myi poraohjaimia") and r[0]["kanava"] == "vero",
   "KVL: sivukartta (vain tuoreet ratkaisusivut) + tunnus, antopäivä, lainvoimaisuus, asiasanat, teksti", r[:1])

# 6. Lautakunnat: RSS + sivu; KRIL vain täysistuntoratkaisut
r = L.SOURCES["YVTLTK"]()
ok(len(r) == 3 and r[0]["kanava"] == "muut" and r[0]["elin"].startswith("Yhdenvertaisuus") and r[0]["annettu"] == "2026-10-08" and r[0]["lainvoimainen"] == "Ei lainvoimainen"
   and r[0]["asiasanat"].startswith("Hyvitys, Perusopetus") and r[0]["kuvaus"].startswith("Kevätjuhla") and r[0]["julkaistu"].startswith("2026-10-08T"), "YVTLTK: RSS ja selosteen metatiedot", r[:1])
r = L.SOURCES["KRIL"]()
ok(len(r) == 3 and all(x["taysistunto"] for x in r) and r[0]["diaari"] == "D/984/34/2026" and r[0]["annettu"] == "2026-10-12" and r[0]["kuvaus"].startswith("Kuluttaja tilasi"),
   "KRIL: täysistuntopäätökset, diaari, antopäivä, selostus", r[:1])

# 7. Komission kilpailutiedotteet: otsikkosuodatus ja yksinkertaistetut yrityskauppahyväksynnät pois
r = L.src_eu_kilpailu()
ok([x["otsikko"][:20] for x in r] == ["Commission fines Kin", "State aid: Commissio"] and r[0]["url"].endswith("/ip_26_2100") and r[0]["kanava"] == "kilpailu" and r[1]["julkaistu"] == "2026-10-07",
   "EU-KILPAILU: sakot ja valtiontuki mukaan, puheet ja rutiinihyväksynnät pois", [x["otsikko"] for x in r])

# 8. validate: uudet kanavat kelpaavat; puuttuvat kanavat ovat huomautus, tuntematon kanava virhe
base = json.load(open(_ROOT + "/data.json", encoding="utf-8"))
E, W = L.validate(base)
ok(not any("kanavat" in e for e in E), "validate: data ilman uusia kanavia ei ole virhe" + (" (puuttuvat huomautuksena)" if any("kanavat puuttuvat" in w for w in W) or set(L.CH_KEYS) <= set(base["kanavat"]) else ""), E[:3])
bad = dict(base); bad["kanavat"] = dict(base["kanavat"]); bad["kanavat"]["tuntematon"] = []
ok(any("kanavat-avaimet" in e for e in L.validate(bad)[0]), "validate: tuntematon kanava on virhe")
ok(L.CH_PAGE["yrityskaupat"] == 520 and L.CH_PAGE["vero"] == 650 and L.CH_NAMES["vero"][1] == "Beskattning", "kanavat: sivunumerot ja nimet")
ok("HE" in L.ZERO_OK and "KVL" in L.ZERO_OK, "ZERO_OK: harvoin julkaisevat lähteet eivät hälytä tyhjästä")

# 9. Presscorner-tiedotteen teksti luetaan documents-rajapinnasta (sivu on JavaScript-sovellus)
_pc_urls = []
def fake_fetch(url, **k):
    _pc_urls.append(url)
    return rd("presscorner_doc.json").encode("utf-8")
L.fetch = fake_fetch
r = L._text("https://ec.europa.eu/commission/presscorner/detail/en/ip_26_2178", 5000)
ok(_pc_urls == ["https://ec.europa.eu/commission/presscorner/api/documents?reference=IP/26/2178&language=en"] and r["julkaistu"] == "2026-10-19"
   and r["otsikko"].startswith("Commission sends Statement") and r["teksti"].startswith("The European Commission has informed KKR & Co.") and "\nThe merger investigation\n" in r["teksti"]
   and r["teksti"].endswith("Point one\nPoint two"), "text: presscorner-tiedote rajapinnasta (viite, päivä, teksti)", r)

# 10. scan: lähteen omaa aikaikkunaa käyttävät (EU-ASETUS, EU-DIR, EU-YK, KVL) eivät karsiudu since-rajaan; muut karsiutuvat; nähdyt eivät tule uudelleen
import tempfile, os
old_day = (datetime.date.today() - datetime.timedelta(days=9)).isoformat()
stub = {
    "EU-ASETUS": lambda: [{"kanava": "eu", "url": "https://eur-lex.europa.eu/eli/reg/2026/9999/oj", "tunnus": "Asetus (EU) 2026/9999", "otsikko": "Testiasetus", "julkaistu": old_day, "valmis": True}],
    "KKO": lambda: [{"kanava": "kko", "url": "https://finlex.fi/fi/oikeuskaytanto/korkein-oikeus/ennakkopaatokset/2026/999", "tunnus": "KKO:2026:999", "otsikko": "Vanha", "julkaistu": old_day + "T10:00", "valmis": True}],
    "KVL": lambda: [{"kanava": "vero", "url": "https://www.vero.fi/syventavat-vero-ohjeet/ennakkoratkaisut/kvl99999/", "tunnus": "KVL:2026/99", "otsikko": "KVL:2026/99", "julkaistu": old_day, "valmis": True}],
}
_src, _per = L.SOURCES, dict(L.PER_SOURCE)
L.SOURCES = stub
with tempfile.TemporaryDirectory() as td:
    cwd = os.getcwd(); os.chdir(td)
    try:
        dd = {"paivitetty": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S+03:00"), "kanavat": {k: [] for k in L.CH_KEYS}, "arkisto": [], "_nahty": [L.url_hash("https://www.vero.fi/syventavat-vero-ohjeet/ennakkoratkaisut/kvl99999/")]}
        json.dump(dd, open("d.json", "w", encoding="utf-8"))
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            L.cmd_scan("d.json")
        e = json.load(open("ehdokkaat.json", encoding="utf-8"))
        tun = sorted(x["tunnus"] for x in e["ehdokkaat"])
        ok(tun == ["Asetus (EU) 2026/9999"], "scan: EU-ASETUS ohittaa since-rajan (oma ikkuna), vanha KKO karsiutuu, nähty KVL ei tule uudelleen", tun)
    finally:
        os.chdir(cwd)
L.SOURCES = _src

# 11. Säädöskokoelma: numeroita tutkitaan suurimmasta tunnetusta eteenpäin; laki ja asetus tunnistetaan; teksti avoimesta datasta
import urllib.error
_fetch = L.fetch
def fake_fetch(url, **k):
    m = re.search(r"/statute/2026/(\d+)/fin@$", url)
    if m and _os.path.exists(F + f"statute_2026_{m.group(1)}.xml"):
        return open(F + f"statute_2026_{m.group(1)}.xml", "rb").read()
    if m:
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    raise OSError("ei verkkoa testissä: " + url)
L.fetch = fake_fetch
_now = L.now
L.now = lambda: datetime.datetime(2026, 10, 20, 12, 0, tzinfo=L.HKI)
L.SCAN_CTX["data"] = {"kanavat": {k: [] for k in L.CH_KEYS}, "arkisto": [], "_nahty": [], "voimaantulot": [{"saados": "899/2026", "pvm": "2026-11-01"}], "vt_arkisto": []}
r = L.src_saadoskokoelma()
ok([x["tunnus"] for x in r] == ["915/2026", "900/2026"] and r[0]["tyyppi"] == "laki" and r[1]["tyyppi"] == "asetus" and r[1]["julkaistu"] == "2026-10-15"
   and r[1]["voimaantulo"] == "2026-10-16" and r[1]["muutossaados"] and r[0]["otsikko"].startswith("Laki tutkintavankeuslain") and r[0]["kuvaus"].startswith("Eduskunnan päätöksen")
   and r[0]["kanava"] == "he" and L.SCAN_CTX.get("sk_viimeisin") == 915, "SÄÄDÖSKOKOELMA: uudet säädökset 899:n jälkeen (laki ja asetus, päivät, voimaantulo)", [(x["tunnus"], x.get("tyyppi"), x.get("julkaistu"), x.get("voimaantulo")) for x in r])
ok(L.api_url_for("https://www.finlex.fi/fi/lainsaadanto/saadoskokoelma/2026/900") == ("sk", 900, 2026), "SÄÄDÖSKOKOELMA: finlex.fi-osoite ohjataan avoimeen dataan (text)")
t = L._text("https://www.finlex.fi/fi/lainsaadanto/saadoskokoelma/2026/900", 400)
ok(t["otsikko"].startswith("Valtioneuvoston asetus maatalousyrittäjän") and t["voimaantulo"] == "2026-10-16" and "Valtion osuuden ennakko" in t["teksti"], "text: säädöksen teksti avoimesta datasta", t)
L.SCAN_CTX["data"]["voimaantulot"] = []
ok(L.src_saadoskokoelma() == [], "SÄÄDÖSKOKOELMA: ilman vertailukohtaa ei arvailla (vt-update antaa numerot)")
L.fetch = _fetch; L.now = _now

# 12. Tiedotteet (WordPress-RSS): rutiini ja rinnakkaiskieliset pois, tuomioistuimen nimi ja kanava (hao/muut), sivun teksti
PAGES.update({
    "https://www.tuomioistuimet.fi/ajankohtaista/tiedotteet/feed/": rd("tuomioistuimet_rss.xml"),
    "https://www.korkeinoikeus.fi/feed/rss-feed?post_type=ajankohtaiset": rd("kko_rss.xml"),
    "https://www.syyttajalaitos.fi/feed/rss-feed?post_type=ajankohtaiset": rd("syyttaja_rss.xml"),
    "https://www.tuomioistuimet.fi/ajankohtaista/tiedotteet/hovioikeuden-tuomio-terrorismirikoksia-koskevassa-asiassa/": rd("tiedote_ho_terrorismi.html"),
    "https://www.korkeinoikeus.fi/ajankohtaista/tiedote-ja-uutisarkisto/korkein-oikeus-myonsi-valitusluvan-lehtisaarelaisen-taloyhtion-maanvuokrasopimusriidassa/": rd("tiedote_kko_valituslupa.html"),
})
_fgt = L.get_text
def fake_get_text2(url, **k):
    try:
        return fake_get_text(url, **k)
    except OSError:
        if "tuomioistuimet.fi/ajankohtais" in url or "korkeinoikeus.fi/ajankohtaista/" in url or "syyttajalaitos.fi/" in url:
            return "<html><head><title>X</title></head><body><main><p>Tiedote. Helsingin käräjäoikeus antoi tuomion.</p></main></body></html>"
        raise
L.get_text = fake_get_text2
L.SCAN_CTX["data"] = {"kanavat": {k: [] for k in L.CH_KEYS}, "arkisto": [], "_nahty": []}
r = L.SOURCES["TUOMIOISTUIMET"]()
titles = [x["otsikko"] for x in r]
ok(all(not L.TIEDOTE_SKIP.search(t) and not L.SV_EN_TITLE.search(t) for t in titles) and not any("Court of Appeal" in t or "Avoimet" in t or "viikkotiedote" in t.lower() for t in titles)
   and any(x["otsikko"].startswith("Hovioikeuden tuomio terrorismi") and x["kanava"] == "muut" and x["elin"] == "Itä-Suomen hovioikeus" and "terrorismi" in x["kuvaus"].lower() for x in r)
   and all(x["kanava"] == "hao" for x in r if "hallinto-oikeu" in x["otsikko"].lower()), "TUOMIOISTUIMET: rutiini ja englanti pois, hovioikeuden nimi sivulta, hallinto-oikeudet hao-kanavalle", [(x["kanava"], x.get("elin"), x["otsikko"][:50]) for x in r])
r = L.SOURCES["KKO-TIED"]()
ok(r and all(x["kanava"] == "kko" and x["elin"] == "Korkein oikeus" for x in r) and not any(re.search(r"Högsta|utlåtande|puhe", x["otsikko"], re.I) for x in r)
   and any(x["otsikko"].startswith("Korkein oikeus myönsi valitusluvan lehtisaarelaisen") and "valituslu" in x["kuvaus"].lower() for x in r), "KKO-TIED: valitusluvat mukaan, ruotsi ja puheet pois, teksti sivulta", [x["otsikko"][:60] for x in r])
r = L.SOURCES["SYYTTAJA"]()
ok(r and all(x["kanava"] == "muut" and x["elin"] == "Syyttäjälaitos" for x in r) and not any(re.search(r"Misstank|Undersökningsled|Käyntiasiointi", x["otsikko"]) for x in r),
   "SYYTTAJA: ruotsi ja asiointitiedotteet pois", [x["otsikko"][:60] for x in r])
L.get_text = fake_get_text

# 13. Komission ehdotukset: vain asetus- ja direktiiviehdotukset (SPARQL-suodatus), suomenkielinen nimike kun saatavilla, tunnus COM(vvvv) n
def sparql_com(q, timeout=90):
    if "PROP_REG" in q:
        return [{"celex": {"value": "52026PC0569"}, "date": {"value": "2026-10-14"}, "rt": {"value": "http://publications.europa.eu/resource/authority/resource-type/PROP_REG"}, "title": {"value": "Proposal for a REGULATION OF THE EUROPEAN PARLIAMENT AND OF THE COUNCIL amending Regulation (EU) 2024/1787"}, "svc": {"value": "ENER"}},
                {"celex": {"value": "52026PC0515"}, "date": {"value": "2026-10-01"}, "rt": {"value": "http://publications.europa.eu/resource/authority/resource-type/PROP_DIR"}, "title": {"value": "Proposal for a COUNCIL DIRECTIVE amending Directive 2006/112/EC"}}]
    if "FIN" in q:
        return [{"celex": {"value": "52026PC0569"}, "title": {"value": "Ehdotus EUROOPAN PARLAMENTIN JA NEUVOSTON ASETUS metaanipäästöjen vähentämisestä"}}]
    return []
L._sparql = sparql_com
r = L.src_eu_ehdotukset()
ok([x["tunnus"] for x in r] == ["COM(2026) 569", "COM(2026) 515"] and r[0]["laji"] == "asetusehdotus" and r[1]["laji"] == "direktiiviehdotus" and r[0]["otsikko"].startswith("Ehdotus EUROOPAN")
   and r[0]["otsikko_fi_saatavilla"] and not r[1]["otsikko_fi_saatavilla"] and r[1]["otsikko"].startswith("Proposal for a COUNCIL DIRECTIVE") and r[0]["id_ehdotus"] == "com-2026-569"
   and r[0]["url"].endswith("CELEX:52026PC0569") and r[0]["kanava"] == "eu", "EU-EHDOTUS: asetus- ja direktiiviehdotukset, nimike fi/en, tunnus ja id", r)

# 14. Eduskunnan vastaus (EV): tunnistus, HE-viite, päätöspäivä, mietintö, päätösteksti ja id he-paatos-N-vvvv
row = json.load(open(F + "ev_100_2026.json", encoding="utf-8"))
ok(L._is_ev_doc(row) and not L._is_he_doc(row) and not L._is_pevl_doc(row), "EV: asiakirja tunnistetaan")
x = L.ev_item(row, re.match(r"EV (\d+)/(\d{4}) vp$", row["Eduskuntatunnus"]))
ok(x["tunnus"] == "EV 100/2026 vp" and x["he"] == "HE 22/2026 vp" and x["paatospvm"] == "2026-06-09" and x["mietinto"] == "TaVM 20/2026 vp" and x["lopputulos_arvio"] == "hyväksytty"
   and x["id_ehdotus"] == "he-paatos-22-2026" and x["asiasanat"].startswith("luottolaitokset") and x["otsikko"].startswith("Eduskunnan vastaus: Hallituksen esitys") and x["kanava"] == "he",
   "EV: kentät (HE, päätöspäivä, mietintö, päätös, id)", x)
ok(L.api_url_for("https://www.eduskunta.fi/valtiopaivaasiakirjat/EV+100/2026") == ("ev", 100, 2026), "EV: osoite ohjataan rajapintaan (text)")
ok({"SAADOSKOKOELMA", "TUOMIOISTUIMET", "KKO-TIED", "KHO-TIED", "SYYTTAJA", "EU-EHDOTUS"} <= set(L.SOURCES) and {"SAADOSKOKOELMA", "EU-EHDOTUS"} <= L.OWN_WINDOW
   and {"KKO-TIED", "SYYTTAJA", "EU-EHDOTUS", "SAADOSKOKOELMA"} <= L.ZERO_OK, "SOURCES/OWN_WINDOW/ZERO_OK: uudet lähteet rekisteröity")

print(("KAIKKI OK" if not fails else f"{len(fails)} virhettä: " + "; ".join(fails)))
sys.exit(1 if fails else 0)
