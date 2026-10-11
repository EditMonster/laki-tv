"""Siirtää kiinteän testidatan (30.9.2026) päivämäärät tähän päivään, jotta aikariippuvat testit pysyvät vakaina."""
import os as _os
ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
import re, json, datetime, sys
sys.path.insert(0, ROOT + "/tools")
import lakitv as L
B = ROOT + "/"
base = datetime.date(2026, 9, 30); today = L.now().date(); delta = (today - base).days
s = open(B + "test/fixture_base.json", encoding="utf-8").read()
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
json.dump(d, open(B + "test/fixture_data.json", "w", encoding="utf-8"), ensure_ascii=False)
print(f"fixture: +{delta} pv")
