#!/usr/bin/env python3
"""Työntää tiedostot GitHub-varastoon yhtenä committina.

  python3 tools/ghpush.py OMISTAJA/VARASTO [--branch main] [-m viesti] [--via auto|api|git] LÄHDE=KOHDE [LÄHDE=KOHDE …]

LÄHDE on tiedosto tai kansio (kansion tiedostot menevät KOHDE/-kansioon). Muuttumattomat tiedostot ohitetaan;
jos mikään ei muuttunut, committia ei tehdä.

Tavat:
  git  git clone --depth 1 + commit + push HTTPS:n yli. Avain ympäristömuuttujassa GITHUB_TOKEN annetaan gitille
       credential helperin kautta: se ei näy komentorivillä, osoitteissa eikä virheilmoituksissa. Ilman avainta
       työnnön onnistuminen riippuu ympäristön omista git-tunnuksista.
  api  Git Data -rajapinta (api.github.com) avaimella GITHUB_TOKEN. Ei toimi Claude-istunnossa, jonka välityspalvelin
       rajaa api.github.com-pyynnöt; tarkoitettu tavalliseen ympäristöön.
  auto git, jos git-ohjelma löytyy; muuten api.

Turvamalli (päivitysajo):
  * Avain on fine-grained personal access token, joka on rajattu VAIN erilliseen data-varastoon (esim. omistaja/laki-tv-data)
    ja Contents: read and write -oikeuteen. Sivuston koodivarastoon avain ei ulotu; sivusto hakee datan data-varastosta
    GitHub Actionsissa ja tarkistaa sen (validate) ennen julkaisua.
  * Oletuksena vain data.json kelpaa kohteeksi (--allow laajentaa), tiedosto enintään 5 Mt, ja tunnukselta näyttävä sisältö
    (webhook-osoite, token, yksityinen avain) pysäyttää työnnön. Mitään ei koskaan poisteta.

  GITHUB_TOKEN=… python3 tools/ghpush.py omistaja/laki-tv-data -m "LAKI-TV 12.10. klo 06.49" data.json=data.json"""
import argparse, base64, hashlib, json, os, re, shutil, subprocess, sys, tempfile, urllib.request, urllib.error

API = "https://api.github.com"
SKIP = {"slack.json", "teams.json", ".DS_Store"}
AUTHOR = ["-c", "user.name=LAKI-TV", "-c", "user.email=laki-tv@users.noreply.github.com"]
# Turvarajat: päivitysajo saa työntää vain datan (sivuston koodi tulee varastosta, ei ajosta); muut kohteet vaativat --allow.
ALLOW_DEFAULT = ["data.json"]
MAX_BYTES = 5 * 1024 * 1024
SECRETS = re.compile(r"hooks\.slack\.com/services/[A-Za-z0-9]|logic\.azure\.com/[^\s\"']{20,}|webhook\.office\.com/[^\s\"']{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----")


def guard(files, allow):
    """Hylkää kohteet sallittujen polkujen ulkopuolella, liian suuret tiedostot ja tiedostot, joissa näyttää olevan tunnuksia."""
    for p, d in files.items():
        if not any(p == a or (a.endswith("/") and p.startswith(a)) for a in allow):
            raise SystemExit(f"kohde {p!r} ei ole sallittujen joukossa ({', '.join(allow)}); käytä --allow, jos tämä on tarkoitus")
        if len(d) > MAX_BYTES:
            raise SystemExit(f"{p}: {len(d) // 1024} kt ylittää rajan {MAX_BYTES // 1024 // 1024} Mt")
        if not p.endswith((".pdf", ".png", ".woff2", ".jpg")) and SECRETS.search(d.decode("utf-8", "replace")):
            raise SystemExit(f"{p}: sisältää tunnukselta näyttävän merkkijonon – ei työnnetä")


def git_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def collect(pairs):
    files = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"odotettiin LÄHDE=KOHDE, saatiin {pair!r}")
        src, dst = pair.split("=", 1)
        dst = dst.strip("/").replace("\\", "/")
        if not dst or dst.startswith("../") or "/../" in dst or dst.startswith(".git/") or dst == ".git":
            raise SystemExit(f"kohde ei kelpaa: {dst!r}")
        if os.path.isdir(src):
            for n in sorted(os.listdir(src)):
                p = os.path.join(src, n)
                if os.path.isfile(p) and n not in SKIP and not n.startswith("."):
                    files[f"{dst}/{n}"] = open(p, "rb").read()
        elif os.path.isfile(src):
            files[dst] = open(src, "rb").read()
        else:
            raise SystemExit(f"lähdettä ei ole: {src}")
    return files


# ---------------------------------------------------------------- api
class GH:
    def __init__(self, repo, token):
        self.repo, self.token = repo, token

    def call(self, method, path, body=None):
        if self.token:
            req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                                                  "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "laki-tv-ghpush", "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.loads(r.read() or b"null")
            except urllib.error.HTTPError as e:
                raise SystemExit(f"GitHub {method} {path}: HTTP {e.code} {e.read()[:300].decode(errors='replace')}")
        cmd = ["gh", "api", "-X", method, path, "-H", "Accept: application/vnd.github+json"]
        inp = None
        if body is not None:
            cmd += ["--input", "-"]; inp = json.dumps(body)
        r = subprocess.run(cmd, input=inp, capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"gh api {method} {path} epäonnistui: {(r.stderr or r.stdout).strip()[:400]}")
        return json.loads(r.stdout or "null")


def push_api(repo, branch, message, files, token, dry):
    gh = GH(repo, token); R = f"/repos/{repo}"
    head = gh.call("GET", f"{R}/git/ref/heads/{branch}")["object"]["sha"]
    commit = gh.call("GET", f"{R}/git/commits/{head}")
    tree = gh.call("GET", f"{R}/git/trees/{commit['tree']['sha']}?recursive=1")
    existing = {e["path"]: e["sha"] for e in tree.get("tree", []) if e["type"] == "blob"}
    changed = {p: d for p, d in files.items() if existing.get(p) != git_sha(d)}
    if not changed:
        print("Ei muutoksia: varasto on ajan tasalla."); return
    print(f"Muuttuu {len(changed)}/{len(files)}: " + ", ".join(sorted(changed)))
    if dry:
        return
    entries = []
    for p, d in changed.items():
        blob = gh.call("POST", f"{R}/git/blobs", {"content": base64.b64encode(d).decode(), "encoding": "base64"})
        entries.append({"path": p, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    new_tree = gh.call("POST", f"{R}/git/trees", {"base_tree": commit["tree"]["sha"], "tree": entries})
    new_commit = gh.call("POST", f"{R}/git/commits", {"message": message, "tree": new_tree["sha"], "parents": [head]})
    gh.call("PATCH", f"{R}/git/refs/heads/{branch}", {"sha": new_commit["sha"], "force": False})
    print(f"OK: commit {new_commit['sha'][:10]} -> {repo}@{branch}")


# ---------------------------------------------------------------- git
def run_git(args, cwd=None, check=True, cfg=(), env=None):
    r = subprocess.run(["git", *AUTHOR, *cfg, *args], cwd=cwd, capture_output=True, text=True,
                       env={**(env or os.environ), "GIT_TERMINAL_PROMPT": "0"})
    if check and r.returncode != 0:
        msg = (r.stderr or r.stdout).strip()[-400:]
        if "Authentication failed" in msg or "Invalid username or token" in msg or "403" in msg:
            msg += "\n  -> tarkista GITHUB_TOKEN: fine-grained token, vain data-varasto, Contents: read and write, ei vanhentunut"
        raise SystemExit(f"git {' '.join(args[:2])} epäonnistui: {msg}")
    return r


def credential_helper(token):
    """Credential helper, joka antaa avaimen gitille ympäristömuuttujasta: avain ei päädy komentoriville, osoitteeseen,
    git-asetuksiin eikä virheilmoituksiin. Palauttaa (git -c -asetukset, ympäristö, siivottava kansio)."""
    d = tempfile.mkdtemp(prefix="ghpush-cred-")
    helper = os.path.join(d, "helper.sh")
    with open(helper, "w", encoding="utf-8") as f:
        f.write('#!/bin/sh\necho username=x-access-token\necho "password=$GHPUSH_TOKEN"\n')
    os.chmod(helper, 0o700)
    return ["-c", f"credential.helper={helper}"], {**os.environ, "GHPUSH_TOKEN": token}, d


def push_git(repo, branch, message, files, remote, dry, token=None):
    if not shutil.which("git"):
        raise SystemExit("git-ohjelmaa ei ole")
    url = remote or f"https://github.com/{repo}.git"
    tmp = tempfile.mkdtemp(prefix="ghpush-")
    cfg, env, cred_dir = credential_helper(token) if token else ([], None, None)
    try:
        run_git(["clone", "--quiet", "--depth", "1", "--branch", branch, url, tmp], cfg=cfg, env=env)
        changed = []
        for p, d in files.items():
            dst = os.path.join(tmp, p)
            if os.path.exists(dst) and git_sha(open(dst, "rb").read()) == git_sha(d):
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(d)
            changed.append(p)
        if not changed:
            print("Ei muutoksia: varasto on ajan tasalla."); return
        print(f"Muuttuu {len(changed)}/{len(files)}: " + ", ".join(sorted(changed)))
        if dry:
            return
        run_git(["add", "-A", "--", *changed], cwd=tmp)
        run_git(["commit", "--quiet", "-m", message], cwd=tmp)
        r = run_git(["push", "--quiet", "origin", f"HEAD:{branch}"], cwd=tmp, check=False, cfg=cfg, env=env)
        if r.returncode != 0:
            if "rejected" in (r.stderr or "") and "fetch first" in (r.stderr or ""):   # joku ehti väliin: nouda ja yritä kerran uudelleen
                run_git(["pull", "--quiet", "--rebase", "origin", branch], cwd=tmp, cfg=cfg, env=env)
                run_git(["push", "--quiet", "origin", f"HEAD:{branch}"], cwd=tmp, cfg=cfg, env=env)
            else:
                run_git(["push", "--quiet", "origin", f"HEAD:{branch}"], cwd=tmp, cfg=cfg, env=env)   # sama virhe uudelleen, nyt selitteen kanssa
        sha = run_git(["rev-parse", "HEAD"], cwd=tmp).stdout.strip()
        print(f"OK: commit {sha[:10]} -> {repo}@{branch}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if cred_dir:
            shutil.rmtree(cred_dir, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", help="omistaja/varasto")
    ap.add_argument("pairs", nargs="+", help="LÄHDE=KOHDE")
    ap.add_argument("--branch", default="main")
    ap.add_argument("-m", "--message", default="LAKI-TV: sisällön päivitys")
    ap.add_argument("--via", choices=["auto", "api", "git"], default="auto")
    ap.add_argument("--remote", help="git-osoite (oletus https://github.com/OMISTAJA/VARASTO.git)")
    ap.add_argument("--allow", action="append", help="sallittu kohdepolku tai kansio/ (oletus: vain data.json)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", a.repo):
        raise SystemExit("varasto muodossa omistaja/nimi")
    files = collect(a.pairs)
    if not files:
        raise SystemExit("ei tiedostoja")
    guard(files, a.allow or ALLOW_DEFAULT)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if a.remote and re.search(r"://[^/]*:[^/@]+@", a.remote):
        raise SystemExit("älä laita avainta --remote-osoitteeseen; anna se ympäristömuuttujassa GITHUB_TOKEN")
    via = a.via
    if via == "auto":
        via = "git" if shutil.which("git") else "api"
    if via == "git":
        push_git(a.repo, a.branch, a.message, files, a.remote, a.dry_run, token)
    else:
        push_api(a.repo, a.branch, a.message, files, token, a.dry_run)


if __name__ == "__main__":
    main()
