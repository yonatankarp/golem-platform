"""Checks for scheduler.py's planning. Run: python3 roles/github_runner/files/test_scheduler.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from scheduler import plan, scope  # noqa: E402

T, B, G = "yonatankarp/the-stack", "yonatankarp/before-dark", "guillotine-mods"
TARGETS = [T, B, G]
NOW = 10_000


def c(name, target, age, runner=None):
    return {"name": name, "target": target, "runner": runner or f"golem-{name}", "created": NOW - age}


def run(containers=(), demand=None, busy=(), max_runners=4, warm=None, idle_after=600, grace=90):
    return plan(TARGETS, list(containers), demand or {}, set(busy), NOW, max_runners, warm or {}, idle_after, grace)


# Nothing queued, nothing running: only the warm runner starts.
assert run(warm={T: 1}) == ([T], [])
assert run() == ([], [])

# A burst takes every free slot.
assert run(demand={T: 6}) == ([T, T, T, T], [])

# Two targets waiting share the slots in turn.
starts, stops = run(demand={T: 5, B: 2})
assert sorted(starts) == [B, B, T, T] and stops == []

# Idle runners already waiting cover the queue: nothing new.
assert run([c("a", T, 30)], demand={T: 1}) == ([], [])

# Busy runners hold their slots; the rest go to whoever waits.
busy4 = [c(n, T, 300) for n in "abcd"]
assert run(busy4, demand={B: 1}, busy={f"golem-{n}" for n in "abcd"}) == ([], [])

# All slots full, the-stack's spares are idle and past their grace: one makes way for before-dark.
mixed = [c("a", T, 300), c("b", T, 300), c("c", T, 500), c("d", T, 400)]
starts, stops = run(mixed, demand={B: 1}, busy={"golem-a", "golem-b"})
assert starts == [B] and stops == ["c"], (starts, stops)  # the oldest spare

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
assert starts == [G] and stops == ["d"], (starts, stops)

# Fewer slots than runners (the maximum was lowered): no starts, idle ones drain.
over = [c(n, T, 900) for n in "abcde"]
starts, stops = run(over, max_runners=2)
assert starts == [] and len(stops) == 5

assert scope(T) == "repos/yonatankarp/the-stack" and scope(G) == "orgs/guillotine-mods"

print("scheduler tests pass")
