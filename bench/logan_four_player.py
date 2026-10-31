"""Black-box four-player evaluation on the unmodified upstream poker engine.

Bots are loaded and timed by the real engine. No bot source is decoded or inspected.
Each worker retains its agents across games, as the live Wins race does.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import itertools
import json
import math
import os
import random
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT
NAMES = ["logan", "riaan", "sid", "will"]


def worker(task):
    paths, games, limit, seed, order, offset, training, live_button = task
    random.seed(seed)
    sys.argv = ["poker.py"]
    spec = importlib.util.spec_from_file_location("four_player_engine", ENGINE / "poker.py")
    poker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(poker)
    poker.HANDS = 1000
    poker.WINS_MODE = True
    poker.clock["limit"] = limit
    failures, actions, timings, observations = Counter(), Counter(), Counter(), {}

    if training:
        original_turn = poker.Seat.take_turn

        def observed_turn(self, dealer, i):
            info = dealer.view(i)
            original_turn(self, dealer, i)
            if info["street"] != "preflop" or order[i] == 0:
                return
            ranks = sorted(("23456789TJQKA".index(c[:-1].replace("10", "T")) for c in info["hole_cards"]), reverse=True)
            hi, lo = ranks
            cls = hi * 13 + lo if hi == lo or info["hole_cards"][0][-1] == info["hole_cards"][1][-1] else lo * 13 + hi
            bb = info["blinds"][1]
            effective = min(info["max_raise_to"], max((info["stacks"][j] + info["street_bet"][j]
                            for j in range(4) if j != i and not info["folded"][j]), default=info["max_raise_to"])) / bb
            depth = next((k for k, bound in enumerate((3, 6, 10, 16, 30, 60)) if effective <= bound), 6)
            n = min(3, sum(not f for f in info["folded"]) - 1)
            acted = dealer.history[-1]
            aggs = [a for a in info["history"] if a["action"] in ("bet", "raise")]
            kind = ("shove" if acted["action"] == "raise" and dealer.stacks[i] == 0 else acted["action"])
            key = f"range:{depth}:{n}:{'facing' if aggs else 'open'}:{kind}"
            observations.setdefault(key, [0] * 169)[cls] += 1
            observations.setdefault(NAMES[order[i]] + ":" + key, [0] * 169)[cls] += 1
            if aggs and info["stacks"][aggs[-1]["seat"]] == 0 and info["to_call"] > 0:
                cost = min(info["stack"], info["to_call"])
                price = cost / max(1, info["pot"] + cost)
                p = min(4, int(price * 10))
                raised = int(any(a["seat"] == i for a in aggs))
                context = f"response:{p}:{raised}"
                observations.setdefault(context + ":total", [0] * 169)[cls] += 1
                observations.setdefault(NAMES[order[i]] + ":" + context + ":total", [0] * 169)[cls] += 1
                if acted["action"] in ("call", "raise"):
                    observations.setdefault(context + ":call", [0] * 169)[cls] += 1
                    observations.setdefault(NAMES[order[i]] + ":" + context + ":call", [0] * 169)[cls] += 1

        poker.Seat.take_turn = observed_turn

    def broadcast(event, dealer, **extra):
        if event == "action":
            name = NAMES[order[extra["actor"]]]
            action = extra["action"]
            if action.get("note"):
                failures[f"{name}:{action['note']}"] += 1
            actions[f"{name}:{action['street']}:{action['action']}"] += 1
            if action["action"] in ("bet", "raise") and dealer.stacks[extra["actor"]] == 0:
                actions[f"{name}:{action['street']}:allin"] += 1

    poker.broadcast = broadcast
    started = time.monotonic()
    with open(os.devnull, "w") as sink:
        old_stdout, sys.stdout = sys.stdout, sink
        try:
            seats = [poker.Seat(NAMES[j], paths[j], i) for i, j in enumerate(order)]
            if any(s.bot is None for s in seats):
                raise RuntimeError("A bot failed to load; refusing to score the lineup")
            dealer = poker.Dealer(4, stack=poker.START_STACK)
            dealer.names = [s.name for s in seats]
            dealer.wins = [0] * 4
            dealer.odds_key = None
            dealer.game_number = None
            outcomes = []
            for game in range(games):
                dealer.stacks = [poker.START_STACK] * 4
                if not live_button:
                    dealer.button = (offset + game) % 4
                before = time.monotonic()
                winner = poker.play_tournament(dealer, seats)
                timings["game_ms"] += round(1000 * (time.monotonic() - before))
                outcomes.append({"game": offset + game, "winner": NAMES[order[winner]],
                                 "hands": dealer.hand_number, "seed": seed,
                                 "order": [NAMES[j] for j in order]})
                if sum(s > 0 for s in dealer.stacks) != 1:
                    failures["hand_cap"] += 1
        finally:
            sys.stdout = old_stdout
    own_bot = seats[order.index(0)].bot
    tracker = getattr(own_bot, "profiles", None)  # our coach only; never inspect opponent objects
    profiles = ({NAMES[order[j]]: tracker.weights(j) for j in range(4) if order[j] != 0}
                if tracker is not None else {})
    return {"outcomes": outcomes, "failures": dict(failures), "actions": dict(actions),
            "seconds": time.monotonic() - started, "observations": observations, "profiles": profiles}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bot", type=Path, default=ENGINE / "agents/logan.py")
    ap.add_argument("--games", type=int, default=400)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--time", type=float, default=0.001)
    ap.add_argument("--seed", type=int, default=31001)
    ap.add_argument("--batch", type=int, default=100)
    ap.add_argument("--permute", action="store_true", help="balance all relative seating orders")
    ap.add_argument("--training", action="store_true", help="record black-box actions and actor-visible cards offline")
    ap.add_argument("--live-button", action="store_true", help="carry button between games exactly as the live viewer")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    paths = [str(args.bot.resolve())] + [str(ENGINE / f"agents/{n}.py") for n in NAMES[1:]]
    orders = list(itertools.permutations(range(4))) if args.permute else [(0, 1, 2, 3)]
    tasks = []
    for k, offset in enumerate(range(0, args.games, args.batch)):
        tasks.append((paths, min(args.batch, args.games - offset), args.time,
                      args.seed + 104729 * k, orders[k % len(orders)], offset, args.training, args.live_button))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    provenance = {"bots": {n: {"path": p, "sha256": hashlib.sha256(Path(p).read_bytes()).hexdigest()}
                           for n, p in zip(NAMES, paths)},
                  "engine_sha256": hashlib.sha256((ENGINE / "poker.py").read_bytes()).hexdigest(),
                  "games": args.games, "time_limit": args.time, "seed": args.seed,
                  "batch": args.batch, "jobs": args.jobs, "permute": args.permute}
    provenance["live_button"] = args.live_button
    wins, failures, actions, observations, profiles = Counter(), Counter(), Counter(), {}, []
    started = time.monotonic()
    with args.output.with_suffix(".jsonl").open("w") as raw, ProcessPoolExecutor(args.jobs) as pool:
        futures = [pool.submit(worker, t) for t in tasks]
        for future in as_completed(futures):
            result = future.result()
            for row in result["outcomes"]:
                raw.write(json.dumps(row) + "\n")
                wins[row["winner"]] += 1
            raw.flush()
            failures.update(result["failures"])
            actions.update(result["actions"])
            if result["profiles"]:
                profiles.append(result["profiles"])
            for key, counts in result["observations"].items():
                target = observations.setdefault(key, [0] * 169)
                for i, value in enumerate(counts):
                    target[i] += value
            print(f"{sum(wins.values())}/{args.games} {dict(wins)} failures={dict(failures)}", flush=True)
    n = sum(wins.values())
    comparisons = {}
    for opponent in NAMES[1:]:
        gap = (wins["logan"] - wins[opponent]) / n
        se = math.sqrt(max(0, (wins["logan"] + wins[opponent]) / n - gap * gap) / n)
        comparisons[opponent] = {"gap": gap, "ci95": [gap - 1.96 * se, gap + 1.96 * se],
                                 "ci99_familywise": [gap - 2.935 * se, gap + 2.935 * se]}
    report = {**provenance, "wins": dict(wins), "rates": {k: wins[k] / n for k in NAMES},
              "comparisons": comparisons, "failures": dict(failures), "actions": dict(actions),
              "seconds": time.monotonic() - started}
    if observations:
        report["observations"] = observations
    if profiles:
        report["inferred_profiles"] = profiles
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("wins", "rates", "comparisons", "failures", "seconds")}, indent=2))


if __name__ == "__main__":
    main()
