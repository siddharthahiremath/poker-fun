"""Checks our readable action coach and packaging; opponents remain opaque."""

import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


policy = load("logan_policy_test", ROOT / "bench/logan_policy.py")
builder = load("logan_builder_test", ROOT / "scripts/build_blackbox.py")
metadata = json.loads((ROOT / "bench/logan_data/metadata.json").read_text())
policy.CONFIG = metadata["config"]
policy._PERCENTILES = metadata["percentiles"]
policy._MODEL = json.loads(zlib.decompress((ROOT / "bench/logan_data/model.json.zlib").read_bytes()))


class FakeBase:
    def __init__(self):
        self.reply = {"action": "check", "amount": 0}
        self.observed = None

    def decide(self, info):
        self.observed = info
        return dict(self.reply)


policy._BaseAgent = FakeBase


def postflop():
    return {"seat": 0, "street": "flop", "time_limit": .001, "hole_cards": ["A♠", "K♥"],
            "board": ["2♣", "7♦", "J♥"], "stack": 100, "stacks": [100, 100, 0, 0],
            "street_bet": [0, 0, 0, 0], "street_bet_self": 0, "current_bet": 0,
            "to_call": 0, "pot": 30, "min_raise_to": 10, "max_raise_to": 100,
            "legal_actions": ["fold", "check", "bet"], "folded": [False, False, True, True],
            "button": 1, "blinds": [5, 10], "history": []}


def entry(equity, continuation=1):
    return {"equity": [equity] * 169,
            "response": {f"{p}:{r}": [continuation, [equity] * 169]
                         for p in range(5) for r in range(2)}}


class LoganTests(unittest.TestCase):
    def test_standalone_is_reproducible_and_is_the_validated_file(self):
        source = builder.build().encode()
        self.assertEqual(source, (ROOT / "agents/logan.py").read_bytes())
        self.assertEqual(hashlib.sha256(source).hexdigest(), metadata["agent_sha256"])

    def test_opaque_base_bytes_are_unchanged(self):
        self.assertEqual(hashlib.sha256((ROOT / "agents/riaan.py").read_bytes()).hexdigest(),
                         metadata["base_sha256"])

    def test_probe_uses_legal_minimum_and_does_not_mutate_engine_clock(self):
        bot, view = policy.Agent(), postflop()
        self.assertEqual(bot.decide(view), {"action": "bet", "amount": 10})
        self.assertEqual(view["time_limit"], .001)
        self.assertEqual(bot.base.observed["time_limit"], .002)

    def test_probe_is_not_used_multiway(self):
        bot, view = policy.Agent(), postflop()
        view["folded"][2], view["stacks"][2] = False, 100
        self.assertEqual(bot.decide(view)["action"], "check")

    def test_previous_aggression_prevents_probe(self):
        bot, view = policy.Agent(), postflop()
        view["history"] = [{"seat": 1, "street": "flop", "action": "bet", "to": 10}]
        self.assertEqual(bot.decide(view)["action"], "check")

    def test_free_fold_is_a_check(self):
        bot, view = policy.Agent(), postflop()
        bot.base.reply = {"action": "fold", "amount": 0}
        self.assertEqual(bot.decide(view)["action"], "check")

    def test_wagers_are_clamped_to_plain_legal_ints(self):
        bot, view = policy.Agent(), postflop()
        bot.base.reply = {"action": "bet", "amount": 999}
        self.assertEqual(bot.decide(view), {"action": "bet", "amount": 100})

    def test_heads_up_allin_values_only_new_cost(self):
        view = {"seat": 0, "street_bet": [10, 100], "stacks": [90, 0],
                "folded": [False, False], "pot": 110}
        ev = policy._allin_ev(view, 100, 0, {"uniform": entry(.6)}, {}, set())
        self.assertAlmostEqual(ev, 30)

    def test_uncalled_excess_is_recovered(self):
        view = {"seat": 0, "street_bet": [5, 10], "stacks": [95, 90],
                "folded": [False, False], "pot": 15}
        ev = policy._allin_ev(view, 100, 0, {"uniform": entry(.1, 0)}, {}, set())
        self.assertAlmostEqual(ev, 15)

    def test_short_opponent_is_excluded_from_uncovered_sidepot(self):
        view = {"seat": 0, "street_bet": [0, 100, 400], "stacks": [200, 0, 0],
                "folded": [False] * 3, "pot": 500}
        model = {"uniform": entry(.5), "short": entry(.6), "deep": entry(.4)}
        ev = policy._allin_ev(view, 200, 0, model, {1: "short", 2: "deep"}, set())
        self.assertAlmostEqual(ev, 300 * .6 * .4 + 200 * .4 - 200)

    def test_folded_chips_remain_dead_money(self):
        view = {"seat": 0, "street_bet": [0, 100, 50], "stacks": [100, 0, 0],
                "folded": [False, False, True], "pot": 150}
        ev = policy._allin_ev(view, 100, 0, {"uniform": entry(1)}, {}, set())
        self.assertAlmostEqual(ev, 150)


if __name__ == "__main__":
    unittest.main()
