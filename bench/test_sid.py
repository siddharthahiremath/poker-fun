"""Sid-only regression tests. Opponent implementations are never inspected."""
import importlib.util
import pathlib
import random
import sys
import time
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import poker

spec = importlib.util.spec_from_file_location("sid_under_test", ROOT / "agents/sid.py")
sid = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sid)


class SidTests(unittest.TestCase):
    def test_evaluator_matches_engine(self):
        rng = random.Random(615)
        for count in (5, 6, 7):
            previous = None
            for _ in range(300):
                cards = rng.sample(poker.DECK, count)
                actual = sid.evaluate([sid.card_id(c) for c in cards])
                expected = poker.best_hand(cards)
                if previous:
                    ours, engine = previous
                    self.assertEqual((actual > ours) - (actual < ours),
                                     (expected > engine) - (expected < engine))
                previous = actual, expected

    def test_legal_actions_across_stacks_and_streets(self):
        rng = random.Random(152)
        bot = sid.Agent()
        bot.rng.seed(152)
        for players in (2, 3, 7, 22):
            for big_blind in (10, 160, 1280):
                dealer = poker.Dealer(players, small_blind=big_blind // 2, big_blind=big_blind)
                dealer.stacks = [rng.randint(1, 2000) for _ in range(players)]
                dealer.start_hand()
                for street, count in (("preflop", 0), ("flop", 3), ("turn", 1), ("river", 1)):
                    if count:
                        dealer.new_street(street)
                        dealer.board += [dealer.deck.pop() for _ in range(count)]
                    for seat in range(players):
                        if not dealer.can_act(seat):
                            continue
                        info = dealer.view(seat)
                        info["time_limit"] = 0.001
                        reply = bot.decide(info)
                        self.assertIs(type(reply), dict)
                        self.assertIs(type(reply["action"]), str)
                        self.assertIs(type(reply["amount"]), int)
                        dealer.act(seat, reply["action"], reply["amount"])

    def test_covered_pot_excludes_unwinnable_chips(self):
        dealer = poker.Dealer(3)
        dealer.stacks = [100, 1000, 1000]
        dealer.start_hand()
        dealer.act(0, "raise", 100)
        dealer.act(1, "raise", 1000)
        dealer.act(2, "call")
        view = sid.View(dealer.view(0))
        self.assertEqual(view.winnable(0, {}), 300)

    def test_short_raise_does_not_reopen_action(self):
        dealer = poker.Dealer(3)
        dealer.stacks = [1000, 35, 1000]
        dealer.start_hand()
        dealer.act(0, "raise", 30)
        dealer.act(1, "raise", 35)
        dealer.act(2, "call")
        info = dealer.view(0)
        self.assertNotIn("raise", info["legal_actions"])
        reply = sid.Agent().decide(info)
        dealer.act(0, reply["action"], reply["amount"])

    def test_postflop_scoring_work_is_bounded(self):
        dealer = poker.Dealer(2)
        dealer.start_hand()
        dealer.new_street("flop")
        dealer.board = ["2♠", "3♥", "8♦"]
        dealer.hands[0] = ["A♠", "A♥"]
        view = sid.View(dealer.view(0))
        bot = sid.Agent()
        bot.build_pool = lambda *args: [(4, 5, 0.5)]
        bot.simulate = lambda *args: [(100, [50], [0.5], [0.5])] * 6000
        calls = []
        utility = bot.utility

        def count_utility(*args):
            calls.append(None)
            return utility(*args)

        bot.utility = count_utility
        started = time.perf_counter()
        with patch.object(sid.time, "perf_counter", return_value=started):
            action = bot.postflop(view, started + 0.03, 0.03)
        self.assertIn(action[0], ("check", "raise"))
        self.assertLess(len(calls), 2000)

    def test_partial_bet_samples_use_their_actual_count(self):
        dealer = poker.Dealer(2)
        dealer.start_hand()
        dealer.new_street("flop")
        dealer.board = ["2♠", "3♥", "8♦"]
        dealer.hands[0] = ["A♠", "A♥"]
        view = sid.View(dealer.view(0))
        bot = sid.Agent()
        bot.build_pool = lambda *args: [(4, 5, 0.0)]
        bot.simulate = lambda *args: [(100, [50], [0.0], [0.5])] * 256
        started = time.perf_counter()
        # Time expires after 16 winning samples of the first bet size.
        with patch.object(sid.time, "perf_counter",
                          side_effect=[started, started, started + 1, started + 1]):
            action = bot.postflop(view, started + 0.03, 0.03)
        self.assertEqual(action[0], "raise")


if __name__ == "__main__":
    unittest.main()
