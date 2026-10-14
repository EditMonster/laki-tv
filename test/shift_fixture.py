"""Siirtää kiinteän testidatan (30.9.2026) päivämäärät tähän päivään, jotta aikariippuvat testit pysyvät vakaina."""
import re, json, datetime, sys
import os as _os
_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # varaston juuri
_FONTS = _os.path.join(_ROOT, 'fonts') if _os.path.isdir(_os.path.join(_ROOT, 'fonts')) else _os.path.join(_ROOT, '..', 'fonts')
sys.path.insert(0, _ROOT + "/tools")
import lakitv as L
B = _ROOT + "/"
base = datetime.date(2026, 9, 30); today = L.now().date(); delta = (today - base).days
s = open(B + "sec/data_0930.json", encoding="utf-8").read()
def shift(m):
    try:
        d = datetime.date.fromisoformat(m.group(0))
    except ValueError:
        return m.group(0)
    return (d + datetime.timedelta(days=delta)).isoformat() if d >= datetime.date(2026, 1, 1) else m.group(0)
s = re.sub(r"\d{4}-\d{2}-\d{2}", shift, s)
d = json.loads(s)
# päivitysaika: tänään klo 06.48, jotta "päivitys myöhässä" -varoitus ei laukea
d["paivitetty"] = today.isoformat() + "T06:48:00+03:00"
# testidatan jutut ovat yhden sivun mallia vanhempia: siirretty lisatty ei saa tehdä niistä "uusia" (tiukat sanarajat, YLI SIVUN -virhe)
cap = (datetime.date.fromisoformat(L.ONE_PAGE_SINCE) - datetime.timedelta(days=1)).isoformat() + "T06:50"
for lst in d["kanavat"].values():
    for it in lst:
        if str(it.get("lisatty") or "") >= L.ONE_PAGE_SINCE:
            it["lisatty"] = cap
json.dump(d, open(B + "test/fixture_data.json", "w", encoding="utf-8"), ensure_ascii=False)
print(f"fixture: +{delta} pv")
