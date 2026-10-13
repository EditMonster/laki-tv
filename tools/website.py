#!/usr/bin/env python3
"""Rakentaa julkaistavan verkkosivuston (GitHub Pages, Cloudflare Pages tai mikä tahansa staattinen palvelin).

Lähde on joko paikallinen rakennus (--page laki-tv.html --feeds out) tai artifaktista haettu kansio (--from-dir fetched,
ks. tools/mirror.py). Tulos on kansio, jossa on index.html (hakukone- ja jakotiedot, PWA), syötteet, kalenteri .ics-nimellä,
manifest, service worker, kuvakkeet ja robots.txt.

  python3 tools/website.py --page laki-tv.html --feeds out --out site --base https://kayttaja.github.io/laki-tv/
  python3 tools/website.py --from-dir fetched --out site --base https://laki-tv.fi/ --domain laki-tv.fi

Ympäristömuuttujat LAKITV_BASE, LAKITV_DOMAIN ja LAKITV_DATA_URL toimivat --base-, --domain- ja --data-url-valitsimien tilalla (GitHub Actions).
--data-url (datavaraston data.json) saa sivun hakemaan uusimman datan itse, jolloin sivusto on ajan tasalla, vaikka rakennusajo olisi myöhässä."""
import argparse, html, os, re, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FEEDS = ["feed.xml", "feed-sv.xml", "feed-en.xml", "feed.json", "lakitv.md", "viikkokatsaus.html", "viikkokatsaus.pdf"]
CAL = {"kalenteri.txt": "kalenteri.ics", "kalenteri-sv.txt": "kalenteri-sv.ics", "kalenteri-en.txt": "kalenteri-en.ics"}
ASSETS = ["icon.svg", "icon-32.png", "icon-180.png", "icon-192.png", "icon-512.png", "og.png"]

DESC = {"fi": "Juridinen teksti-TV: KKO:n ja KHO:n ennakkopäätökset, EU-tuomioistuimen ja EIT:n ratkaisut, hallituksen esitykset, "
              "lausuntokierrokset ja voimaan tulevat lait kolmella kielellä. Päivittyy kahdesti päivässä."}


def page_body(src):
    """Palauttaa sivun sisällön ilman isännän dokumenttikäärettä (doctype/head/body) ja ilman sivun omaa <title>-tagia."""
    m = re.search(r"<body[^>]*>", src[:20000], re.I)
    if m and re.match(r"\s*(<!doctype|<html)", src, re.I):
        src = src[m.end():]
        end = src.lower().rfind("</body>")
        if end >= 0:
            src = src[:end]
    return re.sub(r"^\s*<title>[^<]*</title>\s*", "", src, count=1)


def ics_fold(text):
    """RFC 5545: rivit enintään 75 oktettia, jatkorivi alkaa välilyönnillä (katkaisu merkkirajalla)."""
    out = []
    for line in text.split("\r\n"):
        cur, n, first = "", 0, True
        for ch in line:
            b = len(ch.encode("utf-8")); lim = 75 if first else 74
            if n + b > lim:
                out.append(cur if first else " " + cur); cur, n, first = ch, b, False
            else:
                cur += ch; n += b
        out.append(cur if first else " " + cur)
    return "\r\n".join(out)


def rebase(text, base):
    """Vaihtaa artifaktin osoitteen sivuston osoitteeksi syötteissä (…/artifact/ID#p100 -> https://sivusto/#p100, …/artifact/ID/feed.xml -> https://sivusto/feed.xml)."""
    if not base:
        return text
    return re.sub(r"https://claude\.ai/(?:code/)?artifact/[A-Za-z0-9_-]+(/)?", lambda m: base, text)


def head(base, domain, data_url=""):
    canon = base or ""
    og_img = (base + "og.png") if base else "og.png"
    H = ['<!doctype html>', '<html lang="fi">', '<head>', '<meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">',
         '<title>LAKI-TV – juridinen teksti-TV</title>',
         f'<meta name="description" content="{html.escape(DESC["fi"])}">',
         '<meta name="robots" content="index,follow">', '<meta name="theme-color" content="#000000">',
         '<meta name="color-scheme" content="dark">', '<meta name="referrer" content="no-referrer">',
         '<meta property="og:type" content="website">', '<meta property="og:title" content="LAKI-TV – juridinen teksti-TV">',
         f'<meta property="og:description" content="{html.escape(DESC["fi"])}">', f'<meta property="og:image" content="{og_img}">',
         '<meta property="og:image:width" content="1200">', '<meta property="og:image:height" content="630">', '<meta property="og:locale" content="fi_FI">',
         '<meta name="twitter:card" content="summary_large_image">',
         '<link rel="icon" href="icon.svg" type="image/svg+xml">', '<link rel="icon" href="icon-32.png" type="image/png" sizes="32x32">',
         '<link rel="apple-touch-icon" href="icon-180.png" sizes="180x180">',
         '<link rel="manifest" href="manifest.webmanifest">',
         '<link rel="alternate" type="application/rss+xml" title="LAKI-TV (fi)" href="feed.xml">',
         '<link rel="alternate" type="application/rss+xml" title="LAKI-TV (sv)" href="feed-sv.xml">',
         '<link rel="alternate" type="application/rss+xml" title="LAKI-TV (en)" href="feed-en.xml">',
         '<link rel="alternate" type="application/feed+json" title="LAKI-TV (JSON)" href="feed.json">']
    if canon:
        H.append(f'<link rel="canonical" href="{html.escape(canon)}">')
        H.append(f'<meta property="og:url" content="{html.escape(canon)}">')
    if data_url:   # suora data: sivu hakee uusimman data.jsonin tästä osoitteesta (ks. part_js.html, liveRefresh)
        H.append(f'<meta name="lakitv-data" content="{html.escape(data_url)}">')
    H += ['<style>html,body{margin:0;padding:0;background:#000}</style>', '</head>', '<body>']
    return "\n".join(H) + "\n"


TAIL = """
<noscript><p style="font:16px/1.5 sans-serif;color:#eee;padding:24px">LAKI-TV tarvitsee JavaScriptin. Syötteet toimivat ilman: <a style="color:#ff0" href="feed.xml">RSS</a>, <a style="color:#ff0" href="feed.json">JSON</a>, <a style="color:#ff0" href="lakitv.md">Markdown</a>, <a style="color:#ff0" href="kalenteri.ics">kalenteri</a>.</p></noscript>
<script>if("serviceWorker"in navigator&&(location.protocol==="https:"||location.hostname==="localhost"))addEventListener("load",()=>navigator.serviceWorker.register("./sw.js").catch(()=>{}));</script>
</body>
</html>
"""

MANIFEST = """{
  "name": "LAKI-TV – juridinen teksti-TV",
  "short_name": "LAKI-TV",
  "description": "%s",
  "lang": "fi",
  "start_url": "./",
  "scope": "./",
  "display": "standalone",
  "orientation": "any",
  "background_color": "#000000",
  "theme_color": "#000000",
  "icons": [
    {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
    {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
    {"src": "icon.svg", "sizes": "any", "type": "image/svg+xml"}
  ]
}
""" % DESC["fi"]

SW = """/* LAKI-TV: verkko ensin, välimuisti varalla (viimeisin haettu sisältö näkyy myös ilman yhteyttä). */
const CACHE = "lakitv-v2";
const SCOPE = self.registration.scope;
self.addEventListener("install", e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll([SCOPE, "manifest.webmanifest", "icon.svg"]).catch(() => {}))); self.skipWaiting(); });
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  const r = e.request;
  if (r.method !== "GET" || new URL(r.url).origin !== self.location.origin) return;
  e.respondWith(fetch(r).then(res => {
    if (res.ok && res.type === "basic") { const copy = res.clone(); caches.open(CACHE).then(c => c.put(r, copy)).catch(() => {}); }
    return res;
  }).catch(async () => {
    const m = await caches.match(r, {ignoreSearch:true});
    if (m) return m;
    if (r.mode === "navigate") { const root = await caches.match(SCOPE); if (root) return root; }
    return new Response("LAKI-TV: ei yhteyttä.", {status:503, headers:{"Content-Type":"text/plain; charset=utf-8"}});
  }));
});
"""

ROBOTS = "User-agent: *\nAllow: /\n"

NOTFOUND = """<!doctype html><html lang="fi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>LAKI-TV – sivua ei löydy</title>
<style>body{margin:0;background:#000;color:#fff;font:18px/1.5 "Courier New",monospace;display:grid;place-items:center;min-height:100vh}a{color:#ff0}</style></head>
<body><div><p>P404 &nbsp; SIVUA EI LÖYDY</p><p><a href="./">▶ Etusivu 100</a></p></div></body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", help="rakennettu laki-tv.html")
    ap.add_argument("--feeds", help="kansio, jossa feed-komennon tiedostot")
    ap.add_argument("--from-dir", help="artifaktista haettu kansio (index.html + tiedostot)")
    ap.add_argument("--out", default="site")
    ap.add_argument("--base", default=os.environ.get("LAKITV_BASE", ""), help="sivuston osoite, esim. https://laki-tv.fi/")
    ap.add_argument("--domain", default=os.environ.get("LAKITV_DOMAIN", ""), help="oma domain (kirjoittaa CNAME-tiedoston)")
    ap.add_argument("--data-url", default=os.environ.get("LAKITV_DATA_URL", ""),
                    help="datavaraston data.json-osoite (https); sivu hakee siitä uusimman datan, vaikka rakennusajo olisi myöhässä")
    a = ap.parse_args()
    data_url = a.data_url.strip()
    if data_url and not re.fullmatch(r"https://[^\s\"'<>]+", data_url):
        sys.exit("VIRHE: --data-url ei ole https-osoite")
    if a.from_dir:
        feeds = a.from_dir
        page_path = next((os.path.join(a.from_dir, n) for n in ("laki-tv.html", "index.html") if os.path.exists(os.path.join(a.from_dir, n))), None)
        if not page_path:
            sys.exit(f"VIRHE: {a.from_dir}/laki-tv.html puuttuu")
    else:
        page_path = a.page or os.path.join(ROOT, "laki-tv.html"); feeds = a.feeds or os.path.join(ROOT, "out")
    src = open(page_path, encoding="utf-8").read()
    body = page_body(src)
    if 'id="laki-tv-data"' not in body or "<script>" not in body:
        sys.exit("VIRHE: lähde ei näytä LAKI-TV:n sivulta")
    for old, new in CAL.items():
        body = body.replace(old, new)
    base = a.base.strip()
    if base and not base.endswith("/"):
        base += "/"
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "index.html"), "w", encoding="utf-8") as f:
        f.write(head(base, a.domain, data_url) + body + TAIL)
    copied = []
    TEXTY = (".xml", ".json", ".md", ".html", ".txt", ".ics")
    def put(srcp, dstname):
        if dstname.endswith(TEXTY) and base:
            t = open(srcp, encoding="utf-8", newline="").read()
            if dstname.endswith(".ics"):
                t = ics_fold(rebase(t.replace("\r\n ", ""), base))   # pura taitto, vaihda osoitteet, taita uudelleen
            else:
                t = rebase(t, base)
            for o, n in CAL.items():
                t = t.replace(o, n)
            with open(os.path.join(a.out, dstname), "w", encoding="utf-8", newline="") as f:
                f.write(t)
        else:
            shutil.copy(srcp, os.path.join(a.out, dstname))
        copied.append(dstname)
    for name in FEEDS:
        p = os.path.join(feeds, name)
        if os.path.exists(p):
            put(p, name)
    for old, new in CAL.items():
        p = os.path.join(feeds, old)
        if os.path.exists(p):
            put(p, new)
    for name in ASSETS:
        p = os.path.join(ROOT, "assets", name)
        if os.path.exists(p):
            shutil.copy(p, os.path.join(a.out, name))
    open(os.path.join(a.out, "manifest.webmanifest"), "w", encoding="utf-8").write(MANIFEST)
    open(os.path.join(a.out, "sw.js"), "w", encoding="utf-8").write(SW)
    open(os.path.join(a.out, "robots.txt"), "w", encoding="utf-8").write(ROBOTS + (f"Sitemap: {base}sitemap.xml\n" if base else ""))
    open(os.path.join(a.out, "404.html"), "w", encoding="utf-8").write(NOTFOUND)
    if base:
        open(os.path.join(a.out, "sitemap.xml"), "w", encoding="utf-8").write(
            '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f'<url><loc>{html.escape(base)}</loc><changefreq>daily</changefreq></url></urlset>\n')
    if a.domain:
        open(os.path.join(a.out, "CNAME"), "w").write(a.domain.strip() + "\n")
    open(os.path.join(a.out, ".nojekyll"), "w").write("")
    size = os.path.getsize(os.path.join(a.out, "index.html"))
    print(f"OK: {a.out}/index.html ({size // 1024} kt), tiedostot: {', '.join(copied) or '–'}" + (f", CNAME {a.domain}" if a.domain else ""))


if __name__ == "__main__":
    main()
