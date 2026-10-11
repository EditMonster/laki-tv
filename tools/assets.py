#!/usr/bin/env python3
"""Luo sivuston kuvakkeet ja jakokuvan: icon.svg, icon-192.png, icon-512.png, og.png.

Kuvake on keltainen mosaiikki-L teksti-TV:n sinisellä. Jakokuva (1200×630) on sivun 100 oikea näkymä annetusta
HTML-tiedostosta, kello pysäytettynä datan päivityshetkeen, jotta kuva vastaa sisältöä. Tarvitsee Playwrightin ja Chromiumin.

  python3 tools/assets.py                              # assets/ projektin preview.html:stä
  python3 tools/assets.py --page site/index.html --out site --og-only   # CI: päivitä vain jakokuva"""
import argparse, datetime, json, os, re, zoneinfo
HKI = zoneinfo.ZoneInfo("Europe/Helsinki")
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="RX" fill="#0a0acc"/>
<g fill="#ffe600">
<rect x="13" y="9" width="15" height="15"/><rect x="13" y="25" width="15" height="15"/><rect x="13" y="41" width="15" height="15"/>
<rect x="29" y="41" width="11" height="15"/><rect x="41" y="41" width="11" height="15"/>
</g>
</svg>
"""
# Kuvake: teksti-TV:n sininen otsikkopalkki ja keltainen mosaiikki-L (sivun 100 otsikon värit). Selainvälilehdessä pyöristetty,
# sovelluskuvakkeena (192/512) täysi neliö, koska iOS ja Android pyöristävät itse.
icon_svg = lambda rx: ICON.replace("RX", str(rx))


def stamp_of(page_path):
    """Datan päivityshetki (paivitetty) sivusta; puuttuessa nyt."""
    try:
        src = open(page_path, encoding="utf-8").read()
        m = re.search(r'id="laki-tv-data"[^>]*>(.*?)</script>', src, re.S)
        d = json.loads(m.group(1).replace("<\\/", "</"))
        t = d.get("paivitetty") or ""
        return datetime.datetime.fromisoformat(t[:16]).replace(tzinfo=HKI)
    except Exception:
        return datetime.datetime.now(HKI)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", default=os.path.join(ROOT, "preview.html"))
    ap.add_argument("--out", default=os.path.join(ROOT, "assets"))
    ap.add_argument("--og-only", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        if not a.og_only:
            open(os.path.join(a.out, "icon.svg"), "w", encoding="utf-8").write(icon_svg(12))
            for size in (192, 512):
                pg = b.new_page(viewport={"width": size, "height": size})
                pg.set_content('<!doctype html><html><body style="margin:0;background:transparent">' + icon_svg(0).replace('viewBox="0 0 64 64"', f'viewBox="0 0 64 64" width="{size}" height="{size}"') + "</body></html>")
                pg.locator("svg").screenshot(path=os.path.join(a.out, f"icon-{size}.png"), omit_background=True)
                pg.close()
        pg = b.new_page(viewport={"width": 1200, "height": 630})
        t = stamp_of(a.page)
        pg.clock.set_fixed_time(t.replace(second=0))
        pg.goto("file://" + os.path.abspath(a.page) + "#p100")
        pg.wait_for_timeout(900)
        pg.evaluate("document.querySelectorAll('*').forEach(e => { const s = getComputedStyle(e); if (s.animationName !== 'none') e.style.animation = 'none'; })")
        pg.screenshot(path=os.path.join(a.out, "og.png"), clip={"x": 0, "y": 0, "width": 1200, "height": 630})
        b.close()
    for n in (["og.png"] if a.og_only else ["icon.svg", "icon-192.png", "icon-512.png", "og.png"]):
        print(f"{n}: {os.path.getsize(os.path.join(a.out, n)) // 1024} kt")


if __name__ == "__main__":
    main()
