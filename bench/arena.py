# Plays many freezeouts between agent files and counts who wins each one.
# usage: python3 bench/arena.py --time 0.01 --games 400 [--procs 12] [--seed 42] [--diagnostics] [--json] agent.py agent.py ...
# Seeds control the worker RNG; agents may use private RNGs and wall-clock budgets.
import json
import multiprocessing
import pathlib
import random
import sys
import time
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent


def option(args, flag, default):
    if flag in args:
        i = args.index(flag)
        value = args[i + 1]
        del args[i:i + 2]
        return value
    return default


def worker(job):
    seed, paths, games, limit, diagnostics = job
    random.seed(seed)
    sys.argv = ["poker.py", "--wins", "--time", str(limit)]
    sys.path.insert(0, str(ROOT))
    import io
    import contextlib
    import poker

    poker.HANDS = 1000
    names = [pathlib.Path(p).stem for p in paths]
    names = [n if names.count(n) == 1 else f"{n}-{i}" for i, n in enumerate(names)]
    with contextlib.redirect_stdout(io.StringIO()):
        seats = [poker.Seat(names[i], p, i) for i, p in enumerate(paths)]
    if any(seat.bot is None for seat in seats):
        raise RuntimeError("An agent failed to load; refusing to score a broken lineup")
    dealer = poker.Dealer(len(seats), stack=poker.START_STACK)
    dealer.names = names
    dealer.odds_key = None
    wins = Counter()
    notes = Counter()
    actions = Counter()
    if diagnostics:
        def observe(event, dealer, **extra):
            if event == "action":
                name = names[extra["actor"]]
                actions[name] += 1
                note = extra["action"].get("note")
                if note:
                    notes[f"{name}:{note}"] += 1
        poker.broadcast = observe
    for _ in range(games):
        dealer.stacks = [poker.START_STACK] * dealer.n
        with contextlib.redirect_stdout(io.StringIO()):
            winner = poker.play_tournament(dealer, seats)
        wins[names[winner]] += 1
    return wins, notes, actions


def main():
    args = sys.argv[1:]
    limit = float(option(args, "--time", "0.01"))
    games = int(option(args, "--games", "200"))
    procs = int(option(args, "--procs", "12"))
    seed = int(option(args, "--seed", str(int(time.time()))))
    diagnostics = "--diagnostics" in args
    if diagnostics:
        args.remove("--diagnostics")
    as_json = "--json" in args
    if as_json:
        args.remove("--json")
    paths = [str(pathlib.Path(p).resolve()) for p in args]
    if games < 1 or procs < 1 or len(paths) < 2:
        raise SystemExit("Need positive --games/--procs and at least two agent paths")
    procs = min(procs, games)
    per, extra = divmod(games, procs)
    jobs = []
    for k in range(procs):
        order = list(paths)
        random.Random(k).shuffle(order)  # seats and button order vary between workers
        jobs.append((k * 7919 + seed, order, per + (k < extra), limit, diagnostics))
    started = time.time()
    total = Counter()
    notes, actions = Counter(), Counter()
    with multiprocessing.Pool(procs) as pool:
        for wins, failures, moves in pool.imap_unordered(worker, jobs):
            total.update(wins)
            notes.update(failures)
            actions.update(moves)
    played = sum(total.values())
    if as_json:
        print(json.dumps({"games": played, "time_limit": limit, "seed": seed,
                          "seconds": round(time.time() - started, 2),
                          "wins": dict(total), "notes": dict(notes), "actions": dict(actions)}))
        return
    print(f"{played} games at {limit}s per move in {time.time() - started:.0f}s (seed {seed})")
    for name, count in total.most_common():
        print(f"  {name:12s} {count:5d}  {100 * count / played:5.1f}%")
    names = [pathlib.Path(p).stem for p in paths]
    for n in names:
        if n not in total and names.count(n) == 1:
            print(f"  {n:12s}     0    0.0%")
    if diagnostics:
        print(f"  action notes: {dict(notes)}; moves: {dict(actions)}")


if __name__ == "__main__":
    main()
