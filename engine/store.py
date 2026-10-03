"""Reads and writes JSON files in a private GitHub Gist (or a local folder when testing)."""
import json, os
import requests


class Store:
    def __init__(self, gist_id=None, token=None, local_dir=None):
        self.local = local_dir
        self.gist_id, self.token = gist_id, token
        self._cache = None
        if not local_dir and not (gist_id and token):
            raise RuntimeError("Set GIST_ID and GIST_TOKEN (or use --local DIR for testing)")

    def _h(self):
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"}

    def _gist(self):
        if self._cache is None:
            r = requests.get(f"https://api.github.com/gists/{self.gist_id}", headers=self._h(), timeout=30)
            if r.status_code != 200:
                raise RuntimeError(f"Could not read the gist (HTTP {r.status_code}). Check GIST_ID and GIST_TOKEN.")
            self._cache = r.json().get("files", {})
        return self._cache

    def read(self, name, default=None):
        if self.local:
            p = os.path.join(self.local, name)
            return json.load(open(p)) if os.path.exists(p) else default
        f = self._gist().get(name)
        if not f:
            return default
        txt = f.get("content", "")
        if f.get("truncated"):
            txt = requests.get(f["raw_url"], headers=self._h(), timeout=30).text
        return json.loads(txt) if txt.strip() else default

    def write(self, files: dict):
        """files: name -> python object"""
        if self.local:
            os.makedirs(self.local, exist_ok=True)
            for n, obj in files.items():
                json.dump(obj, open(os.path.join(self.local, n), "w"), indent=1)
            return
        body = {"files": {n: {"content": json.dumps(o, separators=(",", ":"))} for n, o in files.items()}}
        r = requests.patch(f"https://api.github.com/gists/{self.gist_id}", headers=self._h(), json=body, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"Could not save to the gist (HTTP {r.status_code}): {r.text[:150]}")
        self._cache = None
