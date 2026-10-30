"""Atlas: a self-contained, standard-library-only Agent Hold'em submission.

Copy this file into agents/. Only the supplied info dict is used for decisions.
The range model and Monte Carlo equities are estimates, not a solved strategy.
"""

import itertools
import math
import random
import time


_SUITS = {"♠": 0, "♥": 1, "♦": 2, "♣": 3, "s": 0, "h": 1, "d": 2, "c": 3}
_RANKS = {str(n): n for n in range(2, 11)}
_RANKS.update({"T": 10, "J": 11, "Q": 12, "K": 13, "A": 14})
_DECK = tuple(range(52))
_CATEGORY = 15 ** 5


def _card(text):
    return (_RANKS[text[:-1].upper()] - 2) * 4 + _SUITS[text[-1]]


def _straight(mask):
    for high in range(14, 5, -1):
        pattern = 31 << (high - 6)
        if mask & pattern == pattern:
            return high
    return 5 if mask & 0x100F == 0x100F else 0


_STRAIGHTS = tuple(_straight(mask) for mask in range(8192))
_BIT_COUNTS = tuple(bin(mask).count("1") for mask in range(8192))


def _pack(category, kickers):
    value = category * _CATEGORY
    for i, rank in enumerate(kickers):
        value += rank * 15 ** (4 - i)
    return value


def _evaluate(cards):
    """Best five of 5–7 cards, as one comparable integer (including kickers)."""
    counts = [0] * 15
    suits = [0] * 4
    mask = 0
    for card in cards:
        rank = card // 4 + 2
        bit = 1 << (rank - 2)
        counts[rank] += 1
        suits[card % 4] |= bit
        mask |= bit

    flush_mask = next((m for m in suits if _BIT_COUNTS[m] >= 5), 0)
    if flush_mask and _STRAIGHTS[flush_mask]:
        return _pack(8, [_STRAIGHTS[flush_mask]])
    ranks = [r for r in range(14, 1, -1) if counts[r]]
    quads = next((r for r in ranks if counts[r] == 4), 0)
    if quads:
        return _pack(7, [quads, next(r for r in ranks if r != quads)])
    trips = [r for r in ranks if counts[r] >= 3]
    pairs = [r for r in ranks if counts[r] >= 2]
    if trips:
        other = next((r for r in pairs if r != trips[0]), 0)
        if other:
            return _pack(6, [trips[0], other])
    if flush_mask:
        return _pack(5, [r for r in range(14, 1, -1) if flush_mask & (1 << (r - 2))][:5])
    if _STRAIGHTS[mask]:
        return _pack(4, [_STRAIGHTS[mask]])
    if trips:
        return _pack(3, trips[:1] + [r for r in ranks if r != trips[0]][:2])
    if len(pairs) >= 2:
        return _pack(2, pairs[:2] + [r for r in ranks if r not in pairs[:2]][:1])
    if pairs:
        return _pack(1, pairs[:1] + [r for r in ranks if r != pairs[0]][:3])
    return _pack(0, ranks[:5])


def _starting_quality(hole):
    """Starting-hand ordering, not an equity percentage."""
    high, low = sorted((c // 4 + 2 for c in hole), reverse=True)
    if high == low:
        return 0.55 + 0.035 * (high - 2)
    gap = high - low
    suited = hole[0] % 4 == hole[1] % 4
    quality = 0.16 + 0.025 * (high - 2) + 0.012 * (low - 2)
    quality += 0.06 if suited else 0
    quality += 0.07 if low >= 10 else 0
    quality += 0.045 if gap == 1 else 0.02 if gap == 2 else 0
    quality -= 0.025 if gap >= 5 and high < 14 else 0
    quality += 0.025 if high == 14 and suited and low <= 5 else 0
    return min(0.99, quality)


def _draw(hole, board):
    """A live flush or open-ended/double-gutshot straight draw."""
    if len(board) not in (3, 4):
        return False
    cards = hole + board
    suit_counts = [sum(c % 4 == s for c in cards) for s in range(4)]
    if any(suit_counts[c % 4] == 4 for c in hole):
        return True
    ranks = {c // 4 + 2 for c in cards}
    if 14 in ranks:
        ranks.add(1)
    if any(set(range(start, start + 5)) <= ranks for start in range(1, 11)):
        return False
    outs = set()
    for start in range(1, 11):
        missing = set(range(start, start + 5)) - ranks
        if len(missing) == 1:
            outs.update(missing)
    # Do not count a straight already made or a draw entirely on the board.
    return len(outs) >= 2 and any(c // 4 + 2 not in {b // 4 + 2 for b in board} for c in hole)


def _made_quality(hole, board):
    """Cheap fallback for tiny clocks, also used to soften opponent ranges."""
    score = _evaluate(hole + board)
    category = score // _CATEGORY
    rank = (score % _CATEGORY) // (15 ** 4)
    quality = (0.12, 0.43, 0.68, 0.80, 0.88, 0.92, 0.96, 0.99, 1.0)[category]
    if category <= 1:
        quality += 0.015 * (rank - 2)
    if len(board) == 5 and score == _evaluate(board):
        quality *= 0.60
    elif category == 1 and sum(b // 4 + 2 == rank for b in board) >= 2:
        quality *= 0.72
    if _draw(hole, board):
        quality += 0.08
    return min(1.0, quality)


def _contributions(info):
    """Reconstruct committed chips from the engine's street-total history."""
    totals = [0] * len(info["stacks"])
    previous = {}
    for entry in info.get("history", []):
        key = (entry["street"], entry["seat"])
        chips = int(entry.get("to", 0))
        totals[entry["seat"]] += max(0, chips - previous.get(key, 0))
        previous[key] = chips
    return totals


def _pot_layers(info, opponents):
    """Contestable pot after calling, with eligibility for short all-ins.

    An opponent who still has chips may call into a layer later. An all-in
    opponent can only contest layers covered by their committed chips.
    Folded chips add to pot sizes but never to the eligible opponent set.
    """
    hero = info["seat"]
    call = min(info["stack"], info["to_call"])
    committed = _contributions(info)
    # The normal engine always supplies complete history. Keep partial fixtures
    # usable without pretending we can reconstruct their side pots.
    if sum(committed) != info["pot"]:
        return [(float(info["pot"] + call), tuple(range(len(opponents))))]
    committed[hero] += call
    cap = committed[hero]
    levels = sorted({min(c, cap) for c in committed if c > 0} |
                    {min(committed[i] + info["stacks"][i], cap) for i in opponents})
    layers = []
    previous = 0
    for level in levels:
        if level <= previous:
            continue
        chips = sum(max(0, min(c, level) - previous) for c in committed)
        eligible = tuple(j for j, seat in enumerate(opponents)
                         if committed[seat] + info["stacks"][seat] >= level)
        if chips:
            layers.append((float(chips), eligible))
        previous = level
    return layers or [(float(max(1, info["pot"] + call)), tuple(range(len(opponents))))]


def _range_profiles(info, opponents):
    profiles = []
    for seat in opponents:
        actions = [e for e in info.get("history", []) if e["seat"] == seat]
        raises = sum(e["action"] in ("bet", "raise") for e in actions if e["street"] == "preflop")
        called = any(e["action"] == "call" for e in actions if e["street"] == "preflop")
        threshold = min(0.74, 0.49 + 0.08 * raises) if raises else 0.43 if called else 0.30
        post = [e for e in actions if e["street"] != "preflop" and e["action"] in ("bet", "raise")]
        board_length = {"flop": 3, "turn": 4, "river": 5}.get(post[-1]["street"], 0) if post else 0
        profiles.append((threshold, min(len(post), 3), board_length))
    return profiles


def _range_weight(hole, board, profile):
    threshold, aggression, board_length = profile
    # Broad floors avoid treating the arena's random opponents as tight pros.
    quality = _starting_quality(hole)
    weight = 0.18 + 0.82 / (1.0 + math.exp((threshold - quality) * 12))
    if aggression and len(board) >= 3:
        # A flop bet conditions the range on the flop, even if a later card
        # completes or misses a draw. Do not give that earlier action hindsight.
        made = _made_quality(hole, board[:board_length])
        weight *= 0.22 + 0.78 * made ** (1 + 0.4 * aggression)
    return weight


class _HeuristicAgent:
    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.last_decision = {}  # Local diagnostics; never part of the engine reply.
        self.max_samples = 2400
        self.max_think = 0.18

    def _equity(self, info, hole, board, opponents, layers, deadline):
        """Range-weighted Monte Carlo, sharing ties and handling side pots.

        Opponents are drawn sequentially without replacement. Rejection is
        bounded so even a 22-seat game makes progress; this is an approximate
        range model, not exact joint range enumeration.
        """
        count = len(opponents)
        quality = _starting_quality(hole) if not board else _made_quality(hole, board)
        prior = min(0.99, max(0.01, quality ** (0.7 + count * 0.45)))
        if not count:
            return 1.0, 0
        if info["time_limit"] <= 0.004:
            return prior, 0
        known = set(hole + board)
        unseen = [c for c in _DECK if c not in known]
        profiles = _range_profiles(info, opponents)
        caches = [{} for _ in opponents]
        pot = sum(chips for chips, _ in layers)
        samples, total = 0, 0.0
        missing = 5 - len(board)
        while samples < self.max_samples and time.perf_counter() < deadline:
            deck = unseen[:]
            hands = []
            for j, profile in enumerate(profiles):
                for attempt in range(16):
                    first = self.rng.randrange(len(deck))
                    second = self.rng.randrange(len(deck) - 1)
                    if second >= first:
                        second += 1
                    a, b = deck[first], deck[second]
                    key = min(a, b) * 52 + max(a, b)
                    weight = caches[j].get(key)
                    if weight is None:
                        weight = caches[j][key] = _range_weight([a, b], board, profile)
                    if self.rng.random() < weight or attempt == 15:
                        break
                hands.append([a, b])
                # Remove indices descending so both refer to the sampled pair.
                for index in sorted((first, second), reverse=True):
                    deck[index] = deck[-1]
                    deck.pop()
            runout = board + self.rng.sample(deck, missing)
            hero_score = _evaluate(hole + runout)
            scores = [_evaluate(hand + runout) for hand in hands]
            share = 0.0
            for chips, eligible in layers:
                best = max((scores[j] for j in eligible), default=-1)
                if hero_score > best:
                    share += chips
                elif hero_score == best:
                    share += chips / (1 + sum(scores[j] == best for j in eligible))
            total += share / pot
            samples += 1
        # A small prior stabilizes very short runs. At normal clocks the samples
        # dominate; a board that everyone plays must still split correctly.
        if samples >= 32:
            return total / samples, samples
        return (total + 8 * prior) / (samples + 8), samples

    @staticmethod
    def _passive(info, call=False):
        legal = info["legal_actions"]
        action = "check" if "check" in legal else "call" if call and "call" in legal else "fold"
        if action not in legal and legal:
            action = legal[0]
        return {"action": action, "amount": 0}

    def _wager(self, info, target):
        legal = info["legal_actions"]
        action = "raise" if "raise" in legal else "bet" if "bet" in legal else None
        if action is None:
            return self._passive(info, call=True)
        maximum = min(info["max_raise_to"], info["street_bet_self"] + info["stack"])
        minimum = info["min_raise_to"] if action == "raise" else info["min_bet"]
        minimum = min(minimum, maximum)  # Short all-in is still legal.
        amount = int(min(maximum, max(minimum, round(target))))
        if amount <= info["current_bet"]:
            return self._passive(info, call=True)
        return {"action": action, "amount": amount}

    def decide(self, info):
        started = time.perf_counter()
        if not info.get("legal_actions"):
            return {"action": "fold", "amount": 0}
        hole = [_card(c) for c in info["hole_cards"]]
        board = [_card(c) for c in info["board"]]
        seat = info["seat"]
        opponents = [i for i, folded in enumerate(info["folded"]) if i != seat and not folded]
        count = len(opponents)
        active = sorted([seat] + opponents, key=lambda i: (i - info["button"] - 1) % len(info["stacks"]))
        position = active.index(seat) / max(1, count)
        deadline = started + min(self.max_think, max(0, info["time_limit"]) * 0.25)
        layers = _pot_layers(info, opponents)
        pot_after_call = sum(chips for chips, _ in layers)
        call = min(info["to_call"], info["stack"])
        price = call / max(1, pot_after_call)
        equity, samples = self._equity(info, hole, board, opponents, layers, deadline)
        bb = max(1, info["blinds"][1])
        stack_bb = info["stack"] / bb
        quality = _starting_quality(hole)
        legal = info["legal_actions"]
        can_raise = "raise" in legal or "bet" in legal
        reason = "pot odds"

        if not count:
            reply = self._passive(info, call=True)
            reason = "uncontested"
        elif not board:
            raises = [e for e in info.get("history", []) if e["street"] == "preflop" and e["action"] in ("bet", "raise")]
            limpers = sum(e["street"] == "preflop" and e["action"] == "call" for e in info.get("history", []))
            opening = 0.47 + 0.018 * max(0, count - 1) - 0.10 * position
            opening += 0.10 if count >= 3 else 0
            opening -= 0.04 if stack_bb <= 12 else 0
            premium = quality >= 0.88
            value_raise = equity >= max(0.57, 1 / (count + 1) + 0.15) and equity - price > 0.18
            if can_raise and ((not raises and quality >= opening) or premium or (raises and value_raise)):
                if raises:
                    target = max(info["min_raise_to"], info["current_bet"] * (2.7 + 0.5 * (1 - position)))
                else:
                    target = bb * (2.4 + 0.8 * limpers + 0.4 * (1 - position))
                # Fast-rising blinds make shallow-stack pressure important.
                if stack_bb <= 10 or target - info["street_bet_self"] >= 0.65 * info["stack"]:
                    target = info["max_raise_to"]
                reply = self._wager(info, target)
                reason = "preflop value" if raises else "position-aware open"
            else:
                margin = 0.035 + 0.025 * (1 - position)
                can_call = equity >= price + margin
                if not raises and call and quality < opening:
                    can_call = can_call and quality >= (0.35 if count == 1 else 0.46)
                reply = self._passive(info, call=can_call)
        else:
            all_in_call = call >= info["stack"]
            realization = 1.0 if len(board) == 5 or all_in_call else max(0.78, 0.91 + 0.07 * position - 0.025 * (count - 1))
            margin = 0.008 if len(board) == 5 or all_in_call else 0.025
            can_call = equity * realization >= price + margin
            value_floor = max(0.35, 1 / (count + 1) + 0.12)
            raise_floor = max(0.62, 1 / (count + 1) + 0.23)
            draw = _draw(hole, board)
            value = equity >= (raise_floor if call else value_floor)
            semi_bluff = not call and draw and count <= 2 and equity >= 0.30 and self.rng.random() < 0.16 + 0.10 * position
            # A few late-position river bluffs with an ace blocker. Never bluff
            # into an all-in player, who cannot fold, or into multiple players.
            bluff = (not call and len(board) == 5 and count == 1 and position == 1
                     and info["stacks"][opponents[0]] > 0 and equity < 0.25
                     and any(c // 4 == 12 for c in hole) and self.rng.random() < 0.06)
            if can_raise and (value or semi_bluff or bluff) and (not call or equity - price > 0.18):
                fraction = 0.80 if equity >= 0.82 else 0.55 if value else 0.50
                # Raise-to = our previous street bet + call + the new raise.
                # Use only the pot we cover; oversized side pots must not inflate sizing.
                target = info["street_bet_self"] + call + max(bb, pot_after_call * fraction)
                if value and target - info["street_bet_self"] >= 0.65 * info["stack"]:
                    target = info["max_raise_to"]
                reply = self._wager(info, target)
                reason = "value bet" if value else "semi-bluff" if semi_bluff else "ace-blocker bluff"
            else:
                reply = self._passive(info, call=can_call)

        self.last_decision = {**reply, "reason": reason, "equity": round(equity, 4),
                              "pot_odds": round(price, 4), "samples": samples,
                              "eligible_pot": pot_after_call, "seconds": time.perf_counter() - started}
        return reply


class Agent(_HeuristicAgent):
    """Atlas 2: opponent adaptation and sampled action-value search.

    Uses only public history plus our own cards. Chip EV estimates assume a
    modeled call/fold response and a discounted showdown; future raises are
    approximated. This is not CFR, Nash equilibrium, or a solved poker policy.
    """

    def __init__(self, seed=None):
        super().__init__(seed)
        self.max_samples = 3600
        self.max_think = 0.45
        self.opponents = {}
        self._token = None
        self._observed = []
        self._entered = set()
        self._raised = set()
        self._records = []
        self._method = "heuristic"
        self._exact = False

    def _observe(self, info):
        token = (info["button"], tuple(info["hole_cards"]), tuple(info["blinds"]))
        history = info.get("history", [])
        new_hand = token != self._token or history[:len(self._observed)] != self._observed
        if new_hand:
            self._token, self._observed = token, []
            self._entered, self._raised = set(), set()
            for seat, folded in enumerate(info["folded"]):
                if seat == info["seat"]:
                    continue
                stat = self.opponents.setdefault(seat, {"hands": 0, "vpip": 0, "pfr": 0,
                                                        "actions": 0, "aggressive": 0, "facing": 0, "folds": 0})
                if info["stacks"][seat] or not folded:
                    stat["hands"] += 1
        # Rebuild street maxima to recognize folds facing a wager.
        maxima = {}
        for index, entry in enumerate(history):
            street, seat, action = entry["street"], entry["seat"], entry["action"]
            current = maxima.get(street, 0)
            if index >= len(self._observed) and seat != info["seat"]:
                stat = self.opponents.setdefault(seat, {"hands": 1, "vpip": 0, "pfr": 0,
                                                        "actions": 0, "aggressive": 0, "facing": 0, "folds": 0})
                if action != "blind":
                    stat["actions"] += 1
                    stat["aggressive"] += action in ("bet", "raise")
                    # Historical 'to' is still the player's old commitment on a fold.
                    facing = action in ("fold", "call", "raise") and current > (entry.get("to", 0) if action == "fold" else 0)
                    stat["facing"] += bool(facing)
                    stat["folds"] += action == "fold" and facing
                if street == "preflop" and action in ("call", "bet", "raise") and seat not in self._entered:
                    stat["vpip"] += 1
                    self._entered.add(seat)
                if street == "preflop" and action in ("bet", "raise") and seat not in self._raised:
                    stat["pfr"] += 1
                    self._raised.add(seat)
            maxima[street] = max(current, entry.get("to", 0))
        self._observed = [dict(e) for e in history]

    def _style(self, seat):
        s = self.opponents.get(seat, {})
        return {"hands": s.get("hands", 0),
                "vpip": (s.get("vpip", 0) + 4.5) / (s.get("hands", 0) + 10),
                "pfr": (s.get("pfr", 0) + 2.5) / (s.get("hands", 0) + 10),
                "aggression": (s.get("aggressive", 0) + 2) / (s.get("actions", 0) + 8),
                "fold": (s.get("folds", 0) + 2) / (s.get("facing", 0) + 6)}

    def _equity(self, info, hole, board, opponents, layers, deadline):
        self._records = []
        self._method, self._exact = "Monte Carlo", False
        count = len(opponents)
        if not count or info["time_limit"] <= 0.004 or self.max_samples == 0:
            self._method = "fast heuristic"
            return super()._equity(info, hole, board, opponents, layers, deadline)
        # Reserve part of the move for response modeling and action evaluation.
        sample_deadline = time.perf_counter() + max(0, deadline - time.perf_counter()) * 0.72
        known = set(hole + board)
        unseen = [c for c in _DECK if c not in known]
        profiles = []
        for seat, (threshold, aggression, length) in zip(opponents, _range_profiles(info, opponents)):
            style = self._style(seat)
            evidence = style["hands"] / (style["hands"] + 24)
            # Entering many pots does not imply a loose raising range. Use PFR
            # for raised pots, VPIP for passive entries, and shrink small samples.
            frequency, center = (style["pfr"], 0.28) if threshold >= 0.57 else (style["vpip"], 0.40)
            threshold -= min(0.08, evidence * max(0, frequency - center) * 0.32)
            threshold += min(0.08, evidence * max(0, center - frequency) * 0.32)
            profiles.append((threshold, aggression, length))
        caches = [{} for _ in opponents]
        pot = sum(p for p, _ in layers)
        total, weight_sum, samples = 0.0, 0.0, 0
        hero_river = _evaluate(hole + board) if len(board) == 5 else None
        exact = count == 1 and len(board) == 5 and self.max_samples >= 990 and deadline - time.perf_counter() >= 0.025
        combinations = iter(itertools.combinations(unseen, 2)) if exact else None
        exhausted = False
        while samples < self.max_samples and time.perf_counter() < sample_deadline:
            if exact:
                pair = next(combinations, None)
                if pair is None:
                    exhausted = True
                    break
                hands, runout = [list(pair)], board
                weight = _range_weight(list(pair), board, profiles[0])
            else:
                deck, hands = unseen[:], [None] * count
                order = list(range(count))
                self.rng.shuffle(order)  # Avoid always conditioning the same seat last.
                for j in order:
                    for attempt in range(64):
                        first = self.rng.randrange(len(deck))
                        second = self.rng.randrange(len(deck) - 1)
                        second += second >= first
                        a, b = deck[first], deck[second]
                        key = min(a, b) * 52 + max(a, b)
                        likelihood = caches[j].get(key)
                        if likelihood is None:
                            likelihood = caches[j][key] = _range_weight([a, b], board, profiles[j])
                        if self.rng.random() < likelihood:
                            break
                        if attempt % 8 == 7 and time.perf_counter() >= sample_deadline:
                            return (total / weight_sum, samples) if samples else super()._equity(info, hole, board, opponents, layers, time.perf_counter())
                    hands[j] = [a, b]
                    for index in sorted((first, second), reverse=True):
                        deck[index] = deck[-1]
                        deck.pop()
                runout = board + self.rng.sample(deck, 5 - len(board))
                weight = 1.0
            hero = hero_river if hero_river is not None else _evaluate(hole + runout)
            scores = tuple(_evaluate(h + runout) for h in hands)
            qualities = tuple(_starting_quality(h) if not board else _made_quality(h, board) for h in hands)
            randoms = tuple(self.rng.random() for _ in opponents)
            share = 0.0
            for chips, eligible in layers:
                best = max((scores[j] for j in eligible), default=-1)
                if hero >= best:
                    share += chips / (1 + sum(scores[j] == hero for j in eligible))
            total += weight * share / pot
            weight_sum += weight
            samples += 1
            self._records.append((hero, scores, qualities, randoms, weight))
        # Reaching all 990 combinations also completes enumeration without an
        # extra iterator step when max_samples == 990.
        if exact and (exhausted or samples == 990):
            self._method, self._exact = "exact river", True
        elif exact:
            # A partial lexicographic enumeration is biased. Discard it and use
            # the conservative heuristic rather than label it sampled equity.
            self._records = []
            self._method = "fast heuristic"
            return super()._equity(info, hole, board, opponents, layers, time.perf_counter())
        if weight_sum:
            return total / weight_sum, samples
        self._method = "fast heuristic"
        return super()._equity(info, hole, board, opponents, layers, time.perf_counter())

    def _response(self, quality, seat, cost, pot, board, players):
        """Call probability from public texture, price, and observed tendencies.

        Crucially, quality uses the board at the time of the decision, never the
        sampled future runout. Strong ranges therefore stay stronger when called.
        """
        if cost <= 0:
            return 1.0
        style = self._style(seat)
        price = cost / max(1, pot + cost)
        strength = quality ** (0.88 + 0.20 * max(0, players - 1))
        rational = 1 / (1 + math.exp(max(-25, min(25, (price + 0.11 - strength) * 11))))
        # The arena includes loose random bots. Blend the hand-based model with
        # a broad behavior prior instead of assuming every opponent folds trash.
        loose = max(0.12, min(0.88, 1 - style["fold"]))
        evidence = min(0.7, style["hands"] / 28)
        probability = rational * (0.65 - evidence * 0.3) + loose * (0.35 + evidence * 0.3)
        return max(0.06, min(0.98, probability))

    @staticmethod
    def _settlement(committed, live, hero):
        """Pot layers for a hypothetical response; dead chips stay in the pot."""
        cap = committed[hero]
        levels = sorted({min(c, cap) for c in committed if c > 0})
        layers, previous = [], 0
        for level in levels:
            chips = sum(max(0, min(c, level) - previous) for c in committed)
            eligible = tuple(i for i in live if committed[i] >= level)
            if chips and hero in eligible:
                layers.append((chips, eligible))
            previous = level
        return layers

    def _search(self, info, opponents, equity, position, deadline):
        count, seat = len(opponents), info["seat"]
        stack, already, owed = info["stack"], info["street_bet_self"], info["to_call"]
        call = min(stack, owed)
        layers = _pot_layers(info, opponents)
        pot = sum(chips for chips, _ in layers)
        board = info["board"]
        realization = 1.0 if len(board) == 5 or call == stack else max(0.82, 0.92 + 0.06 * position - 0.018 * (count - 1))
        passive = self._passive(info, call=True)
        check = passive["action"] == "check"
        call_ev = equity * pot * realization - call
        choices = [{**passive, "ev": call_ev, "uncertainty": 0.0, "fold_equity": 0.0}]
        if not check:
            choices.append({"action": "fold", "amount": 0, "ev": 0.0, "uncertainty": 0.0, "fold_equity": 0.0})
        if not self._records or not ({"bet", "raise"} & set(info["legal_actions"])):
            return max(choices, key=lambda c: c["ev"]), choices
        if len(board) == 5:
            public = [_card(c) for c in board]
            private = [_card(c) for c in info["hole_cards"]]
            if _evaluate(public + private) == _evaluate(public):
                # Board-only hands cannot value-raise better holdings. In
                # particular, never invent fold equity on a shared royal flush.
                return max(choices, key=lambda c: c["ev"]), choices
        commitments = _contributions(info)
        if sum(commitments) != info["pot"]:
            return max(choices, key=lambda c: c["ev"]), choices
        targets = set()
        for fraction in (0.33, 0.66, 1.0):
            reply = self._wager(info, already + call + max(info["blinds"][1], pot * fraction))
            if reply["action"] in ("raise", "bet"):
                targets.add(reply["amount"])
        # Always consider a shove at <= 15 BB, or when it is at most 1.5 pots.
        # Deep-stack shoves require extremely high equity to limit model error.
        if stack <= 15 * info["blinds"][1] or stack <= 1.5 * pot or equity > 0.93:
            targets.add(info["max_raise_to"])
        for target in sorted(targets):
            if time.perf_counter() >= deadline:
                break
            cost = target - already
            extras = [min(info["stacks"][i], max(0, target - info["street_bet"][i])) for i in opponents]
            settlement_cache = {}
            total, squared, weight_sum, uncontested = 0.0, 0.0, 0.0, 0.0
            for record_index, (hero_score, scores, qualities, randoms, weight) in enumerate(self._records):
                if record_index % 32 == 0 and time.perf_counter() >= deadline:
                    break
                mask = 0
                for j, other in enumerate(opponents):
                    probability = self._response(qualities[j], other, extras[j], info["pot"] + cost, board, count)
                    if info["stacks"][other] == 0 or randoms[j] < probability:
                        mask |= 1 << j
                pots = settlement_cache.get(mask)
                if pots is None:
                    invested = commitments[:]
                    invested[seat] += cost
                    live = [seat]
                    for j, other in enumerate(opponents):
                        if mask & (1 << j):
                            live.append(other)
                            invested[other] += extras[j]
                    pots = self._settlement(invested, live, seat)
                    settlement_cache[mask] = pots
                winnings = 0.0
                for chips, eligible in pots:
                    enemy = [scores[j] for j, other in enumerate(opponents) if other in eligible]
                    best = max(enemy, default=-1)
                    if hero_score >= best:
                        share = chips / (1 + sum(s == hero_score for s in enemy))
                        # Uncalled excess is returned in full; only contestable
                        # showdown shares need a future-street discount.
                        winnings += share * (realization if enemy else 1.0)
                value = winnings - cost
                total += weight * value
                squared += weight * value * value
                weight_sum += weight
                uncontested += weight * (mask == 0)
            if weight_sum:
                ev = total / weight_sum
                variance = max(0, squared / weight_sum - ev * ev)
                error = math.sqrt(variance / max(1, record_index + 1))
                # A sampling-error deduction avoids selecting a noisy, costly
                # shove solely because its few simulations happened to win.
                score = ev - 0.65 * error
                choices.append({**self._wager(info, target), "ev": score,
                                "uncertainty": error, "fold_equity": uncontested / weight_sum})
        best = max(choices, key=lambda c: c["ev"])
        # Tiny predicted gains do not justify a large commitment under a rough
        # response model; retain the passive line in statistically close spots.
        if best["action"] in ("bet", "raise") and best["ev"] < call_ev + max(info["blinds"][1] * 0.18, pot * 0.025):
            best = max(choices[:1] if check else choices[:2], key=lambda c: c["ev"])
        return best, choices

    def decide(self, info):
        started = time.perf_counter()
        if not info.get("legal_actions"):
            return {"action": "fold", "amount": 0}
        self._hero_seat = info["seat"]
        self._observe(info)
        reply = super().decide(info)
        diagnostic = dict(self.last_decision)
        deadline = started + min(self.max_think, max(0, info["time_limit"]) * 0.42)
        opponents = [i for i, folded in enumerate(info["folded"]) if i != info["seat"] and not folded]
        candidates = []
        # Preflop retains structured positional ranges. Postflop uses a joint
        # search over public-range cards, call/fold responses, and bet sizes.
        if info["board"] and opponents and self._records and time.perf_counter() < deadline:
            active = sorted([info["seat"]] + opponents, key=lambda i: (i - info["button"] - 1) % len(info["stacks"]))
            position = active.index(info["seat"]) / len(opponents)
            best, candidates = self._search(info, opponents, diagnostic["equity"], position, deadline)
            # Response models are least reliable when inventing new bluffs or
            # assuming future streets check through. Keep the equity/position
            # policy's continue and value thresholds, and use EV to size its
            # aggressive lines. Exact river equity may refine calls/folds.
            if reply["action"] in ("bet", "raise"):
                aggressive = [c for c in candidates if c["action"] in ("bet", "raise")]
                if diagnostic["equity"] < 0.80:
                    # The response model does not simulate future reraises.
                    # Avoid increasing a marginal value bet or bluff by a large
                    # factor solely on that incomplete model's optimistic EV.
                    aggressive = [c for c in aggressive if c["amount"] - info["street_bet_self"] <= 1.25 * (reply["amount"] - info["street_bet_self"])]
                if aggressive:
                    best = max(aggressive, key=lambda c: c["ev"])
                    reply = {"action": best["action"], "amount": int(best["amount"])}
                    diagnostic["reason"] = "value range / modeled size EV"
            elif self._exact and reply["action"] in ("call", "fold"):
                passive = [c for c in candidates if c["action"] in ("call", "fold")]
                if passive:
                    best = max(passive, key=lambda c: c["ev"])
                    reply = {"action": best["action"], "amount": int(best["amount"])}
                    diagnostic["reason"] = "profitable call" if reply["action"] == "call" else "negative call EV"
        diagnostic.update(reply)
        diagnostic.update({"method": self._method, "exact": self._exact,
                           "equity_error": 0.0 if self._exact else math.sqrt(max(0, diagnostic.get("equity", 0.5) * (1 - diagnostic.get("equity", 0.5))) / max(1, diagnostic.get("samples", 0))),
                           "candidates": [{**c, "ev": round(c["ev"], 2), "uncertainty": round(c["uncertainty"], 2)} for c in candidates],
                           "opponents": {str(i): {k: round(v, 3) if isinstance(v, float) else v for k, v in self._style(i).items()} for i in opponents},
                           "seconds": time.perf_counter() - started})
        self.last_decision = diagnostic
        return reply

    def hand_over(self, result):
        # The fast race does not call this hook. Normal decide() ingestion is
        # sufficient; this optional hook just captures actions after our turn.
        if self._token is not None:
            info = {"button": self._token[0], "hole_cards": self._token[1], "blinds": self._token[2],
                    "history": result["history"], "seat": self._hero_seat, "folded": [False] * len(result["stacks"]),
                    "stacks": result["stacks"]}
            self._observe(info)
