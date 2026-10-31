import random
import time
import math
from collections import defaultdict

class HandStrengthEvaluator:
    def __init__(self):
        self.hand_rankings = {
            'high_card': 1,
            'pair': 2,
            'two_pair': 3,
            'three_of_a_kind': 4,
            'straight': 5,
            'flush': 6,
            'full_house': 7,
            'four_of_a_kind': 8,
            'straight_flush': 9
        }

    def evaluate(self, hole_cards, community_cards):
        cards = hole_cards + community_cards
        suits = [card[1] for card in cards]
        values = [card[0] for card in cards]

        value_counts = defaultdict(int)
        for value in values:
            value_counts[value] += 1

        is_flush = len(set(suits)) == 1
        is_straight = self.is_straight(values)

        if is_straight and is_flush:
            return self.hand_rankings['straight_flush']
        elif max(value_counts.values()) == 4:
            return self.hand_rankings['four_of_a_kind']
        elif set(value_counts.values()) == {3, 2}:
            return self.hand_rankings['full_house']
        elif is_flush:
            return self.hand_rankings['flush']
        elif is_straight:
            return self.hand_rankings['straight']
        elif max(value_counts.values()) == 3:
            return self.hand_rankings['three_of_a_kind']
        elif list(value_counts.values()).count(2) == 2:
            return self.hand_rankings['two_pair']
        elif 2 in value_counts.values():
            return self.hand_rankings['pair']
        else:
            return self.hand_rankings['high_card']

    def is_straight(self, values):
        unique_values = list(set(values))
        unique_values.sort()

        if len(unique_values) < 5:
            return False

        for i in range(len(unique_values) - 4):
            if unique_values[i+4] - unique_values[i] == 4:
                return True

        return False

class Strategy:
    def __init__(self):
        self.preflop_raise_percentages = {9: 0.9, 8: 0.8, 7: 0.7, 6: 0.6, 5: 0.5, 4: 0.4, 3: 0.3, 2: 0.2, 1: 0.1}
        self.postflop_bet_percentages = {9: 0.8, 8: 0.7, 7: 0.6, 6: 0.5, 5: 0.4, 4: 0.3, 3: 0.2, 2: 0.1, 1: 0.05}

    def adjust_hand_strength(self, hand_strength, num_players, betting_round):
        if betting_round == 'preflop':
            return hand_strength
        else:
            adjusted_strength = hand_strength - num_players // 2
            return max(adjusted_strength, 1)

    def decide_action(self, hand_strength, stack, already_bet, legal_actions):
        if hand_strength >= 7:
            return 'raise' if 'raise' in legal_actions else 'call'
        elif hand_strength >= 5:
            return 'call' if 'call' in legal_actions else 'check'
        else:
            return 'check' if 'check' in legal_actions else 'fold'

    def calculate_amount(self, action, stack, already_bet, info):
        if action == 'raise':
            min_raise_to = int(info.get('min_raise_to') or 0)
            pot_size = int(info.get('pot') or 0)
            raise_percentage = self.preflop_raise_percentages.get(info.get('betting_round'), 0.5)
            raise_amount = min(int(pot_size * raise_percentage), stack + already_bet)
            return max(min_raise_to, raise_amount)
        elif action == 'call':
            return min(int(info.get('call_amount') or 0), stack)
        else:
            return 0

class BluffingStrategy:
    def __init__(self):
        self.bluffing_frequency = 0.1

    def should_bluff(self, info):
        return random.random() < self.bluffing_frequency

    def get_bluff_action(self, legal_actions):
        if 'raise' in legal_actions:
            return 'raise'
        elif 'call' in legal_actions:
            return 'call'
        else:
            return 'check'

class Agent:
    def __init__(self):
        self.hand_strength_evaluator = HandStrengthEvaluator()
        self.strategy = Strategy()
        self.bluffing_strategy = BluffingStrategy()

    def decide(self, info):
        start_time = time.time()
        time_limit = info.get("time_limit", 0.5)  # Default to 0.5 seconds if not provided

        legal_actions = list(info.get("legal_actions") or [])
        if not legal_actions:
            return {"action": "fold", "amount": 0}

        stack = int(info.get("stack") or 0)
        already_bet = int(info.get("street_bet_self") or 0)
        
        # Evaluate hand strength
        hole_cards = info.get("hole_cards")
        community_cards = info.get("community_cards")
        hand_strength = self.hand_strength_evaluator.evaluate(hole_cards, community_cards)

        # Adjust hand strength based on game conditions
        num_players = len(info.get("players") or [])
        betting_round = info.get("betting_round")
        adjusted_hand_strength = self.strategy.adjust_hand_strength(hand_strength, num_players, betting_round)

        # Determine the best action based on strategies and game conditions
        best_action = self.strategy.decide_action(adjusted_hand_strength, stack, already_bet, legal_actions)

        # Incorporate bluffing strategy
        if self.bluffing_strategy.should_bluff(info):
            best_action = self.bluffing_strategy.get_bluff_action(legal_actions)

        # Calculate the betting amount based on the chosen action
        amount = self.strategy.calculate_amount(best_action, stack, already_bet, info)

        # Time management: if the algorithm is close to the time limit, make a quick decision
        elapsed_time = time.time() - start_time
        if elapsed_time > time_limit * 0.8:
            if "check" in legal_actions:
                best_action = "check"
                amount = 0
            else:
                best_action = "fold"
                amount = 0

        return {"action": best_action, "amount": amount}