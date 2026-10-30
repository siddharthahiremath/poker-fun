# The bot most people write first: Monte Carlo equity against random hands versus pot odds.
import importlib.util
import pathlib
import random
import time

_spec = importlib.util.spec_from_file_location("eqbot_sid", pathlib.Path(__file__).resolve().parents[2] / "agents" / "sid.py")
m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m)


class Agent:
    def decide(self, info):
        legal = info["legal_actions"]
        hole = [m.card_id(c) for c in info["hole_cards"]]
        board = [m.card_id(c) for c in info["board"]]
        opponents = max(1, sum(1 for i, f in enumerate(info["folded"]) if not f and i != info["seat"]))
        deadline = time.perf_counter() + 0.3 * info["time_limit"]
        deck = [c for c in range(52) if c not in hole and c not in board]
        wins = trials = 0
        while trials < 400 and (trials % 8 or time.perf_counter() < deadline):
            cards = random.sample(deck, 2 * opponents + 5 - len(board))
            full = board + cards[2 * opponents:]
            mine = m.evaluate(hole + full)
            best = max(m.evaluate(cards[2 * i:2 * i + 2] + full) for i in range(opponents))
            wins += 1 if mine > best else 0.5 if mine == best else 0
            trials += 1
        eq = wins / max(1, trials)
        owed = info["to_call"]
        pot = info["pot"]
        word = "raise" if "raise" in legal else "bet" if "bet" in legal else None
        if word and eq > 0.75 / opponents ** 0.5 + 0.05:
            target = info["current_bet"] + pot
            return {"action": word, "amount": max(info["min_raise_to"], min(info["max_raise_to"], target))}
        if owed == 0:
            return {"action": "check", "amount": 0}
        if eq > owed / (pot + owed):
            return {"action": "call", "amount": 0}
        return {"action": "fold", "amount": 0}
