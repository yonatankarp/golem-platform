"""Checks for scheduler.py's planning. Run: python3 roles/github_runner/files/test_scheduler.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from scheduler import Scheduler, plan, scope  # noqa: E402

T, B, G = "yonatankarp/the-stack", "yonatankarp/before-dark", "guillotine-mods"
TARGETS = [T, B, G]
NOW = 10_000
# The pools a runner starts for: a target's plain golem runners, and the-stack's two kinds.
TP, BP, GP, PR, MAIN = (T, ""), (B, ""), (G, ""), (T, "golem-pr"), (T, "golem-main")
LABELS = {T: {"golem-pr": 2, "golem-main": 1}}


def c(name, target, age, runner=None, label=""):
    return {"name": name, "target": target, "label": label, "runner": runner or f"golem-{name}", "created": NOW - age}


def run(containers=(), demand=None, busy=(), max_runners=4, warm=None, target_max=None, target_share=0.75, idle_after=600,
        grace=90, label_max=None):
    # demand and warm by plain target, as before labels, unless given per label.
    demand = {t: v if isinstance(v, dict) else {"": v} for t, v in (demand or {}).items()}
    return plan(TARGETS, list(containers), demand, set(busy), NOW, max_runners, warm or {}, target_max or {},
                target_share, idle_after, grace, label_max or {})


# Nothing queued, nothing running: only the warm runner starts.
assert run(warm={T: 1}) == ([TP], [])
assert run() == ([], [])

# A burst takes its share of the slots, 75% of 4, and leaves the rest for the others.
assert run(demand={T: 6}) == ([TP] * 3, [])
assert run(demand={T: 6}, target_share=1) == ([TP] * 4, [])
# The share rounds down but never to nothing.
assert run(demand={T: 6}, max_runners=1) == ([TP], [])

# Two targets waiting share the slots in turn.
starts, stops = run(demand={T: 5, B: 2})
assert sorted(starts) == [BP, BP, TP, TP] and stops == []

# Idle runners already waiting cover the queue: nothing new.
assert run([c("a", T, 30)], demand={T: 1}) == ([], [])

# Busy runners hold their slots; the rest go to whoever waits.
busy4 = [c(n, T, 300) for n in "abcd"]
assert run(busy4, demand={B: 1}, busy={f"golem-{n}" for n in "abcd"}) == ([], [])

# All slots full, the-stack's spares are idle and past their grace: one makes way for before-dark.
mixed = [c("a", T, 300), c("b", T, 300), c("c", T, 500), c("d", T, 400)]
starts, stops = run(mixed, demand={B: 1}, busy={"golem-a", "golem-b"})
assert starts == [BP] and stops == ["c"], (starts, stops)  # the oldest spare

# A spare still registering is never stopped, even under pressure.
young = [c("a", T, 300), c("b", T, 300), c("c", T, 300), c("d", T, 20)]
starts, stops = run(young, demand={B: 1}, busy={"golem-a", "golem-b", "golem-c"})
assert (starts, stops) == ([], []), (starts, stops)

# Spares beyond the warm count go once they have idled long enough; the warm one stays.
spares = [c("a", T, 900), c("b", T, 700), c("c", T, 100)]
starts, stops = run(spares, warm={T: 1})
assert starts == [] and sorted(stops) == ["a", "b"], (starts, stops)

# A warm runner is reclaimed too when another target needs the slot.
full = [c("a", B, 300), c("b", B, 300), c("c", G, 300), c("d", T, 300)]
starts, stops = run(full, demand={G: 1}, busy={"golem-a", "golem-b", "golem-c"}, warm={T: 1})
assert starts == [GP] and stops == ["d"], (starts, stops)

# Fewer slots than runners (the maximum was lowered): no starts, idle ones drain.
over = [c(n, T, 900) for n in "abcde"]
starts, stops = run(over, max_runners=2)
assert starts == [] and len(stops) == 5

# A capped target stops at its cap, however long its queue; the other slots stay free.
assert run(demand={T: 9}, target_max={T: 2}) == ([TP, TP], [])
starts, stops = run(demand={T: 9, B: 1}, target_max={T: 2})
assert sorted(starts) == [BP, TP, TP] and stops == [], (starts, stops)

# At its cap with every runner busy: nothing new, and no one else's spare is reclaimed for it.
capped = [c("a", T, 300), c("b", T, 300), c("c", B, 300)]
starts, stops = run(capped, demand={T: 5}, busy={"golem-a", "golem-b"}, target_max={T: 2})
assert (starts, stops) == ([], []), (starts, stops)

# The warm runner counts against the cap too.
assert run([c("a", T, 300)], busy={"golem-a"}, warm={T: 1}, target_max={T: 1}) == ([], [])

# The-stack's main gate and nightly keep their slot from its pull-request gates.
L = dict(target_max={T: 3}, label_max=LABELS)
# A main job queued while two PR runners are busy gets the third slot...
prs = [c("a", T, 300, label="golem-pr"), c("b", T, 300, label="golem-pr")]
assert run(prs, demand={T: {"golem-main": 1}}, busy={"golem-a", "golem-b"}, **L) == ([MAIN], [])
# ...and a third PR job waits, though the slot and the target's room are free.
assert run(prs, demand={T: {"golem-pr": 1}}, busy={"golem-a", "golem-b"}, **L) == ([], [])
# A PR burst with nothing on main starts two, and the slots left over go to the others.
starts, stops = run(demand={T: {"golem-pr": 5}, B: 3}, **L)
assert sorted(starts) == [BP, BP, PR, PR] and stops == [], (starts, stops)
# Both queued: main goes first in the-stack's turn.
assert run(demand={T: {"golem-pr": 1, "golem-main": 1}}, **L) == ([MAIN, PR], [])
# An idle PR runner cannot take a main job: main still gets its own.
assert run([c("a", T, 30, label="golem-pr")], demand={T: {"golem-main": 1}}, **L) == ([MAIN], [])
# Every slot full, a main job queued: the warm PR spare makes way, a busy PR runner stays.
full = [c("a", B, 300), c("b", G, 300), c("c", T, 300, label="golem-pr"), c("d", T, 400, label="golem-pr")]
starts, stops = run(full, demand={T: {"golem-main": 1}}, busy={"golem-a", "golem-b", "golem-c"},
                    warm={T: {"golem-pr": 1}}, **L)
assert starts == [MAIN] and stops == ["d"], (starts, stops)
# The warm runner is a PR one, inside the PR cap.
assert run(warm={T: {"golem-pr": 1}}, **L) == ([PR], [])
assert run(prs, busy={"golem-a", "golem-b"}, warm={T: {"golem-pr": 1}}, **L) == ([], [])
# Plain golem jobs of a labelled target (before its workflows ask for a label) keep the target's cap.
assert run(demand={T: 5}, **L) == ([TP] * 3, [])

# demand() counts a job by its one label beside golem, and skips a label unfit for an env file.
class FakeGitHub:
    def get(self, path):
        if path.endswith("status=in_progress&per_page=100"):
            return {"workflow_runs": []}
        if "/jobs?" in path:
            return {"jobs": [{"status": "queued", "labels": lb} for lb in (
                ["self-hosted", "golem"], ["self-hosted", "Linux", "golem", "golem-pr"],
                ["self-hosted", "golem", "golem-pr"],
                ["golem", "golem-main"], ["golem", "bad\nRUNNER_URL=x"], ["ubuntu-latest"])] + [
                {"status": "in_progress", "labels": ["golem", "golem-pr"]}]}
        return {"workflow_runs": [{"id": 1}]}


sched = Scheduler.__new__(Scheduler)
sched.gh = lambda target: FakeGitHub()
assert sched.demand(T) == {"": 1, "golem-pr": 2, "golem-main": 1}, sched.demand(T)

assert scope(T) == "repos/yonatankarp/the-stack" and scope(G) == "orgs/guillotine-mods"

print("scheduler tests pass")
