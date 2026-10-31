"""Atlas v3: a standalone, public-information, range-and-action-value bot.

Copy this file into agents/. Only the supplied info dict is used for decisions.
The range model and Monte Carlo equities are estimates, not a solved strategy.
"""

import base64
import bisect
import json
import zlib
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



# A percentile is a rank in the starting-hand population, not a win percentage.
_ALL_PAIRS = tuple(itertools.combinations(_DECK, 2))
_STARTING = {(a, b): _starting_quality([a, b]) for a, b in _ALL_PAIRS}
_START_SORTED = sorted(_STARTING.values())
_PREFLOP = {pair: (bisect.bisect_left(_START_SORTED, q) + bisect.bisect_right(_START_SORTED, q)) / (2 * len(_START_SORTED))
            for pair, q in _STARTING.items()}


def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-max(-30, min(30, x))))


def _potential(hole, board):
    """Hole-dependent straight/flush improvement probability using rank masks."""
    if len(board) not in (3, 4):
        return 0.0
    suit_counts = [0] * 4
    board_mask = 0
    mask = 0
    for card in hole + board:
        suit_counts[card % 4] += 1
        mask |= 1 << (card // 4)
    for card in board:
        board_mask |= 1 << (card // 4)
    if _STRAIGHTS[mask] or max(suit_counts) >= 5:
        return 0.0
    flush = any(suit_counts[c % 4] == 4 for c in hole)
    private = mask & ~board_mask
    missing_ranks = 0
    for pattern in (0x100F, 31, 62, 124, 248, 496, 992, 1984, 3968, 7936):
        missing = pattern & ~mask
        if pattern & private and missing and not (missing & (missing - 1)):
            missing_ranks |= missing
    ranks = _BIT_COUNTS[missing_ranks]
    outs = (9 if flush else 0) + (3 if flush else 4) * ranks
    remaining = 50 - len(board)
    miss = (remaining - outs) / remaining
    if len(board) == 3:
        miss *= max(0, remaining - outs - 1) / (remaining - 1)
    return min(0.45, (1 - miss) * 0.78)


def _events(info):
    """Public wager deltas and prices, reconstructed without hidden cards."""
    previous, maxima, pot = {}, {}, 0
    result = []
    for entry in info.get('history', []):
        seat, street, action = entry['seat'], entry['street'], entry['action']
        key = (seat, street)
        before = previous.get(key, 0)
        to = int(entry.get('to', 0))
        current = maxima.get(street, 0)
        cost = max(0, to - before)
        owed = max(0, current - before)
        result.append((seat, street, action, cost, owed, pot,
                       max(0, to - current) / max(1, pot + owed)))
        previous[key] = max(before, to)
        maxima[street] = max(current, to)
        pot += cost
    return result


# Generated by tools/build_v3_pushfold.py; no third-party strategy tables.
_PUSHFOLD_DATA = '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'
_PUSHFOLD = json.loads(zlib.decompress(base64.b64decode(_PUSHFOLD_DATA)))
_PUSHFOLD_INDEX = {key: i for i, key in enumerate(_PUSHFOLD["keys"])}
def _hand_class(pair):
    labels='23456789TJQKA';a,b=sorted(pair,key=lambda c:c//4,reverse=True)
    high,low=labels[a//4],labels[b//4]
    key=high+low if high==low else high+low+('s' if a%4==b%4 else 'o')
    return _PUSHFOLD_INDEX[key]

_HAND_CLASS={pair:_hand_class(pair) for pair in _ALL_PAIRS}
_PREFLOP_EQUITY={pair:_PUSHFOLD['equity'][index] for pair,index in _HAND_CLASS.items()}
_EQUITY_SORTED=sorted(_PREFLOP_EQUITY.values())
_PREFLOP={pair:(bisect.bisect_left(_EQUITY_SORTED,value)+bisect.bisect_right(_EQUITY_SORTED,value))/(2*len(_EQUITY_SORTED)) for pair,value in _PREFLOP_EQUITY.items()}



class Agent:
    """Atlas v3. No opponent identities, private cards, or engine introspection.

    Complete public-action likelihood ranges; collision-rejected joint deals;
    exact heads-up river enumeration; common-runout action EV with uncertainty.
    The opponent response model and future-street realization remain estimates.
    """

    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.max_samples = 2400
        self.max_think = 0.32
        self.last_decision = {}
        self.opponents = {}
        self._history = []
        self._token = None
        self._seen_vpip = set()
        self._seen_pfr = set()
        self._texture_cache = {}
        self._vector_cache = {}

    def _observe(self, info):
        token = (tuple(info['hole_cards']), info['button'], tuple(info['blinds']))
        history = info.get('history', [])
        if token != self._token or history[:len(self._history)] != self._history:
            self._token, self._history = token, []
            self._seen_vpip, self._seen_pfr = set(), set()
            self._texture_cache = {}
            self._vector_cache = {}
            for seat, stack in enumerate(info['stacks']):
                if seat != info['seat'] and (stack or not info['folded'][seat]):
                    self._stats(seat)['hands'] += 1
        events = _events(info)
        for seat, street, action, cost, owed, pot, size in events[len(self._history):]:
            if seat == info['seat'] or action == 'blind':
                continue
            s = self._stats(seat)
            s['actions'] += 1
            s['aggressive'] += action in ('bet', 'raise')
            s['facing'] += owed > 0
            s['folds'] += owed > 0 and action == 'fold'
            priced=owed>0 and owed/max(1,pot+owed)>=.18
            s['priced_facing'] += priced
            s['priced_folds'] += priced and action=='fold'
            if street == 'preflop' and action in ('call', 'bet', 'raise'):
                if seat not in self._seen_vpip:
                    s['vpip'] += 1
                    self._seen_vpip.add(seat)
                if action in ('bet', 'raise') and seat not in self._seen_pfr:
                    s['pfr'] += 1
                    self._seen_pfr.add(seat)
        self._history = [dict(e) for e in history]
        return events

    def _stats(self, seat):
        return self.opponents.setdefault(seat, dict(hands=0, vpip=0, pfr=0, actions=0, aggressive=0, facing=0, folds=0, priced_facing=0, priced_folds=0))

    def _style(self, seat, players):
        s = self._stats(seat)
        open_prior = 0.58 if players == 2 else 0.28
        vpip = (s['vpip'] + (0.68 if players == 2 else 0.43) * 7) / (s['hands'] + 7)
        pfr = (s['pfr'] + open_prior * 7) / (s['hands'] + 7)
        fold = (s['folds'] + 2) / (s['facing'] + 6)
        aggression = (s['aggressive'] + 2.4) / (s['actions'] + 8)
        evidence = s['actions'] / (s['actions'] + 12)
        aggressive_mix=min(.82,.10+evidence*max(0,vpip-.55)*max(0,aggression-.25)*5)
        # Competing public-response hypotheses: flat callers fold about 7%,
        # selective defenders about 40% at meaningful prices. Evidence updates
        # the odds directly; low aggression cannot cancel passive calling.
        n=s.get('priced_facing',0);f=s.get('priced_folds',0)
        flat=_sigmoid(math.log(.1/.9)+f*math.log(.07/.40)+(n-f)*math.log(.93/.60))
        unselective=min(.95,1-(1-flat)*(1-aggressive_mix))
        return dict(hands=s['hands'], vpip=vpip, pfr=pfr, fold=fold, aggression=aggression,
                    unselective=unselective,aggressive_unselective=aggressive_mix,flat_caller_probability=flat)

    def _texture(self, board, known, deadline):
        key = (tuple(board), tuple(sorted(known)))
        if key in self._texture_cache:
            return self._texture_cache[key]
        deck = [c for c in _DECK if c not in known]
        scored = []
        for index, pair in enumerate(itertools.combinations(deck, 2)):
            if index % 128 == 0 and time.perf_counter() >= deadline:
                return None
            scored.append(_evaluate(list(pair) + board))
        scored.sort()
        self._texture_cache[key] = scored
        return scored

    @staticmethod
    def _strength(pair, board, texture):
        if not board:
            return _PREFLOP[tuple(sorted(pair))]
        if texture is None:
            return _made_quality(list(pair), board)
        score = _evaluate(list(pair) + board)
        made = (bisect.bisect_left(texture, score) + bisect.bisect_right(texture, score)) / (2 * len(texture))
        potential = _potential(list(pair), board)
        return min(0.995, made + (1 - made) * potential)

    def _ranges(self, info, hole, board, opponents, events, deadline):
        known = set(hole + board)
        unseen = [c for c in _DECK if c not in known]
        pairs = list(itertools.combinations(unseen, 2))
        textures = {}
        for length in (3, 4, 5):
            if len(board) >= length:
                textures[length] = self._texture(board[:length], known, deadline)
        current_texture = textures.get(len(board))
        strength_cache = {}
        def strength(pair, length):
            if length == 0:
                return _PREFLOP[pair]
            key = (pair, length)
            if key not in strength_cache:
                vector_key = (tuple(board[:length]), tuple(sorted(known)))
                cache = self._vector_cache.setdefault(vector_key, {})
                if pair not in cache:
                    cache[pair] = self._strength(pair, board[:length], textures.get(length))
                strength_cache[key] = cache[pair]
            return strength_cache[key]
        ranges = []
        players = sum(stack > 0 or not info['folded'][i] for i, stack in enumerate(info['stacks']))
        annotated=[]
        raises=0
        for event in events:
            if event[1]=='preflop' and event[2] in ('bet','raise'):
                raises+=1
            annotated.append((event,raises))
        for seat in opponents:
            style = self._style(seat, players)
            actions = [(e,ordinal) for e,ordinal in annotated if e[0] == seat and e[2] != 'blind']
            weights, cumulative, total = [], [], 0.0
            likelihood_cache = {}
            for index, pair in enumerate(pairs):
                if index % 128 == 0 and time.perf_counter() >= deadline:
                    # Never return a truncated, lexicographically biased range.
                    weights = [1.0] * len(pairs)
                    cumulative = list(range(1, len(pairs) + 1))
                    total = float(len(pairs))
                    break
                percentile_key = _PREFLOP[pair] if not board else None
                cached_likelihood = likelihood_cache.get(percentile_key) if not board else None
                if cached_likelihood is not None:
                    weights.append(cached_likelihood)
                    total += cached_likelihood
                    cumulative.append(total)
                    continue
                likelihood = 1.0
                for event, ordinal in actions:
                    _, street, action, cost, owed, pot, size = event
                    length = {'preflop': 0, 'flop': 3, 'turn': 4, 'river': 5}.get(street, 0)
                    if length > len(board):
                        continue
                    q = strength(pair, length)
                    if length == 0:
                        if action in ('bet', 'raise'):
                            # Reraises face a narrower range, but loose behavior
                            # supplies a uniform mixture rather than fake value.
                            threshold = 1 - max(.10, min(.85, style['pfr']))
                            # Opening frequency is not a reraising frequency.
                            # Condition on the public raise sequence, not just
                            # the aggressor's overall participation rate.
                            if ordinal>=2:threshold=max(threshold,.82)
                            if ordinal>=3:threshold=max(threshold,.93)
                            p = .04 + .96 * _sigmoid((q - threshold) * 15)
                        elif action == 'call':
                            threshold=max(1-style['vpip'],.70 if ordinal>=2 else 0)
                            p = .12 + .88 * _sigmoid((q - threshold) * 12)
                        else:
                            p = 1.0
                    elif action in ('bet', 'raise'):
                        power = 1.0 + min(2.5, size) * .65 + (action == 'raise') * .45
                        p = .07 + .93 * q ** power
                    elif action == 'call':
                        price = min(1, cost / max(1, pot + cost))
                        p = .06 + .94 * _sigmoid((q - price - .13) * 11)
                    else:
                        p = 1 - .30 * q ** 3  # Allow slowplays.
                    mixture=style['aggressive_unselective'] if action in ('bet','raise') else style['unselective']
                    likelihood *= mixture + (1 - mixture) * p
                weights.append(max(0.0001, likelihood))
                if not board:
                    likelihood_cache[percentile_key] = weights[-1]
                total += weights[-1]
                cumulative.append(total)
            ranges.append((weights, cumulative, total, style))
        qualities = None
        if time.perf_counter() < deadline:
            qualities = [_HAND_CLASS[pair] if not board else strength(pair, len(board)) for pair in pairs]
        return unseen, pairs, ranges, qualities, current_texture

    @staticmethod
    def _share(hero, scores, layers):
        share = 0.0
        for chips, eligible in layers:
            best = max((scores[i] for i in eligible), default=-1)
            if hero >= best:
                share += chips / (1 + sum(scores[i] == hero for i in eligible))
        return share

    def _simulate(self, info, hole, board, opponents, layers, events, deadline):
        quality = _PREFLOP_EQUITY[tuple(sorted(hole))] if not board else _made_quality(hole, board)
        prior = min(.99, max(.01, quality ** (1 + .60 * max(0,len(opponents)-1))))
        if not opponents:
            return 1.0, [], 'uncontested', True, 0.0
        if info['time_limit'] <= .008 or self.max_samples == 0:
            return prior, [], 'fast heuristic', False, .15
        unseen, pairs, ranges, qualities, texture = self._ranges(info, hole, board, opponents, events, deadline)
        pair_index = {pair: i for i, pair in enumerate(pairs)}
        if qualities is None:
            qualities = [_HAND_CLASS[pair] if not board else _PREFLOP[pair] for pair in pairs]
        count = len(opponents)
        records, total, total_sq, total_weight = [], 0.0, 0.0, 0.0
        pot = sum(p for p, _ in layers)
        exact = count == 1 and len(board) == 5 and self.max_samples >= len(pairs) and deadline - time.perf_counter() > .015
        hero_river = _evaluate(hole + board) if len(board) == 5 else None
        sequence = range(len(pairs)) if exact else range(self.max_samples)
        for sample in sequence:
            if time.perf_counter() >= deadline:
                if exact:
                    records, total, total_sq, total_weight = [], 0.0, 0.0, 0.0
                    exact = False
                break
            if exact:
                indices = [sample]
                used = set(pairs[sample])
                weight = ranges[0][0][sample]
            else:
                # Reject the entire colliding deal, not just the last seat.
                # For site tables (<=6 seats), this samples the product ranges
                # conditioned on disjoint cards without seat-order bias.
                for attempt in range(100):
                    used, indices = set(), []
                    for j in range(count):
                        cdf, mass = ranges[j][1], ranges[j][2]
                        index = bisect.bisect_left(cdf, self.rng.random() * mass)
                        pair = pairs[index]
                        if any(card in used for card in pair):
                            break
                        used.update(pair)
                        indices.append(index)
                    if len(indices) == count:
                        break
                    if attempt % 8 == 7 and time.perf_counter() >= deadline:
                        break
                if len(indices) != count:
                    continue
                weight = 1.0
            remaining = [c for c in unseen if c not in used]
            runout = board + self.rng.sample(remaining, 5 - len(board))
            hero = hero_river if hero_river is not None else _evaluate(hole + runout)
            scores = tuple(_evaluate(list(pairs[i]) + runout) for i in indices)
            q = tuple(qualities[i] for i in indices)
            uniforms = tuple(self.rng.random() for _ in opponents)
            share = self._share(hero, scores, layers) / pot
            total += weight * share
            total_sq += weight * share * share
            total_weight += weight
            records.append((hero, scores, q, uniforms, weight, share))
        if not records:
            return prior, [], 'fast heuristic', False, .15
        eq = total / total_weight
        error = 0.0 if exact else math.sqrt(max(0, total_sq / total_weight - eq * eq) / len(records))
        return eq, records, 'exact river' if exact else 'joint range simulation', exact, error

    @staticmethod
    def _passive(info, call=False):
        legal = info['legal_actions']
        action = 'check' if 'check' in legal else 'call' if call and 'call' in legal else 'fold'
        return {'action': action, 'amount': 0}

    @staticmethod
    def _wager(info, target):
        action = 'raise' if 'raise' in info['legal_actions'] else 'bet' if 'bet' in info['legal_actions'] else None
        if action is None:
            return None
        high = min(info['max_raise_to'], info['street_bet_self'] + info['stack'])
        low = min(high, info['min_raise_to'] if action == 'raise' else info['min_bet'])
        amount = int(min(high, max(low, round(target))))
        return {'action': action, 'amount': amount} if amount > info['current_bet'] else None

    @staticmethod
    def _settlement(committed, live, hero):
        levels = sorted({min(c, committed[hero]) for c in committed if c > 0})
        layers, previous = [], 0
        for level in levels:
            chips = sum(max(0, min(c, level) - previous) for c in committed)
            eligible = tuple(i for i in live if committed[i] >= level)
            if chips and hero in eligible:
                layers.append((chips, eligible))
            previous = level
        return layers

    def _call_probability(self, q, style, extra, pot, preflop, players, opening_frequency=.4):
        if extra <= 0:
            return 1.0
        price = extra / max(1, pot + extra)
        if preflop:
            # Equity against a generic aggressive range comes from our own
            # sampled 169x169 matrix, not an arbitrary percentile-to-equity map.
            grid=_PUSHFOLD['response_frequencies']
            upper=min(len(grid)-1,bisect.bisect_left(grid,opening_frequency));lower=max(0,upper-1)
            blend=0 if grid[upper]==grid[lower] else (opening_frequency-grid[lower])/(grid[upper]-grid[lower])
            strength=_PUSHFOLD['responses'][lower][q]*(1-blend)+_PUSHFOLD['responses'][upper][q]*blend
        else:
            bluff_share = price * .90
            versus_value = max(0, min(1, (q - .55) / .45))
            strength = (1 - bluff_share) * versus_value + bluff_share * min(1, q / .25)
        strength = strength ** (1 + .14 * max(0, players - 1))
        rational = _sigmoid((strength - price - .025) * 16)
        loose = 1 - style['fold']
        return max(.025, min(.995, rational * (1 - style['unselective']) + loose * style['unselective']))

    def _actions(self, info, hole, board, opponents, layers, equity, error, records, position, deadline):
        call = min(info['stack'], info['to_call'])
        pot = sum(p for p, _ in layers)
        all_in = call == info['stack'] or all(info['stacks'][i] == 0 for i in opponents)
        realization = 1.0 if len(board) == 5 or all_in else max(.80, .88 + .08 * position - .02 * max(0, len(opponents) - 1))
        passive = self._passive(info, call=True)
        call_ev = equity * pot * realization - call
        choices = [{**passive, 'ev': call_ev - .25 * error * pot, 'uncertainty': error * pot, 'fold_equity': 0.0}]
        if call:
            choices.append(dict(action='fold', amount=0, ev=0.0, uncertainty=0.0, fold_equity=0.0))
        if not records:
            bb = max(1, info['blinds'][1])
            percentile = _PREFLOP[tuple(sorted(hole))]
            raised = any(e['street']=='preflop' and e['action'] in ('bet','raise') for e in info.get('history',[]))
            opens = .80 if len(opponents)==1 else .22+.23*position
            aggressive = (not board and ((not raised and percentile>=1-opens) or percentile>.96)) or (bool(board) and equity>.78)
            if aggressive:
                target = info['current_bet']*3 if raised and not board else max(bb*2.2,info['street_bet_self']+call+pot*.6)
                if info['stack']<=8*bb and percentile>.65:target=info['max_raise_to']
                wager=self._wager(info,target)
                if wager:return wager,choices+[dict(wager,ev=call_ev,uncertainty=error*pot,fold_equity=0.0)]
            return max(choices, key=lambda c: c['ev']), choices
        bb, stack = max(1, info['blinds'][1]), info['stack']
        already = info['street_bet_self']
        preflop = not board
        aggressive_events = [e for e in info.get('history', []) if e['street']=='preflop' and e['action'] in ('bet','raise')]
        percentile = _PREFLOP[tuple(sorted(hole))]
        if preflop:
            frequency = (.80 if len(opponents)==1 else .22 + .23 * position)
            threshold = 1 - frequency
            if not aggressive_events and percentile < threshold:
                return max(choices, key=lambda c: c['ev']), choices
            if aggressive_events and equity < max(.53, 1/(len(opponents)+1)+.12):
                return max(choices, key=lambda c: c['ev']), choices
            limpers = sum(e['street']=='preflop' and e['action']=='call' for e in info.get('history', []))
            target = info['current_bet'] * (2.6 + .4*(1-position)) if aggressive_events else bb * (2.1 + .8*limpers)
            targets = [target]
            if stack <= 14*bb or stack <= 1.7*pot:
                targets.append(info['max_raise_to'])
        else:
            if len(board)==5 and _evaluate(hole+board)==_evaluate(board):
                return max(choices, key=lambda c: c['ev']), choices
            draw = _potential(hole, board)
            value_threshold = max(.43, 1/(len(opponents)+1)+(.16 if call else .09))
            bluff = not call and len(opponents)<=2 and position>.5 and (draw>.10 or (len(board)==5 and max(hole)//4>=11))
            if equity < value_threshold and not bluff:
                return max(choices, key=lambda c: c['ev']), choices
            targets = [already+call+max(bb,pot*f) for f in (.33,.60,.90)]
            if stack <= 1.7*pot or equity>.88:
                targets.append(info['max_raise_to'])
        replies = {}
        for target in targets:
            reply = self._wager(info,target)
            if reply:
                replies[reply['amount']] = reply
        committed = _contributions(info)
        if sum(committed) != info['pot']:
            return max(choices, key=lambda c:c['ev']), choices
        styles = [self._style(i, len(opponents)+1) for i in opponents]
        for amount, reply in sorted(replies.items()):
            if time.perf_counter() >= deadline:
                break
            cost = amount-already
            extras = [min(info['stacks'][i],max(0,amount-info['street_bet'][i])) for i in opponents]
            masks, total, squared, weight_sum, folds = {}, 0.0, 0.0, 0.0, 0.0
            for index, (hero,scores,qualities,uniforms,weight,share) in enumerate(records):
                if index%32==0 and time.perf_counter()>=deadline:
                    break
                mask=0
                for j,other in enumerate(opponents):
                    p=self._call_probability(qualities[j],styles[j],extras[j],info['pot']+cost,preflop,len(opponents),(.16 if aggressive_events else (.80 if len(opponents)==1 else .22+.23*position)))
                    if info['stacks'][other]==0 or uniforms[j]<p:
                        mask|=1<<j
                settlement=masks.get(mask)
                if settlement is None:
                    hypothetical=committed[:]
                    hypothetical[info['seat']]+=cost
                    live=[info['seat']]
                    for j,other in enumerate(opponents):
                        if mask&(1<<j):
                            hypothetical[other]+=extras[j]
                            live.append(other)
                    settlement=self._settlement(hypothetical,live,info['seat'])
                    masks[mask]=settlement
                winnings=0.0
                for chips,eligible in settlement:
                    enemy=[scores[j] for j,other in enumerate(opponents) if other in eligible]
                    best=max(enemy,default=-1)
                    if hero>=best:
                        discount=1.0 if not enemy or len(board)==5 or cost==stack else min(.98,realization+.025)
                        winnings+=chips/(1+sum(s==hero for s in enemy))*discount
                passive_value=share*pot*realization-call
                delta=winnings-cost-passive_value
                total+=weight*delta
                squared+=weight*delta*delta
                weight_sum+=weight
                folds+=weight*(mask==0)
            if weight_sum:
                mean=total/weight_sum
                se=math.sqrt(max(0,squared/weight_sum-mean*mean)/max(1,index+1))
                # Common-runout differences have less noise than independently
                # estimating each bet's EV. Penalize uncertainty, not stack size.
                ev=call_ev+mean-.65*se
                choices.append({**reply,'ev':ev,'uncertainty':se,'fold_equity':folds/weight_sum})
        best=max(choices,key=lambda c:c['ev'])
        if best['action'] in ('bet','raise') and best['ev'] < choices[0]['ev']+max(.12*bb,.018*pot):
            best=max(choices[:2] if call else choices[:1],key=lambda c:c['ev'])
        return best,choices

    def _pushfold(self, info, hole, board, committed):
        if board or sum(stack+committed[i]>0 for i,stack in enumerate(info['stacks'])) != 2:
            return None
        hero=info['seat'];enemy=next((i for i,f in enumerate(info['folded']) if i!=hero and not f),None)
        if enemy is None:return None
        bb=max(1,info['blinds'][1]);already=info['street_bet_self']
        effective=min(info['stack']+already,info['stacks'][enemy]+info['street_bet'][enemy])/bb
        if not 2<=effective<=15:return None
        voluntary=[e for e in info.get('history',[]) if e['action'] not in ('blind','check')]
        button=hero==info['button']
        opening=button and not voluntary and already==info['blinds'][0] and info['current_bet']==bb
        facing_shove=(not button and already==bb and info['stacks'][enemy]==0 and len(voluntary)==1
                      and voluntary[0]['seat']==enemy and voluntary[0]['action']=='raise')
        if not(opening or facing_shove):return None
        labels='23456789TJQKA';a,b=sorted(hole,key=lambda c:c//4,reverse=True)
        high,low=labels[a//4],labels[b//4]
        key=high+low if high==low else high+low+('s' if a%4==b%4 else 'o')
        index=_PUSHFOLD_INDEX[key];grid=_PUSHFOLD['stacks']
        upper=min(len(grid)-1,bisect.bisect_left(grid,effective));lower=max(0,upper-1)
        blend=0 if grid[upper]==grid[lower] else (effective-grid[lower])/(grid[upper]-grid[lower])
        lo=_PUSHFOLD['rows'][lower][index];hi=_PUSHFOLD['rows'][upper][index]
        row=[x+(y-x)*blend for x,y in zip(lo,hi)]
        probability=row[0 if opening else 1]
        if opening:
            aggressive=self._wager(info,info['max_raise_to'])
            if aggressive is None:aggressive=self._passive(info,call=True)
            chosen=aggressive if self.rng.random()<probability else self._passive(info)
            ev=(row[4]+.5)*bb;equity=row[2]
            candidates=[dict(action='fold',amount=0,ev=0.,uncertainty=0.,fold_equity=0.),dict(aggressive,ev=ev,uncertainty=.025*effective*bb,fold_equity=0.)]
        else:
            chosen=self._passive(info,call=self.rng.random()<probability)
            ev=row[5]*bb;equity=row[3]
            candidates=[dict(action='fold',amount=0,ev=0.,uncertainty=0.,fold_equity=0.),dict(action='call',amount=0,ev=ev,uncertainty=.025*effective*bb,fold_equity=0.)]
        return chosen,equity,candidates,effective,probability

    def decide(self, info):
        started=time.perf_counter()
        if not info.get('legal_actions'):
            return dict(action='fold',amount=0)
        self._hero_seat=info['seat']
        events=self._observe(info)
        hole=[_card(c) for c in info['hole_cards']]
        board=[_card(c) for c in info['board']]
        opponents=[i for i,f in enumerate(info['folded']) if i!=info['seat'] and not f]
        solved=self._pushfold(info,hole,board,_contributions(info))
        if solved is not None:
            reply,equity,choices,effective,probability=solved
            layers=_pot_layers(info,opponents);pot=sum(p for p,_ in layers)
            self.last_decision={**reply,'version':'v3','reason':'short-stack equilibrium prior',
                'equity':equity,'pot_odds':min(info['stack'],info['to_call'])/max(1,pot),
                'eligible_pot':pot,'samples':0,'method':'CFR+ push/fold','exact':False,'equity_error':.025,
                'seconds':time.perf_counter()-started,'candidates':choices,
                'effective_bb':effective,'mixed_action_probability':probability,
                'abstraction':'Heads-up jam/fold only, with independently sampled preflop equities.',
                'opponents':{str(i):self._style(i,2) for i in opponents}}
            return reply
        order=sorted([info['seat']]+opponents,key=lambda i:(i-info['button']-1)%len(info['stacks']))
        position=order.index(info['seat'])/max(1,len(opponents))
        budget=min(self.max_think,max(0,info['time_limit'])*.48)
        deadline=started+budget
        layers=_pot_layers(info,opponents)
        equity,records,method,exact,error=self._simulate(info,hole,board,opponents,layers,events,started+budget*.66)
        best,choices=self._actions(info,hole,board,opponents,layers,equity,error,records,position,deadline)
        reply=dict(action=best['action'],amount=int(best['amount']))
        pot=sum(p for p,_ in layers)
        self.last_decision={**reply,'version':'v3','reason':'range-conditioned action EV',
                            'equity':round(equity,5),'pot_odds':min(info['stack'],info['to_call'])/max(1,pot),
                            'eligible_pot':pot,'samples':len(records),'method':method,'exact':exact,
                            'equity_error':error,'seconds':time.perf_counter()-started,
                            'candidates':[{**c,'ev':round(c['ev'],2),'uncertainty':round(c['uncertainty'],2)} for c in choices],
                            'opponents':{str(i):self._style(i,len(opponents)+1) for i in opponents}}
        return reply

    def hand_over(self,result):
        if self._token is not None:
            self._observe(dict(hole_cards=self._token[0],button=self._token[1],blinds=self._token[2],
                               history=result['history'],stacks=result['stacks'],seat=self._hero_seat,
                               folded=[False]*len(result['stacks'])))
