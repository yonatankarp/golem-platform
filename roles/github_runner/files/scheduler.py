#!/usr/bin/env python3
"""Shares golem's runner slots between the targets that have jobs waiting.

Every few seconds: counts the jobs queued for the `golem` label in each target's
repositories, by the one extra label each may ask for (golem-pr, golem-main), sees
which runner containers are busy, and starts an ephemeral runner container (one
job, then gone) with those labels for whichever target is short, round-robin, up
to a shared maximum. A spare idle runner is stopped when another target needs
its slot, or once it has idled too long; a busy one is never touched. Runs as
root: the PATs in /etc/github-runner stay there, and only a one-hour
registration token reaches a container.
"""

import http.client
import json
import os
import re
import secrets
import subprocess
import sys
import time
from datetime import datetime

CONFIG = "/etc/github-runner/scheduler.json"
TARGET_LABEL = "golem.github-runner.target"
RUNNER_LABEL = "golem.github-runner.label"
# A runner has these without asking, so a job naming them needs no extra label.
DEFAULT_LABELS = {"self-hosted", "linux", "x64", "golem"}
RUNTIME = "/run/github-runner-scheduler"


def plan(targets, containers, demand, busy, now, max_runners, warm, target_max, target_share, idle_after, grace,
         label_max):
    """Which (target, label) pools to start a runner for, and which containers to stop.

    A pool is a target's runners with one extra label beside `golem`, or with none
    (""): a job asking for golem-main only runs on a golem-main runner. containers:
    dicts with name, target, label, runner (its GitHub runner name) and created
    (epoch seconds). demand: queued jobs per target per label. busy: names of runners
    running a job. warm: idle runners to keep ready per target, a count for its plain
    pool or one per label. target_max: most runners a target may hold at once (default
    target_share of max_runners, at least one); label_max: most per label within that,
    so a label's slots are kept for it. A container younger than `grace` may still be
    registering, so it counts as idle but is never stopped.
    """
    warm = {(t, l): n for t, v in warm.items() for l, n in (v.items() if isinstance(v, dict) else [("", v)])}
    want = {(t, l): n for t, v in demand.items() for l, n in v.items()}
    # Sorted, so golem-main gets the-stack's turn before golem-pr when both wait.
    pools = {t: sorted({""} | set(label_max.get(t, {})) | {l for (u, l) in [*warm, *want] if u == t}
                       | {c["label"] for c in containers if c["target"] == t}) for t in targets}
    keys = [(t, l) for t in targets for l in pools[t]]
    idle = {p: sorted((c for c in containers if (c["target"], c["label"]) == p and c["runner"] not in busy),
                      key=lambda c: c["created"], reverse=True) for p in keys}
    # The newest idle runners take the queued jobs; the rest are spares.
    spares = {p: idle[p][want.get(p, 0):] for p in keys}
    unmet = {p: max(want.get(p, 0) - len(idle[p]), 0) for p in keys}
    free = max_runners - len(containers)
    share = max(int(max_runners * target_share), 1)
    room = {t: target_max.get(t, share) - sum(c["target"] == t for c in containers) for t in targets}
    lroom = {(t, l): label_max.get(t, {}).get(l, max_runners)
             - sum((c["target"], c["label"]) == (t, l) for c in containers) for (t, l) in keys}
    starts, stops = [], []

    def reclaim():
        # A spare from a pool with no unmet demand, past its grace, oldest first.
        candidates = [c for p in keys if unmet[p] == 0 for c in spares[p]
                      if now - c["created"] >= grace and c["name"] not in stops]
        if not candidates:
            return False
        victim = min(candidates, key=lambda c: c["created"])
        stops.append(victim["name"])
        spares[(victim["target"], victim["label"])].remove(victim)
        return True

    while any(unmet.values()):
        progressed = False
        for t in targets:  # one start per target per round, from its first pool waiting
            p = next(((t, l) for l in pools[t] if unmet[(t, l)] and lroom[(t, l)] > 0), None)
            if p is None or room[t] <= 0:
                continue
            if free <= 0:
                if not reclaim():
                    continue
                free += 1
            starts.append(p)
            unmet[p] -= 1
            room[t] -= 1
            lroom[p] -= 1
            free -= 1
            progressed = True
        if not progressed:
            break

    for p in keys:
        short = warm.get(p, 0) - len(spares[p])
        while short > 0 and free > 0 and room[p[0]] > 0 and lroom[p] > 0:
            starts.append(p)
            short -= 1
            room[p[0]] -= 1
            lroom[p] -= 1
            free -= 1
        for c in sorted(spares[p], key=lambda c: c["created"])[: max(len(spares[p]) - warm.get(p, 0), 0)]:
            if now - c["created"] >= idle_after and c["name"] not in stops:
                stops.append(c["name"])
    return starts, stops


def scope(target):
    """API path of a target: owner/name is a repository, a bare name an organisation."""
    return f"repos/{target}" if "/" in target else f"orgs/{target}"


class GitHubError(Exception):
    pass


class GitHub:
    """GitHub's REST API over one kept-alive connection, with conditional GETs, which
    cost no rate limit when nothing changed."""

    def __init__(self, token):
        self.token = token
        self.conn = None
        self.cache = {}
        self.used = set()

    def request(self, method, path, etag=None):
        """(status, headers, parsed body or None). Reconnects once if the kept connection dropped."""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "golem-runner-scheduler",
        }
        if etag:
            headers["If-None-Match"] = etag
        for attempt in (1, 2):
            if self.conn is None:
                self.conn = http.client.HTTPSConnection("api.github.com", timeout=20)
            try:
                self.conn.request(method, f"/{path}", headers=headers)
                r = self.conn.getresponse()
                data = r.read()
                return r.status, r.headers, json.loads(data) if data else None
            except (http.client.HTTPException, OSError):
                self.conn.close()
                self.conn = None
                if attempt == 2:
                    raise

    def get(self, path):
        self.used.add(path)
        cached = self.cache.get(path)
        status, headers, body = self.request("GET", path, cached and cached[0])
        if status == 304 and cached:
            return cached[1]
        if status != 200:
            raise GitHubError(f"GET {path}: {status} {body}")
        if headers.get("ETag"):
            self.cache[path] = (headers["ETag"], body)
        return body

    def post(self, path):
        status, _, body = self.request("POST", path)
        if status not in (200, 201):
            raise GitHubError(f"POST {path}: {status} {body}")
        return body

    def delete(self, path):
        """True once the runner is gone; False if GitHub refused because it is busy."""
        status, _, body = self.request("DELETE", path)
        if status in (204, 404):
            return True
        if status == 422:
            return False
        raise GitHubError(f"DELETE {path}: {status} {body}")

    def forget_unused(self):
        """Drops cached answers not asked for since the last call, so finished runs don't pile up."""
        self.cache = {p: v for p, v in self.cache.items() if p in self.used}
        self.used = set()


class Scheduler:
    def __init__(self, config):
        self.cfg = config
        self.targets = config["targets"]
        self.github = {o: GitHub(open(f"/etc/github-runner/pat-{o}").read().strip())
                       for o in {t.split("/")[0] for t in self.targets}}
        self.org_repos = {}
        self.last_summary = None

    def gh(self, target):
        return self.github[target.split("/")[0]]

    def repos(self, target):
        """A repository target's own repository; an organisation's private, unarchived ones (cached 10 min)."""
        if "/" in target:
            return [target]
        cached = self.org_repos.get(target)
        if not cached or time.time() - cached[0] > 600:
            listed = self.gh(target).get(f"orgs/{target}/repos?type=private&per_page=100")
            cached = (time.time(), [r["full_name"] for r in listed if not r["archived"]])
            self.org_repos[target] = cached
        return cached[1]

    def demand(self, target):
        """Jobs waiting for a golem runner, per extra label ("" for none): queued runs, and
        the queued jobs of runs already under way."""
        gh, n = self.gh(target), {}
        for repo in self.repos(target):
            for status in ("queued", "in_progress"):
                for run in gh.get(f"repos/{repo}/actions/runs?status={status}&per_page=100")["workflow_runs"]:
                    jobs = gh.get(f"repos/{repo}/actions/runs/{run['id']}/jobs?filter=latest&per_page=100")["jobs"]
                    for j in jobs:
                        if j["status"] == "queued" and "golem" in j["labels"]:
                            extra = [lb for lb in j["labels"] if lb.lower() not in DEFAULT_LABELS]
                            label = extra[0] if extra else ""
                            # It lands in an env file and a Docker label: nothing but a plain name.
                            if re.fullmatch(r"[\w.-]*", label):
                                n[label] = n.get(label, 0) + 1
        return n

    def runners(self, target):
        listed = self.gh(target).get(f"{scope(target)}/actions/runners?per_page=100")["runners"]
        return {r["name"]: r for r in listed if r["name"].startswith("golem-")}

    def docker(self, *args, **kw):
        return subprocess.run(["docker", *args], check=True, capture_output=True, text=True,
                              env={**os.environ, "DOCKER_HOST": f"unix://{self.cfg['socket']}"}, **kw).stdout

    def containers(self):
        # A container from before labels has no RUNNER_LABEL, which reads as "": plain golem.
        out = self.docker("ps", "--filter", f"label={TARGET_LABEL}", "--format",
                          "{{.ID}}\t{{.Names}}\t{{.Label \"" + TARGET_LABEL + "\"}}\t{{.Label \"" + RUNNER_LABEL
                          + "\"}}\t{{.CreatedAt}}")
        found = []
        for line in out.splitlines():
            cid, name, target, label, created = line.split("\t")
            found.append({"name": name, "target": target, "label": label, "runner": f"golem-{cid[:12]}",
                          "created": datetime.strptime(created[:25], "%Y-%m-%d %H:%M:%S %z").timestamp()})
        return found

    def start(self, target, label):
        token = self.gh(target).post(f"{scope(target)}/actions/runners/registration-token")["token"]
        name = f"github-runner-{target.replace('/', '-')}-{secrets.token_hex(3)}"
        env = f"{RUNTIME}/{name}.env"
        fd = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(f"RUNNER_URL=https://github.com/{target}\nRUNNER_TOKEN={token}\n"
                    f"RUNNER_LABELS=golem{',' + label if label else ''}\n")
        try:
            # The container's root is the runner user (rootless Docker), the one uid
            # allowed on the socket its jobs are given.
            self.docker("run", "-d", "--rm", "--name", name, "--label", f"{TARGET_LABEL}={target}",
                        "--label", f"{RUNNER_LABEL}={label}",
                        "--pull", "never", "--user", "0", "-e", "RUNNER_ALLOW_RUNASROOT=1",
                        "-e", "RUNNER_TOOL_CACHE=/opt/hostedtoolcache", "--env-file", env,
                        "-v", f"{self.cfg['socket']}:/var/run/docker.sock",
                        "-v", "github-runner-toolcache:/opt/hostedtoolcache",
                        "--log-opt", "max-size=10m", "--log-opt", "max-file=2", self.cfg["image"])
        finally:
            os.unlink(env)
        print(f"started {name} for {target}{' ' + label if label else ''}", flush=True)

    def stop(self, container, registered):
        """Deregisters an idle runner first: GitHub refuses that for a busy one, so a job that
        landed meanwhile is never cut short. One never registered is past its grace: stop it."""
        runner = registered.get(container["runner"])
        if runner and not self.gh(container["target"]).delete(
                f"{scope(container['target'])}/actions/runners/{runner['id']}"):
            return
        self.docker("stop", "-t", "30", container["name"])
        print(f"stopped idle {container['name']}", flush=True)

    def loop_once(self):
        containers = self.containers()
        registered, busy = {}, set()
        for t in self.targets:
            for name, r in self.runners(t).items():
                registered[name] = r
                if r["busy"]:
                    busy.add(name)
        demand = {t: self.demand(t) for t in self.targets}
        for gh in self.github.values():
            gh.forget_unused()
        starts, stops = plan(self.targets, containers, demand, busy, time.time(),
                             self.cfg["max_runners"], self.cfg["warm"], self.cfg["target_max"],
                             self.cfg["target_share"], self.cfg["idle_after"], self.cfg["grace"],
                             self.cfg["label_max"])
        by_name = {c["name"]: c for c in containers}
        for name in stops:
            self.stop(by_name[name], registered)
        for t, label in starts:
            self.start(t, label)
        summary = {"queued": demand, "running": len(containers), "busy": len(busy & {c["runner"] for c in containers})}
        if summary != self.last_summary:
            print(f"queued {demand}, {summary['busy']} busy of {len(containers)} runners", flush=True)
            self.last_summary = summary
        # The pager reads this file's age: it is only written after a full, successful pass.
        with open(f"{RUNTIME}/status.json.tmp", "w") as f:
            json.dump({"time": time.time(), **summary}, f)
        os.replace(f"{RUNTIME}/status.json.tmp", f"{RUNTIME}/status.json")


def main():
    with open(CONFIG) as f:
        scheduler = Scheduler(json.load(f))
    while True:
        try:
            scheduler.loop_once()
        except Exception as e:  # a GitHub or Docker hiccup: try again next pass, the pager watches the gap
            print(f"pass failed: {e!r}", file=sys.stderr, flush=True)
        time.sleep(scheduler.cfg["poll"])


if __name__ == "__main__":
    main()
