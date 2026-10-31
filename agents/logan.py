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
        self.preflop_hand_range = self.create_preflop_hand_range()
        self.opponent_stats = defaultdict(lambda: {'raise_frequency': 0, 'call_frequency': 0, 'fold_frequency': 0})

    def create_preflop_hand_range(self):
        preflop_hand_range = {}

        # Pocket pairs
        for value in range(2, 15):
            hand = (value, value)
            preflop_hand_range[hand] = 1

        # Suited connectors
        for value1 in range(2, 15):
            for value2 in range(value1 + 1, 15):
                hand = (value1, value2)
                if abs(value1 - value2) <= 2:
                    preflop_hand_range[hand] = 0.9

        # Offsuit connectors
        for value1 in range(2, 15):
            for value2 in range(value1 + 1, 15):
                hand = (value1, value2)
                if abs(value1 - value2) <= 2:
                    preflop_hand_range[hand] = 0.8

        # Suited high cards
        for value1 in range(10, 15):
            for value2 in range(2, value1):
                hand = (value1, value2)
                preflop_hand_range[hand] = 0.7

        return preflop_hand_range

    def update_opponent_stats(self, opponent_id, action):
        self.opponent_stats[opponent_id][action + '_frequency'] += 1

    def adjust_hand_strength(self, hand_strength, num_players, betting_round, community_cards):
        # Adjust hand strength based on the number of players
        adjusted_strength = hand_strength - num_players // 2

        # Adjust hand strength based on the betting round
        if betting_round == 'flop':
            adjusted_strength += 1
        elif betting_round == 'turn':
            adjusted_strength += 2
        elif betting_round == 'river':
            adjusted_strength += 3

        # Adjust hand strength based on potential draws
        suits = [card[1] for card in community_cards]
        values = [card[0] for card in community_cards]

        flush_draw = len(set(suits)) == 3 and any(suit_count >= 2 for suit_count in suits.values())
        straight_draw = any(
            values[i] + 1 == values[i+1] or values[i] + 2 == values[i+1]
            for i in range(len(values) - 1)
        )

        if flush_draw:
            adjusted_strength -= 1
        if straight_draw:
            adjusted_strength -= 1

        return max(adjusted_strength, 1)

    def decide_action(self, hand_strength, stack, already_bet, legal_actions, opponent_id):
        # Calculate the pot odds
        call_amount = min(int(info.get('call_amount') or 0), stack)
        pot_size = int(info.get('pot') or 0)
        pot_odds = call_amount / (pot_size + call_amount)

        # Determine the opponent's playing style
        total_actions = sum(self.opponent_stats[opponent_id].values())
        raise_frequency = self.opponent_stats[opponent_id]['raise_frequency'] / total_actions
        call_frequency = self.opponent_stats[opponent_id]['call_frequency'] / total_actions
        fold_frequency = self.opponent_stats[opponent_id]['fold_frequency'] / total_actions

        # Adjust the raise threshold based on the opponent's playing style
        raise_threshold = 7
        if raise_frequency > 0.3:
            raise_threshold -= 1
        elif call_frequency > 0.5:
            raise_threshold += 1

        # Decide the action based on hand strength and pot odds
        if hand_strength >= raise_threshold and random.random() < 0.8:
            return 'raise'
        elif hand_strength >= 5 and pot_odds <= 0.2:
            return 'call'
        elif hand_strength >= 4 and pot_odds <= 0.3:
            return 'call'
        else:
            return 'fold'

    def calculate_amount(self, action, stack, already_bet, info):
        if action == 'raise':
            min_raise_to = int(info.get('min_raise_to') or 0)
            pot_size = int(info.get('pot') or 0)
            raise_amount = min(int(pot_size * 0.75), stack + already_bet)
            return max(min_raise_to, raise_amount)
        elif action == 'call':
            return min(int(info.get('call_amount') or 0), stack)
        else:
            return 0

class BluffingStrategy:
    def __init__(self):
        self.bluffing_frequency = 0.2
        self.bluff_raise_amount = 0.5

    def should_bluff(self, info, hand_strength):
        # Bluff more often on scary board textures
        community_cards = info.get('community_cards', [])
        board_texture_score = self.evaluate_board_texture(community_cards)

        # Adjust bluffing frequency based on hand strength and board texture
        adjusted_bluffing_frequency = self.bluffing_frequency
        if hand_strength <= 2:
            adjusted_bluffing_frequency += board_texture_score * 0.1
        else:
            adjusted_bluffing_frequency -= hand_strength * 0.02

        return random.random() < adjusted_bluffing_frequency

    def evaluate_board_texture(self, community_cards):
        # Count the number of connected cards and same suits
        values = [card[0] for card in community_cards]
        suits = [card[1] for card in community_cards]

        connected_count = 0
        for i in range(len(values) - 1):
            if values[i] + 1 == values[i+1]:
                connected_count += 1

        max_suit_count = max([suits.count(suit) for suit in set(suits)])

        # Calculate the board texture score
        board_texture_score = connected_count + max_suit_count

        return board_texture_score

    def get_bluff_amount(self, action, stack, already_bet, info):
        if action == 'raise':
            min_raise_to = int(info.get('min_raise_to') or 0)
            pot_size = int(info.get('pot') or 0)
            raise_amount = min(int(pot_size * self.bluff_raise_amount), stack + already_bet)
            return max(min_raise_to, raise_amount)
        else:
            return 0

class Agent:
    def __init__(self):
        self.hand_strength_evaluator = HandStrengthEvaluator()
        self.strategy = Strategy()
        self.bluffing_strategy = BluffingStrategy()

    def decide(self, info):
        start_time = time.time()
        time_limit = info.get("time_limit", 0.5)

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
        adjusted_hand_strength = self.strategy.adjust_hand_strength(hand_strength, num_players, betting_round, community_cards)

        # Determine the opponent's ID
        opponent_id = list(set(player['id'] for player in info.get("players") if player['id'] != info.get("self_id")))[0]

        # Update opponent stats based on their last action
        last_action = info.get("last_action")
        if last_action:
            self.strategy.update_opponent_stats(opponent_id, last_action['action'])

        # Determine the best action based on strategies and game conditions
        best_action = self.strategy.decide_action(adjusted_hand_strength, stack, already_bet, legal_actions, opponent_id)

        # Incorporate bluffing strategy
        if self.bluffing_strategy.should_bluff(info, adjusted_hand_strength):
            bluff_action = self.bluffing_strategy.get_bluff_action(legal_actions)
            bluff_amount = self.bluffing_strategy.get_bluff_amount(bluff_action, stack, already_bet, info)
            best_action = bluff_action
            amount = bluff_amount
        else:
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