"""Push local git history to GitHub via the Git Database REST API.

Fallback for networks where github.com (git smart HTTP) is unreachable but
api.github.com works (e.g. behind selective proxies/GFW). Replays each local
commit as blob/tree/commit/ref API calls, preserving messages and dates.
Handles GitHub's "Git Repository is empty" (HTTP 409) limitation by seeding
the first file through the contents API.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import urllib.error
import urllib.request

REPO = "GaillumXc/profili-mcp"
API = f"https://api.github.com/repos/{REPO}"
PROXY = "http://127.0.0.1:7897"


def get_token() -> str:
    out = subprocess.run(
        ["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
        capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1]
    raise RuntimeError("no github token in credential store")


TOKEN = get_token()
OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({"https": PROXY, "http": PROXY}))


def api_raw(method: str, url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url, method=method, data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {TOKEN}",
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json"})
    try:
        with OPENER.open(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} -> HTTP {exc.code}: {body[:300]}") from exc


def api(method: str, path: str, payload: dict) -> dict:
    return api_raw(method, API + path, payload)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          check=True).stdout


def repo_is_empty() -> bool:
    """Branch presence is the reliable emptiness signal; the repo `size`
    field lags behind content uploads."""
    req = urllib.request.Request(API + "/git/refs/heads/main",
                                 headers={"Authorization": f"Bearer {TOKEN}"})
    try:
        OPENER.open(req, timeout=60).close()
        return False
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return True
        raise


def create_initial_commit(path: str, content: bytes, message: str) -> str:
    payload = {"message": message,
               "content": base64.b64encode(content).decode("ascii"),
               "encoding": "base64"}
    d = api_raw("PUT", API + f"/contents/{path}", payload)
    return d["commit"]["sha"]


def push_commit(rev: str, parent: str, skip: set[str]) -> str:
    entries = []
    for line in git("ls-tree", "-r", rev).splitlines():
        meta, path = line.split("\t", 1)
        if path in skip:
            continue
        raw = subprocess.run(["git", "cat-file", "blob", meta.split()[2]],
                             capture_output=True, check=True).stdout
        blob = api("POST", "/git/blobs", {
            "content": base64.b64encode(raw).decode("ascii"),
            "encoding": "base64"})
        entries.append({"path": path, "mode": "100644",
                        "type": "blob", "sha": blob["sha"]})
        print(f"  blob {path} ({len(raw)}B)")

    tree = api("POST", "/git/trees", {"tree": entries})
    subject = git("log", "-1", "--format=%s", rev).strip()
    body = git("log", "-1", "--format=%b", rev).strip()
    author = {"name": "GaillumXc",
              "email": "GaillumXc@users.noreply.github.com",
              "date": git("log", "-1", "--format=%aI", rev).strip()}
    committer = dict(author, date=git("log", "-1", "--format=%cI", rev).strip())
    payload = {"message": subject + ("\n\n" + body if body else ""),
               "tree": tree["sha"], "author": author, "committer": committer,
               "parents": [parent] if parent else []}
    commit = api("POST", "/git/commits", payload)
    print(f"  commit {commit['sha'][:8]}  {subject[:60]}")
    return commit["sha"]


def main() -> None:
    revs = git("rev-list", "--reverse", "HEAD").split()
    print(f"replaying {len(revs)} commits -> {REPO}")
    parent: str | None = None
    skip: set[str] = set()
    if repo_is_empty():
        meta, path = git("ls-tree", "-r", revs[0]).splitlines()[0].split("\t", 1)
        raw = subprocess.run(["git", "cat-file", "blob", meta.split()[2]],
                             capture_output=True, check=True).stdout
        parent = create_initial_commit(path, raw,
                                       git("log", "-1", "--format=%s", revs[0]).strip())
        skip = {path}
        print(f"seeded empty repo with {path} ({parent[:8]})")
    for rev in revs:
        parent = push_commit(rev, parent, skip)
        skip = set()
    api("PATCH", "/git/refs/heads/main", {"sha": parent, "force": True})
    print(f"DONE: main -> {parent[:8]}  https://github.com/{REPO}")


if __name__ == "__main__":
    sys.exit(main())
