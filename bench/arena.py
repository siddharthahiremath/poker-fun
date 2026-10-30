# Plays many freezeouts between agent files and counts who wins each one.
# usage: python3 bench/arena.py --time 0.01 --games 400 [--procs 12] [--hands-seen] agent.py agent.py ...
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
    seed, paths, games, limit = job
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
    dealer = poker.Dealer(len(seats), stack=poker.START_STACK)
    dealer.names = names
    dealer.odds_key = None
    wins = Counter()
    for _ in range(games):
        dealer.stacks = [poker.START_STACK] * dealer.n
        with contextlib.redirect_stdout(io.StringIO()):
            winner = poker.play_tournament(dealer, seats)
        wins[names[winner]] += 1
    return wins


def main():
    args = sys.argv[1:]
    limit = float(option(args, "--time", "0.01"))
    games = int(option(args, "--games", "200"))
    procs = int(option(args, "--procs", "12"))
    paths = [str(pathlib.Path(p).resolve()) for p in args]
    per = max(1, games // procs)
    jobs = []
    for k in range(procs):
        order = list(paths)
        random.Random(k).shuffle(order)  # seats and button order vary between workers
        jobs.append((k * 7919 + int(time.time()), order, per, limit))
    started = time.time()
    total = Counter()
    with multiprocessing.Pool(procs) as pool:
        for wins in pool.imap_unordered(worker, jobs):
            total.update(wins)
    played = sum(total.values())
    print(f"{played} games at {limit}s per move in {time.time() - started:.0f}s")
    for name, count in total.most_common():
        print(f"  {name:12s} {count:5d}  {100 * count / played:5.1f}%")
    names = [pathlib.Path(p).stem for p in paths]
    for n in names:
        if n not in total and names.count(n) == 1:
            print(f"  {n:12s}     0    0.0%")


if __name__ == "__main__":
    main()
