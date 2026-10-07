"""Where your data lives: a private GitHub repository (recommended), a GitHub Gist (older setups),
or a local folder when testing.

Private repository: every save is one commit containing all the files changed by that run. A commit only goes through
if nobody else saved in between (otherwise it re-reads and tries again), so a trade you record on your phone while the
engine is running is never overwritten.

Moving from the Gist: the first time the engine runs with DATA_REPO set and the repository has no state.json yet,
it copies every file from the Gist into the repository, then leaves a note (moved.json) in the Gist so the
dashboard knows to switch. The Gist itself is left as it was, as a backup."""
import base64, json, os, time
import requests

API = "https://api.github.com"


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "etf-signal-engine"}


class GistStore:
    kind = "gist"

    def __init__(self, gist_id, token):
        self.gist_id, self.token = gist_id, token
        self._cache = None

    def _gist(self):
        if self._cache is None:
            r = requests.get(f"{API}/gists/{self.gist_id}", headers=_headers(self.token), timeout=30)
            if r.status_code != 200:
                raise RuntimeError(f"Could not read the gist (HTTP {r.status_code}). Check GIST_ID and GIST_TOKEN.")
            self._cache = r.json().get("files", {})
        return self._cache

    def refresh(self):
        self._cache = None

    def names(self):
        return sorted(self._gist())

    def read(self, name, default=None):
        f = self._gist().get(name)
        if not f:
            return default
        txt = f.get("content", "")
        if f.get("truncated"):
            r = requests.get(f["raw_url"], headers=_headers(self.token), timeout=60)
            if r.status_code != 200:
                raise RuntimeError(f"Could not read {name} from the gist (HTTP {r.status_code}).")
            txt = r.text
        return json.loads(txt) if txt.strip() else default

    def write(self, files: dict):
        body = {"files": {n: {"content": json.dumps(o, separators=(",", ":"))} for n, o in files.items()}}
        r = requests.patch(f"{API}/gists/{self.gist_id}", headers=_headers(self.token), json=body, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"Could not save to the gist (HTTP {r.status_code}): {r.text[:150]}")
        self._cache = None


class RepoStore:
    kind = "repo"
    BRANCH = "main"

    def __init__(self, repo, token):
        # tolerate a pasted web address, ".git", spaces or a stray line break in the secrets
        repo = repo.strip()
        for pre in ("https://github.com/", "http://github.com/", "github.com/"):
            if repo.lower().startswith(pre):
                repo = repo[len(pre):]
        repo = repo.strip("/")
        if repo.endswith(".git"):
            repo = repo[:-4]
        self.repo, self.token = repo, token.strip()
        self._cache = {}
        self.s = requests.Session()
        self.s.headers.update(_headers(self.token))

    def refresh(self):
        self._cache = {}

    def _url(self, path):
        # no trailing slash: GitHub answers "Not Found" to /repos/owner/name/
        return f"{API}/repos/{self.repo}" + (f"/{path}" if path else "")

    def _check(self, r, what):
        if r.status_code in (401, 403):
            raise RuntimeError(f"GitHub refused access to the data repository while {what} (HTTP {r.status_code}). "
                               "Check DATA_TOKEN: a fine-grained token for that repository with Contents: read and write.")
        if r.status_code == 404:
            raise RuntimeError(f"Data repository {self.repo} not found while {what}. Check DATA_REPO (your-username/etf-data) "
                               "and that DATA_TOKEN can see it.")
        if r.status_code >= 300:
            raise RuntimeError(f"GitHub error while {what} (HTTP {r.status_code}): {r.text[:150]}")
        return r

    def _head(self):
        r = self.s.get(self._url(f"git/ref/heads/{self.BRANCH}"), timeout=30)
        if r.status_code == 409 or (r.status_code == 404 and "empty" in r.text.lower()):
            raise RuntimeError(f"The data repository {self.repo} is empty. Create it with “Add a README file” ticked.")
        if r.status_code == 404:
            # 404 can also mean the branch doesn't exist; check the repository itself for a clearer message
            self._check(self.s.get(self._url(""), timeout=30), "opening the repository")
            raise RuntimeError(f"The data repository {self.repo} has no '{self.BRANCH}' branch. Create it with “Add a README file” ticked.")
        return self._check(r, "reading the latest version").json()["object"]["sha"]

    def names(self):
        r = self._check(self.s.get(self._url(f"contents?ref={self.BRANCH}"), timeout=30), "listing files")
        return sorted(x["name"] for x in r.json() if x.get("type") == "file")

    def read(self, name, default=None):
        if name in self._cache:
            return self._cache[name]
        r = self.s.get(self._url(f"contents/{name}"), params={"ref": self.BRANCH},
                       headers={"Accept": "application/vnd.github.raw+json"}, timeout=60)
        if r.status_code == 404:
            if "empty" in r.text.lower():
                raise RuntimeError(f"The data repository {self.repo} is empty. Create it with “Add a README file” ticked.")
            self._repo_ok()                 # raises if the repository itself can't be reached
            self._cache[name] = default     # the repository is fine; this file just doesn't exist yet
            return default
        self._check(r, f"reading {name}")
        txt = r.text
        val = json.loads(txt) if txt.strip() else default
        self._cache[name] = val
        return val

    def _repo_ok(self):
        r = self.s.get(self._url(""), timeout=30)
        self._check(r, "opening the repository")
        return True

    def write(self, files: dict, message="Engine update"):
        blobs = {n: json.dumps(o, separators=(",", ":")) for n, o in files.items()}
        for attempt in range(4):
            head = self._head()
            base_tree = self._check(self.s.get(self._url(f"git/commits/{head}"), timeout=30), "reading the latest version").json()["tree"]["sha"]
            tree = []
            for n, txt in blobs.items():
                b = self._check(self.s.post(self._url("git/blobs"), json={"content": txt, "encoding": "utf-8"}, timeout=60), f"saving {n}")
                tree.append({"path": n, "mode": "100644", "type": "blob", "sha": b.json()["sha"]})
            new_tree = self._check(self.s.post(self._url("git/trees"), json={"base_tree": base_tree, "tree": tree}, timeout=60), "saving").json()["sha"]
            commit = self._check(self.s.post(self._url("git/commits"), json={"message": message, "tree": new_tree, "parents": [head]},
                                             timeout=60), "saving").json()["sha"]
            r = self.s.patch(self._url(f"git/refs/heads/{self.BRANCH}"), json={"sha": commit, "force": False}, timeout=30)
            if r.status_code in (409, 422) and attempt < 3:
                time.sleep(1 + attempt)         # someone (your phone) saved in between: start again from their version
                continue
            self._check(r, "saving")
            for n, o in files.items():
                self._cache[n] = o
            return
        raise RuntimeError("Could not save to the data repository after several tries.")


class LocalStore:
    kind = "local"

    def __init__(self, folder):
        self.local = folder

    def refresh(self):
        pass

    def names(self):
        return sorted(os.listdir(self.local)) if os.path.isdir(self.local) else []

    def read(self, name, default=None):
        p = os.path.join(self.local, name)
        return json.load(open(p)) if os.path.exists(p) else default

    def write(self, files: dict, message=None):
        os.makedirs(self.local, exist_ok=True)
        for n, obj in files.items():
            json.dump(obj, open(os.path.join(self.local, n), "w"), indent=1)


def open_store(env=os.environ, local_dir=None, log=print):
    """Pick where data lives. With DATA_REPO + DATA_TOKEN, the private repository (copying from the Gist the first
    time). Otherwise the Gist."""
    if local_dir:
        return LocalStore(local_dir)
    repo, rtok = env.get("DATA_REPO"), env.get("DATA_TOKEN")
    gid, gtok = env.get("GIST_ID"), env.get("GIST_TOKEN")
    if repo and rtok:
        st = RepoStore(repo, rtok)
        if st.read("state.json") is None and gid and gtok:
            migrate(GistStore(gid, gtok), st, log)
        return st
    if repo or rtok:
        raise RuntimeError("Set both DATA_REPO and DATA_TOKEN to use the private repository (one is missing).")
    if gid and gtok:
        return GistStore(gid, gtok)
    raise RuntimeError("Set DATA_REPO and DATA_TOKEN (or GIST_ID and GIST_TOKEN), or use --local DIR for testing")


def migrate(gist, repo, log=print):
    """Copy every JSON file from the Gist to the repository in one commit, then mark the Gist as moved."""
    files = {}
    for n in gist.names():
        if n.endswith(".json") and n != "moved.json":
            files[n] = gist.read(n)
    if not files.get("state.json"):
        log("The Gist has no results yet: starting fresh in the private repository.")
        return
    repo.write(files, "Copy data from the Gist")
    try:
        gist.write({"moved.json": {"repo": repo.repo, "files": sorted(files)}})
    except Exception as e:      # only a note for the dashboard; the copy itself is done
        log("Could not leave the 'moved' note in the Gist:", type(e).__name__)
    log(f"Copied {len(files)} files from the Gist to {repo.repo}: {', '.join(sorted(files))}")


Store = None  # kept for older imports; use open_store()
