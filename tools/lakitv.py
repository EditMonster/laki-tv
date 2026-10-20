#!/usr/bin/env python3
"""LAKI-TV-päivitystyökalu. Hoitaa kaiken mekaanisen työn, jotta tekoäly kirjoittaa vain tiivistelmät.

Käyttö (data.json = sivun JSON-lohko):
  python3 lakitv.py extract SIVU.html data.json        JSON-lohko sivusta tiedostoon
  python3 lakitv.py prune data.json                    järjestä kanavat (max 9/kanava); pudonneet arkistoon 35 pv:ksi
  python3 lakitv.py scan data.json [--hours 48] [--all]  uudet jutut lähteistä -> ehdokkaat.json (merkitsee nähdyiksi)
  python3 lakitv.py text URL [--max 6000]              sivun tai PDF:n pääteksti + julkaisuaika tiivistämistä varten
  python3 lakitv.py add data.json KANAVA kohde.json    lisää/korvaa kohde (sama id korvaa), järjestää ja rajaa
  python3 lakitv.py he-update data.json                HE-tulostaulun vaiheet eduskunnan avoimesta datasta
  python3 lakitv.py he-range A B                       HE:t A..B (kuluva vuosi): nimi, vaihe, pvm
  python3 lakitv.py vt-update data.json                voimaantulot ja vt_paivat Finlexin avoimesta datasta
  python3 lakitv.py status data.json                   tiivis tilannekuva
  python3 lakitv.py validate data.json                 tarkistukset (paluukoodi 1, jos virheitä)
  python3 lakitv.py stamp data.json                    paivitetty = nyt; merkitsee skannatut linkit nähdyiksi; ajoloki
  python3 lakitv.py diff alku.json data.json           mitä ajossa muuttui (lisätyt, arkistoituneet, muuttuneet, HE-vaiheet)
  python3 lakitv.py digest data.json [--laji aamu|viikko|heti] [--kieli fi|sv|en] [--kanavat kko,kho] [--aiheet vero] [--since ISO] [--out kooste.json] [--muoto slack|teams]
                                                       sähköpostikooste; --tilaukset tilaukset.json tekee viestin jokaiselle tilaajalle (viestit.json, myös seuranta)
  python3 lakitv.py feed data.json [--out hakemisto]   feed.xml/-sv/-en, feed.json, lakitv.md, kalenteri.txt/-sv/-en (iCalendar) sivun rinnalle julkaistaviksi
  python3 lakitv.py viikkokatsaus data.json [--out viikkokatsaus] [--kieli fi]  viime viikon katsaus HTML + PDF (maanantaisin)
  python3 lakitv.py post kuorma.json WEBHOOK_URL       lähettää Slack-/Teams-kuorman webhookiin
  python3 lakitv.py post kuorma.json --asetukset jakelu.json [--kanava slack|teams]  sama, osoite asetustiedostosta (ei komentoriville)
  python3 lakitv.py inject SIVU.html data.json UUSI.html  kirjoita JSON takaisin; muu sivu pysyy tavulleen samana
  python3 lakitv.py julkaise SIVU.html data.json UUSI.html [--out jakelu] [--asetukset jakelu.json] [--viesti "LAKI-TV 19.10. klo 14.48"]
                                                       validate + inject + feed (+ viikkokatsaus maanantaina) + peilaus datavarastoon
                                                       varmistuksineen, yhdellä komennolla ENNEN artefaktin julkaisua (paluukoodi 3 = peilaus epäonnistui)
  python3 lakitv.py peilaa data.json --asetukset jakelu.json [--viesti …]  vain peilaus + varmistus (varmistusajot)
Asetustiedosto on ArtifactData-dokumentti asetukset/jakelu tallennettuna tiedostoksi (out_dir): github_repo, github_token,
data_url (datavaraston raw-osoite varmistusta varten), slack_webhook, teams_webhook. Avaimet eivät kulje komentorivin kautta.
"""
import sys, re, json, html, time, hashlib, datetime, subprocess, tempfile, os
import urllib.request, urllib.parse, urllib.error
import email.utils, ipaddress, socket, zlib
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

HKI = ZoneInfo("Europe/Helsinki")
UA = "Mozilla/5.0 (compatible; LAKI-TV/1.0; avoimen lahdekoodin juridinen teksti-TV)"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
CH_KEYS = ["kko", "eu", "eit", "icj", "kho", "laillisuus", "hao", "muut", "kilpailu", "yrityskaupat", "fiva", "tsv", "vero", "he", "lausunnot"]
AIHEET = {"sote", "digi", "eu", "tyo", "vero", "tietosuoja", "kilpailu", "rikos", "maahanmuutto", "ymparisto", "asuminen",
          "hallinto", "finanssi", "kuluttaja", "yhtio", "perhe", "ihmisoikeudet", "turvallisuus", "koulutus"}
TEKSTITYYPIT = {"virallinen tiivistelmä", "tiivistelmä", "asiasanat", "asiasanoista koottu", "nimike", "tiedotteen mukaan"}
EU_LAJIT = {"sovelletaan", "osittain", "voimaan", "täytäntöönpano"}
MAX_ITEMS = 9
MAX_FETCH = 25 * 1024 * 1024   # tavua; suurempi vastaus katkaistaan (PDF:t ja HTML-sivut ovat alle tämän)


# ---------------------------------------------------------------- yleiset
def now():
    v = os.environ.get("LAKITV_NOW")   # testit: kiinteä kello (ISO, Helsingin aikaa)
    if v:
        t = datetime.datetime.fromisoformat(v)
        return t.astimezone(HKI) if t.tzinfo else t.replace(tzinfo=HKI)
    return datetime.datetime.now(HKI)


def today():
    return now().date().isoformat()


def days_ago(n):
    return (now().date() - datetime.timedelta(days=n)).isoformat()


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def write_text(p, s):
    """Kirjoittaa tekstitiedoston atomisesti (väliaikaistiedosto + siirto)."""
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    tmp = f"{p}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(s)
    os.replace(tmp, p)


def save(p, d):
    tmp = f"{p}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def check_url(url, https_only=False):
    """Sallii vain http(s)-osoitteet; https_only lisäksi kieltää paikalliset ja yksityiset osoitteet (webhookit)."""
    u = urllib.parse.urlsplit(str(url or ""))
    if u.scheme not in (("https",) if https_only else ("http", "https")) or not u.hostname:
        raise ValueError(f"osoite ei kelpaa: {u.scheme or '?'}://{u.hostname or '?'}")
    host = u.hostname.lower()
    if host in ("localhost",) or host.endswith(".local") or host.endswith(".internal"):
        raise ValueError("paikallinen osoite ei kelpaa")
    try:
        addrs = {ai[4][0] for ai in socket.getaddrinfo(host, None)}
    except (socket.gaierror, OSError):
        addrs = set()   # nimeä ei voi selvittää täältä (esim. välityspalvelin hoitaa sen): yhteys ratkaisee
        try:
            addrs = {str(ipaddress.ip_address(host))}   # IP-osoite nimen paikalla tarkistetaan silti
        except ValueError:
            pass
    for a in addrs:
        ip = ipaddress.ip_address(a)
        if not ip.is_global:
            raise ValueError("yksityinen verkko-osoite ei kelpaa")
    return url


class TooBig(Exception):
    pass


class _CheckedRedirect(urllib.request.HTTPRedirectHandler):
    """Uudelleenohjauksen kohdekin tarkistetaan (ei yksityisiä osoitteita, vain http/https)."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_CheckedRedirect)


def _gunzip(b):
    """Purkaa gzipin kokorajan sisällä (purkupommi ei syö muistia)."""
    z = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = z.decompress(b, MAX_FETCH + 1)
    if len(out) > MAX_FETCH or z.unconsumed_tail:
        raise TooBig(f"purettu vastaus yli {MAX_FETCH // 1024 // 1024} Mt")
    return out


def fetch(url, ua=UA, timeout=30, tries=2, accept="*/*"):
    check_url(url)
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": accept, "Accept-Encoding": "gzip"})
            with _OPENER.open(req, timeout=timeout) as r:
                b = r.read(MAX_FETCH + 1)
                ctype = r.headers.get("Content-Type", "")
            if len(b) > MAX_FETCH:
                raise TooBig(f"vastaus yli {MAX_FETCH // 1024 // 1024} Mt")
            b = _gunzip(b) if b[:2] == b"\x1f\x8b" else b
            _CTYPE[url] = ctype
            return b
        except TooBig:
            raise
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                raise
            if e.code == 403:  # osa palvelimista (esim. HUDOC) torjuu Pythonin mutta ei curlia
                try:
                    r = subprocess.run(["curl", "-sfL", "--compressed", "--proto", "=http,https", "--proto-redir", "=https", "--max-redirs", "3", "--max-filesize", str(MAX_FETCH), "-m", str(timeout),
                                        "-A", BROWSER_UA, "-H", f"Accept: {accept}", "-w", "\n@@LAKITV@@%{url_effective}@@%{content_type}", url], capture_output=True, timeout=timeout + 5, check=False)
                    # (erotin ei saa olla NUL-tavu: subprocess ei hyväksy sitä argumentissa, jolloin varamenettely ei koskaan käynnistynyt)
                    if r.returncode == 0 and r.stdout:
                        body, _, tail = r.stdout.rpartition(b"\n@@LAKITV@@")
                        eff, _, ct = tail.partition(b"@@")
                        check_url(eff.decode("ascii", "replace"))   # curl seurasi ohjauksia: kohde tarkistetaan jälkikäteen
                        _CTYPE[url] = ct.decode("ascii", "replace")
                        return body
                except Exception:
                    pass
            last = e
        except Exception as e:
            last = e
        time.sleep(1.5 * (i + 1))
    raise last


_CTYPE = {}   # url -> viimeisin Content-Type


def decode_body(b, ctype=""):
    """Purkaa tavut tekstiksi Content-Typen tai <meta charset>-tiedon mukaan; oletus UTF-8."""
    m = re.search(r"charset=['\"]?([\w.-]+)", ctype or "", re.I) or re.search(rb"<meta[^>]+charset=['\"]?([\w.-]+)", b[:4096], re.I)
    enc = (m.group(1) if isinstance(m.group(1), str) else m.group(1).decode("ascii", "replace")) if m else "utf-8"
    try:
        return b.decode(enc, "replace")
    except LookupError:
        return b.decode("utf-8", "replace")


def get_text(url, **k):
    b = fetch(url, **k)
    return decode_body(b, _CTYPE.get(url, ""))


def clean(s):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


def words(s):
    return len([w for w in str(s or "").split() if w not in ("–", "—", "-")])


def to_hki(s):
    """ISO-aika (UTC tai offsetilla) tai 'YYYY-MM-DD HH:MM:SS' (paikallinen) -> 'YYYY-MM-DDTHH:MM' Helsingin aikaa."""
    if not s:
        return None
    s = s.strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$", s)
    if not m:
        m2 = re.match(r"^(\d{4}-\d{2}-\d{2})$", s)
        return m2.group(1) if m2 else None
    date, hh, mm, tz = m.groups()
    dt = datetime.datetime.fromisoformat(f"{date}T{hh}:{mm}:00")
    if tz:
        tz = "+00:00" if tz == "Z" else (tz if ":" in tz else tz[:3] + ":" + tz[3:])
        dt = datetime.datetime.fromisoformat(f"{date}T{hh}:{mm}:00{tz}").astimezone(HKI)
    return dt.strftime("%Y-%m-%dT%H:%M")


def fi_date(s):
    """'29.9.2026' (+ '9.36' tai '09:39') -> ISO."""
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:(?:\s+klo\.?\s*|\s+kl\.?\s*|\s+at\s+|\s+|,\s*)(\d{1,2})[.:](\d{2})(?![.:]?\d))?", s or "")
    if not m:
        return None
    d, mo, y, hh, mm = m.groups()
    base = f"{y}-{int(mo):02d}-{int(d):02d}"
    return f"{base}T{int(hh):02d}:{mm}" if hh else base


def as_dt(julk):
    if not julk:
        return None
    try:
        if "T" in julk:
            return datetime.datetime.fromisoformat(julk).replace(tzinfo=HKI)
        return datetime.datetime.fromisoformat(julk + "T12:00").replace(tzinfo=HKI)
    except ValueError:
        return None


def norm_url(u):
    u = html.unescape(u or "").strip()
    p = urllib.parse.urlsplit(u)
    # kysely säilytetään, kun se yksilöi asiakirjan (esim. curia ?num=C-1/25); seurantaparametrit pois
    keep = [(k, v) for k, v in urllib.parse.parse_qsl(p.query) if not re.match(r"^(utm_|publisherId$|lang$|language$|fbclid$)", k)]
    q = ("?" + urllib.parse.urlencode(sorted(keep))) if keep else ""
    path = p.path.rstrip("/")
    if p.netloc.endswith("hudoc.echr.coe.int"):
        m = re.search(r"(00\d-[\d-]+)", u)
        return "hudoc:" + (m.group(1) if m else u)
    return f"{p.netloc.lower().removeprefix('www.')}{path}{q}"


def url_hash(u):
    return hashlib.sha1(norm_url(u).encode()).hexdigest()[:8]


def all_items(d):
    for k in CH_KEYS:
        for it in d.get("kanavat", {}).get(k, []):
            yield k, it


def pub_key(it):
    return str(it.get("julkaistu") or it.get("pvm") or "")


# ---------------------------------------------------------------- JSON-lohko
BLOCK = re.compile(r'(<script type="application/json" id="laki-tv-data">)(.*?)(</script>)', re.S)


def cmd_extract(page, out):
    h = open(page, encoding="utf-8", newline="").read()
    m = list(BLOCK.finditer(h))
    if len(m) != 1:
        sys.exit(f"VIRHE: JSON-lohkoja löytyi {len(m)}, odotettiin 1")
    d = json.loads(m[0].group(2))
    save(out, d)
    print(f"OK: {out} ({sum(1 for _ in all_items(d))} juttua, päivitetty {d.get('paivitetty')})")


def cmd_inject(page, data, out, force=False):
    h = open(page, encoding="utf-8", newline="").read()
    d = load(data)
    errs, warns = validate(d)
    for w in warns:
        print("HUOM:", w)
    if errs and not force:
        for e in errs:
            print("VIRHE:", e)
        sys.exit("Ei kirjoitettu: korjaa virheet (tai --force).")
    s = json.dumps(d, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/").replace("<!--", "<\\u0021--")
    m = list(BLOCK.finditer(h))
    if len(m) != 1:
        sys.exit(f"VIRHE: JSON-lohkoja löytyi {len(m)}, odotettiin 1")
    a, b = m[0].start(2), m[0].end(2)
    new = h[:a] + s + h[b:]
    assert new[:a] == h[:a] and new[a + len(s):] == h[b:], "sivun muu osa muuttui"
    json.loads(BLOCK.search(new).group(2))  # jäsentyy
    write_text(out, new)
    print(f"OK: {out} ({len(new):,} tavua, JSON {len(s):,} tavua). Muu sivu tavulleen ennallaan.")


# ---------------------------------------------------------------- siivous
def sort_channel(lst):
    lst.sort(key=lambda it: (pub_key(it), str(it.get("pvm") or "")), reverse=True)


# Arkisto: kanavilta poistuvat jutut säilyvät tiiviinä 35 päivää (viikon tärkeimmät 102, kalenteri 103–105).
ARCHIVE_DAYS = 35
ARCHIVE_FIELDS = ("id", "tunnus", "otsikko", "otsikko_sv", "otsikko_en", "pvm", "pvm_selite", "julkaistu", "lisatty", "paino", "aiheet",
                  "teksti", "teksti_sv", "teksti_en", "tekstityyppi", "lahde", "elin", "lainvoimainen", "maaraaika", "vaihe", "vaihe_sv", "vaihe_en")


def archive_items(d, kanava, items):
    arch = d.setdefault("arkisto", [])
    ids = {x["id"] for x in items}
    arch[:] = [a for a in arch if a.get("id") not in ids]
    for it in items:
        a = {f: it[f] for f in ARCHIVE_FIELDS if it.get(f) not in (None, "", [])}
        a["k"] = kanava
        arch.append(a)


def drop_dead_refs(d):
    """Visa- ja etusivunostot, joiden juttu ei enää ole kanavalla, poistetaan (muuten validate estää julkaisun)."""
    ids = {it["id"] for _, it in all_items(d)}
    before = len(d.get("visa", [])) + len(d.get("etusivu", []))
    d["visa"] = [q for q in d.get("visa", []) if q.get("ref") in ids]
    d["etusivu"] = [e for e in d.get("etusivu", []) if e.get("ref") in ids or e.get("sivu")]
    gone = before - len(d["visa"]) - len(d["etusivu"])
    if gone:
        print(f"HUOM: {gone} visa-/etusivuviittausta poistettiin (juttu siirtyi arkistoon)")
    return gone


def prune_archive(d):
    cut = days_ago(ARCHIVE_DAYS)
    live = {it["id"] for _, it in all_items(d)}
    arch = d.get("arkisto") or []
    d["arkisto"] = sorted([a for a in arch if a.get("id") not in live and pub_key(a)[:10] >= cut], key=pub_key, reverse=True)
    vta = d.get("vt_arkisto") or []
    d["vt_arkisto"] = sorted([v for v in vta if v.get("pvm", "") >= cut], key=lambda v: v["pvm"])
    return len(arch) - len(d["arkisto"])


def prune(d, quiet=False):
    t, log = today(), []
    kan = d.setdefault("kanavat", {})
    for k in CH_KEYS:
        kan.setdefault(k, [])
    old = kan["lausunnot"]
    kan["lausunnot"] = [x for x in old if not x.get("maaraaika") or x["maaraaika"] >= t]
    gone = [x for x in old if x not in kan["lausunnot"]]
    archive_items(d, "lausunnot", gone)
    log += [f"lausunnot: arkistoon {x['id']} (määräaika {x.get('maaraaika')})" for x in gone]
    for k in CH_KEYS:
        lst = kan[k]
        for it in lst:
            it.pop("uusi", None)  # UUSI lasketaan sivulla julkaistu-kentästä
        sort_channel(lst)
        if len(lst) > MAX_ITEMS:
            log += [f"{k}: arkistoon vanhin {x['id']}" for x in lst[MAX_ITEMS:]]
            archive_items(d, k, lst[MAX_ITEMS:])
            del lst[MAX_ITEMS:]
    n = len(d.get("voimaantulot", []))
    past = [v for v in d.get("voimaantulot", []) if v.get("pvm", "") < t]
    vpd = d.get("vt_paivat") or {}
    for v in past:  # voimaan tulleet jäävät kalenteriin
        r = {f: v[f] for f in ("pvm", "nimi", "nimi_sv", "nimi_en", "saados", "he", "lahde", "aiheet", "lakeja") if v.get(f)}
        if vpd.get(v["pvm"]):
            r["paiva_lakeja"] = vpd[v["pvm"]].get("lakeja")
        d.setdefault("vt_arkisto", [])
        d["vt_arkisto"] = [x for x in d["vt_arkisto"] if not (x.get("pvm") == r["pvm"] and x.get("saados") == r.get("saados"))] + [r]
    d["voimaantulot"] = sorted([v for v in d.get("voimaantulot", []) if v.get("pvm", "") >= t], key=lambda v: v["pvm"])
    if n != len(d["voimaantulot"]):
        log.append(f"voimaantulot: {n - len(d['voimaantulot'])} mennyttä kalenteriin (vt_arkisto)")
    k = prune_archive(d)
    if k:
        log.append(f"arkisto: poistettu {k} yli {ARCHIVE_DAYS} pv vanhaa")
    c30 = days_ago(ARCHIVE_DAYS)
    n = len(d.get("eu_voimaantulot", []))
    d["eu_voimaantulot"] = sorted([v for v in d.get("eu_voimaantulot", []) if v.get("pvm", "") >= c30], key=lambda v: v["pvm"])
    if n != len(d["eu_voimaantulot"]):
        log.append(f"eu_voimaantulot: poistettu {n - len(d['eu_voimaantulot'])} yli {ARCHIVE_DAYS} pv vanhaa")
    n = len(d.get("he_tila", []))
    d["he_tila"] = [h for h in d.get("he_tila", []) if not (h.get("vaihe") == 6 and str(h.get("pvm") or "") < c30)]
    if n != len(d["he_tila"]):
        log.append(f"he_tila: poistettu {n - len(d['he_tila'])} yli {ARCHIVE_DAYS} pv sitten vahvistettua")
    d["vt_paivat"] = {k: v for k, v in (d.get("vt_paivat") or {}).items() if k >= t}
    c14 = days_ago(14)
    d["he_muutokset"] = [m for m in d.get("he_muutokset", []) if str(m.get("havaittu") or m.get("pvm") or "") >= c14][-60:]
    ids = {it["id"] for _, it in all_items(d)}
    ref_ok = lambda e: e.get("ref") in ids or e.get("sivu")
    n = len(d.get("etusivu", []))
    d["etusivu"] = [e for e in d.get("etusivu", []) if ref_ok(e)][:3]
    if n != len(d["etusivu"]):
        log.append(f"etusivu: poistettu {n - len(d['etusivu'])} nostoa")
    n = len(d.get("visa", []))
    d["visa"] = [q for q in d.get("visa", []) if q.get("ref") in ids]
    if n != len(d["visa"]):
        log.append(f"visa: poistettu {n - len(d['visa'])} kysymystä, joiden juttu poistui")
    d["_nahty"] = (d.get("_nahty") or [])[-600:]
    if not quiet:
        print("\n".join(log) if log else "Ei poistettavaa.")
    return log


# ---------------------------------------------------------------- tarkistus
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
JULK = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?$")


def date_ok(v):
    """YYYY-MM-DD, joka on olemassa kalenterissa."""
    v = str(v or "")
    if not DATE.match(v):
        return False
    try:
        datetime.date.fromisoformat(v); return True
    except ValueError:
        return False


def julk_ok(v):
    """YYYY-MM-DD tai YYYY-MM-DDTHH:MM, joka on olemassa kalenterissa."""
    v = str(v or "")
    return bool(JULK.match(v)) and as_dt(v) is not None


BAD_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _walk_urls(o, path, E):
    """Kaikki lahde-/url-kentät datassa: vain https, ei skriptiosoitteita."""
    if isinstance(o, dict):
        for k, v in o.items():
            if k in ("lahde", "url", "lahde_url") and v is not None and (not isinstance(v, str) or not v.startswith("https://")):
                E.append(f"{path}.{k}: {str(v)[:60]!r} (vain https)")
            elif isinstance(v, str) and (BAD_CTRL.search(v) or re.search(r"[\ud800-\udfff]", v)):
                E.append(f"{path}.{k}: ohjausmerkkejä tai rikkinäisiä merkkejä tekstissä")
            else:
                _walk_urls(v, f"{path}.{k}", E)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            if isinstance(v, str) and (BAD_CTRL.search(v) or re.search(r"[\ud800-\udfff]", v)):
                E.append(f"{path}[{i}]: ohjausmerkkejä tai rikkinäisiä merkkejä tekstissä")
            else:
                _walk_urls(v, f"{path}[{i}]", E)


def sane_date(v):
    """Kalenterissa oleva päivä 2000–(tämä vuosi + 5): kirjoitusvirhe 2099 tai 1900 ei mene läpi."""
    return date_ok(str(v or "")) and 2000 <= int(str(v)[:4]) <= now().year + 5



# ---------------------------------------------------------------- tiivistelmäsivun rivibudjetti (sama kuin sivun buildItem)
# Juttu on yksi sivu; lähdetiedot (asiasanat, aiheet, seuranta, lähde) avautuvat samalle numerolle. Sivu on 23 riviä:
# kaista, otsikko (2 riviä/rivi), tunnusrivi(t), määräaika- tai vaiherivi, tyhjä, teksti, lopputulos, huom, lainvoimahuomautus,
# alarivi (NÄYTÄ LÄHDETIEDOT). Jos rivejä tulee enemmän, sivu näyttää vain sivulle mahtuvat kokonaiset virkkeet ja lähdetiedoissa
# lukee "Lyhennetty": validate pyytää lyhentämään (uusille jutuille virhe YLI SIVUN, vanhoille huomautus LYHENNÄ).
ONE_PAGE_SINCE = os.environ.get("LAKITV_ONE_PAGE_SINCE") or "2026-10-15"   # tästä päivästä lisätyille jutuille sanarajat ja YLI SIVUN ovat virheitä (testit siirtävät rajaa)
TEKSTI_MAX = {"fi": 50, "sv": 55, "en": 65}   # ohjeellinen sanaraja; ratkaiseva on tiivistelmäsivun rivibudjetti
LOPPUTULOS_MAX = 15
SELKO_MAX = {"fi": 60, "sv": 70, "en": 80}
SELITE_SV = {"annettu": "meddelad", "tiedote": "meddelande", "päätös": "beslut", "tuomio": "dom", "ratkaisu": "avgörande", "julkaistu": "publicerad",
             "esitys": "proposition", "kanne": "talan", "suullinen käsittely": "muntlig förhandling", "uutisoitu": "rapporterad",
             "päätös tiedotettu": "beslut meddelat", "lausunto": "utlåtande"}
SELITE_EN = {"annettu": "issued", "tiedote": "release", "päätös": "decision", "tuomio": "judgment", "ratkaisu": "ruling", "julkaistu": "published",
             "esitys": "submitted", "kanne": "action", "suullinen käsittely": "hearing", "uutisoitu": "reported", "päätös tiedotettu": "decision announced",
             "lausunto": "opinion"}


# Suomen tavutus (Kielitoimiston ohjeet): tavuraja yhden konsonantin edellä (ta-lo), konsonanttijonossa viimeisen konsonantin
# edellä (kis-sa, myrs-ky) ja kahden vokaalin välissä, jos ne eivät ole diftongi tai pitkä vokaali (ko-e, kau-an). Yhtä kirjainta
# ei jätetä yksin kummallekaan riville. Sama algoritmi kuin sivun sylPoints/hyphSplit/wrap: rivimäärien on täsmättävä.
HYPH_VOW = "aeiouyäöå"
HYPH_DIPH = set("ai ei oi ui yi äi öi au eu iu ou äy öy ey iy ie uo yö aa ee ii oo uu yy ää öö".split())
HYPH_WORD = re.compile(r"^([^\w]*)([^\W\d_]+(?:-[^\W\d_]+)*)([^\w]*)$")   # etuliite, kirjainydin (yhdysmerkit sallittu), jälkiliite


def syl_points(word):
    """Kohdat k (katkaisu ennen merkkiä k), joissa tavuraja on; sana sisältää vain kirjaimia."""
    lw = word.lower(); n = len(lw); pts = []
    k, paired = 1, False
    while k < n:
        p, c = lw[k - 1], lw[k]
        if p in HYPH_VOW and c in HYPH_VOW:
            if (p + c) in HYPH_DIPH and not paired:
                paired = True
            else:
                pts.append(k); paired = False
            k += 1
        elif p in HYPH_VOW:
            j = k
            while j < n and lw[j] not in HYPH_VOW:
                j += 1
            if j < n:
                pts.append(j - 1)   # konsonanttijono: raja viimeisen konsonantin edellä
            paired = False; k = j + 1
        else:
            paired = False; k += 1
    return [x for x in pts if x >= 2 and n - x >= 2]


def hyph_split(word, avail):
    """[alkuosa, loppuosa] niin, että alkuosa tavuviivoineen mahtuu avail-merkkiin, tai None. Valmis yhdysmerkki on myös
    katkaisukohta ilman lisäviivaa. Numeroita tai muita merkkejä sisältäviä sanoja ei tavuteta."""
    m = HYPH_WORD.match(word)
    if not m or avail < 3:
        return None
    pre, core, suf = m.group(1), m.group(2), m.group(3)
    cand, off = [], 0
    for part in core.split("-"):
        cand += [(off + k, True) for k in syl_points(part)]
        off += len(part)
        if off < len(core):
            cand.append((off + 1, False)); off += 1
    best = None
    for k, dash in cand:
        head = pre + core[:k] + ("-" if dash else "")
        if len(head) <= avail and (best is None or k > best[0]):
            best = (k, head, core[k:] + suf)
    return [best[1], best[2]] if best else None


def tt_wrap(text, width=38, lang="fi"):
    """Sivun wrap(): sanat riveille; suomeksi rivin loppuun jäävä sana tavutetaan, ylipitkät sanat katkaistaan."""
    hyph = lang == "fi"
    out, cur = [], ""
    for w in re.sub(r"\s+", " ", str(text or "")).strip().split(" "):
        if not w:
            continue
        while len(w) > width:
            if cur:
                out.append(cur); cur = ""
            h = hyph_split(w, width) if hyph else None
            if h:
                out.append(h[0]); w = h[1]
            else:
                out.append(w[:width]); w = w[width:]
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= width:
            cur += " " + w
        else:
            h = hyph_split(w, width - len(cur) - 1) if hyph else None
            if h:
                out.append(cur + " " + h[0]); cur = h[1]
            else:
                out.append(cur); cur = w
    if cur:
        out.append(cur)
    return out


def _tx(it, f, lang):
    return (lang != "fi" and it.get(f + "_" + lang)) or it.get(f) or ""


def item_rows(it, kanava, d, lang="fi"):
    """Tiivistelmäsivun (1/2) rivimäärä kielellä lang (sama laskenta kuin sivun buildItem); enintään 23 = mahtuu yhdelle sivulle."""
    sfx = "" if lang == "fi" else "_" + lang
    fdate = lambda iso, short=False: (lambda m: (f"{int(m.group(3))}.{int(m.group(2))}." if short else f"{int(m.group(3))}.{int(m.group(2))}.{m.group(1)}") if m else "")(re.match(r"(\d{4})-(\d{2})-(\d{2})", str(iso or "")))
    norm = lambda x: re.sub(r"\s+", " ", str(x or "")).strip().lower()
    tun = str(it.get("tunnus") or it.get("id") or "")
    if lang == "sv":
        tun = re.sub(r"\bKKO:", "HD:", tun); tun = re.sub(r"\bKHO:", "HFD:", tun); tun = re.sub(r"\bHE (\d+/\d{4}) vp\b", r"RP \1 rd", tun); tun = re.sub(r"\bHE (\d+/\d{4})", r"RP \1", tun)
    sel = it.get("pvm_selite") or "annettu"
    selite = sel if lang == "fi" else (SELITE_SV.get(sel) or it.get("pvm_selite_sv") or "meddelad") if lang == "sv" else (SELITE_EN.get(sel) or it.get("pvm_selite_en") or "issued")
    when = f"{selite} {fdate(it.get('pvm'))}" if it.get("pvm") else ""
    if when and norm(when) in norm(tun):
        when = ""
    rows = 1 + 2 * min(2, len(tt_wrap(_tx(it, "otsikko", lang), 38, lang)))          # kaista + otsikko
    rows += 1 if (not when or len(tun) + 2 + len(when) <= 38) else 2         # tunnusrivi(t)
    if it.get("maaraaika"):
        rows += 1
    if it.get("vaihe"):
        rows += 1
    rows += 1                                                                 # tyhjä
    if lang != "fi" and it.get("teksti") and not it.get("teksti" + sfx):
        rows += 1                                                             # "Texten finns endast på finska"
    rows += len(tt_wrap(_tx(it, "teksti", lang), 38, lang))
    if it.get("lopputulos"):
        rows += len(tt_wrap(("LOPPUTULOS: " if lang == "fi" else "UTGÅNG: " if lang == "sv" else "OUTCOME: ") + _tx(it, "lopputulos", lang), 38, lang))
    if it.get("huom"):
        rows += len(tt_wrap(_tx(it, "huom", lang), 38, lang))
    if it.get("lainvoimainen") is False:
        rows += 1
    return rows + 1                                                           # vihjerivi (lisätiedot, lähde ja seuranta)

def validate(d):
    E, W = [], []
    _walk_urls(d, "data", E)
    pv = str(d.get("paivitetty") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?[+-]\d{2}:\d{2}", pv):
        E.append(f"paivitetty {pv!r}: muoto YYYY-MM-DDTHH:MM:SS+03:00 (aikavyöhyke pakollinen; stamp asettaa sen)")
    lahteet = {}
    kan = d.get("kanavat")
    if not isinstance(kan, dict) or set(kan) - set(CH_KEYS):
        E.append(f"kanavat-avaimet väärin: {sorted(kan or {})}")
        kan = kan if isinstance(kan, dict) else {}
    elif set(CH_KEYS) - set(kan):
        W.append(f"kanavat puuttuvat (prune lisää tyhjinä): {sorted(set(CH_KEYS) - set(kan))}")
    ids, limit, tunnukset = set(), now() + datetime.timedelta(minutes=15), {}
    for k, lst in kan.items():
        if len(lst) > MAX_ITEMS:
            E.append(f"{k}: {len(lst)} kohdetta (max {MAX_ITEMS})")
        for it in lst:
            p = f"{k}/{it.get('id')}"
            for f in ("id", "tunnus", "otsikko", "pvm_selite", "teksti", "tekstityyppi", "lahde", "selko", "julkaistu"):
                if not it.get(f):
                    E.append(f"{p}: puuttuu {f}")
            if not re.fullmatch(r"[^\r\n\t]{1,120}", str(it.get("id") or "")):
                E.append(f"{p}: id ei kelpaa (1–120 merkkiä, ei rivinvaihtoja)")
            if it.get("id") in ids:
                E.append(f"{p}: id ei ole yksilöllinen")
            ids.add(it.get("id"))
            lu = str(it.get("lahde") or "")
            if lu in lahteet:
                E.append(f"{p}: sama lahde kuin jutulla {lahteet[lu]}")
            lahteet[lu] = p
            tun = str(it.get("tunnus") or "")
            if re.match(r"^(KKO|KHO|HE |TT |MAO|C-|T-)", tun):
                if tun in tunnukset:
                    E.append(f"{p}: sama tunnus {tun} on jo kanavalla {tunnukset[tun]}")
                tunnukset[tun] = k
            # selkon luvut (summat, määräajat, pykälät) on löydyttävä tekstistä tai tunnuksesta: tekoäly ei saa keksiä numeroita
            numset = lambda t: {n.replace(" ", "").replace("\u00a0", "") for n in re.findall(r"\d[\d\s\u00a0]*\d|\d", str(t or ""))}
            ref = numset(" ".join(str(it.get(f) or "") for f in ("teksti", "tunnus", "pvm", "asiasanat", "lopputulos", "huom", "maaraaika", "voimaantulo_pvm")))
            nums = numset(it.get("selko")) - ref
            nums = {n for n in nums if not any(r.isdigit() and n.isdigit() and int(r) and abs(int(n) - int(r)) / int(r) <= 0.1 for r in ref)}  # pyöristys sallitaan
            if nums:
                W.append(f"SELKO {p}: luvut {sorted(nums)} eivät esiinny tekstissä – tarkista lähteestä")
            o = it.get("otsikko") or ""
            if len(o) > 35:
                E.append(f"{p}: otsikko {len(o)} merkkiä (max 35)")
            if o != o.upper():
                E.append(f"{p}: otsikko ei ole ISOILLA")
            for f, v in (("otsikko", o), ("otsikko_sv", it.get("otsikko_sv") or ""), ("otsikko_en", it.get("otsikko_en") or "")):
                if re.search(r"([,:;\-–]|\b(JA|TAI|SEKÄ|ETTÄ|OCH|ELLER|AND|OR|OF|FOR|TO))$", v.strip()):
                    W.append(f"{p}: {f} näyttää katkenneelta ({v!r}) – muotoile kokonaiseksi ≤35 merkin otsikoksi")
            strict = str(it.get("lisatty") or "") >= ONE_PAGE_SINCE      # uudet jutut: sanarajat ja yhden sivun budjetti ovat virheitä
            if strict and words(it.get("teksti")) > TEKSTI_MAX["fi"]:
                E.append(f"{p}: teksti {words(it.get('teksti'))} sanaa (max {TEKSTI_MAX['fi']})")
            if strict and words(it.get("lopputulos")) > LOPPUTULOS_MAX:
                E.append(f"{p}: lopputulos {words(it.get('lopputulos'))} sanaa (max {LOPPUTULOS_MAX})")
            if words(it.get("selko")) > SELKO_MAX["fi"]:
                E.append(f"{p}: selko {words(it.get('selko'))} sanaa (max {SELKO_MAX['fi']})")
            for lang in ("fi", "sv", "en"):
                need = item_rows(it, k, d, lang)
                if need > 23:
                    msg = f"{p}: {lang}: tiivistelmäsivu {need} riviä, sivulle mahtuu 23 – lyhennä teksti{'' if lang == 'fi' else '_' + lang}" \
                          f" ({words(_tx(it, 'teksti', lang))} sanaa){' tai lopputulos' if it.get('lopputulos') else ''}"
                    if strict:
                        E.append("YLI SIVUN " + msg)   # uusi juttu: ei julkaista ennen kuin mahtuu
                    else:
                        W.append("LYHENNÄ " + msg)     # vanha juttu: sivu näyttää vain sivulle mahtuvat kokonaiset virkkeet; ajo lyhentää tekstin
            a = it.get("aiheet") or []
            if not isinstance(a, list) or not a or not set(a) <= AIHEET or len(a) > 3 or len(set(a)) != len(a):
                E.append(f"{p}: aiheet {a} (1–3 eri sallittua avainta)")
            pa = it.get("paino")
            if not isinstance(pa, int) or isinstance(pa, bool) or not 1 <= pa <= 5:
                E.append(f"{p}: paino {pa!r} (kokonaisluku 1–5)")
            j = it.get("julkaistu") or ""
            if not julk_ok(j):
                E.append(f"{p}: julkaistu {j!r} (YYYY-MM-DD tai YYYY-MM-DDTHH:MM)")
            elif as_dt(j) > limit + datetime.timedelta(hours=12 if "T" not in j else 0):
                E.append(f"{p}: julkaistu {j} on tulevaisuudessa")
            if it.get("pvm") is not None and not sane_date(it.get("pvm")):
                E.append(f"{p}: pvm {it.get('pvm')!r}")
            if len(it.get("vaihe") or "") > 30:
                E.append(f"{p}: vaihe yli 30 merkkiä")
            u = it.get("lahde") or ""
            if not u.startswith("https://") or "edilex" in u.lower():
                E.append(f"{p}: lahde {u!r} (https, ei Edilexiä)")
            if it.get("tekstityyppi") not in TEKSTITYYPIT:
                E.append(f"{p}: tekstityyppi {it.get('tekstityyppi')!r}")
            if k == "lausunnot" and not sane_date(it.get("maaraaika")):
                E.append(f"{p}: maaraaika puuttuu tai väärä")
            if it.get("maaraaika") and k != "lausunnot" and not sane_date(it["maaraaika"]):
                E.append(f"{p}: maaraaika väärä")
            if it.get("voimaantulo_pvm") and not sane_date(it["voimaantulo_pvm"]):
                E.append(f"{p}: voimaantulo_pvm väärä")
            if it.get("lisatty") and not julk_ok(it["lisatty"]):
                E.append(f"{p}: lisatty {it['lisatty']!r}")
            # ruotsinkielinen versio: pakollinen uusille (lisatty-kentällinen) jutuille, muille huomautus
            miss = [f + "_sv" for f in ("otsikko", "teksti", "selko") if not it.get(f + "_sv")]
            if miss:  # huomautus, ei virhe: sivu näyttää puuttuvan käännöksen suomeksi, eikä julkaisu saa kaatua tähän
                W.append(f"RUOTSI PUUTTUU {p}: {', '.join(miss)}")
            osv = it.get("otsikko_sv") or ""
            if len(osv) > 35 or osv != osv.upper():
                E.append(f"{p}: otsikko_sv ISOILLA ja ≤35 merkkiä")
            if strict and words(it.get("teksti_sv")) > TEKSTI_MAX["sv"]:
                E.append(f"{p}: teksti_sv {words(it.get('teksti_sv'))} sanaa (max {TEKSTI_MAX['sv']})")
            if words(it.get("selko_sv")) > SELKO_MAX["sv"]:
                E.append(f"{p}: selko_sv {words(it.get('selko_sv'))} sanaa (max {SELKO_MAX['sv']})")
            if len(it.get("vaihe_sv") or "") > 30:
                E.append(f"{p}: vaihe_sv yli 30 merkkiä")
            # englanninkielinen versio: samat säännöt, sanarajat väljemmät (englanti on suomea pitempää)
            miss = [f + "_en" for f in ("otsikko", "teksti", "selko") if not it.get(f + "_en")]
            if miss:
                W.append(f"ENGLANTI PUUTTUU {p}: {', '.join(miss)}")
            oen = it.get("otsikko_en") or ""
            if len(oen) > 35 or oen != oen.upper():
                E.append(f"{p}: otsikko_en ISOILLA ja ≤35 merkkiä")
            if strict and words(it.get("teksti_en")) > TEKSTI_MAX["en"]:
                E.append(f"{p}: teksti_en {words(it.get('teksti_en'))} sanaa (max {TEKSTI_MAX['en']})")
            if words(it.get("selko_en")) > SELKO_MAX["en"]:
                E.append(f"{p}: selko_en {words(it.get('selko_en'))} sanaa (max {SELKO_MAX['en']})")
            if len(it.get("vaihe_en") or "") > 30:
                E.append(f"{p}: vaihe_en yli 30 merkkiä")
            for f in ("teksti_en", "selko_en", "otsikko_en"):
                if re.search(r"\b(HD|HFD):\d{4}:", it.get(f) or ""):
                    E.append(f"{p}: {f} sisältää HD/HFD-tunnuksen (englanniksi KKO/KHO)")
    for a in d.get("arkisto", []):
        p = f"arkisto/{a.get('id')}"
        if a.get("k") not in CH_KEYS or not a.get("otsikko") or not julk_ok(a.get("julkaistu") or ""):
            E.append(f"{p}: k, otsikko tai julkaistu puuttuu")
        if a.get("id") in ids:
            W.append(f"{p}: on myös kanavalla (prune poistaa)")
        tun = str(a.get("tunnus") or "")
        if tun and tun in tunnukset and a.get("id") not in ids:
            W.append(f"{p}: sama tunnus {tun} on kanavalla {tunnukset[tun]} (eri id)")
    for e in d.get("etusivu", []):
        if not (e.get("ref") in ids or e.get("sivu")):
            E.append(f"etusivu: ref {e.get('ref')!r} ei löydy")
        for f in ("otsikko", "otsikko_sv", "otsikko_en"):
            if len(e.get(f) or "") > 35:
                E.append(f"etusivu: {f} yli 35")
    if len(d.get("etusivu", [])) > 3:
        W.append("etusivu: yli 3 nostoa")
    for q in d.get("visa", []):
        if q.get("ref") not in ids:
            E.append(f"visa: ref {q.get('ref')!r} ei löydy")
        if len(q.get("vaihtoehdot") or []) != 3 or q.get("oikea") not in ("A", "B", "C"):
            E.append(f"visa: {q.get('kysymys', '')[:40]}… vaihtoehdot/oikea")
        for f in ("vaihtoehdot", "vaihtoehdot_sv", "vaihtoehdot_en"):
            if any(len(str(v)) > 66 for v in (q.get(f) or [])):
                E.append(f"visa: {q.get('kysymys', '')[:40]}… {f}: vaihtoehto yli 66 merkkiä (sivu rivittää 33 merkin riveille)")
    for v in d.get("voimaantulot", []):
        p = f"voimaantulot/{v.get('saados')}"
        if not sane_date(v.get("pvm")):
            E.append(f"{p}: pvm")
        if not v.get("nimi") or len(v["nimi"]) > 33:
            E.append(f"{p}: nimi puuttuu tai yli 33")
        if v.get("lakeja") is not None and (not isinstance(v["lakeja"], int) or isinstance(v["lakeja"], bool) or v["lakeja"] < 1):
            E.append(f"{p}: lakeja ei ole kokonaisluku")
        if len(v.get("muutos") or "") > 76:
            E.append(f"{p}: muutos yli 76")
        if not set(v.get("aiheet") or []) <= AIHEET:
            E.append(f"{p}: aiheet")
        if not v.get("aiheet"):
            W.append(f"{p}: aiheet tyhjä (ei näy aihesivuilla)")
        if v.get("_auto"):
            W.append(f"{p}: automaattinen nimi '{v.get('nimi')}' – tarkista ja aja tidy")
        if not v.get("nimi_sv") or len(v["nimi_sv"]) > 33:
            W.append(f"RUOTSI PUUTTUU {p}: nimi_sv puuttuu tai yli 33")
        if len(v.get("muutos_sv") or "") > 76 or (v.get("muutos") and not v.get("muutos_sv")):
            W.append(f"{p}: muutos_sv puuttuu tai yli 76")
        if not v.get("nimi_en") or len(v["nimi_en"]) > 33:
            W.append(f"ENGLANTI PUUTTUU {p}: nimi_en puuttuu tai yli 33")
        if len(v.get("muutos_en") or "") > 76 or (v.get("muutos") and not v.get("muutos_en")):
            W.append(f"{p}: muutos_en puuttuu tai yli 76")
    for v in d.get("eu_voimaantulot", []):
        p = f"eu_voimaantulot/{v.get('nimi')}"
        if not sane_date(v.get("pvm")):
            E.append(f"{p}: pvm")
        if len(v.get("nimi") or "") > 30 or not v.get("nimi"):
            E.append(f"{p}: nimi (1–30)")
        if len(v.get("saados") or "") > 38:
            E.append(f"{p}: saados yli 38")
        if len(v.get("kuvaus") or "") > 76:
            E.append(f"{p}: kuvaus yli 76")
        if v.get("laji") not in EU_LAJIT:
            E.append(f"{p}: laji {v.get('laji')!r}")
        if not v.get("nimi_sv") or len(v["nimi_sv"]) > 30 or len(v.get("kuvaus_sv") or "") > 76 or not v.get("kuvaus_sv"):
            W.append(f"{p}: nimi_sv (≤30) tai kuvaus_sv (≤76) puuttuu tai liian pitkä")
        if not v.get("nimi_en") or len(v["nimi_en"]) > 30 or len(v.get("kuvaus_en") or "") > 76 or not v.get("kuvaus_en"):
            W.append(f"ENGLANTI PUUTTUU {p}: nimi_en (≤30) tai kuvaus_en (≤76) puuttuu tai liian pitkä")
    for h in d.get("he_tila", []):
        p = f"he_tila/{h.get('he')}"
        if not re.match(r"^HE \d+/\d{4} vp$", h.get("he") or ""):
            E.append(f"{p}: he-muoto")
        if not h.get("nimi") or len(h["nimi"]) > 18:
            E.append(f"{p}: nimi puuttuu tai yli 18")
        if h.get("vaihe") not in (1, 2, 3, 4, 5, 6):
            E.append(f"{p}: vaihe")
        if not h.get("nimi_sv") or len(h["nimi_sv"]) > 18:
            W.append(f"{p}: nimi_sv puuttuu tai yli 18")
        if not h.get("nimi_en") or len(h["nimi_en"]) > 18:
            W.append(f"ENGLANTI PUUTTUU {p}: nimi_en puuttuu tai yli 18")
    for q in d.get("visa", []):
        if not q.get("kysymys_sv") or len(q.get("vaihtoehdot_sv") or []) != 3 or len(q.get("selitys_sv") or "") > 45:
            W.append(f"visa: {q.get('kysymys', '')[:30]}… ruotsinkieliset kentät (kysymys_sv, vaihtoehdot_sv[3], selitys_sv ≤45)")
        if not q.get("kysymys_en") or len(q.get("vaihtoehdot_en") or []) != 3 or len(q.get("selitys_en") or "") > 45:
            W.append(f"ENGLANTI PUUTTUU visa: {q.get('kysymys', '')[:30]}… (kysymys_en, vaihtoehdot_en[3], selitys_en ≤45)")
    if len(d.get("tiedote") or "") > 38 or len(d.get("tiedote_sv") or "") > 38 or len(d.get("tiedote_en") or "") > 38:
        E.append("tiedote, tiedote_sv tai tiedote_en yli 38 merkkiä")
    if d.get("tiedote") and not d.get("tiedote_sv"):
        W.append("tiedote_sv puuttuu (ruotsinkielinen tiedote)")
    if d.get("tiedote") and not d.get("tiedote_en"):
        W.append("ENGLANTI PUUTTUU tiedote_en")
    try:
        datetime.datetime.fromisoformat(d.get("paivitetty") or "")
    except ValueError:
        E.append("paivitetty ei ole ISO-aika")
    return E, W


def cmd_validate(p):
    E, W = validate(load(p))
    for w in W:
        print("HUOM:", w)
    for e in E:
        print("VIRHE:", e)
    print(f"{len(E)} virhettä, {len(W)} huomautusta")
    sys.exit(1 if E else 0)


# ---------------------------------------------------------------- lähteiden skannaus
def anchors(h, base):
    for m in re.finditer(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', h, re.S):
        yield urllib.parse.urljoin(base, html.unescape(m.group(1))), clean(m.group(2))


def page_meta(url, ua=UA, html_=None):
    """Otsikko, julkaistu (Helsingin aikaa) ja kuvaus sivun metatiedoista."""
    h = html_ if html_ is not None else get_text(url, ua=ua)
    out = {}
    for m in re.finditer(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", h, re.S):
        for key in ("datePublished", "headline"):
            mm = re.search(r'"%s"\s*:\s*"([^"]+)"' % key, m.group(1))
            if mm and key not in out:
                out[key] = mm.group(1)

    def meta(name):
        mm = (re.search(r'<meta[^>]+(?:property|name)="%s"[^>]+content="([^"]*)"' % re.escape(name), h)
              or re.search(r'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="%s"' % re.escape(name), h))
        return html.unescape(mm.group(1)) if mm else None
    julk = to_hki(out.get("datePublished")) or to_hki((meta("article:published_time") or "").replace("+0300", "+03:00").replace("+0200", "+02:00"))
    if not julk:
        mm = re.search(r'<time[^>]*datetime="([^"]+)"', h)
        julk = to_hki(mm.group(1)) if mm else None
    if not julk:
        mm = re.search(r"(?:Julkaisu\w*|Julkaistu|Antopäivä|Päivämäärä)\W{0,40}(\d{1,2}\.\d{1,2}\.\d{4}(?:\s+(?:klo\s+)?\d{1,2}[.:]\d{2})?)", clean(h))
        julk = fi_date(mm.group(1)) if mm else None
    title = out.get("headline") or meta("og:title") or clean((re.search(r"<title>(.*?)</title>", h, re.S) or [None, ""])[1])
    title = re.sub(r"\s+[-|–]\s+(Korkein oikeus|Korkein hallinto-oikeus|Työtuomioistuin|Markkinaoikeus|Tuomioistuimet\.fi|Finanssivalvonta)$", "", title or "")
    return {"otsikko": title.strip(), "julkaistu": julk, "kuvaus": (meta("og:description") or meta("description") or "")[:240]}


def src_kko():
    """KKO:n RSS-syöte (tarkat julkaisuajat); varalla listaussivun linkit."""
    base = "https://www.korkeinoikeus.fi/ennakkopaatokset/ennakkopaatokset-vuosittain/"
    out = []
    try:
        x = get_text(base + "rss", timeout=25)
        for item in re.findall(r"<item>(.*?)</item>", x, re.S):
            link = re.search(r"<link>\s*(https://www\.korkeinoikeus\.fi/[^<\s]+/kko20\d{4,}/)\s*</link>", item)
            pub = re.search(r"<pubDate>(.*?)</pubDate>", item)
            if not link:
                continue
            julk = None
            if pub:
                try:
                    from email.utils import parsedate_to_datetime
                    julk = parsedate_to_datetime(pub.group(1).strip()).astimezone(HKI).strftime("%Y-%m-%dT%H:%M")
                except Exception:
                    julk = None
            out.append({"kanava": "kko", "url": link.group(1), "julkaistu": julk})
    except Exception:
        out = []
    if out:
        return out
    h = get_text(base)
    urls = list(dict.fromkeys(u for u, _ in anchors(h, base) if re.search(r"/kko20\d{4,}/$", u)))
    return [{"kanava": "kko", "url": u} for u in probe_next(urls, r"kko(20\d\d)(\d+)/$", "{y}{n}")]


def src_kho():
    base = "https://www.kho.fi/kho-paatokset/ennakkopaatokset/"
    h = get_text(base)
    urls = list(dict.fromkeys(u for u, _ in anchors(h, base) if re.search(r"/paatokset/kho20\d{4,}/$", u)))
    return [{"kanava": "kho", "url": u} for u in probe_next(urls, r"kho(20\d\d)(\d+)/$", "{y}{n}")]


def probe_next(urls, pat, fmt, extra=2):
    """Lisää listaan 1–2 seuraavaa numeroa, jos ne ovat jo julki mutta listaus ei vielä näytä niitä."""
    best = None
    for u in urls:
        m = re.search(pat, u)
        if m and (best is None or (int(m.group(1)), int(m.group(2))) > best[:2]):
            best = (int(m.group(1)), int(m.group(2)), u)
    out = list(urls)
    if best:
        y, n, u = best
        for k in range(1, extra + 1):
            cand = re.sub(pat, lambda m: m.group(0).replace(f"{y}{n}", fmt.format(y=y, n=n + k)), u)
            try:
                fetch(cand, tries=1, timeout=15)
                out.insert(0, cand)
            except Exception:
                break
    return out


def src_liferay(kanava, base, host, skip=r"^(tarkastus|lausunto|kannanotto-lausunto)"):
    h = get_text(base)
    out = []
    for u, t in anchors(h, base):
        if urllib.parse.urlsplit(u).netloc.endswith(host) and "/-/" in u and "asset_publisher" not in u:
            slug = u.split("/-/")[-1]
            if re.match(skip, slug):
                continue
            out.append({"kanava": kanava, "url": u.split("?")[0], "otsikko": t})
    return dedupe(out)


def src_kkv():
    base = "https://www.kkv.fi/ajankohtaista/tiedotteet/"
    h = get_text(base)
    return dedupe([{"kanava": "kilpailu", "url": u, "otsikko": t} for u, t in anchors(h, base)
                   if re.match(r"https://www\.kkv\.fi/ajankohtaista/tiedotteet/[^/]+/$", u) and t])


def src_finlex_tsv():
    base = "https://www.finlex.fi/fi/viranomaiset/tietosuojavaltuutettu"
    h = get_text(base)
    best = {}
    for u, t in anchors(h, base):
        if re.search(r"/viranomaiset/tietosuojavaltuutettu/20\d\d/\d+$", u) and len(t) > len(best.get(u, "")):
            best[u] = t
    out = [{"kanava": "tsv", "url": u, "otsikko": t.split(" | ")[0], "julkaistu": fi_date(t)} for u, t in best.items()]
    out.sort(key=lambda x: x.get("julkaistu") or "", reverse=True)
    return out


def src_archive(kanava, base, pat):
    h = get_text(base)
    return dedupe([{"kanava": kanava, "url": u} for u, _ in anchors(h, base) if re.search(pat, u)])


def src_vn():
    base = "https://valtioneuvosto.fi/ajankohtaista/tiedotteet"
    h = get_text(base)
    keep = re.compile(r"lausun|esitys|esityksen|esittää|eduskunnalle|lakiin|lain |laki|asetus|direktiiv|uudistu|säänt", re.I)
    out = []
    for u, t in anchors(h, base):
        if re.search(r"valtioneuvosto\.fi/-/\d+/", u) and keep.search(t or u):
            kan = "lausunnot" if re.search(r"lausun", t or u, re.I) else "he"
            out.append({"kanava": kan, "url": u.split("?")[0], "otsikko": t})
    return dedupe(out)


def src_fiva():
    base = "https://www.sttinfo.fi/uutishuone/69817444/finanssivalvonta/r"
    h = get_text(base)
    out = []
    for u, t in anchors(h, base):
        if "/tiedote/" in u and t and not re.search(r"kutsu|virka|haettavaksi|rekry|webinaari|tilaisuu", t, re.I):
            out.append({"kanava": "fiva", "url": u.split("?")[0], "otsikko": re.split(r"\s\d{1,2}\.\d{1,2}\.\d{4}", t)[0],
                        "julkaistu": fi_date(t)})
    return dedupe(out)


def src_icj():
    base = "https://www.icj-cij.org/press-releases"
    h = get_text(base)
    out = []
    for u, t in anchors(h, base):
        m = re.search(r"/(\d+|000)-(20\d{6})-pre-\d\d-\d\d-en\.pdf$", u)
        if m:
            d = m.group(2)
            out.append({"kanava": "icj", "url": u, "otsikko": t, "julkaistu": f"{d[:4]}-{d[4:6]}-{d[6:]}"})
    return dedupe(out)


def src_hudoc():
    out, fails = [], []
    queries = [
        ('contentsitename:ECHR AND respondent="FIN" AND (documentcollectionid="JUDGMENTS" OR documentcollectionid="DECISIONS")'
         ' AND languageisocode="ENG"', "Suomi"),
        ('contentsitename:ECHR AND documentcollectionid="GRANDCHAMBER" AND languageisocode="ENG"', "suuri jaosto"),
    ]
    for q, label in queries:
        u = "https://hudoc.echr.coe.int/app/query/results?" + urllib.parse.urlencode(
            {"query": q, "select": "itemid,docname,kpdate", "sort": "kpdate Descending", "start": 0, "length": 8})
        try:
            res = json.loads(get_text(u, ua=BROWSER_UA, accept="application/json"))
        except Exception as e:
            fails.append(e)
            continue
        for r in res.get("results", []):
            c = r["columns"]
            if re.search(r"translation|summary by", c.get("docname", ""), re.I):
                continue
            out.append({"kanava": "eit", "url": f"https://hudoc.echr.coe.int/?i={c['itemid']}",
                        "otsikko": f"{c.get('docname')} ({label})", "julkaistu": (c.get("kpdate") or "")[:10]})
    if fails and not out:
        raise fails[-1]   # verkkovirhe raportoidaan virheenä, ei hiljaisuutena
    return dedupe(out)


def dedupe(lst):
    seen, out = set(), []
    for x in lst:
        k = norm_url(x["url"])
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


CURIA_SPARQL = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?celex ?date ?title ?country WHERE {
 ?w cdm:resource_legal_id_celex ?celex ; cdm:work_date_document ?date .
 FILTER(?date >= "%s"^^xsd:date)
 FILTER(REGEX(STR(?celex), "^6[0-9]{4}(CJ|TJ|CC)[0-9]{4}$"))
 ?e cdm:expression_belongs_to_work ?w ; cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/FIN> ; cdm:expression_title ?title .
 OPTIONAL { ?w cdm:case-law_originates_in_country ?country . }
} ORDER BY DESC(?date) LIMIT 80"""


def src_curia(days=10):
    """Unionin tuomioistuimen ja unionin yleisen tuomioistuimen tuomiot sekä julkisasiamiesten ratkaisuehdotukset
    EU:n julkaisutoimiston avoimesta CELLAR-rajapinnasta (suomenkieliset viralliset otsikot ja asiasanat)."""
    since = (now().date() - datetime.timedelta(days=days)).isoformat()
    url = "https://publications.europa.eu/webapi/rdf/sparql?" + urllib.parse.urlencode(
        {"query": CURIA_SPARQL % since, "format": "application/sparql-results+json"})
    res = json.loads(get_text(url, timeout=90, accept="application/sparql-results+json"))
    sv = {}
    try:  # viralliset ruotsinkieliset asiasanat (sivun ruotsinkielinen versio)
        vals = " ".join(sorted({f'"{b["celex"]["value"]}"^^xsd:string' for b in res["results"]["bindings"]}))
        qsv = ("PREFIX cdm: <http://publications.europa.eu/ontology/cdm#> PREFIX xsd: <http://www.w3.org/2001/XMLSchema#> "
               "SELECT DISTINCT ?celex ?title WHERE { VALUES ?celex { %s } "
               "?w cdm:resource_legal_id_celex ?celex . ?e cdm:expression_belongs_to_work ?w ; "
               "cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/SWE> ; cdm:expression_title ?title . }") % vals
        r2 = json.loads(get_text("https://publications.europa.eu/webapi/rdf/sparql?" + urllib.parse.urlencode(
            {"query": qsv, "format": "application/sparql-results+json"}), timeout=90, accept="application/sparql-results+json"))
        sv = {b["celex"]["value"]: b["title"]["value"] for b in r2["results"]["bindings"]}
    except Exception:
        pass
    out, seen = [], set()
    for b in res["results"]["bindings"]:
        celex = b["celex"]["value"]
        if celex in seen or b["date"]["value"][:10] > now().date().isoformat():   # tulevan antopäivän merkintä ei ole vielä tuomio
            continue
        seen.add(celex)
        m = re.match(r"^6(\d{4})(CJ|TJ|CC)(\d{4})$", celex)
        yy, typ, nro = m.group(1)[2:], m.group(2), int(m.group(3))
        case = f"{'T' if typ == 'TJ' else 'C'}-{nro}/{yy}"
        parts = [x.strip() for x in b["title"]["value"].split("#") if x.strip()]
        kw = next((x for x in parts if " – " in x), "")
        kw = re.sub(r"^Ennakkoratkaisupyyntö – ", "", kw).rstrip(".")
        maa = (b.get("country", {}).get("value", "") or "")[-3:]
        psv = [x.strip() for x in sv.get(celex, "").split("#") if x.strip()]
        kw_sv = re.sub(r"^Begäran om förhandsavgörande – ", "", next((x for x in psv if x.startswith("Begäran om förhandsavgörande –")),
                       next((x for x in psv if " – " in x), ""))).rstrip(".")
        laji = {"CJ": "tuomio", "TJ": "yleisen tuomioistuimen tuomio", "CC": "julkisasiamiehen ratkaisuehdotus"}[typ]
        out.append({"kanava": "eu", "url": f"https://curia.europa.eu/juris/liste.jsf?num={case}&language=fi",
                    "otsikko": f"{case} {laji}{' – SUOMEN ENNAKKORATKAISUPYYNTÖ' if maa == 'FIN' else ''}",
                    "julkaistu": b["date"]["value"][:10],
                    "kuvaus": " | ".join(x for x in parts[1:3] if x)[:200] + (f" | {kw[:600]}" if kw else ""),
                    "maa": maa, "asiasanat_sv": kw_sv[:600] or None})
    rank = lambda x: (0 if x["maa"] == "FIN" else 1, "".join(chr(255 - ord(c)) for c in x["julkaistu"]),
                      2 if "ratkaisuehdotus" in x["otsikko"] else 1 if "yleisen" in x["otsikko"] else 0)
    out.sort(key=rank)
    return out


def src_tuomioistuimet(base, text_pat, kanava="muut"):
    """tuomioistuimet.fi:n koosteet (hovioikeudet, vakuutusoikeus): linkit, joiden teksti on ratkaisutunnus."""
    h = get_text(base)
    return dedupe([{"kanava": kanava, "url": u, "otsikko": t} for u, t in anchors(h, base)
                   if re.search(text_pat, t.replace("\u00ad", "")) and "/ratkaisu" in u])


def src_edpb():
    """Euroopan tietosuojaneuvoston ja kansallisten tietosuojaviranomaisten uutiset (esim. suuret seuraamusmaksut)."""
    base = "https://www.edpb.europa.eu/news/news_en"
    h = get_text(base)
    out = []
    for m in re.finditer(r'href="(/news/[^"#?]+_en)"', h):
        u = urllib.parse.urljoin(base, m.group(1))
        if u.endswith("/news/news_en"):
            continue
        dts = re.findall(r'datetime="(\d{4}-\d{2}-\d{2})', h[max(0, m.start() - 1500):m.start()])
        slug = m.group(1).rsplit("/", 1)[-1].removesuffix("_en").replace("-", " ")
        out.append({"kanava": "tsv", "url": u, "otsikko": slug[:1].upper() + slug[1:], "julkaistu": dts[-1] if dts else None})
    return dedupe(out)



# ---------------------------------------------------------------- Finlex, eduskunta ja Hankeikkuna (avoimet rajapinnat)
# oikeuskansleri.fi, oikeusasiamies.fi, tietosuoja.fi, valtioneuvosto.fi ja ministeriöiden sivut sekä lausuntopalvelu.fi torjuvat
# automaattiset haut (Cloudflaren selaintarkistus; myös WebFetch epäonnistuu). Siksi laillisuusvalvonnan ratkaisut luetaan
# Finlexistä, hallituksen esitykset eduskunnan avoimesta datasta ja lausuntokierrokset valtioneuvoston Hankeikkunan rajapinnasta.
# Lukijalle näytettävä lähde on silti virallinen sivu; text- ja check_source-komennot lukevat sen sisällön rajapinnasta.
BLOCKED_HOSTS = ("oikeuskansleri.fi", "oikeusasiamies.fi", "tietosuoja.fi", "valtioneuvosto.fi", "lausuntopalvelu.fi", "oikeusministerio.fi",
                 "vnk.fi", "um.fi", "intermin.fi", "defmin.fi", "vm.fi", "okm.fi", "mmm.fi", "lvm.fi", "tem.fi", "stm.fi", "ym.fi")
SCAN_CTX = {}   # cmd_scan asettaa "data": lähteet voivat jatkaa edellisen ajon kohdasta (eduskunnan avoin data)
FINLEX_NOISE = re.compile(r"^(404: This page|This page could not|Siirry sisältöön|Sivun alkuun|Finlex on oikeusministeriön|Finlexin sisältö|"
                          r"Hallituksen esitysten tekstit|Valtioneuvoston oikeuskanslerin ja apulais|Eduskunnan oikeusasiamiehen ja apulais|"
                          r"Hae kaikista|Suomeksi$|På svenska$|In English$|Valikko$|Hae$|Etusivu$|Lainsäädäntö$|Oikeuskäytäntö$|Viranomaiset$|"
                          r"Valtiosopimukset$|Hallituksen esitykset$|Avoin data$)")


def blocked_host(u):
    h = (urllib.parse.urlsplit(u or "").hostname or "").lower()
    return any(h == b or h.endswith("." + b) for b in BLOCKED_HOSTS)


FINLEX_TAIL = re.compile(r"^(Voit antaa Finlex-palvelua|Palaa \"|Hakemaasi dokumenttia|selaa sisältöjä|Uusimmat julkaistut|10 Finlexin haetuinta|Tietoa Finlexistä|Saavutettavuusseloste|Tietosuoja$)")


def finlex_doc_text(h, title=""):
    """Finlexin sivun oma sisältö: alkaa dokumentin ensimmäisestä sisältöotsikosta (esim. ESITYKSEN PÄÄASIALLINEN SISÄLTÖ) tai
    sivun otsikosta ja päättyy alatunnisteeseen. Palauttaa tyhjän, jos sisältöä ei löydy (viranomaisratkaisu on silloin PDF-liitteenä)."""
    lines = [l for l in finlex_rsc_text(h).split("\n") if not FINLEX_TAIL.match(l) and l not in ("404", "Finlex")]
    starts = [i for i, l in enumerate(lines) if l.startswith("ESITYKSEN PÄÄASIALLINEN SISÄLTÖ") or (title and l == title)]
    if not starts:
        return ""
    body = lines[starts[0]:]
    # sisällysluettelo toistuu ennen varsinaista tekstiä: aloitetaan toisesta esiintymästä, jos sellainen on
    again = [i for i, l in enumerate(body[1:], 1) if l == body[0]]
    if again:
        body = body[again[0]:]
    return "\n".join(body)


def finlex_rsc_text(h):
    """Finlexin (Next.js) sivun teksti React-palvelinkomponenttien kuormasta: HTML:ssä on vain navigointi."""
    out, prev = [], None
    for chunk in re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', h, flags=re.S):
        try:
            s = json.loads('"' + chunk + '"')
        except ValueError:
            continue
        for m in re.finditer(r'"children":(\[(?:"(?:[^"\\]|\\.)*"(?:,\s*)?)+\]|"(?:[^"\\]|\\.)*")', s):
            try:
                t = json.loads(m.group(1))
            except ValueError:
                continue
            for x in (t if isinstance(t, list) else [t]):
                x = " ".join(str(x).split())
                if len(x) > 1 and not x.startswith("$") and not FINLEX_NOISE.match(x) and x != prev:
                    out.append(x); prev = x
    return "\n".join(out)


def finlex_pdf_link(h):
    m = re.search(r'/api/media/[^"\\\s<>]+?\.(?:pdf|PDF)(?:\?[^"\\\s<>]*)?', h)
    return ("https://www.finlex.fi" + html.unescape(m.group(0)).replace("\\u0026", "&")) if m else None


def src_finlex_auth(kanava, slug, prefix=""):
    """Finlexin viranomaisosio (valtioneuvoston oikeuskansleri, eduskunnan oikeusasiamies): päivä, diaarinumero ja otsikko listasta.
    Muille annetut lausunnot ja tarkastukset ohitetaan rutiinina, kuten viranomaisten omilla sivuilla."""
    base = f"https://www.finlex.fi/fi/viranomaiset/{slug}"
    h = get_text(base)
    out = []
    for m in re.finditer(r'<a aria-label="([^"]*)"[^>]*href="(/fi/viranomaiset/%s/20\d\d/\d+)"' % re.escape(slug), h):
        lab = html.unescape(" ".join(m.group(1).split()))
        mm = re.match(r"(\d{1,2}\.\d{1,2}\.\d{4})\s+([^,]+),\s*(.+)$", lab)
        if not mm:
            continue
        pvm, tunnus, title = mm.groups()
        if re.match(r"(?i)^(lausunto|kannanotto|tarkastus)", title):
            continue
        if prefix and not tunnus.upper().startswith(prefix.split("/")[0].upper()):
            tunnus = prefix + tunnus
        out.append({"kanava": kanava, "url": "https://www.finlex.fi" + m.group(2), "otsikko": title, "tunnus": tunnus,
                    "julkaistu": fi_date(pvm), "valmis": True})
    return dedupe(out)


VASKI_ROWS = "https://avoindata.eduskunta.fi/api/v1/tables/VaskiData/rows"
VASKI_BATCH = "https://avoindata.eduskunta.fi/api/v1/tables/VaskiData/batch"
VASKI_ID_FLOOR = 351000   # lokakuu 2026; ensimmäinen ajo lukee tästä eteenpäin, seuraavat data.jsonin _vaski_id-kohdasta


def he_paragraphs(x):
    """HE:n XML -> (nimeke, [pääasiallisen sisällön kappaleet], [koko tekstin rivit])."""
    nm = re.search(r"<[\w:]*NimekeTeksti[^>]*>(.*?)</", x, re.S)
    m = re.search(r"<[\w:]*SisaltoKuvaus\b[^>]*>(.*?)</[\w:]*SisaltoKuvaus>", x, re.S)
    summary = [clean(t) for t in re.findall(r"<[\w:]*KappaleKooste\b[^>]*>(.*?)</[\w:]*KappaleKooste>", m.group(1) if m else "", re.S) if clean(t)]
    lines = [clean(t) for _, t in re.findall(r"<[\w:]*(OtsikkoTeksti|KappaleKooste|SaadosNimeke|PykalaTunnus)\b[^>]*>(.*?)</", x, re.S) if clean(t)]
    return (clean(nm.group(1)) if nm else ""), summary, lines


def _is_he_doc(r):
    x = r.get("XmlData") or ""
    return (r.get("Eduskuntatunnus") or "").startswith("HE ") and "AsiakirjatyyppiKoodi>HE<" in x and "KasittelytiedotValtiopaivaasia" not in x


def _is_pevl_doc(r):
    """Perustuslakivaliokunnan lausunto (PeVL): juridisesti painavin kotimainen valiokunta-asiakirja."""
    x = r.get("XmlData") or ""
    return (r.get("Eduskuntatunnus") or "").startswith("PeVL ") and "AsiakirjatyyppiKoodi>PeVL<" in x and "KasittelytiedotValtiopaivaasia" not in x


def _is_ev_doc(r):
    """Eduskunnan vastaus (EV): eduskunnan lopullinen päätös hallituksen esityksestä (hyväksytty tai hylätty)."""
    x = r.get("XmlData") or ""
    return (r.get("Eduskuntatunnus") or "").startswith("EV ") and "AsiakirjatyyppiKoodi>EV<" in x and "KasittelytiedotValtiopaivaasia" not in x


def ev_item(r, em):
    """EV-ehdokas: mihin esitykseen vastaus liittyy, päätöspäivä (täysistunto), mietintö, asiasanat ja päätösteksti
    ('Eduskunta on hyväksynyt seuraavan lain …' / 'hylännyt')."""
    x = r["XmlData"]
    nimi = _xml_text(x, "NimekeTeksti")
    he = re.search(r"\b(HE \d+/\d{4} vp)\b", _xml_text(x, "EduskuntaTunnus") + " " + x[:4000])
    miet = re.search(r"\b([A-ZÅÄÖ][a-zåäö]+VM \d+/\d{4} vp)\b", x)
    pvm = fi_date(_xml_text(x, "LaadintaPvmTeksti"))
    aiheet = re.findall(r"<[\w:]*AiheTeksti[^>]*>([^<]+)<", x)
    i = x.find("Päätös</")
    paatos = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", x[i:i + 20000])).split()) if i > 0 else ""
    paatos = re.sub(r"^Päätös\s*", "", paatos)
    paatos = paatos.split(" Helsingissä ")[0][:900]
    hyv = "hyväksynyt" in paatos.lower() or "hyväksyi" in paatos.lower()
    hyl = "hylännyt" in paatos.lower() or "hylkäsi" in paatos.lower()
    hm = re.match(r"HE (\d+)/(\d{4}) vp", he.group(1)) if he else None
    return {"kanava": "he", "url": f"https://www.eduskunta.fi/valtiopaivaasiakirjat/EV+{em.group(1)}/{em.group(2)}", "tunnus": r.get("Eduskuntatunnus"),
            "otsikko": f"Eduskunnan vastaus: {nimi}" if nimi else r.get("Eduskuntatunnus"), "julkaistu": to_hki(r.get("Created") or ""), "valmis": True,
            "he": he.group(1) if he else None, "paatospvm": (pvm or "")[:10] or None, "mietinto": miet.group(1) if miet else None,
            "asiasanat": ", ".join(dict.fromkeys(a.strip() for a in aiheet)), "paatos": paatos, "lopputulos_arvio": "hyväksytty" if hyv and not hyl else ("hylätty" if hyl else None),
            "id_ehdotus": f"he-paatos-{hm.group(1)}-{hm.group(2)}" if hm else f"ev-{em.group(1)}-{em.group(2)}",
            "kuvaus": (f"Eduskunnan vastaus esitykseen {he.group(1)}. " if he else "") + paatos[:600], "laji": "eduskunnan vastaus"}


def _xml_text(x, tag):
    m = re.search(r"<[\w:]*%s\b[^>]*>(.*?)</[\w:]*%s>" % (tag, tag), x, re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).split()) if m else ""


def pevl_item(r, pm):
    """PeVL-ehdokas: lausunnon kohde (HE), vastaanottava valiokunta ja valiokunnan päätösesitys (säätämisjärjestys, huomautukset)."""
    x = r["XmlData"]
    nimi = _xml_text(x, "NimekeTeksti")
    he = re.search(r"\b(HE \d+/\d{4} vp)\b", _xml_text(x, "VireilletuloAsia") + " " + " ".join(re.findall(r"<sis1:AsiakirjaViiteTunnus[^>]*>(.*?)</", x)[:1]))
    paatos = re.sub(r"^VALIOKUNNAN PÄÄTÖSESITYS\s*", "", _xml_text(x, "PaatosOsa"))
    vast = _xml_text(x, "OtsikkoTeksti")
    return {"kanava": "he", "url": f"https://www.eduskunta.fi/valtiopaivaasiakirjat/PeVL+{pm.group(1)}/{pm.group(2)}", "tunnus": r.get("Eduskuntatunnus"),
            "otsikko": f"PeVL: {nimi}" if nimi else r.get("Eduskuntatunnus"), "julkaistu": to_hki(r.get("Created") or ""), "valmis": True,
            "he": he.group(1) if he else None, "vastaanottaja": vast if vast.endswith("lle") else None, "paatosesitys": paatos[:700],
            "kuvaus": (f"Lausunto esityksestä {he.group(1)}. " if he else "") + paatos[:600], "laji": "perustuslakivaliokunnan lausunto"}


def src_eduskunta_he():
    """Uudet hallituksen esitykset eduskunnan avoimesta datasta (VaskiData) edellisen ajon kohdasta eteenpäin."""
    d = SCAN_CTX.get("data") or {}
    start = int(d.get("_vaski_id") or VASKI_ID_FLOOR)
    have = {it.get("tunnus") for it in (d.get("kanavat") or {}).get("he", [])} | {r.get("he") for r in d.get("he_tila", [])}
    best, pages, last = {}, 0, start
    while pages < 60:
        data = json.loads(get_text(f"{VASKI_BATCH}?pkName=Id&pkStartValue={last}&perPage=20", timeout=120))
        rows = [dict(zip(data["columnNames"], r)) for r in data.get("rowData") or []]
        if not rows:
            break
        pages += 1
        for r in rows:
            last = max(last, int(r["Id"]))
            t = r.get("Eduskuntatunnus") or ""
            if (_is_he_doc(r) or _is_pevl_doc(r) or _is_ev_doc(r)) and (t not in best or len(r["XmlData"]) > len(best[t]["XmlData"])):
                best[t] = r
        if not data.get("hasMore"):
            break
    SCAN_CTX["vaski_id"] = max(start, last - 400)   # päällekkäisyys (n. 5 pv) varmistaa, ettei esitys jää väliin
    out = []
    for t, r in best.items():
        pm = re.match(r"PeVL (\d+)/(\d{4}) vp$", t)
        if pm and t not in have:
            out.append(pevl_item(r, pm))
            continue
        em = re.match(r"EV (\d+)/(\d{4}) vp$", t)
        if em and t not in have:
            out.append(ev_item(r, em))
            continue
        m = re.match(r"HE (\d+)/(\d{4}) vp$", t)
        if not m or t in have:
            continue
        nimi, summary, _ = he_paragraphs(r["XmlData"])
        lp = re.search(r"<[\w:]*LaadintaPvm[^>]*>(\d{1,2}\.\d{1,2}\.\d{4})</", r["XmlData"])
        voim = next((p for p in summary if re.search(r"tulemaan voimaan|tulisivat voimaan|tulisi voimaan|voimaantulo", p, re.I)), None)
        out.append({"kanava": "he", "url": f"https://www.eduskunta.fi/valtiopaivaasiakirjat/HE+{m.group(1)}/{m.group(2)}", "tunnus": t,
                    "otsikko": nimi or t, "julkaistu": to_hki(r.get("Created") or ""), "annettu": fi_date(lp.group(1)) if lp else None,
                    "kuvaus": " ".join(summary)[:700], "voimaantulo": voim, "valmis": True})
    out.sort(key=lambda x: x.get("julkaistu") or "", reverse=True)
    return out


def he_text(n, year, url, maxc):
    """HE:n teksti eduskunnan avoimesta datasta (eduskunta.fi:n sivu rakentuu selaimessa, eikä sitä voi lukea skriptillä)."""
    q = VASKI_ROWS + "?" + urllib.parse.urlencode({"columnName": "Eduskuntatunnus", "columnValue": f"HE {n}/{year} vp", "perPage": 20})
    data = json.loads(get_text(q, timeout=90))
    rows = [r for r in (dict(zip(data["columnNames"], r)) for r in data.get("rowData") or []) if _is_he_doc(r)]
    if not rows:
        raise ValueError(f"HE {n}/{year} vp ei löydy eduskunnan avoimesta datasta")
    r = max(rows, key=lambda r: len(r["XmlData"]))
    nimi, summary, lines = he_paragraphs(r["XmlData"])
    t = "\n".join(lines)
    return {"url": url, "otsikko": nimi, "julkaistu": to_hki(r.get("Created") or ""), "tunnus": f"HE {n}/{year} vp",
            "paaasiallinen_sisalto": " ".join(summary), "teksti": t[:maxc] + (f"\n[… katkaistu, yhteensä {len(t)} merkkiä]" if len(t) > maxc else "")}


def ev_text(n, year, url, maxc):
    """Eduskunnan vastauksen teksti eduskunnan avoimesta datasta: päätös ja hyväksytyt lait."""
    q = VASKI_ROWS + "?" + urllib.parse.urlencode({"columnName": "Eduskuntatunnus", "columnValue": f"EV {n}/{year} vp", "perPage": 20})
    data = json.loads(get_text(q, timeout=90))
    rows = [r for r in (dict(zip(data["columnNames"], r)) for r in data.get("rowData") or []) if _is_ev_doc(r)]
    if not rows:
        raise ValueError("eduskunnan vastausta ei löydy avoimesta datasta")
    r = max(rows, key=lambda r: len(r["XmlData"]))
    it = ev_item(r, re.match(r"EV (\d+)/(\d{4}) vp$", r.get("Eduskuntatunnus") or f"EV {n}/{year} vp"))
    x = r["XmlData"]
    i = x.find("<sis1:Asia") if "<sis1:Asia" in x else x.find("Asia</")
    t = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", x[max(i, 0):])).split())
    t = re.sub(r"\s*\{[0-9A-F-]{36}\}.*$", "", t)   # liitetiedoston tunnisteet pois lopusta
    out = {"url": url, "otsikko": it["otsikko"], "julkaistu": it["julkaistu"], "he": it["he"], "paatospvm": it["paatospvm"], "mietinto": it["mietinto"],
           "lahde_teksti": q}
    out["teksti"] = t[:maxc] + (f"\n[… katkaistu, yhteensä {len(t)} merkkiä]" if len(t) > maxc else "")
    return out


def pevl_text(n, year, url, maxc):
    """Perustuslakivaliokunnan lausunnon teksti eduskunnan avoimesta datasta: kohde-HE, lausunnon perustelut ja päätösesitys."""
    q = VASKI_ROWS + "?" + urllib.parse.urlencode({"columnName": "Eduskuntatunnus", "columnValue": f"PeVL {n}/{year} vp", "perPage": 20})
    data = json.loads(get_text(q, timeout=90))
    rows = [r for r in (dict(zip(data["columnNames"], r)) for r in data.get("rowData") or []) if _is_pevl_doc(r)]
    if not rows:
        raise ValueError(f"PeVL {n}/{year} vp ei löydy eduskunnan avoimesta datasta")
    r = max(rows, key=lambda r: len(r["XmlData"]))
    x = r["XmlData"]
    item = pevl_item(r, re.match(r"PeVL (\d+)/(\d{4}) vp$", r.get("Eduskuntatunnus") or f"PeVL {n}/{year} vp"))
    found = []
    for tag in ("OtsikkoTeksti", "LihavaKursiiviOtsikkoTeksti", "KappaleKooste", "SisennettyKappaleKooste"):
        for m in re.finditer(r"<[\w:]*%s\b[^>]*>(.*?)</[\w:]*%s>" % (tag, tag), x, re.S):
            if clean(m.group(1)):
                found.append((m.start(), clean(m.group(1))))
    lines = [t for _, t in sorted(found)]
    t = "\n".join(lines)
    return {"url": url, "otsikko": item["otsikko"], "julkaistu": item["julkaistu"], "tunnus": item["tunnus"], "he": item.get("he"),
            "vastaanottaja": item.get("vastaanottaja"), "paatosesitys": item.get("paatosesitys"),
            "teksti": t[:maxc] + (f"\n[… katkaistu, yhteensä {len(t)} merkkiä]" if len(t) > maxc else "")}


HANKE_API = "https://api.hankeikkuna.fi/api/v2"
_ASETTAJAT = None


def post_json(url, body, timeout=60):
    check_url(url)
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json"})
    with _OPENER.open(req, timeout=timeout) as r:
        b = r.read(MAX_FETCH + 1)
    if len(b) > MAX_FETCH:
        raise TooBig(f"vastaus yli {MAX_FETCH // 1024 // 1024} Mt")
    return json.loads(b.decode("utf-8", "replace"))


def asettaja_nimi(uuid):
    global _ASETTAJAT
    if _ASETTAJAT is None:
        try:
            a = json.loads(get_text(HANKE_API + "/asettajat", timeout=40))
            _ASETTAJAT = {x["uuid"]: x for x in (a.get("result") if isinstance(a, dict) else a) if x.get("uuid")}
        except Exception:
            _ASETTAJAT = {}
    nimi = (_ASETTAJAT.get(uuid) or {}).get("nimi") or {}
    return {k: (nimi.get(k) or "") for k in ("fi", "sv", "en")}


def _hanke_item(r, since=None):
    k = r.get("kohde") or {}
    et = [e for e in r.get("etapit") or [] if e.get("tyyppi") == "LAUSUNTOKIERROS" and e.get("alku") and (since is None or e["alku"] >= since)]
    if not et or not k.get("tunnus"):
        return None
    e = max(et, key=lambda e: e.get("alku") or "")
    docs = [a for a in r.get("asiakirjat") or [] if a.get("tyyppi") == "LAUSUNTOPYYNTO" and a.get("url")]
    # Lausuntopyyntökirje: PDF ensin (suomenkielinen nimi ennen ruotsinkielistä), sitten .docx; Outlook-viestiä (.msg) ei lueta
    SV = re.compile(r"\b(statsrådets|regeringens|förordning|lag|om|av|och|för|till|utkast|remiss)\b", re.I)
    doc_name = lambda a: (a.get("nimi") or {}).get("fi") if isinstance(a.get("nimi"), dict) else str(a.get("nimi") or "")
    rank = lambda a: (0 if a["url"].lower().endswith(".pdf") else 1 if a["url"].lower().endswith(".docx") else 9,
                      1 if len(SV.findall(doc_name(a) or "")) >= 2 else 0)   # ruotsinkielinen versio viimeiseksi
    docs = sorted((a for a in docs if not a["url"].lower().endswith((".msg", ".doc", ".xlsx", ".xls", ".zip"))), key=rank)
    nimi, kuvaus, elin = k.get("nimi") or {}, k.get("kuvaus") or {}, asettaja_nimi(k.get("asettajaUuid"))
    return {"kanava": "lausunnot", "url": f"https://valtioneuvosto.fi/hanke?tunnus={k['tunnus']}", "tunnus": k["tunnus"],
            "otsikko": nimi.get("fi") or "", "otsikko_sv": nimi.get("sv") or "", "otsikko_en": nimi.get("en") or "",
            "julkaistu": e.get("alku"), "maaraaika": e.get("loppu"), "elin": elin["fi"], "elin_sv": elin["sv"], "elin_en": elin["en"],
            "kuvaus": (kuvaus.get("fi") or "")[:700], "asianumero": (k.get("asianumerot") or [None])[0],
            "lausuntopyynto_pdf": docs[0]["url"] if docs else None, "valmis": True}


def src_hankeikkuna(days=14):
    """Lausuntokierrokset (lait ja asetukset) valtioneuvoston Hankeikkunan avoimesta rajapinnasta: alku, määräaika, ministeriö."""
    since = days_ago(days)
    res = post_json(HANKE_API + "/kohteet/haku", {"tyyppi": ["LAINSAADANTO"], "etappiTyyppi": ["LAUSUNTOKIERROS"],
                                                   "etappiAlkamisPaivaAlku": since, "size": 100})
    out = [x for x in (_hanke_item(r, since) for r in res.get("result") or []) if x]
    out.sort(key=lambda x: x.get("julkaistu") or "", reverse=True)
    return out


def hanke_text(tunnus, url, maxc):
    """Hankkeen kuvaus, lausuntokierros ja lausuntopyyntökirjeen teksti Hankeikkunan rajapinnasta."""
    res = post_json(HANKE_API + "/kohteet/haku", {"tunnus": [tunnus], "size": 5})
    rows = [r for r in res.get("result") or [] if ((r.get("kohde") or {}).get("tunnus") or "").lower() == tunnus.lower()]
    if not rows:
        raise ValueError(f"hanketta {tunnus} ei löydy Hankeikkunasta")
    r = rows[0]
    x = _hanke_item(r) or {"otsikko": ((r["kohde"].get("nimi") or {}).get("fi") or ""), "kuvaus": ((r["kohde"].get("kuvaus") or {}).get("fi") or "")}
    k = r["kohde"]
    parts = [x.get("otsikko") or "", x.get("kuvaus") or "", (k.get("vaikutukset") or {}).get("fi") or ""]
    if x.get("maaraaika"):
        parts.append(f"Lausuntokierros {x.get('julkaistu')} – {x['maaraaika']}.")
    pdf = x.get("lausuntopyynto_pdf")
    if pdf:
        try:
            parts.append(_text(pdf, maxc)["teksti"])
        except Exception as e:
            parts.append(f"[lausuntopyyntökirjettä ei saatu luettua: {str(e)[:60]}]")
    t = "\n".join(p for p in parts if p)
    return {"url": url, "otsikko": x.get("otsikko"), "julkaistu": x.get("julkaistu"), "maaraaika": x.get("maaraaika"), "elin": x.get("elin"),
            "lausuntopyynto_pdf": pdf, "teksti": t[:maxc] + (f"\n[… katkaistu, yhteensä {len(t)} merkkiä]" if len(t) > maxc else "")}


def api_url_for(url):
    """Osoitteet, joiden sisältö luetaan rajapinnasta: (tyyppi, tunnistetiedot) tai None."""
    m = re.match(r"https://www\.eduskunta\.fi/valtiopaivaasiakirjat/HE\+(\d+)/(\d{4})$", url or "") or \
        re.search(r"eduskunta\.fi/.*?HE(?:%20|\+| )(\d+)(?:%2F|/)(\d{4})", url or "")
    if m:
        return ("he", int(m.group(1)), int(m.group(2)))
    m = re.match(r"https://www\.eduskunta\.fi/valtiopaivaasiakirjat/PeVL\+(\d+)/(\d{4})$", url or "") or \
        re.search(r"eduskunta\.fi/.*?PeVL(?:%20|\+| )(\d+)(?:%2F|/)(\d{4})", url or "")
    if m:
        return ("pevl", int(m.group(1)), int(m.group(2)))
    m = re.match(r"https://www\.eduskunta\.fi/valtiopaivaasiakirjat/EV\+(\d+)/(\d{4})$", url or "") or \
        re.search(r"eduskunta\.fi/.*?EV(?:%20|\+| )(\d+)(?:%2F|/)(\d{4})", url or "")
    if m:
        return ("ev", int(m.group(1)), int(m.group(2)))
    m = re.match(r"https://valtioneuvosto\.fi/hanke\?tunnus=([^&#]+)", url or "")
    if m:
        return ("hanke", urllib.parse.unquote(m.group(1)))
    m = re.match(r"https://(?:www\.)?finlex\.fi/fi/lainsaadanto/saadoskokoelma/(\d{4})/(\d+)/?$", url or "")
    if m:
        return ("sk", int(m.group(2)), int(m.group(1)))
    m = re.match(r"https://eur-lex\.europa\.eu/legal-content/([A-Z]{2})/[A-Z]+/\?uri=CELEX(?::|%3A)([0-9A-Z()]+)", url or "")
    if m:
        return ("eurlex", m.group(2), m.group(1))
    return None


DIR_SPARQL = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?celex ?date ?pub ?eif (MIN(?tr) AS ?trans) ?title WHERE {
 ?w cdm:resource_legal_id_celex ?celex ; cdm:work_date_document ?date ; cdm:official-journal-act_date_publication ?pub .
 FILTER(?pub >= "%s"^^xsd:date)
 FILTER(REGEX(STR(?celex), "^3[0-9]{4}L[0-9]{4}$"))
 OPTIONAL { ?w cdm:resource_legal_date_entry-into-force ?eif . }
 OPTIONAL { ?w cdm:directive_date_transposition ?tr . }
 ?e cdm:expression_belongs_to_work ?w ; cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/FIN> ; cdm:expression_title ?title .
} GROUP BY ?celex ?date ?pub ?eif ?title ORDER BY DESC(?pub) LIMIT 60"""


def _sparql(q, timeout=90):
    url = "https://publications.europa.eu/webapi/rdf/sparql?" + urllib.parse.urlencode({"query": q, "format": "application/sparql-results+json"})
    return json.loads(get_text(url, timeout=timeout, accept="application/sparql-results+json"))["results"]["bindings"]


def eurlex_url(celex, lang="FI"):
    return f"https://eur-lex.europa.eu/legal-content/{lang}/TXT/?uri=CELEX:{celex}"


def _pvm_fi(iso):
    y, m, d = iso[:10].split("-")
    return f"{int(d)}.{int(m)}.{y}"


def src_eu_direktiivit(days=21):
    """Uudet direktiivit sillä hetkellä, kun ne julkaistaan EU:n virallisessa lehdessä (EU:n julkaisutoimiston CELLAR-rajapinta):
    viralliset nimikkeet suomeksi, ruotsiksi ja englanniksi, antopäivä (hyväksyminen/allekirjoitus), julkaisupäivä,
    voimaantulo ja täytäntöönpanon määräaika. Tyhjä tulos on tavallinen (direktiivejä annetaan vain muutamia kuukaudessa)."""
    since = (now().date() - datetime.timedelta(days=days)).isoformat()
    res = _sparql(DIR_SPARQL % since)
    other = {}
    if res:
        vals = " ".join(sorted({f'"{b["celex"]["value"]}"^^xsd:string' for b in res}))
        for lang in ("SWE", "ENG"):
            try:
                q = ("PREFIX cdm: <http://publications.europa.eu/ontology/cdm#> PREFIX xsd: <http://www.w3.org/2001/XMLSchema#> "
                     "SELECT DISTINCT ?celex ?title WHERE { VALUES ?celex { %s } ?w cdm:resource_legal_id_celex ?celex . "
                     "?e cdm:expression_belongs_to_work ?w ; cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/%s> ; "
                     "cdm:expression_title ?title . }") % (vals, lang)
                other[lang] = {b["celex"]["value"]: b["title"]["value"] for b in _sparql(q)}
            except Exception:
                other[lang] = {}
    out, seen = [], set()
    for b in res:
        celex = b["celex"]["value"]
        if celex in seen:
            continue
        seen.add(celex)
        title = " ".join(b["title"]["value"].split())
        num = re.search(r"\(EU\)\s*(\d{4}/\d+)", title)
        tunnus = f"Direktiivi (EU) {num.group(1)}" if num else celex
        laatija = ("komissio" if re.match(r"(?i)komission", title) else
                   "EP ja neuvosto" if re.match(r"(?i)euroopan parlamentin ja neuvoston", title) else
                   "neuvosto" if re.match(r"(?i)neuvoston", title) else "")
        g = lambda k: (b.get(k, {}).get("value") or "")[:10] or None
        hyv, pub, eif, tr = g("date"), g("pub"), g("eif"), g("trans")
        kuv = f"Annettu {_pvm_fi(hyv) if hyv else '?'}; julkaistu EUVL:ssä {_pvm_fi(pub) if pub else '?'}"
        if eif:
            kuv += f"; voimaan {_pvm_fi(eif)}"
        if tr:
            kuv += f"; täytäntöönpano viimeistään {_pvm_fi(tr)}"
        out.append({"kanava": "eu", "url": eurlex_url(celex), "otsikko": title[:300], "julkaistu": pub,
                    "kuvaus": f"{kuv}. Laatija: {laatija or '?'}.", "tunnus": tunnus, "celex": celex, "laatija": laatija,
                    "hyvaksytty": hyv, "julkaistu_euvl": pub, "voimaantulo": eif, "taytantoonpano": tr,
                    "eli": f"https://eur-lex.europa.eu/eli/{'dir_impl' if 'TÄYTÄNTÖÖNPANODIREKTIIVI' in title.upper() else 'dir_del' if 'DELEGOITU' in title.upper() else 'dir'}/{num.group(1)}/oj" if num else None,
                    "otsikko_sv": " ".join(other.get("SWE", {}).get(celex, "").split())[:300] or None,
                    "otsikko_en": " ".join(other.get("ENG", {}).get(celex, "").split())[:300] or None,
                    "vaihe": "Julkaistu EUVL:ssä", "valmis": True})
    out.sort(key=lambda x: (0 if x["laatija"] != "komissio" else 1, "".join(chr(255 - ord(c)) for c in x["julkaistu"] or "")))
    return out


ADOPT_RE = re.compile(r"(?i)\b(adopts?|adopted|adoption|final (green )?light|final approval|formally approve[sd]?|signs? off|gives? (its )?green light)\b")


ADOPT_NOT = re.compile(r"(?i)conclusions|mandate|general approach|negotiating position|sanction|restrictive measures|statement|remarks|declaration|budget")


def src_neuvosto():
    """Neuvoston lopulliset hyväksymispäätökset (Council of the EU, lehdistötiedotteiden RSS): säädös on hyväksytty, mutta
    ei vielä julkaistu virallisessa lehdessä. Sivut torjuvat skriptin (403), joten tiedote luetaan WebFetchillä."""
    t = get_text("https://www.consilium.europa.eu/en/rss/pressreleases.ashx", timeout=40)
    items = re.findall(r"(?s)<item>(.*?)</item>", t)
    if not items:
        raise RuntimeError("RSS-syötteessä ei ole kohteita (rakenne muuttunut?)")
    out = []
    for it in items:
        tag = lambda n: clean((re.search(rf"(?s)<{n}[^>]*>(.*?)</{n}>", it) or [None, ""])[1])
        title, link, desc = tag("title"), tag("link"), tag("description")
        upd = tag("a10:updated") or tag("pubDate")
        if not link or not ADOPT_RE.search(title) or ADOPT_NOT.search(title):
            continue
        txt = f"{title} {desc}"
        out.append({"kanava": "eu", "url": link, "otsikko": title, "julkaistu": to_hki(upd) if re.match(r"\d{4}-", upd) else None,
                    "kuvaus": desc[:400], "direktiivi": bool(re.search(r"(?i)directive", txt)),
                    "asetus": bool(re.search(r"(?i)regulation", txt)), "vaihe": "Hyväksytty neuvostossa", "valmis": True,
                    "ohje": "Lue tiedote WebFetchillä (consilium.europa.eu torjuu skriptin)."})
    return out



# ---------------------------------------------------------------- uudet lähteet 10/2026: yrityskaupat, PeVL, EU-asetukset, KVL, lautakunnat, EU-kilpailu
def _plain(h):
    """HTML -> yksi tekstirivi (skriptit ja tyylit pois)."""
    h = re.sub(r"(?is)<(script|style|noscript|svg)\b[^>]*>.*?</\1>", " ", h)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", h)).split())


def _after(txt, label, n=200, stop=None):
    """Teksti otsakkeen jälkeen seuraavaan otsakkeeseen (stop) tai n merkkiin asti."""
    i = txt.find(label)
    if i < 0:
        return ""
    seg = txt[i + len(label):i + len(label) + n]
    if stop:
        j = min([seg.find(s) for s in stop if seg.find(s) > 0] or [len(seg)])
        seg = seg[:j]
    return seg.strip(" :")


def _kkv_tunnus(slug):
    """kkv-1410-14-00-10-2026 -> KKV/1410/14.00.10/2026"""
    m = re.match(r"^kkv-(\d+)-(\d+)-(\d+)-(\d+)-(\d{4})$", slug)
    return f"KVV/{m.group(1)}/{m.group(2)}.{m.group(3)}.{m.group(4)}/{m.group(5)}".replace("KVV", "KKV") if m else slug


def src_kkv_yrityskaupat():
    """KKV:n yrityskauppavalvonta: ratkaistut yrityskaupat (hyväksyminen sellaisenaan tai ehdollisena, kielto, raukeaminen)
    päätöslistalta sekä vireillä olevat yrityskaupat (kuuleminen)."""
    out = []
    h = get_text("https://www.kkv.fi/paatokset/kilpailuasiat/yrityskauppavalvonta/")
    for m in re.finditer(r'<h2[^>]*><a href="(https://www\.kkv\.fi/paatokset/kilpailuasiat/yrityskauppavalvonta/([^/"]+)/)"[^>]*>(.*?)</a></h2>(.*?)(?=<h2|$)', h, re.S):
        url, slug, title, meta = m.group(1), m.group(2), _plain(m.group(3)), m.group(4)
        dt = re.search(r'datetime="?(\d{4}-\d{2}-\d{2})', meta)
        laji = re.search(r'<span class="?entry__meta-info"?>\s*([^<]{4,80}?)\s*</span>', meta)
        out.append({"kanava": "yrityskaupat", "url": url, "otsikko": title, "julkaistu": dt.group(1) if dt else None,
                    "tunnus": _kkv_tunnus(slug), "laji": (laji.group(1).strip() if laji else "päätös"), "vaihe": "päätös"})
    h2 = get_text("https://www.kkv.fi/paatokset/vireilla-olevat-yrityskaupat/")
    for m in re.finditer(r'<a href="(https://www\.kkv\.fi/paatokset/vireilla-olevat-yrityskaupat/([^/"]+)/)"[^>]*>(.*?)</a>', h2, re.S):
        url, slug, title = m.group(1), m.group(2), _plain(m.group(3))
        if not title or title.lower().startswith("lue lisää"):
            continue
        kuul = re.search(r"kuuleminen (\d{1,2}\.\d{1,2}\.\d{4}) asti", title)
        out.append({"kanava": "yrityskaupat", "url": url, "otsikko": re.sub(r"\s*\(kuuleminen[^)]*\)\s*$", "", title),
                    "tunnus": _kkv_tunnus(slug), "laji": "vireillä" + (f", kuuleminen {kuul.group(1)} asti" if kuul else ""), "vaihe": "vireillä",
                    "kuuleminen": fi_date(kuul.group(1)) if kuul else None, "valmis": True})
    return dedupe(out)


EU_M_SPARQL = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT ?celex ?pub ?title WHERE {
 ?w cdm:resource_legal_id_celex ?celex ; cdm:official-journal-act_date_publication ?pub .
 FILTER(?pub >= "%s"^^xsd:date)
 FILTER(REGEX(STR(?celex), "^5[0-9]{4}M[0-9]+"))
 ?e cdm:expression_belongs_to_work ?w ; cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/FIN> ; cdm:expression_title ?title .
} ORDER BY DESC(?pub) LIMIT 120"""


def src_eu_yrityskaupat(days=8):
    """Komission yrityskauppavalvonta EU:n virallisen lehden C-sarjasta (CELLAR): ennakkoilmoitukset, joissa on suomalainen osapuoli
    (ilmoituksen teksti luetaan ja osapuolen maa tarkistetaan), sekä päätökset (vastustamatta jättäminen, ehdollinen hyväksyminen)
    asioissa, jotka ovat jo LAKI-TV:ssä. Tyhjä tulos on tavallinen."""
    d = SCAN_CTX.get("data") or {}
    known_cases = {re.sub(r"^eu-m-", "M.", it.get("id") or "") for _, it in all_items(d) if str(it.get("id") or "").startswith("eu-m-")}
    known_cases |= {re.sub(r"^eu-m-", "M.", a.get("id") or "") for a in d.get("arkisto", []) if str(a.get("id") or "").startswith("eu-m-")}
    since = (now().date() - datetime.timedelta(days=days)).isoformat()
    res = _sparql(EU_M_SPARQL % since)
    out, seen, reads = [], set(), 0
    for b in res:
        celex, pub, title = b["celex"]["value"], b["pub"]["value"][:10], " ".join(b["title"]["value"].split())
        if celex in seen:
            continue
        seen.add(celex)
        cm = re.search(r"\(Asia (M\.\d+)\s*[–-]\s*(.*?)\)", title)
        case, parties = (cm.group(1), cm.group(2).strip()) if cm else (None, title)
        kind = ("ennakkoilmoitus" if title.startswith("Ennakkoilmoitus") else "hyväksytty" if "vastustamatta" in title else "päätös")
        url = eurlex_url(celex)
        if kind == "ennakkoilmoitus":
            if "(" in celex or reads >= 12:
                continue
            reads += 1
            try:
                t = cellar_text(celex, url, 3000)["teksti"]
            except Exception:
                continue
            osap = re.findall(r"—\s*([^—\n]+?\((?:[^()\n]*?),\s*([^()\n]+)\))", t)   # "— Kesko Oyj (Kesko, Suomi)"
            maat = [m[1].strip() for m in osap]
            if not any(re.search(r"\bSuomi\b|\bFinland\b", x) for x in maat):
                continue
            lines = [l.strip() for l in t.split("\n") if l.strip()]
            i = next((k for k, l in enumerate(lines) if l.startswith("2.")), None)
            kuv = " ".join(lines[i:i + 8]) if i is not None else t[:600]
            out.append({"kanava": "yrityskaupat", "url": url, "otsikko": f"{case} {parties}" if case else title, "julkaistu": pub, "valmis": True,
                        "tunnus": case, "osapuolet": parties, "maat": maat, "laji": "ennakkoilmoitus komissiolle" + (" (yksinkertaistettu menettely)" if "ksinkertaistettu" in title else ""),
                        "kuvaus": kuv[:700], "celex": celex, "id_ehdotus": f"eu-m-{case[2:]}" if case else None})
        elif case and case in known_cases:
            out.append({"kanava": "yrityskaupat", "url": url, "otsikko": f"{case} {parties}", "julkaistu": pub, "valmis": True, "tunnus": case,
                        "osapuolet": parties, "laji": "komissio hyväksyi (vastustamatta jättäminen)" if kind == "hyväksytty" else "komission päätös",
                        "kuvaus": title[:300], "celex": celex, "id_ehdotus": f"eu-m-{case[2:]}", "paivitys": True})
    return out


REG_SPARQL = DIR_SPARQL.replace('"^3[0-9]{4}L[0-9]{4}$"', '"^3[0-9]{4}R[0-9]{4}$"').replace("OPTIONAL { ?w cdm:directive_date_transposition ?tr . }", "OPTIONAL { ?w cdm:resource_legal_date_application ?tr . }").replace("LIMIT 60", "LIMIT 150")


def _titles_lang(celexes, lang):
    """Virallinen nimike toisella kielellä (SWE/ENG) CELEX-tunnuksille."""
    if not celexes:
        return {}
    vals = " ".join(sorted({f'"{c}"^^xsd:string' for c in celexes}))
    q = ("PREFIX cdm: <http://publications.europa.eu/ontology/cdm#> PREFIX xsd: <http://www.w3.org/2001/XMLSchema#> "
         "SELECT DISTINCT ?celex ?title WHERE { VALUES ?celex { %s } ?w cdm:resource_legal_id_celex ?celex . "
         "?e cdm:expression_belongs_to_work ?w ; cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/%s> ; "
         "cdm:expression_title ?title . }") % (vals, lang)
    try:
        return {b["celex"]["value"]: " ".join(b["title"]["value"].split()) for b in _sparql(q)}
    except Exception:
        return {}


def src_eu_asetukset(days=14):
    """Uudet EU-asetukset EU:n virallisessa lehdessä (CELLAR): Euroopan parlamentin ja neuvoston asetukset, neuvoston asetukset ja komission
    delegoidut asetukset. Komission täytäntöönpanoasetukset (polkumyynti, tekniset) jätetään pois."""
    since = (now().date() - datetime.timedelta(days=days)).isoformat()
    res = _sparql(REG_SPARQL % since)
    keep = []
    for b in res:
        title = " ".join(b["title"]["value"].split())
        if re.match(r"(?i)euroopan parlamentin ja neuvoston asetus|neuvoston asetus|komission delegoitu asetus", title):
            keep.append((b, title))
    cel = {b["celex"]["value"] for b, _ in keep}
    sv, en = _titles_lang(cel, "SWE"), _titles_lang(cel, "ENG")
    out, seen = [], set()
    for b, title in keep:
        celex = b["celex"]["value"]
        if celex in seen:
            continue
        seen.add(celex)
        num = re.search(r"\(EU\)\s*(\d{4}/\d+)", title)
        tunnus = f"Asetus (EU) {num.group(1)}" if num else celex
        laatija = ("komissio (delegoitu)" if re.match(r"(?i)komission", title) else "EP ja neuvosto" if re.match(r"(?i)euroopan parlamentin", title) else "neuvosto")
        g = lambda k: (b.get(k, {}).get("value") or "")[:10] or None
        hyv, pub, eif, sov = g("date"), g("pub"), g("eif"), g("trans")
        kuv = f"Annettu {_pvm_fi(hyv) if hyv else '?'}; julkaistu EUVL:ssä {_pvm_fi(pub) if pub else '?'}"
        if eif:
            kuv += f"; voimaan {_pvm_fi(eif)}"
        if sov and sov != eif:
            kuv += f"; sovelletaan {_pvm_fi(sov)}"
        out.append({"kanava": "eu", "url": eurlex_url(celex), "otsikko": title, "otsikko_sv": sv.get(celex), "otsikko_en": en.get(celex),
                    "tunnus": tunnus, "laatija": laatija, "hyvaksytty": hyv, "julkaistu": pub, "julkaistu_euvl": pub, "voimaantulo": eif, "soveltaminen": sov,
                    "eli": f"http://data.europa.eu/eli/reg/{num.group(1).split('/')[0]}/{num.group(1).split('/')[1]}/oj" if num else None,
                    "kuvaus": kuv, "valmis": True, "saados": "asetus"})
    out.sort(key=lambda x: (0 if x["laatija"] != "komissio (delegoitu)" else 1, x.get("julkaistu") or ""), reverse=False)
    return out


def src_kvl(days=14, max_read=8):
    """Keskusverolautakunnan ennakkoratkaisut vero.fi:stä: sivukartta kertoo uudet ja päivittyneet ratkaisusivut (lastmod), joista luetaan tunnus,
    antopäivä, asiasanat, lainvoimaisuus ja lyhennelmän alku."""
    sm = get_text("https://www.vero.fi/sitemap.xml", timeout=90)
    since = (now().date() - datetime.timedelta(days=days)).isoformat()
    urls = [(u, lm) for u, lm in re.findall(r"<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>", sm)
            if "/syventavat-vero-ohjeet/ennakkoratkaisut/" in u and re.search(r"/kvl\d+/?$", u) and lm[:10] >= since]
    urls.sort(key=lambda x: x[1], reverse=True)
    d = SCAN_CTX.get("data") or {}
    known = {norm_url(it.get("lahde")) for _, it in all_items(d)} | {norm_url(a.get("lahde")) for a in d.get("arkisto", [])}
    out = []
    for u, lm in urls:
        if norm_url(u) in known or len(out) >= max_read:
            continue
        try:
            h = get_text(u)
        except Exception:
            continue
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", h, re.S)
        tunnus = _plain(h1.group(1)) if h1 else ""
        body = _plain(h[h1.end():] if h1 else h)
        anto = re.search(r"Antopäivä\s*(\d{1,2}\.\d{1,2}\.\d{4})", body)
        dd = re.search(r"<dt>\s*Avainsanat\s*</dt>\s*<dd>(.*?)</dd>", h, re.S)
        asiasanat = _plain(dd.group(1)) if dd else ""
        lainv = "Ei lainvoimainen" if "Ei lainvoimainen" in body else ("Lainvoimainen" if "Lainvoimainen" in body else None)
        kho = re.search(r"KHO[^.]{0,60}\d{1,2}\.\d{1,2}\.\d{4}[^.]{0,80}\.", body)
        mb = re.search(r'<div class="main-body">(.*?)</article>', h, re.S) or re.search(r"<article[^>]*>(.*?)</article>", h, re.S)
        teksti = _plain(mb.group(1)) if mb else body
        teksti = re.split(r"\s(?:Lainvoimainen|Ei lainvoimainen|Sivu on viimeksi päivitetty)\b", teksti)[0]
        out.append({"kanava": "vero", "url": u, "otsikko": tunnus or u, "tunnus": re.sub(r"^KVL:(\d{4})/(\d+)$", r"KVL:\1/\2", tunnus),
                    "julkaistu": lm[:10], "annettu": fi_date(anto.group(1)) if anto else None, "asiasanat": asiasanat, "lainvoimainen": lainv,
                    "kho": kho.group(0) if kho else None, "kuvaus": teksti[:900], "valmis": True, "paivitys_sivukartassa": lm[:16]})
    return out


def _rss_items(url):
    x = get_text(url)
    out = []
    for it in re.findall(r"<item>(.*?)</item>", x, re.S):
        g = lambda tag: html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", (re.search(r"<%s[^>]*>(.*?)</%s>" % (tag, tag), it, re.S) or [None, ""])[1])).strip()
        link = g("link") or (re.search(r"<link[^>]*/>\s*([^<\s]+)", it) or [None, ""])[1]
        pub = g("pubDate")
        try:
            dt = email.utils.parsedate_to_datetime(pub).astimezone(HKI).strftime("%Y-%m-%dT%H:%M") if pub else None
        except Exception:
            dt = None
        out.append({"url": link.strip(), "otsikko": g("title"), "julkaistu": dt})
    return out


def _lautakunta_page(u):
    """Lautakunnan ratkaisusivu (WordPress): antopäivä, diaarinumero, asiasanat, lainvoimaisuus, täysistunto ja selostuksen alku."""
    h = get_text(u)
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", h, re.S)
    body = _plain(h[h1.end():] if h1 else h)
    anto = re.search(r"Antopäivä\s*(\d{1,2}\.\d{1,2}\.\d{4})", body)
    return {"annettu": fi_date(anto.group(1)) if anto else None, "diaari": _after(body, "Diaarinumero", 40, stop=[" Aihe", " Syrjintä", " Asiasanat", " Täysistunto", " Antopäivä", " Lainvoima"]),
            "asiasanat": _after(body, "Asiasanat", 300, stop=[" Asiaselostus", " Lainvoimaisuus", " Hakija", " Kuluttaja", " Lautakunnan"]),
            "taysistunto": bool(re.search(r"Täysistuntopäätös\s*Kyllä", body)),
            "lainvoimainen": "Ei lainvoimainen" if "Ei lainvoimainen" in body else ("Lainvoimainen" if re.search(r"Lainvoimaisuus\s*Lainvoimainen", body) else None),
            "kuvaus": re.sub(r"^.*?(Asiaselostus|Lainvoimaisuus\s+\S+\s+\S+)\s*", "", body[:2500], count=1)[:900]}


def src_lautakunta(feed, kanava, elin, max_read=6, vain_taysistunto=False):
    """Yhdenvertaisuus- ja tasa-arvolautakunta ja kuluttajariitalautakunta: RSS-syöte + ratkaisusivun metatiedot."""
    d = SCAN_CTX.get("data") or {}
    known = {norm_url(it.get("lahde")) for _, it in all_items(d)} | {norm_url(a.get("lahde")) for a in d.get("arkisto", [])}
    seen = set(d.get("_nahty") or [])
    out, reads = [], 0
    for x in _rss_items(feed):
        if not x["url"]:
            continue
        x.update({"kanava": kanava, "elin": elin, "valmis": True})
        if norm_url(x["url"]) in known or url_hash(x["url"]) in seen or reads >= max_read:
            out.append(x)   # nähty tai luettu jo: pelkkä otsikko riittää (karsitaan scanissa)
            continue
        reads += 1
        try:
            x.update(_lautakunta_page(x["url"]))
        except Exception as e:
            x["virhe"] = str(e)[:80]
        out.append(x)
    if vain_taysistunto:
        out = [x for x in out if x.get("taysistunto") or norm_url(x["url"]) in known or url_hash(x["url"]) in seen]
    return out


def src_eu_kilpailu():
    """Komission kilpailu- ja valtiontukitiedotteet (presscorner-haku: uusimmat tiedotteet, otsikosta suodatettuna)."""
    out = []
    for page in (0, 1):
        try:
            data = json.loads(get_text(f"https://ec.europa.eu/commission/presscorner/api/search?language=en&pagesize=100&pagenumber={page}", accept="application/json"))
        except Exception:
            break
        for x in data.get("docuLanguageListResources") or []:
            title = " ".join((x.get("title") or "").split())
            if not re.search(r"(?i)^(antitrust|mergers?|state aid|cartel|competition)\b|\b(antitrust|state aid|cartel|fines? .{0,40}(competition|antitrust)|clears (the )?acquisition|prohibits (the )?acquisition|merger)\b", title):
                continue
            if re.match(r"(?i)daily news|mergers?: commission (clears|approves) acquisition", title) and not re.search(r"(?i)finland|finnish", title):
                continue   # yksinkertaistetut hyväksynnät ilman Suomi-kytköstä eivät ole juttuja
            ref = (x.get("refCode") or "").replace("/", "_").lower()
            url = f"https://ec.europa.eu/commission/presscorner/detail/en/{ref}" if ref else None
            if not url:
                continue
            kan = "yrityskaupat" if re.match(r"(?i)mergers?", title) else "kilpailu"
            out.append({"kanava": kan, "url": url, "otsikko": title, "julkaistu": (x.get("eventDate") or "")[:10] or None,
                        "kuvaus": " ".join((x.get("leadText") or "").split())[:400], "elin": "Euroopan komissio", "valmis": True})
        if len(data.get("docuLanguageListResources") or []) < 100:
            break
    return dedupe(out)


ZERO_OK = {"EU-DIR", "NEUVOSTO", "HE", "EU-YK", "EU-ASETUS", "KVL", "YVTLTK", "KRIL", "EU-KILPAILU", "SAADOSKOKOELMA", "KKO-TIED", "KHO-TIED", "SYYTTAJA", "EU-EHDOTUS"}   # lähteet, joilla tyhjä tulos on tavallinen (HE: vain uudet esitykset edellisen ajon jälkeen): ei LÄHDE HILJAA -hälytystä


# ---------------------------------------------------------------- Säädöskokoelma: vahvistetut lait ja asetukset
def src_saadoskokoelma(max_new=40):
    """Uudet säädökset Finlexin avoimesta datasta: numeroita tutkitaan tunnetusta (suurin data.jsonin säädösnumero) eteenpäin,
    kunnes 20 peräkkäistä puuttuu. Juttu syntyy vahvistamishetkellä ('laki vahvistettu, voimaan p.k.vvvv')."""
    d = SCAN_CTX.get("data") or {}
    year = now().year
    known = {int(d.get("_sk_viimeisin") or 0)} if str(d.get("_sk_viimeisin") or "").split("/")[-1] == str(year) or isinstance(d.get("_sk_viimeisin"), int) else set()
    for v in d.get("voimaantulot", []) + d.get("vt_arkisto", []):
        for sa in [v.get("saados")] + list(v.get("_saadokset") or []):
            m = re.match(r"^(\d+)/(\d{4})$", sa or "")
            if m and int(m.group(2)) == year:
                known.add(int(m.group(1)))
    for _, it in all_items(d):
        m = re.match(r"^(\d+)/(\d{4})$", it.get("tunnus") or "")
        if m and int(m.group(2)) == year:
            known.add(int(m.group(1)))
    known.discard(0)
    if not known:
        return []   # ensimmäinen ajo ilman vertailukohtaa: vt-update tuottaa numerot, seuraava ajo jatkaa niistä
    start, out, n, misses, errors = max(known), [], max(known) + 1, 0, 0
    with ThreadPoolExecutor(8) as ex:
        while misses < 20 and len(out) < max_new and errors < 20 and n < start + 400:
            batch = list(range(n, n + 16))
            for nn, r in zip(batch, ex.map(lambda k: statute(k, year), batch)):
                if r:
                    misses = 0
                    out.append({"kanava": "he", "url": r["lahde"], "tunnus": r["saados"], "otsikko": r["nimi"], "julkaistu": r["julkaistu"] or r["annettu"],
                                "annettu": r["annettu"], "voimaantulo": r["voimaan"], "he": r["he"], "tyyppi": r["tyyppi"], "muutossaados": r["muutossaados"],
                                "kuvaus": r["teksti"][:700], "laji": "vahvistettu " + r["tyyppi"], "valmis": True})
                elif r is False:
                    errors += 1
                else:
                    misses += 1
            n += 16
    if out:
        SCAN_CTX["sk_viimeisin"] = max(int(x["tunnus"].split("/")[0]) for x in out)
    out.sort(key=lambda x: int(x["tunnus"].split("/")[0]), reverse=True)
    return out


def statute_text(n, year, url, maxc):
    """Säädöksen teksti Finlexin avoimesta datasta (finlex.fi:n sivu rakentuu selaimessa)."""
    r = statute(n, year)
    if not r:
        raise ValueError("säädöstä ei löydy avoimesta datasta")
    t = r["teksti"]
    out = {"url": url, "otsikko": r["nimi"], "julkaistu": r["julkaistu"], "annettu": r["annettu"], "voimaantulo": r["voimaan"], "he": r["he"],
           "lahde_teksti": f"https://opendata.finlex.fi/finlex/avoindata/v1/akn/fi/act/statute/{year}/{n}/fin@"}
    out["teksti"] = t[:maxc] + (f"\n[… katkaistu, yhteensä {len(t)} merkkiä]" if len(t) > maxc else "")
    return out


# ---------------------------------------------------------------- Tiedotteet (WordPress-RSS): tuomioistuimet, KKO, KHO, syyttäjä
TIEDOTE_SKIP = re.compile(r"(?i)avoim\w* ov|viikkotiedote|viikolla \d+ antamia|ratkaisuja$|ilmoittautuminen|rekrytoi|haettavana|nimitet|nimitt|"
                          r"virkasuhtee|virkaan\b|utnämn|utsedd|toimintakertomus|verksamhetsberättelse|puhe\b|tal på|on uudistunut|har förnyats|ruuhka|"
                          r"aukioloaj|asiakaspalvelu|käyntiasiointi|asiointi\b|toimipist|tuomaripäiv|seminaari|webinaari|vierail|tutustumis|harjoittelu|"
                          r"kesätyö|\bsome\b|sosiaalisessa mediassa|tiedonsaantioikeus|tilastot|vuosikertomus|strategia")
SV_EN_TITLE = re.compile(r"(?i)^(the|a|an|court|supreme|högsta|hovrätt|domstol|marknads|arbets|förvaltnings|utlåtande|kompletterande|misstank|"
                         r"undersökningsled|pressmeddelande|åklagar|förundersökn|tingsrätt)|\b(domstolen|rätten|dom i|beslut|ärende|åtal|"
                         r"judgement|judgment|ruling|decision|appeal|prosecut)\b")
COURT_NAMES = [("hallinto-oikeu", "hao"), ("hovioikeu", "muut"), ("käräjäoikeu", "muut"), ("markkinaoikeu", "muut"), ("työtuomioistui", "muut"),
               ("vakuutusoikeu", "muut"), ("korkein hallinto-oikeus", "kho"), ("korkein oikeus", "kko")]
COURT_STEM = {"hallinto-oikeu": "hallinto-oikeus", "hovioikeu": "hovioikeus", "käräjäoikeu": "käräjäoikeus", "markkinaoikeu": "markkinaoikeus",
              "työtuomioistui": "työtuomioistuin", "vakuutusoikeu": "vakuutusoikeus"}


def _court_name(text):
    """Tuomioistuimen nimi nominatiivissa tekstistä, esim. 'Itä-Uudenmaan käräjäoikeuden' -> 'Itä-Uudenmaan käräjäoikeus'."""
    ms = list(re.finditer(r"(?:([A-ZÅÄÖ][\w-]+n(?: ja [A-ZÅÄÖ][\w-]+n)?)\s+)?([Hh]allinto-oikeu|[Hh]ovioikeu|[Kk]äräjäoikeu|[Mm]arkkinaoikeu|[Tt]yötuomioistui|[Vv]akuutusoikeu)\w*", text or ""))
    if not ms:
        return None
    m = next((m for m in ms if m.group(1) and m.group(1).lower() not in ("suomen",)), ms[0])   # nimen kanssa ("Vaasan hallinto-oikeus") ennen yleisnimeä
    pre = (m.group(1) + " ") if m.group(1) and m.group(1).lower() not in ("suomen",) else ""
    stem = COURT_STEM[m.group(2).lower()]
    return (pre + stem) if pre else stem[0].upper() + stem[1:]


def _tiedote_page(u):
    """Tiedotesivun (WordPress) leipäteksti ja julkaisupäivä."""
    h = get_text(u)
    m = page_meta(u, html_=h)
    body = main_text(h)
    body = re.sub(r"^\s*(Julkaistu|Tiedote)\s*\d{1,2}\.\d{1,2}\.\d{4}\s*", "", body)
    return {"kuvaus": " ".join(body.split())[:1200], "julkaistu_sivu": m.get("julkaistu")}


def src_tiedotteet(feed, kanava, elin=None, max_read=8, skip=TIEDOTE_SKIP):
    """Viranomaisen tiedotteet RSS-syötteestä: otsikko, julkaisuaika ja sivun teksti. Ruotsin- ja englanninkieliset
    rinnakkaisversiot sekä rutiini (avoimet ovet, nimitykset, viikkotiedotteet) karsitaan."""
    d = SCAN_CTX.get("data") or {}
    known = {norm_url(it.get("lahde")) for _, it in all_items(d)} | {norm_url(a.get("lahde")) for a in d.get("arkisto", [])}
    seen = set(d.get("_nahty") or [])
    out, reads = [], 0
    for x in _rss_items(feed):
        t = x.get("otsikko") or ""
        if not x["url"] or skip.search(t) or SV_EN_TITLE.search(t) or re.search(r"/(en|sv)/", x["url"]):
            continue
        x.update({"kanava": kanava, "valmis": True})
        if elin:
            x["elin"] = elin
        low = t.lower()
        for key, kan in COURT_NAMES:
            if key in low:
                if kanava == "muut" and kan in ("hao", "kho", "kko"):
                    x["kanava"] = kan
                if not elin:
                    x["elin"] = _court_name(t)
                break
        if norm_url(x["url"]) in known or url_hash(x["url"]) in seen or reads >= max_read:
            out.append(x)
            continue
        reads += 1
        try:
            x.update(_tiedote_page(x["url"]))
            if not elin and " " not in (x.get("elin") or ""):   # otsikosta vain yleisnimi ("Hovioikeus"): tarkempi nimi sivun tekstistä
                name = _court_name(x.get("kuvaus") or "")
                if name and (" " in name or not x.get("elin")):
                    x["elin"] = name
                if kanava == "muut" and "hallinto-oikeus" in (x.get("elin") or ""):
                    x["kanava"] = "hao"
        except Exception as e:
            x["virhe"] = str(e)[:80]
        out.append(x)
    return out


# ---------------------------------------------------------------- Komission lainsäädäntöehdotukset (CELLAR)
COM_SPARQL = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?celex ?date ?rt ?title ?svc WHERE {
 ?w cdm:resource_legal_id_celex ?celex ; cdm:work_date_document ?date ; cdm:work_title ?title ; cdm:work_has_resource-type ?rt .
 OPTIONAL { ?w cdm:resource_legal_service_responsible ?svc }
 FILTER(REGEX(STR(?celex), "^5[0-9]{4}PC[0-9]+$"))
 FILTER(?rt IN (<http://publications.europa.eu/resource/authority/resource-type/PROP_REG>, <http://publications.europa.eu/resource/authority/resource-type/PROP_DIR>))
 FILTER(?date >= "%s"^^xsd:date)
} ORDER BY DESC(?date) LIMIT 60"""


def src_eu_ehdotukset(days=14):
    """Komission ehdotukset uusiksi asetuksiksi ja direktiiveiksi (COM-asiakirjat EU:n julkaisutoimiston avoimesta datasta):
    lainsäädäntöprosessin alkupää. Neuvoston päätösehdotukset ja tiedonannot eivät ole mukana."""
    since = (now().date() - datetime.timedelta(days=days)).isoformat()
    res = _sparql(COM_SPARQL % since)
    rows = {}
    for b in res:
        c = b["celex"]["value"]
        if c in rows:
            continue
        rt = b["rt"]["value"].split("/")[-1]
        rows[c] = {"celex": c, "pvm": b["date"]["value"], "otsikko_en": " ".join(b["title"]["value"].split()),
                   "laji": "asetusehdotus" if rt == "PROP_REG" else "direktiiviehdotus", "paaosasto": (b.get("svc") or {}).get("value") or ""}
    if not rows:
        return []
    fi, sv = _titles_lang(list(rows), "FIN"), _titles_lang(list(rows), "SWE")
    out = []
    for c, r in rows.items():
        m = re.match(r"^5(\d{4})PC(\d+)$", c)
        tunnus = f"COM({m.group(1)}) {int(m.group(2))}"
        ehd = fi.get(c) or ""
        out.append({"kanava": "eu", "url": f"https://eur-lex.europa.eu/legal-content/FI/TXT/?uri=CELEX:{c}", "celex": c, "tunnus": tunnus,
                    "otsikko": ehd or r["otsikko_en"], "otsikko_fi_saatavilla": bool(ehd), "otsikko_sv": sv.get(c) or "", "otsikko_en": r["otsikko_en"],
                    "pvm": r["pvm"], "julkaistu": r["pvm"], "laji": r["laji"], "paaosasto": r["paaosasto"], "laatija": "Euroopan komissio",
                    "id_ehdotus": f"com-{m.group(1)}-{int(m.group(2))}", "valmis": True})
    out.sort(key=lambda x: x["pvm"], reverse=True)
    return out


SOURCES = {
    "KKO": src_kko,
    "KHO": src_kho,
    "OKV": lambda: src_finlex_auth("laillisuus", "oikeuskansleri"),              # oikeuskansleri.fi torjuu haut -> Finlex
    "EOA": lambda: src_finlex_auth("laillisuus", "eduskunnan-oikeusasiamies", "EOAK/"),   # oikeusasiamies.fi torjuu haut -> Finlex
    "KKV": src_kkv,
    "TSV-Finlex": src_finlex_tsv,
    "TT": lambda: src_archive("muut", "https://www.tyotuomioistuin.fi/ratkaisut/", r"/ratkaisujen-arkisto/[^/]+/$"),
    "MAO": lambda: src_archive("muut", "https://www.markkinaoikeus.fi/ratkaisut/", r"/ratkaisujen-arkisto/mao[^/]+/$"),
    "HAO": lambda: src_archive("hao", "https://www.tuomioistuimet.fi/tuomioistuinten-ratkaisut/hallinto-oikeuksien-ratkaisut/",
                               r"/ratkaisut/[a-z-]+-hao-[^/]+/$"),
    "HE": src_eduskunta_he,        # valtioneuvosto.fi torjuu haut -> eduskunnan avoin data (kaikki annetut esitykset)
    "LAUSUNNOT": src_hankeikkuna,  # lausuntokierrokset Hankeikkunan rajapinnasta (lausuntopalvelu.fi torjuu haut)
    "FIVA": src_fiva,
    "ICJ": src_icj,
    "EIT": src_hudoc,
    "EUT": src_curia,
    "HO": lambda: src_tuomioistuimet("https://www.tuomioistuimet.fi/tuomioistuinten-ratkaisut/hovioikeuksien-ratkaisut/",
                                     r"^[A-ZÅÄÖa-zåäö]*HO:20\d\d:\d+$"),
    "VakO": lambda: src_tuomioistuimet("https://www.tuomioistuimet.fi/tuomioistuinten-ratkaisut/vakuutusoikeuden-ratkaisut/",
                                       r"^VakO \d+:20\d\d$"),
    "EDPB": src_edpb,
    "EU-DIR": src_eu_direktiivit,   # uudet direktiivit EU:n virallisessa lehdessä (julkaisuhetki)
    "NEUVOSTO": src_neuvosto,       # neuvoston lopullinen hyväksyminen (hyväksymishetki, ennen julkaisua)
    "KKV-YK": src_kkv_yrityskaupat, # KKV:n yrityskauppapäätökset ja vireillä olevat yrityskaupat
    "EU-YK": src_eu_yrityskaupat,   # komission yrityskauppavalvonta EUVL:n C-sarjasta: suomalainen osapuoli
    "EU-ASETUS": src_eu_asetukset,  # uudet EU-asetukset EUVL:ssä (EP ja neuvosto, neuvosto, komission delegoidut)
    "KVL": src_kvl,                 # keskusverolautakunnan ennakkoratkaisut (vero.fi)
    "YVTLTK": lambda: src_lautakunta("https://www.yvtltk.fi/feed/rss-feed?post_type=tapausseloste", "muut", "Yhdenvertaisuus- ja tasa-arvolautakunta"),
    "KRIL": lambda: src_lautakunta("https://www.kuluttajariita.fi/feed/rss-feed?post_type=paatos", "muut", "Kuluttajariitalautakunta", vain_taysistunto=True),
    "EU-KILPAILU": src_eu_kilpailu, # komission kilpailu- ja valtiontukitiedotteet
    "SAADOSKOKOELMA": src_saadoskokoelma,   # vahvistetut lait ja asetukset Finlexin avoimesta datasta (vahvistamishetki)
    "TUOMIOISTUIMET": lambda: src_tiedotteet("https://www.tuomioistuimet.fi/ajankohtaista/tiedotteet/feed/", "muut"),   # käräjä- ja hovioikeuksien tiedotteet
    "KKO-TIED": lambda: src_tiedotteet("https://www.korkeinoikeus.fi/feed/rss-feed?post_type=ajankohtaiset", "kko", "Korkein oikeus"),   # valitusluvat, lausunnot
    "KHO-TIED": lambda: src_tiedotteet("https://www.kho.fi/feed/rss-feed?post_type=ajankohtaiset", "kho", "Korkein hallinto-oikeus"),
    "SYYTTAJA": lambda: src_tiedotteet("https://www.syyttajalaitos.fi/feed/rss-feed?post_type=ajankohtaiset", "muut", "Syyttäjälaitos"),   # syyteharkintaratkaisut
    "EU-EHDOTUS": src_eu_ehdotukset,       # komission asetus- ja direktiiviehdotukset (lainsäädäntöprosessin alku)
}
OWN_WINDOW = {"EU-DIR", "EU-ASETUS", "EU-YK", "KVL", "EU-EHDOTUS", "SAADOSKOKOELMA"}   # lähde rajaa aikaikkunan itse (CELLAR 8–21 pv, vero.fi:n sivukartta 14 pv) ja julkaisupäivä on
                                                      # päivän tarkkuudella; metatiedot voivat tulla päiviä julkaisun jälkeen, joten scanin since-raja ei karsi
                                                      # näitä – toiston estää nähdyt-luettelo (_nahty) ja tunnettujen lähteiden joukko
SOURCE_BASE = {"OKV": "finlex", "EOA": "finlex"}   # lähteen perusta vaihtui: linkkimäärän historia aloitetaan alusta (ei väärää HILJAA-hälytystä)
PER_SOURCE = {"HAO": 10, "HE": 20, "LAUSUNNOT": 20, "TT": 6, "MAO": 6, "EIT": 10, "ICJ": 8, "EUT": 40, "HO": 8, "VakO": 8, "EDPB": 10, "EU-DIR": 20, "NEUVOSTO": 10,
              "KKV-YK": 12, "EU-YK": 10, "EU-ASETUS": 15, "KVL": 8, "YVTLTK": 6, "KRIL": 6, "EU-KILPAILU": 10,
              "SAADOSKOKOELMA": 25, "TUOMIOISTUIMET": 10, "KKO-TIED": 8, "KHO-TIED": 8, "SYYTTAJA": 8, "EU-EHDOTUS": 12}


def cmd_scan(p, hours=None, include_seen=False):
    d = load(p)
    upd = as_dt((d.get("paivitetty") or "")[:16]) if d.get("paivitetty") else None
    if hours is None:
        since = min(now() - datetime.timedelta(hours=48), (upd or now()) - datetime.timedelta(hours=12))
    else:
        since = now() - datetime.timedelta(hours=hours)
    known = {norm_url(it.get("lahde")) for _, it in all_items(d)} | {norm_url(x.get("lahde")) for x in d.get("arkisto", [])}
    seen = set(d.get("_nahty") or [])
    found, errors = [], {}
    stats = d.setdefault("_lahteet", {})   # lähdevahti: linkkimäärä ja viimeisin onnistuminen lähteittäin
    for k in [k for k in stats if k not in SOURCES]:   # poistuneet lähteet (esim. tietosuoja.fi, VN) eivät jää tilasivulle VANHA-merkinnällä
        del stats[k]
    SCAN_CTX["data"] = d
    quiet = []

    def run(name):
        try:
            return name, SOURCES[name](), None
        except Exception as e:
            return name, [], f"{type(e).__name__}: {str(e)[:80]}"
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(run, SOURCES))
    todo = []
    for name, lst, err in results:
        st = stats.setdefault(name, {"hist": []})
        if SOURCE_BASE.get(name) and st.get("perusta") != SOURCE_BASE[name]:
            st["hist"], st["perusta"] = [], SOURCE_BASE[name]
            st.pop("hiljaa", None)
        if err:
            errors[name] = err
            st["virhe"] = f"{now():%Y-%m-%dT%H:%M} {err[:60]}"
        else:
            st["aika"] = now().strftime("%Y-%m-%dT%H:%M"); st["n"] = len(lst); st.pop("virhe", None)
            hist = [h for h in st.get("hist", []) if isinstance(h, int)]
            typical = sorted(hist)[len(hist) // 2] if hist else None
            if name not in ZERO_OK and (len(lst) == 0 or (typical and len(lst) < typical / 2)):
                quiet.append(f"{name} {len(lst)} linkkiä (tavallisesti {typical if typical is not None else '?'})")
                st["hiljaa"] = now().strftime("%Y-%m-%dT%H:%M")
            else:
                st.pop("hiljaa", None)
            st["hist"] = (hist + [len(lst)])[-10:]
        for x in lst[:PER_SOURCE.get(name, 8)]:
            if norm_url(x["url"]) in known or (not include_seen and url_hash(x["url"]) in seen):
                continue
            x["lahde_nimi"] = name
            todo.append(x)

    def enrich(x):
        if x.get("valmis") or x["url"].endswith(".pdf") or "hudoc" in x["url"] or "curia.europa.eu" in x["url"] or blocked_host(x["url"]):
            return x   # rajapinnasta saadut tiedot ovat valmiit; torjuvia palvelimia ei yritetä lukea
        try:
            m = page_meta(x["url"])
            x["otsikko"] = (m["otsikko"] or x.get("otsikko") or "").split(" | ")[0]
            cands = [v for v in (x.get("julkaistu"), m["julkaistu"]) if v]
            x["julkaistu"] = max(cands, key=lambda v: ("T" in v, v == x.get("julkaistu"))) if cands else None  # tarkin (kellonajallinen) voittaa, RSS ennen sivun metaa
            x["kuvaus"] = m["kuvaus"]
        except Exception as e:
            x["virhe"] = str(e)[:80]
        return x
    with ThreadPoolExecutor(8) as ex:
        todo = list(ex.map(enrich, todo))
    cand = []
    for x in todo:
        dt = as_dt(x.get("julkaistu"))
        if dt is None or dt >= since or x.get("lahde_nimi") in OWN_WINDOW:
            cand.append(x)
    cand.sort(key=lambda x: x.get("julkaistu") or "", reverse=True)
    # tarkistetut linkit merkitään nähdyiksi vasta julkaisussa (stamp): jos ajo kaatuu, ne tulevat uudelleen ehdolle
    d["_nahty_odottaa"] = sorted({url_hash(x["url"]) for x in todo if url_hash(x["url"]) not in seen})
    if SCAN_CTX.get("vaski_id"):
        d["_vaski_id"] = SCAN_CTX["vaski_id"]   # eduskunnan avoin data: seuraava ajo jatkaa tästä (päällekkäisyydellä)
    if SCAN_CTX.get("sk_viimeisin"):
        d["_sk_viimeisin"] = max(int(d.get("_sk_viimeisin") or 0), SCAN_CTX["sk_viimeisin"])   # säädöskokoelma: suurin tutkittu numero
    save(p, d)
    write_text("ehdokkaat.json", json.dumps({"since": since.strftime("%Y-%m-%dT%H:%M"), "virheet": errors, "ehdokkaat": cand}, ensure_ascii=False, indent=1))
    print(f"Tarkistettu {len(todo)} uutta linkkiä {len(SOURCES)} lähteestä; ehdokkaita {len(cand)} (julkaistu {since:%d.%m. %H.%M} jälkeen).")
    for x in cand:
        print(f"- [{x['kanava']}] {x.get('julkaistu') or '?'}  {(x.get('otsikko') or '')[:90]}\n    {x['url']}")
    if errors:
        print("Lähteet, jotka eivät vastanneet (tarkista tarvittaessa WebSearchilla):", ", ".join(f"{k} ({v})" for k, v in errors.items()))
    if quiet:
        print("LÄHDE HILJAA (sivun rakenne on ehkä muuttunut; tarkista lähde WebSearchilla ja lisää jutut käsin):", "; ".join(quiet))


def main_text(h):
    h = re.sub(r"(?is)<(script|style|noscript|svg|nav|header|footer|form|aside)\b[^>]*>.*?</\1>", " ", h)
    m = re.search(r"(?is)<main\b[^>]*>(.*)</main>", h) or re.search(r"(?is)<article\b[^>]*>(.*)</article>", h)
    body = m.group(1) if m else h
    body = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</li>|</div>|</tr>", "\n", body)
    t = html.unescape(re.sub(r"<[^>]+>", " ", body))
    lines = [" ".join(ln.split()) for ln in t.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def cmd_text(url, maxc=6000):
    if "hudoc.echr.coe.int" in url:
        print(json.dumps({"url": url, "ohje": "HUDOC on JavaScript-sovellus: lue tuomion tiivistelmä WebFetchillä EIT:n tiedotteesta tai HUDOCista."}, ensure_ascii=False))
        return
    try:
        print(json.dumps(_text(url, maxc), ensure_ascii=False, indent=1))
    except Exception as e:
        ohje = ("Palvelin torjuu kaikki automaattiset haut (myös WebFetchin). Käytä samaa asiaa Finlexissä, eduskunnan avoimessa datassa "
                "(eduskunta.fi/valtiopaivaasiakirjat/HE+n/vvvv) tai Hankeikkunassa (valtioneuvosto.fi/hanke?tunnus=…), tai WebSearchia."
                if blocked_host(url) else "Palvelin ei päästänyt skriptiä sisään. Lue sivu WebFetch-työkalulla.")
        print(json.dumps({"url": url, "virhe": f"{type(e).__name__}: {str(e)[:80]}", "ohje": ohje}, ensure_ascii=False))


def docx_text(b):
    """Word-asiakirjan (.docx) kappaleet ilman lisäkirjastoja: word/document.xml -> teksti."""
    import zipfile, io
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        x = z.read("word/document.xml").decode("utf-8", "replace")
    paras = re.findall(r"<w:p[ >].*?</w:p>", x, flags=re.S)
    out = [html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<w:tab/>", "\t", p))) for p in paras]
    return "\n".join(l for l in (o.strip() for o in out) if l)


CELLAR_LANG = {"FI": "fin", "SV": "swe", "EN": "eng"}


def cellar_text(celex, url, maxc, lang="FI"):
    """EUR-Lex torjuu skriptin (tyhjä vastaus), joten säädöksen teksti haetaan EU:n julkaisutoimiston CELLAR-palvelusta
    (sama virallinen teksti, XHTML) kielivalinnalla."""
    src = f"https://publications.europa.eu/resource/celex/{celex}"
    req = urllib.request.Request(src, headers={"User-Agent": UA, "Accept": "application/xhtml+xml, text/html;q=0.9",
                                               "Accept-Language": CELLAR_LANG.get(lang, "fin")})
    with _OPENER.open(req, timeout=60) as r:
        b = r.read(MAX_FETCH + 1)
    b = _gunzip(b) if b[:2] == b"\x1f\x8b" else b
    h = decode_body(b, "charset=utf-8")
    h = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?i)<(/p|br|/div|/tr|/h\d)\b[^>]*>", "\n", h)
    t = html.unescape(re.sub(r"<[^>]+>", " ", h))
    t = "\n".join(" ".join(l.split()) for l in t.splitlines())
    t = re.sub(r"\n{2,}", "\n", t).strip()
    t = re.sub(r"^L_\d+\w*\.\d+\.fmx\.xml\s*", "", t)
    m = re.search(r"(?m)^(.*(DIREKTIIVI|ASETUS|PÄÄTÖS|DIREKTIV|FÖRORDNING|BESLUT|DIRECTIVE|REGULATION|DECISION)\b.*)$", t)
    out = {"url": url, "otsikko": m.group(1)[:300] if m else "", "julkaistu": None, "lahde_teksti": src}
    out["teksti"] = t[:maxc] + (f"\n[… katkaistu, yhteensä {len(t)} merkkiä]" if len(t) > maxc else "")
    return out


def presscorner_text(url, maxc):
    """Komission presscorner-sivu on JavaScript-sovellus (sivulla ei ole tekstiä); tiedote luetaan sen omasta
    documents-rajapinnasta (viite ip_26_2178 -> IP/26/2178)."""
    m = re.search(r"/detail/(\w\w)/([a-z]+)_(\d+)_(\d+)", url)
    if not m:
        raise ValueError("presscorner-osoitetta ei tunnistettu")
    lang, ref = m.group(1), f"{m.group(2).upper()}/{m.group(3)}/{m.group(4)}"
    src = f"https://ec.europa.eu/commission/presscorner/api/documents?reference={ref}&language={lang}"
    d = json.loads(fetch(src).decode("utf-8", "replace") or "{}")
    r = d.get("docuLanguageResource") or {}
    h = r.get("htmlContent") or ""
    h = re.sub(r"(?i)<(/p|br|/div|/tr|/h\d|/li)\b[^>]*>", "\n", h)
    t = html.unescape(re.sub(r"<[^>]+>", " ", h))
    t = re.sub(r"\n{2,}", "\n", "\n".join(" ".join(l.split()) for l in t.splitlines())).strip()
    pub = (d.get("publishDate") or r.get("publishDate") or "")[:10] or None
    out = {"url": url, "otsikko": r.get("title") or "", "julkaistu": pub, "lahde_teksti": src}
    out["teksti"] = t[:maxc] + (f"\n[… katkaistu, yhteensä {len(t)} merkkiä]" if len(t) > maxc else "")
    return out


def _text(url, maxc):
    api = api_url_for(url)
    if "ec.europa.eu/commission/presscorner/detail/" in url:
        return presscorner_text(url, maxc)
    if api and api[0] == "he":
        return he_text(api[1], api[2], url, maxc)
    if api and api[0] == "pevl":
        return pevl_text(api[1], api[2], url, maxc)
    if api and api[0] == "sk":
        return statute_text(api[1], api[2], url, maxc)
    if api and api[0] == "ev":
        return ev_text(api[1], api[2], url, maxc)
    if api and api[0] == "hanke":
        return hanke_text(api[1], url, maxc)
    if api and api[0] == "eurlex":
        return cellar_text(api[1], url, maxc, api[2])
    if blocked_host(url):
        raise ValueError("palvelin torjuu automaattiset haut (Cloudflare); käytä Finlexin, eduskunnan tai Hankeikkunan osoitetta")
    out = {"url": url}
    ua = BROWSER_UA if "hudoc" in url else UA
    b = fetch(url, ua=ua)
    if b[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":   # OLE-tiedosto (.msg, .doc): ei luettavaa tekstiä ilman lisäkirjastoja
        raise ValueError("liite on Outlook- tai Word 97 -tiedosto (.msg/.doc), jota ei lueta")
    if b[:4] == b"PK\x03\x04" and (url.lower().endswith(".docx") or b"word/document.xml" in b):
        out["teksti"] = docx_text(b)
    elif b[:5] == b"%PDF-" or url.lower().endswith(".pdf"):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b)
        try:
            out["teksti"] = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True, timeout=60).stdout
        finally:
            os.unlink(f.name)
    else:
        h = decode_body(b, _CTYPE.get(url, ""))
        try:
            out.update(page_meta(url, ua=ua, html_=h))
        except Exception:
            pass
        out["teksti"] = main_text(h)
        if "finlex.fi" in (urllib.parse.urlsplit(url).hostname or "") and len(out["teksti"]) < 1500:
            # Finlexin sivut rakentuvat React-kuormasta; viranomaisratkaisut ovat yleensä vain PDF-liitteenä
            title = (out.get("otsikko") or "").split(" | ")[0].strip()
            doc, pdf = finlex_doc_text(h, title), finlex_pdf_link(h)
            if doc:
                out["teksti"] = doc
            if pdf and len(doc) < 4000:   # ratkaisun koko teksti on PDF-liitteessä; sivulla on enintään tiivistelmä ja asiasanat
                out["pdf"] = pdf
                try:
                    out["teksti"] = (doc + "\n\n[PDF-liite]\n" if doc else "") + _text(pdf, maxc)["teksti"]
                except Exception as e:
                    out["teksti"] = doc + f"\n[PDF-liitettä ei saatu luettua: {str(e)[:60]}]"
    t = out["teksti"]
    out["teksti"] = t[:maxc] + (f"\n[… katkaistu, yhteensä {len(t)} merkkiä]" if len(t) > maxc else "")
    return out


# ---------------------------------------------------------------- lisäys
def check_source(x):
    """Lähde vastaa, ja 'virallinen tiivistelmä' löytyy lähteestä sanatarkasti (ensimmäiset 12 sanaa)."""
    u = x.get("lahde") or ""
    if (urllib.parse.urlsplit(u).hostname or "").lower().endswith("consilium.europa.eu"):
        print(f"HUOM: {x.get('id')}: neuvoston sivut torjuvat skriptin; varmista tiedote WebFetchillä (osoitetta ei tarkistettu).")
        return True
    if blocked_host(u) and not api_url_for(u):
        print(f"HUOM: {x.get('id')}: lähde {urllib.parse.urlsplit(u).hostname} torjuu automaattiset haut, joten osoitetta ei voitu tarkistaa. "
              f"Käytä mieluummin Finlexin osoitetta (oikeuskansleri, oikeusasiamies, tietosuojavaltuutettu) tai eduskunnan/Hankeikkunan osoitetta.")
        return True
    try:
        if u.lower().endswith(".pdf"):
            fetch(u, timeout=40); txt = ""   # PDF: riittää, että lähde vastaa
        else:
            txt = _text(u, 60000)["teksti"]
    except Exception as e:
        print(f"VIRHE: {x.get('id')}: lähde ei vastaa ({str(e)[:60]}); tarkista osoite {u}")
        return False
    if x.get("tekstityyppi") == "virallinen tiivistelmä" and not txt.strip() and not u.lower().endswith(".pdf"):
        print(f"VIRHE: {x.get('id')}: lähteestä ei saatu tekstiä, joten 'virallinen tiivistelmä' ei ole tarkistettavissa; vaihda tekstityypiksi 'tiivistelmä' tai korjaa osoite.")
        return False
    if x.get("tekstityyppi") == "virallinen tiivistelmä" and txt:
        norm = lambda s: re.sub(r"\s+", " ", str(s or "")).strip().lower()
        head = " ".join(norm(x.get("teksti")).split(" ")[:12])
        if head and head not in norm(txt):
            print(f"VIRHE: {x.get('id')}: tekstityyppi on 'virallinen tiivistelmä', mutta tekstin alkua ei löydy lähteestä sanatarkasti. "
                  f"Kopioi tiivistelmä lähteestä tai vaihda tekstityypiksi 'tiivistelmä'.")
            return False
    return True


def cmd_add(p, kanava, item_path):
    if kanava not in CH_KEYS:
        sys.exit(f"Tuntematon kanava {kanava}")
    d = load(p)
    it = load(item_path)
    items = it if isinstance(it, list) else [it]
    lst = d["kanavat"][kanava]
    bad = []
    for x in items:
        x.setdefault("id", x.get("tunnus"))
        x.pop("uusi", None)
        if not julk_ok(x.get("julkaistu")):
            sys.exit(f"VIRHE: {x.get('id')}: julkaistu puuttuu tai väärä (YYYY-MM-DDTHH:MM Helsingin aikaa)")
        if check_source(x) is False:
            bad.append(x["id"])
        prev = next((y for y in lst if y.get("id") == x["id"]), None) or next((y for y in d.get("arkisto", []) if y.get("id") == x["id"]), None)
        # lisatty = milloin juttu tuli LAKI-TV:hen; viikon tärkeimmät (102) ja kalenteri (104) käyttävät sitä
        x.setdefault("lisatty", (prev or {}).get("lisatty") or now().strftime("%Y-%m-%dT%H:%M"))
        lst[:] = [y for y in lst if y.get("id") != x["id"]]
        lst.append(x)
        print(f"{kanava}: lisätty {x['id']} ({x.get('julkaistu')}, paino {x.get('paino')})")
    sort_channel(lst)
    for y in lst[MAX_ITEMS:]:
        print(f"{kanava}: arkistoon vanhin {y['id']}")
    archive_items(d, kanava, lst[MAX_ITEMS:])
    del lst[MAX_ITEMS:]
    prune_archive(d)
    drop_dead_refs(d)
    save(p, d)
    E, _ = validate(d)
    mine = [e for e in E if any(f"/{x['id']}" in e or f" {x['id']} " in f" {e} " or (x.get("tunnus") and x["tunnus"] in e) for x in items)]
    for e in mine:
        print("VIRHE:", e)
    if bad:
        sys.exit(f"VIRHE: lähde ei kelpaa: {', '.join(bad)} (juttu tallennettiin; korjaa lahde tai poista juttu ennen julkaisua)")


# ---------------------------------------------------------------- eduskunta: HE-tila
ABBR = {"lakivaliokunta": "LaV", "perustuslakivaliokunta": "PeV", "hallintovaliokunta": "HaV", "talousvaliokunta": "TaV",
        "ympäristövaliokunta": "YmV", "sosiaali- ja terveysvaliokunta": "StV", "työelämä- ja tasa-arvovaliokunta": "TyV",
        "valtiovarainvaliokunta": "VaV", "sivistysvaliokunta": "SiV", "liikenne- ja viestintävaliokunta": "LiV",
        "maa- ja metsätalousvaliokunta": "MmV", "puolustusvaliokunta": "PuV", "ulkoasiainvaliokunta": "UaV",
        "tulevaisuusvaliokunta": "TuV", "tarkastusvaliokunta": "TrV", "suuri valiokunta": "SuV"}


def _vk(s):
    s = s.strip().lower()
    for k in sorted(ABBR, key=len, reverse=True):
        if s.startswith(k[:-1]):
            return ABBR[k]
    return ""


def _d(s):
    try:
        return datetime.datetime.strptime(s, "%d.%m.%Y").date()
    except Exception:
        return None


def he_status(n, year=None):
    from lxml import etree
    year = year or now().year
    t = f"HE {n}/{year} vp"
    url = "https://avoindata.eduskunta.fi/api/v1/tables/VaskiData/rows?" + urllib.parse.urlencode(
        {"columnName": "Eduskuntatunnus", "columnValue": t, "perPage": 20})
    try:
        data = json.loads(get_text(url, timeout=60))
    except Exception as e:
        return {"he": t, "virhe": str(e)[:80]}
    ln = lambda e: etree.QName(e).localname

    def first(e, name):
        for x in e.iter():
            if isinstance(x.tag, str) and ln(x) == name:
                return (x.text or "").strip()
        return ""
    rows = [dict(zip(data["columnNames"], r)) for r in (data.get("rowData") or [])]
    rows = [r for r in rows if "KasittelytiedotValtiopaivaasia" in r["XmlData"]]
    if not rows:
        return {"he": t, "loytyi": False}
    rows.sort(key=lambda r: r["Created"], reverse=True)
    kv = next((x for r in rows for x in etree.fromstring(r["XmlData"].encode()).iter()
               if isinstance(x.tag, str) and ln(x) == "KasittelytiedotValtiopaivaasia"), None)
    if kv is None:
        return {"he": t, "loytyi": False}
    stage, label, last, com, laws = 1, "Annettu", _d(first(kv, "LaadintaPvmTeksti")), "", []
    for yv in kv:
        if not isinstance(yv.tag, str):
            continue
        if ln(yv) == "YleinenKasittelyvaihe":
            title = first(yv, "OtsikkoTeksti")
            if "aliasia" in title:
                continue
            for tj in yv:
                if not (isinstance(tj.tag, str) and ln(tj) == "ToimenpideJulkaisu"):
                    continue
                dt, tp = _d(first(tj, "TapahtumaPvmTeksti")), first(tj, "ValiotsikkoTeksti")
                vks = [(x.text or "") for x in tj.iter() if isinstance(x.tag, str) and ln(x) == "FraasiValiokuntaTeksti"]
                kok = [(x.text or "") for x in tj.iter() if isinstance(x.tag, str) and ln(x) == "YhteisoTeksti"
                       and ln(x.getparent().getparent()) == "KokousToimija"]
                if title == "Lähetekeskustelu":
                    stage, label = max(stage, 2), label if stage > 2 else "Lähetekeskustelu"
                    if vks and not com:
                        com = _vk(vks[0])
                if title == "Käsittely valiokunnassa" and kok and not com:
                    com = _vk(kok[0])
                if title.startswith("Valiokunnan mietintö") and "mietintö" in tp.lower() and stage < 3:
                    stage, label = 3, "Mietintö"
                if title == "Ensimmäinen käsittely" and stage < 4:
                    stage, label = 4, "1. käsittely"
                if title == "Toinen käsittely" and stage < 5:
                    stage, label = 5, "2. käsittely"
                if title == "Ainoa käsittely" and stage < 5:   # esim. valtiosopimukset: yksi käsittely
                    stage, label = 5, "Ainoa käsittely"
                if title.startswith("Eduskunnan vastaus") and stage < 5:
                    stage, label = 5, "Eduskunnan vastaus"
                if dt and (last is None or dt > last):
                    last = dt
        if ln(yv) == "EduskuntakasittelyPaatosKuvaus":
            for lj in yv:
                if isinstance(lj.tag, str) and ln(lj) == "LakiehdotusJulkaisu":
                    laws.append({"nimi": first(lj, "NimekeTeksti"), "vahvistettu": first(lj, "VahvistusPvmTeksti"),
                                 "saados": first(lj, "SaadoskokoelmaViiteTunnus")})
    vahv = [x for x in laws if x["vahvistettu"]]
    if vahv:
        stage, label = 6, "Vahvistettu"
        dv = max(_d(x["vahvistettu"]) for x in vahv)
        if dv and (last is None or dv > last):
            last = dv
    return {"he": t, "nimi": first(kv, "NimekeTeksti"), "annettu": first(kv, "LaadintaPvmTeksti"), "vaihe": stage,
            "vaihe_nimi": label, "valiokunta": com, "pvm": last.isoformat() if last else None,
            "saadokset": [x["saados"] for x in vahv][:8]}


def he_parts(he):
    m = re.match(r"HE (\d+)/(\d{4})", he or "")
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def cmd_he_update(p):
    d = load(p)
    rows = d.setdefault("he_tila", [])
    have = {r["he"] for r in rows}
    for it in d["kanavat"]["he"]:
        if re.match(r"^HE \d+/\d{4} vp$", it.get("tunnus") or "") and it["tunnus"] not in have:
            rows.append({"he": it["tunnus"], "nimi": "", "vaihe": 1, "vaihe_nimi": "Annettu", "valiokunta": "", "pvm": it.get("pvm")})
            have.add(it["tunnus"])
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda r: he_status(*he_parts(r["he"])), rows))
    changed, missing, errors = 0, [], 0
    for r, s in zip(rows, res):
        if not s.get("vaihe"):
            errors += 1
            continue
        new = {"vaihe": s["vaihe"], "vaihe_nimi": s["vaihe_nimi"], "valiokunta": s["valiokunta"] or r.get("valiokunta", ""),
               "pvm": s["pvm"] or r.get("pvm")}
        if any(r.get(k) != v for k, v in new.items()):
            changed += 1
            print(f"{r['he']}: {r.get('vaihe_nimi')} -> {new['vaihe_nimi']} {new['valiokunta']} {new['pvm']}")
            if new["vaihe"] >= 5 and (r.get("vaihe") or 0) < 5:
                hp = he_parts(r["he"])
                print(f"EDUSKUNTA PÄÄTTI: {r['he']} {r.get('nimi') or s.get('nimi') or ''} ({new['pvm']}) -> lisää juttu he-kanavalle id he-paatos-{hp[0]}-{hp[1]} "
                      f"(tunnus {r['he']}, pvm_selite 'päätös'); eduskunnan vastaus EV päivittää saman jutun myöhemmin.")
            if new["vaihe"] != r.get("vaihe") and r.get("vaihe"):
                # eduskunnassa eilen: vaihemuutokset talteen 14 päiväksi (101, kooste, 720)
                d.setdefault("he_muutokset", []).append({"he": r["he"], "nimi": r.get("nimi", ""), "nimi_sv": r.get("nimi_sv", ""), "nimi_en": r.get("nimi_en", ""),
                    "vanha": r.get("vaihe"), "uusi": new["vaihe"], "valiokunta": new["valiokunta"], "pvm": new["pvm"] or today(), "havaittu": today()})
        r.update(new)
        if not r.get("nimi"):
            missing.append((r["he"], s.get("nimi")))
    c30 = days_ago(30)
    d["he_tila"] = [r for r in rows if not (r.get("vaihe") == 6 and str(r.get("pvm") or "") < c30)]
    save(p, d)
    print(f"HE-tulostaulu: {len(rows)} riviä, {changed} muuttui, {errors} ei vastausta.")
    for he, nimi in missing:
        print(f"ANNA LYHYT NIMI (≤18 merkkiä) riville {he}: {nimi}")


def cmd_he_range(a, b):
    with ThreadPoolExecutor(8) as ex:
        out = [r for r in ex.map(lambda n: he_status(n), range(a, b + 1)) if r.get("vaihe")]
    print(json.dumps(out, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- Finlex: voimaantulot
KK = {"tammikuuta": 1, "helmikuuta": 2, "maaliskuuta": 3, "huhtikuuta": 4, "toukokuuta": 5, "kesäkuuta": 6, "heinäkuuta": 7,
      "elokuuta": 8, "syyskuuta": 9, "lokakuuta": 10, "marraskuuta": 11, "joulukuuta": 12}


def statute(n, year):
    from lxml import etree
    NS = {"a": "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"}
    url = f"https://opendata.finlex.fi/finlex/avoindata/v1/akn/fi/act/statute/{year}/{n}/fin@"
    try:
        root = etree.fromstring(fetch(url, timeout=40))
    except urllib.error.HTTPError as e:
        if e.code in (404, 410):
            return None        # säädöstä ei ole (vielä)
        return False           # palvelinvirhe: ei tietoa
    except Exception:
        return False           # verkkovirhe tai rikkinäinen XML: ei tietoa
    title = " ".join(root.xpath("string(//a:docTitle)", namespaces=NS).split())
    ps = root.xpath("//a:hcontainer[@name='entryIntoForce']//a:p", namespaces=NS)
    txt = " ".join("".join(ps[0].itertext()).split()) if ps else ""
    m = re.search(r"(\d{1,2})\s+päivänä\s+(\w+)\s+(\d{4})", txt)
    pvm = datetime.date(int(m.group(3)), KK[m.group(2)], int(m.group(1))).isoformat() if m and m.group(2) in KK else None
    hm = re.search(r"HE\s*(\d+/\d{4})", etree.tostring(root, encoding="unicode"))
    first = title.split(" ")[0] if title else ""
    issued = root.xpath("string(//a:FRBRWork/a:FRBRdate[@name='dateIssued']/@date)", namespaces=NS) or None
    published = root.xpath("string(//a:FRBRWork/a:FRBRdate[@name='datePublished']/@date)", namespaces=NS) or None
    meta = etree.tostring(root.find(".//a:meta", NS), encoding="unicode") if root.find(".//a:meta", NS) is not None else ""
    tyyppi = "laki" if "type-statute.act" in meta or first == "Laki" or first.endswith("laki") else ("asetus" if "decree" in meta or "asetus" in first.lower() else "muu")
    pre, body = root.find(".//a:preamble", NS), root.find(".//a:body", NS)
    teksti = " ".join(("".join(pre.itertext()) if pre is not None else "").split() + ("".join(body.itertext()) if body is not None else "").split())
    return {"nro": n, "saados": f"{n}/{year}", "nimi": title, "voimaan": pvm, "he": f"HE {hm.group(1)} vp" if hm else None,
            "laki": first == "Laki" or first.endswith("laki"), "tyyppi": tyyppi, "muutossaados": "amending-statute" in meta,
            "annettu": issued, "julkaistu": published, "teksti": teksti,
            "lahde": f"https://www.finlex.fi/fi/lainsaadanto/saadoskokoelma/{year}/{n}"}


def statute_sv(saados):
    """Säädöksen virallinen ruotsinkielinen nimike Finlexin avoimesta datasta (esim. 'Lag om ändring av barnskyddslagen')."""
    from lxml import etree
    try:
        n, y = saados.split("/")
        root = etree.fromstring(fetch(f"https://opendata.finlex.fi/finlex/avoindata/v1/akn/fi/act/statute/{y}/{n}/swe@", timeout=40))
        return " ".join(root.xpath("string(//a:docTitle)", namespaces={"a": "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"}).split())
    except Exception:
        return None


def guess_name(title):
    t = title or ""
    m = re.match(r"^Laki (\S+?)lain (?:.*?)muuttamisesta", t)
    if m:
        return (m.group(1)[0].upper() + m.group(1)[1:] + "laki")[:33]
    m = re.match(r"^Laki (.+?) annetun lain", t)
    if m:
        s = m.group(1)
        s = s[0].upper() + s[1:]
        return s if len(s) <= 33 else s[:32].rsplit(" ", 1)[0]
    m = re.match(r"^(\S*laki)\b", t)
    if m:
        return m.group(1)[:33]
    m = re.match(r"^Laki (.+?)$", t)
    s = (m.group(1) if m else t)
    s = s[0].upper() + s[1:] if s else s
    return s if len(s) <= 33 else s[:32].rsplit(" ", 1)[0]


def scan_statutes(year, known_nums):
    """Hakee vuoden säädökset tunnetusta numerosta alaspäin 400 ja ylöspäin, kunnes 20 peräkkäistä puuttuu.
    Palauttaa (tulokset {nro: tiedot}, lo, top, virheiden määrä)."""
    hi = max(known_nums) if known_nums else 1
    lo = max(1, hi - 400)
    results, errors = {}, 0
    with ThreadPoolExecutor(8) as ex:
        for r in ex.map(lambda n: statute(n, year), range(lo, hi + 1)):
            if r:
                results[r["nro"]] = r
            elif r is False:
                errors += 1
        n, misses = hi + 1, 0
        while misses < 20 and n < hi + 400 and errors < 30:
            batch = list(range(n, n + 16))
            for nn, r in zip(batch, ex.map(lambda k: statute(k, year), batch)):
                if r:
                    results[nn] = r
                    misses = 0
                elif r is False:
                    errors += 1
                else:
                    misses += 1
            n += 16
    return results, lo, (max(results) if results else hi), errors


def cmd_vt_update(p):
    d = load(p)
    t, year = today(), now().year
    end = (now().date() + datetime.timedelta(days=14)).isoformat()
    vt = [v for v in d.get("voimaantulot", []) if v.get("pvm", "") >= t]
    known = set()
    for v in vt:
        known.add(v.get("saados"))
        known.update(v.get("_saadokset", []))
    years = [year - 1, year] if now().month == 1 else [year]   # tammikuussa myös edellisen vuoden loppu (1.1. voimaantulot)
    results, errors, spans = {}, 0, []
    for y in years:
        nums = [int(s.split("/")[0]) for s in known if s and s.endswith(f"/{y}")]
        if y != year and not nums:
            continue
        res, lo, top, err = scan_statutes(y, nums)
        results.update({(y, k): r for k, r in res.items()}); errors += err; spans.append(f"{lo}–{top}/{y}")
    paivat = {}
    for r in results.values():
        if r["voimaan"] and t <= r["voimaan"] <= end:
            k = "lakeja" if r["laki"] else "asetuksia"
            paivat.setdefault(r["voimaan"], {"lakeja": 0, "asetuksia": 0})[k] += 1
    if errors:
        # osa hauista epäonnistui: vanhat päivätiedot säilyvät niiltä päiviltä, joille ei saatu uutta tulosta
        old = {k: v for k, v in (d.get("vt_paivat") or {}).items() if k >= t}
        paivat = {**old, **paivat}
        print(f"VIRHE: Finlex ei vastannut {errors} hakuun; vanhat voimaantulopäivät säilytettiin. Aja vt-update uudelleen.")
    d["vt_paivat"] = dict(sorted(paivat.items()))
    groups = {}
    for r in sorted(results.values(), key=lambda r: r["nro"]):
        if r["laki"] and r["voimaan"] and r["voimaan"] >= t:
            groups.setdefault((r["voimaan"], r["he"] or r["saados"]), []).append(r)
    by_key = {(v["pvm"], v.get("he") or v.get("saados")): v for v in vt}
    added = []
    for (pvm, key), rs in sorted(groups.items()):
        old = by_key.get((pvm, key)) or next((v for v in vt if v["pvm"] == pvm and v.get("saados") in {r["saados"] for r in rs}), None)
        if old:
            if len(rs) > (old.get("lakeja") or 1):
                old["lakeja"] = len(rs)
            continue
        main = rs[0]
        v = {"pvm": pvm, "nimi": guess_name(main["nimi"]), "saados": main["saados"], "he": main["he"], "lahde": main["lahde"],
             "aiheet": [], "lakeja": len(rs), "_auto": True, "_otsikot": [r["nimi"] for r in rs][:6]}
        v["_otsikko_sv"] = statute_sv(main["saados"])  # virallinen ruotsinkielinen nimike nimi_sv:n pohjaksi
        vt.append(v)
        added.append(v)
    vt.sort(key=lambda v: (v["pvm"], -(v.get("lakeja") or 1)))
    d["voimaantulot"] = vt
    save(p, d)
    print(f"Finlex: tarkistettu säädökset {', '.join(spans) or '–'}; vt_paivat: {d['vt_paivat']}")
    print(f"Voimaantulot: {len(vt)} riviä, uusia {len(added)}.")
    for v in added:
        print(f"UUSI {v['pvm']} {v['saados']} {v['he'] or ''} -> nimi '{v['nimi']}' (tarkista nimi ≤33, kirjoita nimi_sv ≤33 ja nimi_en ≤33, lisää aiheet"
              f"{' ja muutos ≤76 + muutos_sv ≤76 + muutos_en ≤76' if v['pvm'] <= days_ago(-30) else ''})\n    {' | '.join(v['_otsikot'][:3])}\n    sv: {v.get('_otsikko_sv')}")
    print("Poista lopuksi kentät _otsikot: python3 lakitv.py tidy data.json")


def cmd_tidy(p):
    d = load(p)
    for v in d.get("voimaantulot", []):
        v.pop("_otsikot", None)
        v.pop("_otsikko_sv", None)
        v.pop("_auto", None)
        if v.get("he") is None:
            v.pop("he", None)
    save(p, d)
    print("OK")


# ---------------------------------------------------------------- tilanne
def cmd_status(p):
    d = load(p)
    n = now()
    print(f"paivitetty {d.get('paivitetty')}  (nyt {n:%Y-%m-%dT%H:%M})")
    for k in CH_KEYS:
        lst = d["kanavat"].get(k, [])
        fresh = sum(1 for it in lst if as_dt(it.get("julkaistu")) and n - as_dt(it["julkaistu"]) <= datetime.timedelta(hours=24))
        newest = max((pub_key(it) for it in lst), default="-")
        print(f"  {k:<11} {len(lst)} juttua, uusin {newest}, alle 24 h: {fresh}")
    vt = d.get("voimaantulot", [])
    print(f"voimaantulot {len(vt)} (lähin {vt[0]['pvm'] if vt else '-'}), vt_paivat {d.get('vt_paivat')}")
    print(f"eu_voimaantulot {len(d.get('eu_voimaantulot', []))}, he_tila {len(d.get('he_tila', []))}, visa {len(d.get('visa', []))}, "
          f"etusivu-nostot {len(d.get('etusivu', []))}, tiedote {d.get('tiedote')!r}")
    print(f"arkisto {len(d.get('arkisto', []))} juttua (35 pv), vt_arkisto {len(d.get('vt_arkisto', []))}")


# ---------------------------------------------------------------- sähköpostikooste
CH_NAMES = {"kko": ("Korkein oikeus", "Högsta domstolen", "Supreme Court"), "eu": ("EU-tuomioistuin", "EU-domstolen", "Court of Justice of the EU"),
            "eit": ("Ihmisoikeustuomioistuin", "Människorättsdomstolen", "European Court of Human Rights"),
            "icj": ("Kansainvälinen tuomioistuin", "Internationella domstolen", "International Court of Justice"),
            "kho": ("Korkein hallinto-oikeus", "Högsta förvaltningsdomstolen", "Supreme Administrative Court"),
            "laillisuus": ("Laillisuusvalvonta", "Laglighetsövervakning", "Oversight of legality"), "hao": ("Hallinto-oikeudet", "Förvaltningsdomstolarna", "Administrative courts"),
            "muut": ("Muut tuomioistuimet ja viranomaiset", "Övriga domstolar och myndigheter", "Other courts and authorities"), "kilpailu": ("Kilpailuoikeus", "Konkurrensrätt", "Competition law"),
            "fiva": ("Finanssivalvonta", "Finansinspektionen", "Financial supervision"), "tsv": ("Tietosuoja", "Dataskydd", "Data protection"),
            "he": ("Eduskunta ja säädökset", "Riksdagen och författningar", "Parliament and legislation"), "lausunnot": ("Lausuntokierrokset", "Remisser", "Consultations"),
            "yrityskaupat": ("Yrityskaupat", "Företagsförvärv", "Mergers and acquisitions"), "vero": ("Verotus", "Beskattning", "Taxation")}
LANGS = ("fi", "sv", "en")
CH_PAGE = {"kko": 200, "eu": 250, "eit": 260, "icj": 270, "kho": 300, "laillisuus": 350, "hao": 400, "muut": 450, "kilpailu": 500, "yrityskaupat": 520, "fiva": 550, "tsv": 600, "vero": 650, "he": 700, "lausunnot": 740}
ARTIFACT_URL = "https://claude.ai/artifact/FzxtiPmCVWQEz2S2vBa7js"
BASE_URL = ARTIFACT_URL   # feed/digest/viikkokatsaus: --base tai LAKITV_BASE vaihtaa osoitteen (esim. oma sivusto)


def set_base(u):
    global BASE_URL
    u = (u or "").strip()
    if u:
        check_url(u, https_only=True)
        BASE_URL = u.rstrip("/") if "/artifact/" in u else u if u.endswith("/") else u + "/"


def page_url(page=None, ident=None):
    """Linkki sivulle tai juttuun: artifaktissa …/ID#p100, sivustolla …/#p100."""
    frag = ("j=" + urllib.parse.quote(ident, safe="")) if ident else ("p" + str(page))
    return f"{BASE_URL}#{frag}"


def file_url(name):
    return f"{BASE_URL}/{name}" if "/artifact/" in BASE_URL else f"{BASE_URL}{name}"
WD_FI, WD_SV, WD_EN = ["ma", "ti", "ke", "to", "pe", "la", "su"], ["må", "ti", "on", "to", "fr", "lö", "sö"], ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
T = {  # käyttöliittymätekstit fi/sv/en
    "aamu_otsikko": ("LAKI-TV aamukooste", "LAKI-TV morgonsammandrag", "LAKI-TV morning digest"),
    "viikko_otsikko": ("LAKI-TV viikon tärkeimmät", "LAKI-TV veckans viktigaste", "LAKI-TV top of the week"),
    "heti_otsikko": ("LAKI-TV: tärkeä uusi ratkaisu", "LAKI-TV: viktigt nytt avgörande", "LAKI-TV: major new ruling"),
    "karki": ("PÄIVÄN KÄRKI", "DAGENS TOPP", "TOP OF THE DAY"), "uudet": ("UUDET JUTUT", "NYA NYHETER", "NEW ITEMS"),
    "tanaan_voimaan": ("TÄNÄÄN VOIMAAN", "I KRAFT I DAG", "IN FORCE TODAY"),
    "viikolla_voimaan": ("TÄLLÄ VIIKOLLA VOIMAAN", "I KRAFT DENNA VECKA", "IN FORCE THIS WEEK"),
    "lausunnot": ("LAUSUNTOAJAT PÄÄTTYVÄT", "REMISSTIDER GÅR UT", "CONSULTATION DEADLINES"),
    "viime_viikko": ("VIIME VIIKON TÄRKEIMMÄT", "FÖRRA VECKANS VIKTIGASTE", "LAST WEEK'S TOP ITEMS"), "viikon": ("VIIKON TÄRKEIMMÄT", "VECKANS VIKTIGASTE", "TOP OF THE WEEK"),
    "ei_uusia": ("Ei uusia juttuja edellisen koosteen jälkeen.", "Inga nya nyheter sedan förra sammandraget.", "No new items since the previous digest."),
    "lakia": ("lakia", "lagar", "acts"), "laki": ("laki", "lag", "act"), "tanaan": ("tänään", "i dag", "today"), "huomenna": ("huomenna", "i morgon", "tomorrow"),
    "uutta": ("uutta", "nya", "new"), "voimaan": ("voimaan", "i kraft", "in force"), "eduskunnassa": ("EDUSKUNNASSA", "I RIKSDAGEN", "IN PARLIAMENT"),
    "lue": ("Lue LAKI-TV:stä", "Läs i LAKI-TV", "Read on LAKI-TV"), "lahde": ("lähde", "källa", "source"), "sivu": ("sivu", "sida", "page"),
    "footer": ("Tämä kooste on koottu LAKI-TV:n virallisista lähteistä poimituista tiedoista, eikä se ole oikeudellista neuvontaa. Tarkista aina alkuperäinen lähde. Muuta tai peru tilaus LAKI-TV:n sivulla 106.",
               "Sammandraget bygger på uppgifter som LAKI-TV hämtat ur officiella källor och är inte juridisk rådgivning. Kontrollera alltid den ursprungliga källan. Ändra eller avsluta prenumerationen på LAKI-TV:s sida 106.",
               "This digest is compiled from information LAKI-TV has collected from official sources and is not legal advice. Always check the original source. Change or cancel your subscription on LAKI-TV page 106."),
    "ai": ("Tiivistelmät ja käännökset ovat tekoälyn tekemiä.", "Sammandragen och översättningarna är gjorda med AI.", "Summaries and translations are AI-generated."),
    "paatos": ("Selkeällä kielellä", "På klarspråk", "In plain language"), "eu_voimaan": ("EU", "EU", "EU"), "maaraaika": ("määräaika", "tidsfrist", "deadline"), "pv": ("pv", "d", "d"),
    "header": ("JURIDINEN TEKSTI-TV", "JURIDISK TEXT-TV", "LEGAL TELETEXT"),
    "seuranta": ("SEURANNASSA", "BEVAKNING", "FOLLOWING"), "lausunnot_dl": ("Lausuntoaika päättyy", "Remisstiden går ut", "Consultation deadline"),
    "eu_alkaa": ("säädöstä alkaa", "rättsakter börjar", "acts start to apply"), "seur_poistunut": ("Poistunut LAKI-TV:stä (yli 35 pv)", "Borttagen från LAKI-TV (över 35 d)", "Removed from LAKI-TV (over 35 d)"),
    "seur_kuittaa": ("Kuittaa muutokset sivulla 108.", "Kvittera ändringarna på sidan 108.", "Acknowledge the changes on page 108."),
    "viikkokatsaus": ("LAKI-TV viikkokatsaus", "LAKI-TV veckoöversikt", "LAKI-TV weekly review"),
}
STAGE_T = {1: ("annettu", "avlämnad", "submitted"), 2: ("valiokunnassa", "i utskott", "in committee"), 3: ("mietintö valmis", "betänkande klart", "report ready"),
           4: ("1. käsittely", "första behandling", "1st reading"), 5: ("2. käsittely", "andra behandling", "2nd reading"), 6: ("vahvistettu", "stadfäst", "confirmed")}


def _li(sv):
    """Kieli-indeksi: sv voi olla False/True (vanha tapa) tai kielikoodi fi/sv/en."""
    if sv is True or sv == "sv":
        return 1
    if sv == "en":
        return 2
    return 0


def _t(k, sv):
    return T[k][_li(sv)]


def _tx(o, f, sv):
    i = _li(sv)
    return (o.get(f + ("_sv", "_en")[i - 1]) if i else None) or o.get(f) or ""


def _tun(t, sv):
    t = str(t or "")
    if _li(sv) != 1:
        return t
    return re.sub(r"\bHE (\d+/\d{4}) vp\b", r"RP \1 rd", t.replace("KKO:", "HD:").replace("KHO:", "HFD:"))


def _wd(iso, sv):
    return (WD_FI, WD_SV, WD_EN)[_li(sv)][datetime.date.fromisoformat(iso).weekday()]


SAADOS_TX = {1: (("Täytäntöönpanoasetus", "Genomförandeförordning"), ("Täytäntöönpanopäätös", "Genomförandebeslut"), ("Delegoitu asetus", "Delegerad förordning"), ("Asetus", "Förordning"), ("Direktiivi", "Direktiv"), ("Päätös", "Beslut")),
             2: (("Täytäntöönpanoasetus", "Implementing Regulation"), ("Täytäntöönpanopäätös", "Implementing Decision"), ("Delegoitu asetus", "Delegated Regulation"), ("Asetus", "Regulation"), ("Direktiivi", "Directive"), ("Päätös", "Decision"))}


def _saados(sd, sv):
    """EU-säädöstyypin nimi valitulla kielellä: Asetus (EU) 2024/1689 → Regulation (EU) 2024/1689."""
    sd = str(sd or "")
    for a, b in SAADOS_TX.get(_li(sv), ()):
        if sd.startswith(a):
            return b + sd[len(a):]
    return sd


def _fd(iso):
    d = datetime.date.fromisoformat(iso[:10])
    return f"{d.day}.{d.month}."


def prev_send(now_dt, hour=7):
    """Edellisen aamukoosteen hetki (klo 7.00). Aamuajo valmistuu 6.45–9.00, joten ennen klo 10 edellinen hetki on eilen klo 7;
    sen jälkeen tänään klo 7. Ikkunat ovat peräkkäisiä päiviä myös viikonloppuna, joten mikään ei toistu eikä jää väliin."""
    d = now_dt.date()
    if now_dt.hour < hour + 3:
        d -= datetime.timedelta(days=1)
    return datetime.datetime.combine(d, datetime.time(hour), tzinfo=HKI)


def all_known(d):
    """Kanavien jutut + arkisto (id, kanava, kohde)."""
    seen, out = set(), []
    for k, it in all_items(d):
        seen.add(it["id"]); out.append((k, it))
    for a in d.get("arkisto", []):
        if a.get("id") not in seen and a.get("k") in CH_KEYS:
            out.append((a["k"], a))
    return out


def snapshot_of(k, it, d):
    """Sama tilannekuva kuin sivulla: HE = käsittelyvaihe, EIT/ICJ = vaihe, lausunto = määräaika, muut = julkaisuaika."""
    if k == "he":
        st = next((h for h in d.get("he_tila", []) if h.get("he") == (it.get("tunnus") or it.get("id"))), None)
        return f"he:{st['vaihe'] if st else 0}"
    if it.get("vaihe"):
        return f"vaihe:{it['vaihe']}"
    if it.get("maaraaika"):
        return f"dl:{it['maaraaika']}"
    return f"pvm:{it.get('julkaistu') or it.get('pvm') or ''}"


def snapshot_label(snap, sv):
    k, _, v = str(snap or "").partition(":")
    if k == "he":
        return STAGE_T.get(int(v), (v, v, v))[_li(sv)] if v.isdigit() and v != "0" else STAGE_T[1][_li(sv)]
    if k == "dl":
        return f"DL {_fd(v)}" if v else ""
    return v


def follow_changes(d, seuranta, sv, since_dt, today):
    """Tilaajan seurannat: (otsikko, tunnus, id, kuvaus, kiireellinen). Muuttuneet, poistuneet, päättyvät määräajat."""
    known = {it["id"]: (k, it) for k, it in all_known(d)}
    out = []
    for f in (seuranta if isinstance(seuranta, list) else [])[:100]:
        if not isinstance(f, dict) or not isinstance(f.get("id"), str) or not f["id"]:
            continue
        if not isinstance(f.get("tila"), str):
            f = {**f, "tila": ""}
        hit = known.get(f["id"])
        title = f.get("otsikko") or f["id"]
        if not hit:
            out.append((title, f.get("tunnus") or f["id"], f["id"], _t("seur_poistunut", sv), False)); continue
        k, it = hit
        title = _tx(it, "otsikko", sv)
        now_s = snapshot_of(k, it, d)
        if f.get("tila") and f["tila"] != now_s:
            new_label = snapshot_label(now_s, sv)
            if k == "he":
                st = next((h for h in d.get("he_tila", []) if h.get("he") == (it.get("tunnus") or it.get("id"))), None)
                if st and st.get("valiokunta"):
                    new_label += f" · {st['valiokunta']}"
            elif it.get("vaihe"):
                new_label = _tx(it, "vaihe", sv)
            out.append((title, _tun(it.get("tunnus") or it["id"], sv), it["id"], f"{snapshot_label(f['tila'], sv)} → {new_label}", True))
        elif it.get("maaraaika") and today <= it["maaraaika"] <= (datetime.date.fromisoformat(today) + datetime.timedelta(days=7)).isoformat():
            dd = (datetime.date.fromisoformat(it["maaraaika"]) - datetime.date.fromisoformat(today)).days
            out.append((title, _tun(it.get("tunnus") or it["id"], sv), it["id"], f"{_t('maaraaika', sv)} {_fd(it['maaraaika'])} · {dd} {_t('pv', sv)}", dd <= 2))
    return out


def digest(d, laji="aamu", sv=False, kanavat=None, aiheet=None, since=None, now_dt=None, hour=7, seuranta=None, osat=None):
    """Palauttaa {subject, text, html}. laji: aamu (edellisen lähetyksen jälkeen), viikko (viime viikko ma–su), heti (paino 5 since-hetken jälkeen).
    osat: aamukoosteen osat, joita tilaaja haluaa ({"paiva","voimaan","lausunnot"}); None = kaikki."""
    now_dt = now_dt or now()
    osat = set(osat) if osat is not None else {"paiva", "voimaan", "lausunnot"}
    want_news = "paiva" in osat
    today = now_dt.date().isoformat()
    kan = set(kanavat or []); aih = set(aiheet or [])
    ok = lambda k, it: (not kan or k in kan) and (not aih or aih & set(it.get("aiheet") or []))
    ok_v = lambda v: not aih or aih & set(v.get("aiheet") or [])
    items = [(k, it) for k, it in all_known(d) if ok(k, it)]
    key_w = lambda kit: (-(kit[1].get("paino") or 2), str(kit[1].get("lisatty") or pub_key(kit[1])))
    L = []          # tekstirivit (plain)
    H = []          # html-lohkot
    link = lambda page, ident=None: page_url(page, ident)

    def sect(title):
        L.append(""); L.append(title); L.append("-" * len(title))
        H.append(f"<h2 style='font:700 14px/1.3 Arial,sans-serif;letter-spacing:.08em;color:#1a3ea8;margin:22px 0 8px'>{html.escape(title)}</h2>")

    def item_full(k, it):
        tun = _tun(it.get("tunnus") or it["id"], sv)
        o = _tx(it, "otsikko", sv)
        selko = _tx(it, "selko", sv) or _tx(it, "teksti", sv)
        src = it.get("lahde") or ""
        L.append(f"• {o} ({tun})"); L.append(f"  {selko}"); L.append(f"  {_t('lue', sv)}: {link(None, it['id'])}" + (f"  |  {_t('lahde', sv)}: {src}" if src else ""))
        H.append(f"<p style='margin:0 0 12px'><b>{html.escape(o)}</b> <span style='color:#666'>({html.escape(tun)})</span><br>"
                 f"<span style='font-size:14px;line-height:1.45'>{html.escape(selko)}</span><br>"
                 f"<a href='{link(None, it['id'])}' style='color:#1a3ea8'>{html.escape(_t('lue', sv))}</a>"
                 + (f" · <a href='{html.escape(src)}' style='color:#1a3ea8'>{html.escape(_t('lahde', sv))}</a>" if src else "") + "</p>")

    def item_short(k, it):
        tun = _tun(it.get("tunnus") or it["id"], sv)
        o = _tx(it, "otsikko", sv)
        L.append(f"• {o} ({tun}) {link(None, it['id'])}")
        H.append(f"<li style='margin:0 0 6px'><a href='{link(None, it['id'])}' style='color:#111;text-decoration:none'><b>{html.escape(o)}</b></a> <span style='color:#666'>({html.escape(tun)})</span></li>")

    def by_channel(lst, full_n):
        # tärkeimmät kokonaan, loput kanavittain lyhyinä
        lst = sorted(lst, key=key_w)
        for k, it in lst[:full_n]:
            item_full(k, it)
        rest = lst[full_n:]
        if rest:
            H.append("<ul style='padding-left:18px;margin:6px 0'>")
            prev = None
            for k, it in sorted(rest, key=lambda kit: (CH_KEYS.index(kit[0]), key_w(kit))):
                if k != prev:
                    L.append(f"  {CH_NAMES[k][_li(sv)]}:")
                    H.append(f"<li style='list-style:none;margin:8px 0 4px -18px;color:#666;font-size:12px;letter-spacing:.06em'>{html.escape(CH_NAMES[k][_li(sv)]).upper()}</li>")
                    prev = k
                item_short(k, it)
            H.append("</ul>")

    def vt_rows(vts, eus, label_day=True):
        for v in vts:
            n = v.get("lakeja") or 1
            nm = _tx(v, "nimi", sv); mu = _tx(v, "muutos", sv)
            extra = f" ({n} {_t('lakia', sv)})" if n > 1 else ""
            L.append(f"• {(_wd(v['pvm'], sv) + ' ' + _fd(v['pvm']) + ' ') if label_day else ''}{nm}{extra}" + (f" – {mu}" if mu else "") + (f" [{v.get('saados')}]" if v.get("saados") else ""))
            H.append(f"<li style='margin:0 0 5px'>{(html.escape(_wd(v['pvm'], sv) + ' ' + _fd(v['pvm'])) + ' ') if label_day else ''}<b>{html.escape(nm)}</b>{html.escape(extra)}"
                     + (f" – {html.escape(mu)}" if mu else "") + (f" <a href='{html.escape(v['lahde'])}' style='color:#1a3ea8'>{html.escape(v.get('saados') or 'Finlex')}</a>" if v.get("lahde") else "") + "</li>")
        for v in eus:
            nm = _tx(v, "nimi", sv); ku = _tx(v, "kuvaus", sv)
            L.append(f"• EU {(_wd(v['pvm'], sv) + ' ' + _fd(v['pvm']) + ' ') if label_day else ''}{nm}: {ku} [{_saados(v.get('saados', ''), sv)}]")
            H.append(f"<li style='margin:0 0 5px'>EU {(html.escape(_wd(v['pvm'], sv) + ' ' + _fd(v['pvm'])) + ' ') if label_day else ''}<b>{html.escape(nm)}</b>: {html.escape(ku)}"
                     + (f" <a href='{html.escape(v['lahde'])}' style='color:#1a3ea8'>{html.escape(_saados(v.get('saados'), sv) or 'EUR-Lex')}</a>" if v.get("lahde") else "") + "</li>")

    vt_all = list(d.get("vt_arkisto", [])) + list(d.get("voimaantulot", []))
    eu_all = list(d.get("eu_voimaantulot", []))
    week_end = (now_dt.date() + datetime.timedelta(days=6)).isoformat()
    if laji == "aamu":
        since_dt = since or prev_send(now_dt, hour)
        added = lambda it: as_dt(it.get("lisatty") or it.get("julkaistu"))
        new = [(k, it) for k, it in items if added(it) and since_dt < added(it)]   # ei ylärajaa: lisätty-aika ei voi olla tulevaisuudessa, pieni kellopoikkeama ei saa pudottaa juttua
        subject = f"{_t('aamu_otsikko', sv)} {_wd(today, sv)} {_fd(today)}"
        vt_today = [v for v in vt_all if v.get("pvm") == today and ok_v(v)]
        eu_today = [v for v in eu_all if v.get("pvm") == today and ok_v(v)]
        if not want_news:
            new = []
        parts = []
        if new:
            parts.append(f"{len(new)} {_t('uutta', sv)}")
        if vt_today and "voimaan" not in osat:
            vt_today, eu_today = [], []
        if vt_today:
            s0 = (d.get("vt_paivat") or {}).get(today); n0 = s0["lakeja"] if s0 else sum(v.get("lakeja") or 1 for v in vt_today)
            parts.append(f"{n0} {_t('laki', sv) if n0 == 1 else _t('lakia', sv)} {_t('voimaan', sv)}")
        if parts:
            subject += ": " + ", ".join(parts)
        # vaihemuutokset vain edellisen lähetyksen jälkeen (havaittu-päivä > since-päivä; saman päivän muutokset menivät jo)
        hm = [m for m in d.get("he_muutokset", []) if want_news and str(m.get("havaittu") or m.get("pvm") or "") > since_dt.date().isoformat()
              and (not kan or "he" in kan)]
        if now_dt.weekday() >= 5 and not new and not vt_today and not eu_today and not hm:
            return None   # viikonloppuna ei tyhjää koostetta
        if new:
            top = sorted(new, key=key_w)[0]
            sect(_t("karki", sv)); item_full(*top)
            rest = [x for x in new if x is not top]
            if rest:
                sect(f"{_t('uudet', sv)} ({len(new)})"); by_channel(rest, 3)
        elif want_news:
            sect(_t("uudet", sv)); L.append(_t("ei_uusia", sv)); H.append(f"<p>{html.escape(_t('ei_uusia', sv))}</p>")
        if vt_today or eu_today:
            s = (d.get("vt_paivat") or {}).get(today)
            n = s["lakeja"] if s else sum(v.get("lakeja") or 1 for v in vt_today)
            sect(f"{_t('tanaan_voimaan', sv)} · {n} {_t('laki', sv) if n == 1 else _t('lakia', sv)}"); H.append("<ul style='padding-left:18px;margin:6px 0'>"); vt_rows(vt_today, eu_today, False); H.append("</ul>")
        vt_week = [v for v in vt_all if today < v.get("pvm", "") <= week_end and ok_v(v)] if "voimaan" in osat else []
        eu_week = [v for v in eu_all if today < v.get("pvm", "") <= week_end and ok_v(v)] if "voimaan" in osat else []
        if vt_week or eu_week:
            sect(_t("viikolla_voimaan", sv)); H.append("<ul style='padding-left:18px;margin:6px 0'>"); vt_rows(vt_week, eu_week); H.append("</ul>")
        if hm:
            sect(_t("eduskunnassa", sv)); H.append("<ul style='padding-left:18px;margin:6px 0'>")
            for m in hm[:8]:
                st_ = lambda v: STAGE_T.get(v, (str(v), str(v), str(v)))[_li(sv)]
                he = _tun(m["he"], sv); nm = _tx(m, "nimi", sv)
                L.append(f"• {he} {nm}: {st_(m.get('vanha'))} → {st_(m.get('uusi'))}" + (f" ({m['valiokunta']})" if m.get("valiokunta") else ""))
                H.append(f"<li style='margin:0 0 5px'><b>{html.escape(he)}</b> {html.escape(nm)}: {html.escape(st_(m.get('vanha')))} → <b>{html.escape(st_(m.get('uusi')))}</b>"
                         + (f" ({html.escape(m['valiokunta'])})" if m.get("valiokunta") else "") + f" · <a href='{link(720)}' style='color:#1a3ea8'>720</a></li>")
            H.append("</ul>")
        fc = follow_changes(d, seuranta, sv, since_dt, today) if seuranta else []
        if fc:
            sect(_t("seuranta", sv)); H.append("<ul style='padding-left:18px;margin:6px 0'>")
            for title, tun, ident, desc, hot in fc:
                L.append(f"• {title} ({tun}): {desc} {link(None, ident)}")
                H.append(f"<li style='margin:0 0 5px'><a href='{link(None, ident)}' style='color:#111;text-decoration:none'><b>{html.escape(title)}</b></a> <span style='color:#666'>({html.escape(tun)})</span>: "
                         f"{'<b style=color:#b00>' if hot else ''}{html.escape(desc)}{'</b>' if hot else ''}</li>")
            H.append("</ul>"); L.append(f"  {_t('seur_kuittaa', sv)}"); H.append(f"<p style='color:#666;font-size:12px'>{html.escape(_t('seur_kuittaa', sv))} · <a href='{link(108)}' style='color:#1a3ea8'>108</a></p>")
        dls = sorted([(k, it) for k, it in items if k == "lausunnot" and today <= str(it.get("maaraaika") or "") <= week_end], key=lambda kit: kit[1]["maaraaika"]) if "lausunnot" in osat else []
        if dls:
            sect(_t("lausunnot", sv)); H.append("<ul style='padding-left:18px;margin:6px 0'>")
            for k, it in dls:
                dd = it["maaraaika"]; lab = _t("tanaan", sv) if dd == today else f"{_wd(dd, sv)} {_fd(dd)}"
                L.append(f"• {lab}: {_tx(it, 'otsikko', sv)} {link(None, it['id'])}")
                H.append(f"<li style='margin:0 0 5px'><b>{html.escape(lab)}</b>: <a href='{link(None, it['id'])}' style='color:#111'>{html.escape(_tx(it, 'otsikko', sv))}</a></li>")
            H.append("</ul>")
        if now_dt.weekday() == 0 and want_news:  # maanantaina viime viikon kärki
            ws = now_dt.date() - datetime.timedelta(days=7); we = ws + datetime.timedelta(days=6)
            wk = sorted([(k, it) for k, it in items if ws.isoformat() <= pub_key(it)[:10] <= we.isoformat()], key=key_w)[:5]
            if wk:
                sect(f"{_t('viime_viikko', sv)} ({_fd(ws.isoformat())}–{_fd(we.isoformat())})"); H.append("<ul style='padding-left:18px;margin:6px 0'>")
                for k, it in wk: item_short(k, it)
                H.append("</ul>")
    elif laji == "viikko":
        ws = now_dt.date() - datetime.timedelta(days=now_dt.weekday() + 7); we = ws + datetime.timedelta(days=6)
        wk = sorted([(k, it) for k, it in items if ws.isoformat() <= pub_key(it)[:10] <= we.isoformat()], key=key_w)[:10]
        subject = f"{_t('viikko_otsikko', sv)} {_fd(ws.isoformat())}–{_fd(we.isoformat())}"
        sect(_t("viikon", sv))
        if wk:
            by_channel(wk, 5)
        else:
            L.append(_t("ei_uusia", sv)); H.append(f"<p>{html.escape(_t('ei_uusia', sv))}</p>")
        vt_week = [v for v in vt_all if today <= v.get("pvm", "") <= week_end and ok_v(v)]
        eu_week = [v for v in eu_all if today <= v.get("pvm", "") <= week_end and ok_v(v)]
        if vt_week or eu_week:
            sect(_t("viikolla_voimaan", sv)); H.append("<ul style='padding-left:18px;margin:6px 0'>"); vt_rows(vt_week, eu_week); H.append("</ul>")
    else:  # heti: painon 5 jutut since-hetken jälkeen
        since_dt = since or max(now_dt - datetime.timedelta(hours=9), prev_send(now_dt, hour))
        hot = [(k, it) for k, it in items if (it.get("paino") or 0) >= 5 and as_dt(it.get("lisatty") or it.get("julkaistu")) and as_dt(it.get("lisatty") or it.get("julkaistu")) > since_dt]
        if not hot:
            return None
        subject = f"{_t('heti_otsikko', sv)}: {_tx(hot[0][1], 'otsikko', sv)}"
        sect(_t("karki", sv))
        for k, it in sorted(hot, key=key_w): item_full(k, it)
    if not H:
        return None   # tilaajalle ei ole tällä kertaa mitään
    L.append(""); L.append(_t("ai", sv)); L.append(_t("footer", sv)); L.append(f"LAKI-TV: {BASE_URL}")
    body = "\n".join(L).strip()
    htm = ("<div style='font:15px/1.5 Arial,Helvetica,sans-serif;color:#111;max-width:640px;margin:0 auto;padding:16px'>"
           f"<div style='background:#0000c8;color:#ffff00;font:700 20px/1 Arial;padding:12px 14px;letter-spacing:.1em'>LAKI-TV <span style='color:#00ffff;font-size:12px;font-weight:400'>{_t('header', sv)}</span></div>"
           + "".join(H) +
           f"<p style='color:#666;font-size:12px;margin-top:24px'>{html.escape(_t('ai', sv))} {html.escape(_t('footer', sv))}<br><a href='{BASE_URL}' style='color:#1a3ea8'>LAKI-TV</a></p></div>")
    return {"subject": subject, "text": body, "html": htm}


def to_slack(m):
    """Slack incoming webhook: {text} mrkdwn. Otsikot lihavoituna, linkit <url|teksti>."""
    t = m["text"]
    t = re.sub(r"^(?P<h>[^\n]{4,})\n-{4,}$", lambda mm: f"*{mm.group('h').strip()}*", t, flags=re.M)
    t = re.sub(r"(Lue LAKI-TV:stä|Läs i LAKI-TV|Read on LAKI-TV): (https?://\S+)", lambda mm: f"<{mm.group(2)}|{mm.group(1)}>", t)
    t = re.sub(r"(lähde|källa|source): (https?://\S+)", lambda mm: f"<{mm.group(2)}|{mm.group(1)}>", t)
    return {"text": f"*{m['subject']}*\n\n{t}"}


def to_teams(m):
    """Teams (Workflows-webhook): Adaptive Card, jossa markdown-tekstilohkot."""
    t = m["text"]
    t = re.sub(r"^(?P<h>[^\n]{4,})\n-{4,}$", lambda mm: f"**{mm.group('h').strip()}**", t, flags=re.M)
    t = re.sub(r"(Lue LAKI-TV:stä|Läs i LAKI-TV|Read on LAKI-TV): (https?://\S+)", lambda mm: f"[{mm.group(1)}]({mm.group(2)})", t)
    t = re.sub(r"(lähde|källa|source): (https?://\S+)", lambda mm: f"[{mm.group(1)}]({mm.group(2)})", t)
    blocks = [{"type": "TextBlock", "text": m["subject"], "weight": "Bolder", "size": "Medium", "wrap": True}]
    for para in t.split("\n\n"):
        para = para.strip()
        while para:
            cut = len(para)
            if cut > 3500:
                cut = para.rfind("\n", 0, 3500)
                if cut < 500:
                    cut = 3500
            blocks.append({"type": "TextBlock", "text": para[:cut].strip(), "wrap": True, "spacing": "Medium"}); para = para[cut:].strip()
    return {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None,
            "content": {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard", "version": "1.4", "body": blocks[:60]}}]}


def cmd_post(payload_path, url):
    """Lähettää JSON-kuorman webhook-osoitteeseen (Slack, Teams). Osoite annetaan komentorivillä, ei tallenneta eikä tulosteta."""
    try:
        check_url(url, https_only=True)
    except ValueError as e:
        print(f"VIRHE webhook: {e}"); sys.exit(1)
    body = open(payload_path, "rb").read()
    json.loads(body)   # kuorman on oltava JSON
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": UA}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"OK {r.status} {r.read(200).decode('utf-8', 'replace').strip()}")
    except urllib.error.HTTPError as e:
        print(f"VIRHE HTTP {e.code}: {e.read(300).decode('utf-8', 'replace')}"); sys.exit(1)
    except Exception as e:
        print(f"VIRHE {type(e).__name__}: {str(e).replace(url, '<webhook>')}"); sys.exit(1)


def cmd_digest(p, laji, kieli, kanavat, aiheet, since, out, tilaukset, muoto=None):
    d = load(p)
    since_dt = None
    if since:
        since_dt = datetime.datetime.fromisoformat(since.replace("Z", "+00:00"))
        since_dt = since_dt.replace(tzinfo=HKI) if since_dt.tzinfo is None else since_dt.astimezone(HKI)
    if tilaukset:  # {"<id>": {email, sisalto[], kanavat[], aiheet[], kieli}} tai lista
        subs = load(tilaukset)
        subs = list(subs.values()) if isinstance(subs, dict) else subs
        msgs = []
        for s in subs:
            if not isinstance(s, dict) or not isinstance(s.get("email"), str) or not s.get("email") or not s.get("suostumus", True):
                continue
            want = set(x for x in (s.get("sisalto") or []) if isinstance(x, str))
            lj = laji
            if lj == "heti":
                if "heti" not in want:
                    continue
            elif lj == "aamu" and "paiva" not in want:
                # viikko-tilaajille maanantain aamukooste = viikon tärkeimmät
                if "viikko" in want and now().weekday() == 0:
                    lj = "viikko"
                elif not ({"voimaan", "lausunnot"} & want):
                    continue
            elif lj == "viikko" and "viikko" not in want:
                continue
            try:
                lst = lambda v: [x for x in v if isinstance(x, str)] if isinstance(v, list) else None
                m = digest(d, lj, s.get("kieli") if s.get("kieli") in LANGS else "fi", lst(s.get("kanavat")), lst(s.get("aiheet")), since_dt, seuranta=s.get("seuranta"),
                           osat=(want & {"paiva", "voimaan", "lausunnot"}) if lj == "aamu" else None)
            except Exception as e:
                print(f"HUOM: tilaajan kooste ohitettiin ({type(e).__name__})"); continue
            if m:
                msgs.append({"email": s["email"], "kieli": s.get("kieli", "fi"), "laji": lj, **m})
        write_text(out or "viestit.json", json.dumps(msgs, ensure_ascii=False, indent=1))
        print(f"{len(msgs)} viestiä -> {out or 'viestit.json'}")
        return
    m = digest(d, laji, kieli if kieli in LANGS else "fi", kanavat.split(",") if kanavat else None, aiheet.split(",") if aiheet else None, since_dt)
    if not m:
        print("Ei lähetettävää."); sys.exit(3)
    if muoto == "slack":
        m = to_slack(m)
    elif muoto == "teams":
        m = to_teams(m)
    if out:
        write_text(out, json.dumps(m, ensure_ascii=False, indent=1))
        print(f"OK: {out} ({m.get('subject') or muoto})")
    else:
        print(m["subject"]); print(); print(m["text"])


# ---------------------------------------------------------------- jakelu: syötteet, kalenteri, viikkokatsaus
def _lang_items(d, sv):
    """Kanavien jutut uusin ensin (kanava, kohde, epoch)."""
    rows = []
    for k, it in all_items(d):
        dt = as_dt(it.get("julkaistu") or it.get("pvm"))
        rows.append((k, it, dt or datetime.datetime(2000, 1, 1, tzinfo=HKI)))
    rows.sort(key=lambda r: r[2], reverse=True)
    return rows


def rss_text(d, sv, limit=80):
    lang = ("fi", "sv", "en")[_li(sv)]
    link = lambda ident: page_url(None, ident)
    L = ['<?xml version="1.0" encoding="UTF-8"?>', '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">', "<channel>",
         "<title>LAKI-TV</title>", f"<link>{html.escape(BASE_URL)}</link>", f"<description>{html.escape(_t('header', sv).capitalize())}</description>",
         f"<language>{lang}</language>", f"<lastBuildDate>{email.utils.format_datetime(now())}</lastBuildDate>"]
    for k, it, dt in _lang_items(d, sv)[:limit]:
        title = f"{_tx(it, 'otsikko', sv)} ({_tun(it.get('tunnus') or it['id'], sv)})"
        desc = (_tx(it, "selko", sv) or _tx(it, "teksti", sv)) + (f" — {_tx(it, 'lopputulos', sv)}" if it.get("lopputulos") else "")
        src = it.get("lahde") or ""
        body = f"<p>{html.escape(desc)}</p>" + (f"<p><a href='{html.escape(src)}'>{html.escape(_t('lahde', sv))}</a></p>" if src else "")
        L += ["<item>", f"<title>{html.escape(title)}</title>", f"<link>{html.escape(link(it['id']))}</link>", f"<guid isPermaLink=\"false\">{html.escape(it['id'])}</guid>",
              f"<category>{html.escape(CH_NAMES[k][_li(sv)])}</category>", f"<pubDate>{email.utils.format_datetime(dt)}</pubDate>",
              f"<description>{html.escape(body)}</description>", "</item>"]
    L += ["</channel>", "</rss>"]
    return "\n".join(L) + "\n"


def json_feed(d):
    """JSON Feed 1.1 + _lakitv-laajennus: kaikki kentät kolmella kielellä."""
    link = lambda ident: page_url(None, ident)
    items = []
    for k, it, dt in _lang_items(d, False):
        x = {kk: vv for kk, vv in it.items() if not kk.startswith("_")}
        items.append({"id": it["id"], "url": link(it["id"]), "external_url": it.get("lahde"), "title": it.get("otsikko"),
                      "content_text": it.get("selko") or it.get("teksti"), "date_published": dt.isoformat(), "tags": (it.get("aiheet") or []) + [k],
                      "_lakitv": {"kanava": k, **x}})
    return json.dumps({"version": "https://jsonfeed.org/version/1.1", "title": "LAKI-TV", "home_page_url": BASE_URL, "feed_url": file_url("feed.json"),
                       "description": "Juridinen teksti-TV: tuomioistuinten, valvojien ja lainsäädännön uutiset virallisista lähteistä.", "language": "fi",
                       "items": items, "_lakitv": {"paivitetty": d.get("paivitetty"), "voimaantulot": d.get("voimaantulot", []), "eu_voimaantulot": d.get("eu_voimaantulot", []),
                                                    "he_tila": d.get("he_tila", []), "he_muutokset": d.get("he_muutokset", [])}},
                      ensure_ascii=False, indent=1)


def markdown_text(d):
    """Obsidian/Notion-vienti: yksi tiedosto, jutut kanavittain, kaikki kielet."""
    L = ["---", "title: LAKI-TV", f"updated: {d.get('paivitetty')}", "source: " + BASE_URL, "---", "", "# LAKI-TV", "",
         f"Päivitetty {d.get('paivitetty')}. Jutut kanavittain, uusin ensin. Lähde aina virallinen; tiivistelmät ja käännökset tekoälyn tekemiä.", ""]
    for k in CH_KEYS:
        lst = d.get("kanavat", {}).get(k, [])
        if not lst:
            continue
        L += [f"## {CH_NAMES[k][0]}", ""]
        for it in lst:
            L += [f"### {it.get('otsikko')} — {it.get('tunnus') or it['id']}", "",
                  f"- pvm: {it.get('pvm')} ({it.get('pvm_selite') or ''}) · julkaistu: {it.get('julkaistu')} · paino: {it.get('paino')} · aiheet: {', '.join(it.get('aiheet') or [])}",
                  f"- lähde: {it.get('lahde')}", f"- LAKI-TV: {page_url(None, it['id'])}", ""]
            if it.get("asiasanat"):
                L += [f"*{it['asiasanat']}*", ""]
            L += [it.get("teksti") or "", ""]
            if it.get("lopputulos"):
                L += [f"**Lopputulos:** {it['lopputulos']}", ""]
            if it.get("selko"):
                L += [f"> {it['selko']}", ""]
            if it.get("teksti_sv"):
                L += ["<details><summary>Svenska</summary>", "", it.get("otsikko_sv", ""), "", it["teksti_sv"], "", "</details>", ""]
            if it.get("teksti_en"):
                L += ["<details><summary>English</summary>", "", it.get("otsikko_en", ""), "", it["teksti_en"], "", "</details>", ""]
    vt = [v for v in d.get("voimaantulot", []) if v.get("pvm", "") >= today()]
    if vt:
        L += ["## Voimaantulot", ""] + [f"- {v['pvm']} {v.get('nimi')} ({v.get('saados')})" + (f" – {v['muutos']}" if v.get("muutos") else "") for v in vt] + [""]
    return "\n".join(L)


def ics_fold(line):
    """Taittaa yli 75 oktetin rivin jatkoriveiksi (välilyönti alussa), UTF-8-merkin rajalta."""
    b = line.encode("utf-8"); out = []
    while len(b) > 75:
        cut = 75
        while cut > 1 and (b[cut] & 0xC0) == 0x80:
            cut -= 1
        out.append(b[:cut].decode("utf-8")); b = b" " + b[cut:]
    out.append(b.decode("utf-8"))
    return "\r\n".join(out)


def ics_uid(u):
    """UID ilman välilyöntejä, rivinvaihtoja ja erotinmerkkejä (ei rivi-injektiota)."""
    return re.sub(r"[\s,;:\\]", "", str(u))


def ics_esc(s):
    return str(s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


def ics_text(d, sv, days=90):
    """Tilattava kalenteri: lausuntoajat, voimaantulopäivät (yksi tapahtuma / päivä) ja EU-säädösten alkamiset."""
    t0 = today(); end = (now().date() + datetime.timedelta(days=days)).isoformat()
    stamp = now().astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    evs = []
    link = lambda ident: page_url(None, ident)
    for k, it in all_items(d):
        if it.get("maaraaika") and t0 <= it["maaraaika"] <= end:
            evs.append(("dl-" + it["id"], it["maaraaika"], f"{_t('lausunnot_dl', sv)}: {_tx(it, 'otsikko', sv).capitalize()}",
                        f"{_tx(it, 'elin', sv)}\n{_tx(it, 'selko', sv) or _tx(it, 'teksti', sv)}\n{it.get('lahde') or ''}", link(it["id"])))
    by = {}
    for v in d.get("voimaantulot", []):
        if t0 <= v.get("pvm", "") <= end:
            by.setdefault(v["pvm"], []).append(v)
    for dd, vs in sorted(by.items()):
        s0 = (d.get("vt_paivat") or {}).get(dd); n = s0["lakeja"] if s0 else sum(v.get("lakeja") or 1 for v in vs)
        names = "\n".join(f"• {_tx(v, 'nimi', sv)}" + (f" ({v['saados']})" if v.get("saados") else "") for v in vs[:15])
        evs.append(("vt-" + dd, dd, f"{_t('voimaan', sv).capitalize()}: {n} {_t('laki', sv) if n == 1 else _t('lakia', sv)}", names, page_url(800)))
    by = {}
    for v in d.get("eu_voimaantulot", []):
        if t0 <= v.get("pvm", "") <= end:
            by.setdefault(v["pvm"], []).append(v)
    for dd, vs in sorted(by.items()):
        names = "\n".join(f"• {_tx(v, 'nimi', sv)} ({_saados(v.get('saados'), sv)})" for v in vs[:15])
        evs.append(("eu-" + dd, dd, f"EU: {len(vs)} {_t('eu_alkaa', sv)}", names, page_url(801)))
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//LAKI-TV//FI", "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:LAKI-TV", "X-PUBLISHED-TTL:PT12H"]
    for uid, dd, title, desc, url in sorted(evs, key=lambda e: e[1]):
        d2 = (datetime.date.fromisoformat(dd) + datetime.timedelta(days=1)).strftime("%Y%m%d")
        L += ["BEGIN:VEVENT", f"UID:{ics_uid(uid)}@laki-tv", f"DTSTAMP:{stamp}", f"DTSTART;VALUE=DATE:{dd.replace('-', '')}", f"DTEND;VALUE=DATE:{d2}",
              f"SUMMARY:{ics_esc(title)}", f"DESCRIPTION:{ics_esc(desc)}", f"URL:{url}", "END:VEVENT"]
    L.append("END:VCALENDAR")
    return "\r\n".join(ics_fold(x) for x in L) + "\r\n"


def cmd_feed(p, outdir="."):
    """Kirjoittaa feed.xml, feed-sv.xml, feed-en.xml, feed.json, lakitv.md ja kalenteri.txt (+ -sv, -en; iCalendar-sisältö)."""
    d = load(p); os.makedirs(outdir, exist_ok=True)
    files = {"feed.xml": rss_text(d, "fi"), "feed-sv.xml": rss_text(d, "sv"), "feed-en.xml": rss_text(d, "en"), "feed.json": json_feed(d), "lakitv.md": markdown_text(d),
             "kalenteri.txt": ics_text(d, "fi"), "kalenteri-sv.txt": ics_text(d, "sv"), "kalenteri-en.txt": ics_text(d, "en")}   # .txt: sivun rinnalla ei tarjoilla .ics-päätettä; sisältö on iCalendar
    for name, txt in files.items():
        write_text(os.path.join(outdir, name), txt)
    print("OK: " + ", ".join(f"{n} ({len(t.encode('utf-8')) // 1024} kt)" for n, t in files.items()))


def weekly_html(d, sv=False, now_dt=None):
    """Viime viikon (ma–su) katsaus A4-tulostusta varten: kärki, kanavittain, voimaan tulevat, lausuntoajat, eduskunta."""
    now_dt = now_dt or now()
    ws = now_dt.date() - datetime.timedelta(days=now_dt.weekday() + 7); we = ws + datetime.timedelta(days=6)
    known = all_known(d)
    key_w = lambda kit: (-(kit[1].get("paino") or 2), str(kit[1].get("lisatty") or pub_key(kit[1])))
    wk = sorted([(k, it) for k, it in known if ws.isoformat() <= pub_key(it)[:10] <= we.isoformat()], key=key_w)
    top = wk[:5]; rest = wk[5:]
    t0 = now_dt.date().isoformat(); end = (now_dt.date() + datetime.timedelta(days=14)).isoformat()
    vt = [v for v in list(d.get("vt_arkisto", [])) + list(d.get("voimaantulot", [])) if t0 <= v.get("pvm", "") <= end]
    eu = [v for v in d.get("eu_voimaantulot", []) if t0 <= v.get("pvm", "") <= end]
    dls = sorted([(k, it) for k, it in known if k == "lausunnot" and it.get("maaraaika", "") >= t0], key=lambda kit: kit[1]["maaraaika"])[:8]
    hm = [m for m in d.get("he_muutokset", []) if str(m.get("havaittu") or m.get("pvm") or "") >= ws.isoformat()][:10]
    link = lambda ident: page_url(None, ident)
    e = html.escape
    H = [f"<!doctype html><html lang='{('fi', 'sv', 'en')[_li(sv)]}'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
         f"<title>{e(_t('viikkokatsaus', sv))} {_fd(ws.isoformat())}–{_fd(we.isoformat())}{we.year}</title>",
         "<style>@page{size:A4;margin:16mm 18mm}body{font:11pt/1.45 Georgia,'Times New Roman',serif;color:#111;max-width:180mm;margin:0 auto;padding:12mm 8mm}"
         "h1{font:700 22pt/1.1 Arial,Helvetica,sans-serif;letter-spacing:.04em;margin:0 0 2pt}h1 small{font-size:10pt;font-weight:400;letter-spacing:.2em;color:#555;display:block;margin-top:4pt}"
         "h2{font:700 11pt/1.2 Arial,Helvetica,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:#1a3ea8;border-bottom:1.5pt solid #1a3ea8;margin:16pt 0 6pt;padding-bottom:2pt}"
         "h3{font:700 11pt/1.3 Arial,Helvetica,sans-serif;margin:8pt 0 2pt}p{margin:0 0 6pt}.m{color:#555;font-size:9.5pt}.k{font-size:9pt;color:#555;letter-spacing:.06em;text-transform:uppercase}"
         "ul{margin:0 0 6pt;padding-left:16pt}li{margin:0 0 3pt}a{color:#1a3ea8;text-decoration:none}.f{font-size:9pt;color:#666;border-top:1pt solid #ccc;margin-top:18pt;padding-top:6pt}"
         "@media print{a[href]:after{content:''}}</style></head><body>",
         f"<h1>LAKI-TV <small>{e(_t('viikkokatsaus', sv).replace('LAKI-TV ', '').upper())} · {_fd(ws.isoformat())}–{_fd(we.isoformat())}{we.year}</small></h1>"]
    def item_block(k, it, full):
        tun = _tun(it.get("tunnus") or it["id"], sv); o = _tx(it, "otsikko", sv)
        H.append(f"<h3>{e(o)} <span class='m'>({e(tun)}) · {e(CH_NAMES[k][_li(sv)])}</span></h3>")
        if full:
            H.append(f"<p>{e(_tx(it, 'selko', sv) or _tx(it, 'teksti', sv))}</p>")
            if it.get("lopputulos"):
                H.append(f"<p class='m'>{e(_tx(it, 'lopputulos', sv))}</p>")
        H.append(f"<p class='m'><a href='{link(it['id'])}'>LAKI-TV</a>" + (f" · <a href='{e(it['lahde'])}'>{e(_t('lahde', sv))}</a>" if it.get("lahde") else "") + "</p>")
    H.append(f"<h2>{e(_t('viikon', sv))}</h2>")
    if top:
        for k, it in top: item_block(k, it, True)
    else:
        H.append(f"<p>{e(_t('ei_uusia', sv))}</p>")
    if rest:
        H.append(f"<h2>{e(_t('uudet', sv))} ({len(rest)})</h2><ul>")
        for k, it in sorted(rest, key=lambda kit: (CH_KEYS.index(kit[0]), key_w(kit))):
            H.append(f"<li><b>{e(_tx(it, 'otsikko', sv))}</b> <span class='m'>({e(_tun(it.get('tunnus') or it['id'], sv))} · {e(CH_NAMES[k][_li(sv)])})</span> <a href='{link(it['id'])}'>›</a></li>")
        H.append("</ul>")
    if vt or eu:
        H.append(f"<h2>{e(_t('viikolla_voimaan', sv))} · 14 {e(_t('pv', sv))}</h2><ul>")
        for v in vt:
            n = v.get("lakeja") or 1
            H.append(f"<li><b>{_wd(v['pvm'], sv)} {_fd(v['pvm'])}</b> {e(_tx(v, 'nimi', sv))}" + (f" ({n} {e(_t('lakia', sv))})" if n > 1 else "") + (f" – {e(_tx(v, 'muutos', sv))}" if v.get("muutos") else "") + "</li>")
        for v in eu:
            H.append(f"<li><b>{_wd(v['pvm'], sv)} {_fd(v['pvm'])}</b> EU: {e(_tx(v, 'nimi', sv))} – {e(_tx(v, 'kuvaus', sv))} <span class='m'>[{e(_saados(v.get('saados'), sv))}]</span></li>")
        H.append("</ul>")
    if dls:
        H.append(f"<h2>{e(_t('lausunnot', sv))}</h2><ul>")
        for k, it in dls:
            H.append(f"<li><b>{_wd(it['maaraaika'], sv)} {_fd(it['maaraaika'])}</b> {e(_tx(it, 'otsikko', sv))} <span class='m'>({e(_tx(it, 'elin', sv))})</span> <a href='{link(it['id'])}'>›</a></li>")
        H.append("</ul>")
    if hm:
        H.append(f"<h2>{e(_t('eduskunnassa', sv))}</h2><ul>")
        for m in hm:
            st_ = lambda v: STAGE_T.get(v, (str(v), str(v), str(v)))[_li(sv)]
            H.append(f"<li><b>{e(_tun(m['he'], sv))}</b> {e(_tx(m, 'nimi', sv))}: {e(st_(m.get('vanha')))} → <b>{e(st_(m.get('uusi')))}</b>" + (f" ({e(m['valiokunta'])})" if m.get("valiokunta") else "") + "</li>")
        H.append("</ul>")
    H.append(f"<p class='f'>{e(_t('ai', sv))} {e(_t('footer', sv))} <a href='{BASE_URL}'>{BASE_URL}</a></p></body></html>")
    return "\n".join(H)


def cmd_viikkokatsaus(p, out="viikkokatsaus", kieli="fi"):
    """Kirjoittaa viikkokatsaus.html ja, jos Chromium löytyy, viikkokatsaus.pdf (A4)."""
    d = load(p)
    htm = weekly_html(d, kieli if kieli in LANGS else "fi")
    write_text(out + ".html", htm)
    print(f"OK: {out}.html ({len(htm) // 1024} kt)")
    try:
        os.remove(out + ".pdf")   # vanha PDF ei saa näyttää onnistumiselta
    except OSError:
        pass
    import glob
    pw = sorted(glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux*/chrome")) + glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome"))
    for exe in ("/opt/pw-browsers/chromium", *pw[::-1], "chromium", "chromium-browser", "google-chrome"):
        try:
            r = subprocess.run([exe, "--headless=new", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={os.path.abspath(out + '.pdf')}",
                                "file://" + os.path.abspath(out + ".html")], capture_output=True, text=True, timeout=120, check=False)
            if os.path.exists(out + ".pdf") and os.path.getsize(out + ".pdf") > 1000:
                print(f"OK: {out}.pdf ({os.path.getsize(out + '.pdf') // 1024} kt)"); return
        except (OSError, subprocess.SubprocessError):
            continue
    print("HUOM: PDF:ää ei tehty (Chromium puuttuu); julkaise vain HTML.")


def cmd_diff(a, b):
    """Muutokset kahden data.jsonin välillä: lisätyt, arkistoituneet ja poistuneet jutut, voimaantulot, HE-vaiheet."""
    A, B = load(a), load(b)
    ia = {it["id"]: (k, it) for k, it in all_items(A)}; ib = {it["id"]: (k, it) for k, it in all_items(B)}
    arch_b = {x["id"] for x in B.get("arkisto", [])}
    for i in ib:
        if i not in ia:
            print(f"+ [{ib[i][0]}] {i}: {ib[i][1].get('otsikko')} (paino {ib[i][1].get('paino')})")
    for i in ia:
        if i not in ib:
            print(f"- [{ia[i][0]}] {i}: {ia[i][1].get('otsikko')} {'(arkistoon)' if i in arch_b else '(POISTUI KOKONAAN)'}")
    for i in set(ia) & set(ib):
        ch = [f for f in ("otsikko", "teksti", "selko", "paino", "julkaistu", "lahde") if ia[i][1].get(f) != ib[i][1].get(f)]
        if ch:
            print(f"~ {i}: muuttui {', '.join(ch)}")
    va = {(v["pvm"], v.get("saados")) for v in A.get("voimaantulot", [])}; vb = {(v["pvm"], v.get("saados")) for v in B.get("voimaantulot", [])}
    for v in sorted(vb - va): print(f"+ voimaantulo {v[0]} {v[1]}")
    for v in sorted(va - vb): print(f"- voimaantulo {v[0]} {v[1]}")
    ha = {h["he"]: h.get("vaihe") for h in A.get("he_tila", [])}; hb = {h["he"]: h.get("vaihe") for h in B.get("he_tila", [])}
    for he in hb:
        if ha.get(he) != hb[he]:
            print(f"~ HE-vaihe {he}: {ha.get(he)} -> {hb[he]}")
    print(f"paivitetty {A.get('paivitetty')} -> {B.get('paivitetty')}; juttuja {len(ia)} -> {len(ib)}; arkisto {len(A.get('arkisto', []))} -> {len(B.get('arkisto', []))}")


def cmd_stamp(p):
    d = load(p)
    d["paivitetty"] = now().isoformat(timespec="seconds")
    odottaa = d.pop("_nahty_odottaa", None) or []
    d["_nahty"] = (list(d.get("_nahty") or []) + [h for h in odottaa if h not in set(d.get("_nahty") or [])])[-600:]
    t = today()
    uusia = sum(1 for _, it in all_items(d) if str(it.get("lisatty") or "")[:10] == t)
    d["_ajot"] = ((d.get("_ajot") or []) + [{"aika": d["paivitetty"][:16], "uusia": uusia, "juttuja": sum(1 for _ in all_items(d)),
                                             "hiljaa": [k for k, v in (d.get("_lahteet") or {}).items() if v.get("hiljaa")]}])[-14:]
    save(p, d)
    print("paivitetty =", d["paivitetty"], f"({len(odottaa)} linkkiä merkitty nähdyiksi, {uusia} uutta juttua tänään)")


# ---------------------------------------------------------------- julkaisu ja peilaus
# Datavarasto (gist) on se, mistä verkkosivusto ja lukijan sivu hakevat datan. Peilaus tehdään samassa komennossa kuin
# sivun ja jakelutiedostojen kirjoitus – ENNEN artefaktin julkaisua – jotta ajon katkeaminen (käyttöraja, verkkovirhe,
# istunnon päättyminen) julkaisun jälkeen ei jätä sivustoa vanhaksi. Avaimet luetaan asetustiedostosta (ArtifactData
# asetukset/jakelu tallennettuna out_dir-kansioon) ja annetaan ghpush.py:lle vain ympäristömuuttujassa: ne eivät kulje
# komentorivin, raportin tai tulosteen kautta.
MIRROR_WAIT = float(os.environ.get("LAKITV_PEILAUS_ODOTUS", "1"))   # testit: 0 = ei odotuksia yritysten välillä
SECRET_PAT = re.compile(r"ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|gh[ousr]_[A-Za-z0-9]{20,}|(?:https?://)?(?:hooks\.slack\.com/services/|[\w.-]*webhook\.office\.com/|[\w.-]*logic\.azure\.com/)\S+")


def mask(s, secrets=()):
    """Peittää avaimet ja webhook-osoitteet tulosteesta."""
    for t in secrets:
        if t and len(str(t)) >= 8:
            s = s.replace(str(t), "[AVAIN]")
    return SECRET_PAT.sub("[AVAIN]", s)


def read_settings(p):
    """Jakeluasetukset (asetukset/jakelu-dokumentti JSON-tiedostona). Puuttuva tiedosto = ei asetuksia."""
    if not p:
        return {}
    try:
        d = load(p)
    except (OSError, ValueError) as e:
        print(f"HUOM: asetustiedostoa ei saatu luettua ({type(e).__name__})")
        return {}
    return d if isinstance(d, dict) else {}


def find_tool(name):
    """Työkalu samasta kansiosta kuin tämä tiedosto, työhakemistosta tai tools/-kansiosta."""
    here = os.path.dirname(os.path.abspath(__file__))
    return next((c for c in (os.path.join(here, name), name, os.path.join("tools", name)) if os.path.isfile(c)), None)


def gist_git_url(repo):
    """gist:TUNNUS -> https://gist.github.com/TUNNUS.git; omistaja/varasto -> https://github.com/omistaja/varasto.git"""
    return f"https://gist.github.com/{repo[5:]}.git" if repo.startswith("gist:") else f"https://github.com/{repo}.git"


def remote_head(repo, remote=None):
    """Datavaraston HEAD-commit (git ls-remote); jos HEAD ei osoita mihinkään, main, master tai ainoa haara. None, jos ei saatu."""
    try:
        r = subprocess.run(["git", "ls-remote", remote or gist_git_url(repo)], capture_output=True, text=True, timeout=60,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        if r.returncode != 0:
            return None
        refs = {n: h for h, n in re.findall(r"^([0-9a-f]{40})\t(\S+)$", r.stdout, re.M)}
        heads = {n[len("refs/heads/"):]: h for n, h in refs.items() if n.startswith("refs/heads/")}
        return refs.get("HEAD") or heads.get("main") or heads.get("master") or (next(iter(heads.values())) if len(heads) == 1 else None)
    except (OSError, subprocess.SubprocessError):
        return None


def remote_stamp(data_url):
    """Datavaraston raw-osoitteen paivitetty-arvo (välimuistin ohittava kysely); None, jos ei saatu."""
    try:
        b = fetch(f"{data_url}{'&' if '?' in data_url else '?'}v={int(time.time())}", timeout=30, tries=1)
        return json.loads(b.decode("utf-8")).get("paivitetty")
    except Exception:
        return None


def verify_mirror(repo, data_url, stamp, commit, wait=60, remote=None):
    wait *= MIRROR_WAIT
    """Varmistaa työnnön: HEAD on työnnetty commit (git ls-remote) ja raw-osoitteen paivitetty on oma (jos osoite tiedossa).
    Raw-osoite voi laahata hetken committia jäljessä, siksi odotetaan enintään wait sekuntia. Palauttaa (ok, selite)."""
    deadline = time.time() + wait
    note = "työntöä ei saatu varmistettua"
    while True:
        head = remote_head(repo, remote)
        head_ok = bool(head and commit and head.startswith(commit)) if commit not in (None, "ennallaan") else bool(head)
        got = remote_stamp(data_url) if data_url else None
        if data_url and got == stamp and (head_ok or head is None):
            return True, f"datavaraston paivitetty = {got}" + (f", HEAD {head[:10]}" if head else "")
        if not data_url and head_ok:
            return True, f"datavaraston HEAD {head[:10]} = työnnetty commit"
        if head is not None and not head_ok:
            note = f"datavaraston HEAD {head[:10]} ei ole työnnetty commit {str(commit)[:10]}"
        elif data_url and got is None:
            note = "datavaraston raw-osoitetta ei saatu luettua"
        elif data_url and got != stamp:
            note = f"datavaraston paivitetty {got} ≠ oma {stamp}"
        if time.time() >= deadline:
            return False, note
        time.sleep(5 * MIRROR_WAIT)


def mirror(data_path, settings, message=None, data_url=None, tries=3):
    """Työntää data.json-tiedoston datavarastoon ghpush.py:llä (avain vain ympäristömuuttujassa) ja varmistaa työnnön.
    Palauttaa (tila, viesti): tila True = peilattu ja varmistettu, False = epäonnistui, None = asetus puuttuu (ohitettu)."""
    repo, token = str(settings.get("github_repo") or "").strip(), str(settings.get("github_token") or "").strip()
    data_url = data_url or settings.get("data_url")
    remote = settings.get("github_remote")   # vain testit tai oma git-palvelin: git-osoite gist.github.comin sijaan
    if not repo or not token:
        return None, "PEILAUS: asetus puuttuu (github_repo tai github_token)"
    if not re.fullmatch(r"[\w.-]+/[\w.-]+|gist:[0-9a-fA-F]{8,}", repo):
        return False, "PEILAUS EPÄONNISTUI: github_repo ei ole muodossa gist:tunnus tai omistaja/varasto"
    tool = find_tool("ghpush.py")
    if not tool:
        return False, "PEILAUS EPÄONNISTUI: ghpush.py puuttuu (hae tools/ghpush.py.txt ja kopioi työhakemistoon nimelle ghpush.py)"
    stamp = load(data_path).get("paivitetty") or ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", stamp)
    message = message or (f"LAKI-TV {int(m.group(3))}.{int(m.group(2))}. klo {m.group(4)}.{m.group(5)}" if m else "LAKI-TV: sisällön päivitys")
    env = {**os.environ, "GITHUB_TOKEN": token}
    last = "ghpush ei tulostanut mitään"
    for i in range(tries):
        try:
            r = subprocess.run([sys.executable, tool, repo, "-m", message, *(["--remote", remote] if remote else []), f"{data_path}=data.json"],
                               env=env, capture_output=True, text=True, timeout=300)
            out = mask((r.stdout + "\n" + r.stderr).strip(), [token])
        except subprocess.TimeoutExpired:
            r, out = None, "ghpush: aikakatkaisu (300 s)"
        if r is None or r.returncode != 0:
            last = out[-400:]
            if "validate hylkäsi" in out or "sallittujen" in out or "tunnukselta" in out:   # ei korjaannu toistamalla
                return False, f"PEILAUS EPÄONNISTUI: {last}"
            time.sleep(5 * (i + 1) * MIRROR_WAIT)
            continue
        cm = re.search(r"OK: commit ([0-9a-f]{7,40})", out)
        commit = cm.group(1) if cm else ("ennallaan" if "Ei muutoksia" in out else None)
        ok, note = verify_mirror(repo, data_url, stamp, commit, remote=remote)
        if ok:
            return True, f"PEILAUS OK: commit {commit[:10] if commit and commit != 'ennallaan' else commit}; {note}"
        last = note
        time.sleep(5 * (i + 1) * MIRROR_WAIT)
    return False, f"PEILAUS EPÄONNISTUI: {mask(last, [token])}"


def cmd_peilaa(data, asetukset, message=None, data_url=None):
    """Vain peilaus: data.json datavarastoon ja työnnön varmistus (varmistusajot)."""
    state, msg = mirror(data, read_settings(asetukset), message, data_url)
    print(msg)
    if state is False:
        sys.exit(3)


def cmd_julkaise(page, data, out, outdir="jakelu", asetukset=None, message=None, data_url=None, no_mirror=False, viikko=None):
    """Yksi komento ennen artefaktin julkaisua: validate (virheet pysäyttävät, mitään ei kirjoiteta) -> UUSI.html (inject)
    -> jakelutiedostot (feed; maanantaina myös viikkokatsaus) -> peilaus datavarastoon varmistuksineen.
    Paluukoodi 0 = kaikki tehty; 1 = validate hylkäsi; 3 = sivu ja jakelutiedostot tehty, mutta peilaus epäonnistui
    (julkaise artefakti silti ja kirjaa syy raporttiin)."""
    d = load(data)
    errs, warns = validate(d)
    for w in warns:
        print("HUOM:", w)
    if errs:
        for e in errs:
            print("VIRHE:", e)
        sys.exit("Ei kirjoitettu: korjaa virheet ja aja julkaise uudelleen.")
    try:
        age_h = (now() - datetime.datetime.fromisoformat(d.get("paivitetty"))).total_seconds() / 3600
        if age_h > 0.75:
            print(f"HUOM: paivitetty on {age_h:.1f} h vanha – ajoitko stamp-komennon ennen julkaisua?")
    except (TypeError, ValueError):
        print("HUOM: paivitetty puuttuu tai ei jäsenny")
    cmd_inject(page, data, out)
    cmd_feed(data, outdir)
    if viikko is None:
        viikko = now().weekday() == 0
    if viikko:
        try:
            cmd_viikkokatsaus(data, os.path.join(outdir, "viikkokatsaus"))
        except Exception as e:   # viikkokatsaus ei saa estää julkaisua
            print(f"HUOM: viikkokatsaus ei onnistunut ({type(e).__name__}); julkaise ilman sitä")
    if no_mirror:
        print("PEILAUS: ohitettu (--ei-peilausta)")
        return
    state, msg = mirror(data, read_settings(asetukset), message, data_url)
    print(msg)
    if state is False:
        print(f"{out} ja {outdir}/ ovat valmiit: julkaise artefakti silti ja kirjaa raporttiin, että peilaus epäonnistui.")
        sys.exit(3)


# ---------------------------------------------------------------- CLI
def main(a):
    if len(a) < 2 or a[1] in ("-h", "--help", "help"):
        print(__doc__)
        return
    c = a[1]
    opt = lambda name, default=None, cast=str: cast(a[a.index(name) + 1]) if name in a else default
    set_base(opt("--base", os.environ.get("LAKITV_BASE", "")))
    if c == "extract":
        cmd_extract(a[2], a[3])
    elif c == "inject":
        cmd_inject(a[2], a[3], a[4], force="--force" in a)
    elif c == "prune":
        d = load(a[2]); prune(d); save(a[2], d)
    elif c == "validate":
        cmd_validate(a[2])
    elif c == "scan":
        cmd_scan(a[2], hours=opt("--hours", None, float), include_seen="--all" in a)
    elif c == "text":
        cmd_text(a[2], opt("--max", 6000, int))
    elif c == "add":
        cmd_add(a[2], a[3], a[4])
    elif c == "he-update":
        cmd_he_update(a[2])
    elif c == "he-range":
        cmd_he_range(int(a[2]), int(a[3]))
    elif c == "vt-update":
        cmd_vt_update(a[2])
    elif c == "tidy":
        cmd_tidy(a[2])
    elif c == "status":
        cmd_status(a[2])
    elif c == "stamp":
        cmd_stamp(a[2])
    elif c == "diff":
        cmd_diff(a[2], a[3])
    elif c == "digest":
        cmd_digest(a[2], opt("--laji", "aamu"), opt("--kieli", "fi"), opt("--kanavat"), opt("--aiheet"), opt("--since"), opt("--out"), opt("--tilaukset"), opt("--muoto"))
    elif c == "feed":
        cmd_feed(a[2], opt("--out", "."))
    elif c == "viikkokatsaus":
        cmd_viikkokatsaus(a[2], opt("--out", "viikkokatsaus"), opt("--kieli", "fi"))
    elif c == "post":
        if "--asetukset" in a:   # webhook-osoite asetustiedostosta (slack_webhook / teams_webhook), ei komentoriviltä
            kanava = opt("--kanava", "slack")
            url = read_settings(opt("--asetukset")).get(f"{kanava}_webhook") or ""
            if not str(url).strip():
                print(f"Ei lähetetty: {kanava}_webhook puuttuu asetuksista."); return
            cmd_post(a[2], str(url).strip())
        else:
            cmd_post(a[2], a[3])
    elif c == "peilaa":
        cmd_peilaa(a[2], opt("--asetukset"), opt("--viesti"), opt("--data-url"))
    elif c == "julkaise":
        cmd_julkaise(a[2], a[3], a[4], opt("--out", "jakelu"), opt("--asetukset"), opt("--viesti"), opt("--data-url"),
                     no_mirror="--ei-peilausta" in a, viikko=True if "--viikkokatsaus" in a else (False if "--ei-viikkokatsausta" in a else None))
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv)
