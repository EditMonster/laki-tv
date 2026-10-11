#!/usr/bin/env python3
"""Työntää tiedostot GitHub-varastoon yhtenä committina.

  python3 tools/ghpush.py OMISTAJA/VARASTO [--branch main] [-m viesti] [--via auto|api|git] LÄHDE=KOHDE [LÄHDE=KOHDE …]

LÄHDE on tiedosto tai kansio (kansion tiedostot menevät KOHDE/-kansioon). Muuttumattomat tiedostot ohitetaan;
jos mikään ei muuttunut, committia ei tehdä.

Tavat:
  api  Git Data -rajapinta, tunnus ympäristömuuttujassa GITHUB_TOKEN (fine-grained PAT, Contents: read/write kyseiseen varastoon).
  git  git clone --depth 1 + commit + push HTTPS:n yli; tunnus tulee git-ympäristöstä (Claude-istunnon git-välityspalvelin,
       credential helper tai GITHUB_TOKEN). Tämä on tapa, joka toimii päivitysajossa.
  auto GITHUB_TOKEN -> api; muuten git, jos git-ohjelma löytyy; muuten `gh api` (Claude-istunnon gh ei salli kirjoituksia, joten
       se toimii vain oikean GitHub CLI:n kanssa).

Turvarajat: oletuksena vain data.json ja source/-kansio kelpaavat kohteiksi (--allow laajentaa), tiedosto enintään 5 Mt,
ja tunnukselta näyttävä sisältö (webhook-osoite, token, yksityinen avain) pysäyttää työnnön. Mitään ei koskaan poisteta.

Päivitysajo työntää vain datan; sivusto rakennetaan varaston omasta koodista GitHub Actionsissa:
  python3 tools/ghpush.py omistaja/laki-tv -m "LAKI-TV 4.10. klo 06.48" data.json=data.json"""
import argparse, base64, hashlib, json, os, re, shutil, subprocess, sys, tempfile, urllib.request, urllib.error

API = "https://api.github.com"
SKIP = {"slack.json", "teams.json", ".DS_Store"}
AUTHOR = ["-c", "user.name=LAKI-TV", "-c", "user.email=laki-tv@users.noreply.github.com"]
# Turvarajat: päivitysajo saa työntää vain datan (sivuston koodi tulee varastosta, ei ajosta); muut kohteet vaativat --allow.
ALLOW_DEFAULT = ["data.json", "source/"]
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
def run_git(args, cwd=None, check=True):
    r = subprocess.run(["git", *AUTHOR, *args], cwd=cwd, capture_output=True, text=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if check and r.returncode != 0:
        raise SystemExit(f"git {' '.join(args[:2])} epäonnistui: {(r.stderr or r.stdout).strip()[-400:]}")
    return r


def push_git(repo, branch, message, files, remote, dry):
    if not shutil.which("git"):
        raise SystemExit("git-ohjelmaa ei ole")
    url = remote or f"https://github.com/{repo}.git"
    tmp = tempfile.mkdtemp(prefix="ghpush-")
    try:
        run_git(["clone", "--quiet", "--depth", "1", "--branch", branch, url, tmp])
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
        r = run_git(["push", "--quiet", "origin", f"HEAD:{branch}"], cwd=tmp, check=False)
        if r.returncode != 0:   # joku ehti väliin: nouda ja yritä kerran uudelleen
            run_git(["pull", "--quiet", "--rebase", "origin", branch], cwd=tmp)
            run_git(["push", "--quiet", "origin", f"HEAD:{branch}"], cwd=tmp)
        sha = run_git(["rev-parse", "HEAD"], cwd=tmp).stdout.strip()
        print(f"OK: commit {sha[:10]} -> {repo}@{branch}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", help="omistaja/varasto")
    ap.add_argument("pairs", nargs="+", help="LÄHDE=KOHDE")
    ap.add_argument("--branch", default="main")
    ap.add_argument("-m", "--message", default="LAKI-TV: sisällön päivitys")
    ap.add_argument("--via", choices=["auto", "api", "git"], default="auto")
    ap.add_argument("--remote", help="git-osoite (oletus https://github.com/OMISTAJA/VARASTO.git)")
    ap.add_argument("--allow", action="append", help="sallittu kohdepolku tai kansio/ (oletus: data.json ja source/)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", a.repo):
        raise SystemExit("varasto muodossa omistaja/nimi")
    files = collect(a.pairs)
    if not files:
        raise SystemExit("ei tiedostoja")
    guard(files, a.allow or ALLOW_DEFAULT)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    via = a.via
    if via == "auto":
        via = "api" if token else "git" if shutil.which("git") else "api"
    if via == "git":
        push_git(a.repo, a.branch, a.message, files, a.remote, a.dry_run)
    else:
        push_api(a.repo, a.branch, a.message, files, token, a.dry_run)


if __name__ == "__main__":
    main()
