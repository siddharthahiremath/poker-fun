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

    def test_side_pots_exclude_short_stack_from_deeper_layers(self):
        dealer = poker.Dealer(3)
        dealer.stacks = [1000, 100, 1000]
        dealer.start_hand()
        dealer.act(0, "raise", 1000)
        dealer.act(1, "call")
        dealer.act(2, "call")
        view = sid.View(dealer.view(0))
        self.assertEqual(view.pot_layers(0, {}, view.live),
                         [(300, (1, 2)), (1800, (2,))])
        dealer.board = ["K♦", "2♣", "4♥", "7♦", "9♣"]
        dealer.hands = [["A♠", "A♥"], ["K♠", "K♥"], ["Q♠", "Q♥"]]
        # Sid loses the main pot but wins the side pot, not zero chips.
        self.assertEqual(dealer.award()[0], 1800)

    def test_profitable_side_pot_call_survives_lost_main_pot(self):
        dealer = poker.Dealer(3)
        dealer.stacks = [1000, 100, 1000]
        dealer.start_hand()
        dealer.act(0, "call")
        dealer.act(1, "raise", 100)
        dealer.act(2, "call")
        dealer.act(0, "call")
        dealer.new_street("flop")
        dealer.board = ["K♦", "2♣", "4♥"]
        dealer.hands[0] = ["A♠", "A♥"]
        dealer.act(2, "bet", 900)
        view = sid.View(dealer.view(0))
        bot = sid.Agent()
        bot.build_pool = lambda *args: [(4, 5, 0.0)]
        # Short stack always wins the main pot; Sid always beats the deep stack.
        bot.simulate = lambda *args: [(100, [200, 50], [0.0, 0.0], [0.5, 0.5])] * 32
        started = time.perf_counter()
        with patch.object(sid.time, "perf_counter", return_value=started):
            self.assertEqual(bot.postflop(view, started + 0.03, 0.03), ("call", 0))

    def test_pot_layers_keep_folded_money_but_not_folded_players(self):
        dealer = poker.Dealer(3)
        dealer.stacks = [1000, 100, 1000]
        dealer.start_hand()
        dealer.act(0, "raise", 1000)
        dealer.act(1, "call")
        dealer.act(2, "call")
        dealer.folded[2] = True
        view = sid.View(dealer.view(0))
        self.assertEqual(view.pot_layers(0, {}, view.live),
                         [(300, (1,)), (1800, ())])

    def test_pot_layers_respect_hero_cap_and_future_calls(self):
        dealer = poker.Dealer(3)
        dealer.stacks = [100, 1000, 1000]
        dealer.start_hand()
        view = sid.View(dealer.view(0))
        layers = view.pot_layers(100, {1: 995, 2: 990}, view.live)
        self.assertEqual(layers, [(300, (1, 2))])
        self.assertEqual(sum(amount for amount, _ in layers),
                         view.winnable(100, {1: 995, 2: 990}))

    def test_shove_read_preserves_depth_when_observations_match_chart(self):
        bot, opponent = sid.Agent(), sid.Opponent()
        opponent.counts["jam"] = [40.0, 60.0]
        opponent.jam_expected = 60.0
        for depth in (2, 8, 25):
            action = (1, "preflop", "raise", "pf0", 0, True, depth, 1)
            self.assertAlmostEqual(bot.act_share(opponent, action),
                                   sid.shove_share(1, depth))

    def test_precomputed_shove_frequencies_match_full_chart(self):
        for behind in (1, 2, 8, 21):
            for depth in (0.5, 1.25, 7.7, 20, 30, 100):
                expected = sum(sid.shove_prob(behind, depth, c) * sid.CLASS_SIZE[c]
                               for c in sid.CLASSES) / 1326
                self.assertAlmostEqual(sid.shove_share(behind, depth), expected, places=12)

    def test_shove_read_learns_aggression_and_decays_consistently(self):
        bot, opponent = sid.Agent(), sid.Opponent()
        opponent.counts["jam"] = [10.0, 20.0]
        opponent.jam_expected = 10.0
        action = (1, "preflop", "raise", "pf0", 0, True, 20, 1)
        self.assertGreater(bot.act_share(opponent, action), sid.shove_share(1, 20))
        opponent.decay()
        self.assertAlmostEqual(opponent.jam_expected, 10 * sid.DECAY)
        self.assertAlmostEqual(opponent.counts["jam"][1], 20 * sid.DECAY)

    def test_no_future_betting_means_full_equity_realization(self):
        dealer = poker.Dealer(2)
        dealer.stacks = [1000, 100]
        dealer.start_hand()
        dealer.act(0, "call")
        dealer.act(1, "raise", 100)
        view = sid.View(dealer.view(0))
        self.assertEqual(sid.Agent().realization(view, [1], False), 1.0)

    def test_fast_path_calls_a_guaranteed_three_way_chop(self):
        dealer = poker.Dealer(3)
        dealer.start_hand()
        dealer.act(0, "raise", 100)
        dealer.act(1, "call")
        dealer.act(2, "call")
        dealer.new_street("river")
        dealer.act(1, "bet", 900)
        dealer.act(2, "call")
        dealer.board = ["10♠", "J♠", "Q♠", "K♠", "A♠"]
        dealer.hands[0] = ["2♥", "3♦"]
        view = sid.View(dealer.view(0))
        bot = sid.Agent()
        bot.rng.seed(173)
        self.assertEqual(bot.quick_postflop(view), ("call", 0))

    def test_fast_call_values_the_side_pot_without_the_short_stack(self):
        dealer = poker.Dealer(3)
        dealer.stacks = [1000, 100, 1000]
        dealer.start_hand()
        dealer.act(0, "call")
        dealer.act(1, "raise", 100)
        dealer.act(2, "call")
        dealer.act(0, "call")
        dealer.new_street("flop")
        dealer.board = ["K♦", "2♣", "4♥"]
        dealer.act(2, "bet", 900)
        view = sid.View(dealer.view(0))
        self.assertEqual(sid.Agent.quick_call_value(
            view, 900, {1: (0.0, 0.0), 2: (1.0, 0.0)}, 1.0), 1800)
        self.assertEqual(sid.Agent.quick_call_value(
            view, 900, {1: (0.0, 0.0), 2: (0.0, 0.0)}, 1.0), 0)

    def test_fast_call_values_partial_multiway_ties(self):
        dealer = poker.Dealer(3, stack=100)
        dealer.start_hand()
        dealer.act(0, "raise", 100)
        dealer.act(1, "call")
        dealer.act(2, "call")
        view = sid.View(dealer.view(0))
        # Win outright 1/4, tie one opponent 1/2, tie both 1/4.
        expected = 300 * (0.25 + 0.5 / 2 + 0.25 / 3)
        actual = sid.Agent.quick_call_value(view, 0, {1: (0.5, 0.5), 2: (0.5, 0.5)}, 1.0)
        self.assertAlmostEqual(actual, expected)

    def test_fast_call_keeps_uncontested_money_at_full_value(self):
        dealer = poker.Dealer(3)
        dealer.stacks = [1000, 100, 1000]
        dealer.start_hand()
        dealer.act(0, "raise", 1000)
        dealer.act(1, "call")
        dealer.act(2, "call")
        dealer.folded[2] = True
        view = sid.View(dealer.view(0))
        self.assertEqual(sid.Agent.quick_call_value(view, 0, {1: (0.0, 0.0)}, 0.5), 1800)

    def test_fast_call_preserves_heads_up_equity(self):
        dealer = poker.Dealer(2, stack=100)
        dealer.start_hand()
        dealer.act(0, "raise", 100)
        dealer.act(1, "call")
        view = sid.View(dealer.view(0))
        self.assertAlmostEqual(sid.Agent.quick_call_value(view, 0, {1: (0.6, 0.2)}, 0.9),
                               200 * (0.6 + 0.2 / 2) * 0.9)

    def test_fast_call_keeps_upstream_runout_equity_calibration(self):
        dealer = poker.Dealer(3)
        dealer.start_hand()
        dealer.act(0, "raise", 100)
        dealer.act(1, "call")
        dealer.act(2, "call")
        dealer.new_street("flop")
        dealer.board = ["2♠", "3♥", "8♦"]
        dealer.hands[0] = ["A♠", "A♥"]
        dealer.act(1, "bet", 900)
        dealer.act(2, "call")
        view = sid.View(dealer.view(0))
        bot = sid.Agent()
        # Made-hand ranking alone says we lose. The merged bot must still use
        # upstream's calibrated equity for cards that have not arrived yet.
        def rank(a, b, board):
            return 0 if (a, b) == tuple(view.hole) else 1
        with patch.object(sid, "strength", side_effect=rank):
            with patch.object(sid, "beat_equity", return_value=0.75) as calibration:
                self.assertEqual(bot.quick_postflop(view), ("call", 0))
                self.assertEqual(calibration.call_count, 2)
            with patch.object(sid, "beat_equity", return_value=0.1):
                self.assertEqual(bot.quick_postflop(view), ("fold", 0))

    def test_postflop_contract_at_supported_clock_profiles(self):
        bot = sid.Agent()
        bot.rng.seed(171)
        for limit in (0.001, 0.01, 0.1, 1.0, 10.0):
            for street, board in (
                ("flop", ["2♠", "3♥", "8♦"]),
                ("turn", ["2♠", "3♥", "8♦", "J♣"]),
                ("river", ["2♠", "3♥", "8♦", "J♣", "Q♥"]),
            ):
                dealer = poker.Dealer(3)
                dealer.start_hand()
                dealer.new_street(street)
                dealer.board = board
                dealer.hands[0] = ["A♠", "A♥"]
                dealer.act(1, "bet", 40)
                dealer.act(2, "call")
                info = dealer.view(0)
                info["time_limit"] = limit
                with patch.object(sid, "fallback", side_effect=AssertionError("unexpected fallback")):
                    reply = bot.decide(info)
                dealer.act(0, reply["action"], reply["amount"])


if __name__ == "__main__":
    unittest.main()
