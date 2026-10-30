# A reasonable tight-aggressive heuristic bot: Chen-style preflop score, made-hand postflop,
# shoves wider as the stack gets short.
import itertools

RANKS = "2 3 4 5 6 7 8 9 10 J Q K A".split()


def score5(cards):
    values = sorted((RANKS.index(c[:-1]) for c in cards), reverse=True)
    if values == [12, 3, 2, 1, 0]:
        values = [3, 2, 1, 0, -1]
    counts = sorted(((values.count(v), v) for v in set(values)), reverse=True)
    flush = len({c[-1] for c in cards}) == 1
    straight = len(counts) == 5 and values[0] - values[4] == 4
    if straight and flush:
        return 8
    if flush:
        return 5
    if straight:
        return 4
    return {(4, 1): 7, (3, 2): 6, (3, 1, 1): 3, (2, 2, 1): 2, (2, 1, 1, 1): 1}.get(tuple(c for c, _ in counts), 0)


def chen(cards):
    a, b = sorted((RANKS.index(c[:-1]) for c in cards), reverse=True)
    points = {12: 10, 11: 8, 10: 7, 9: 6}.get(a, (a + 2) / 2)
    if a == b:
        return max(5, points * 2)
    if cards[0][-1] == cards[1][-1]:
        points += 2
    gap = a - b - 1
    points -= [0, 1, 2, 4][gap] if gap < 4 else 5
    if gap <= 1 and a < 10:
        points += 1
    return points


class Agent:
    def decide(self, info):
        legal = info["legal_actions"]
        bb = info["blinds"][1]
        stack_bb = (info["stack"] + info["street_bet_self"]) / bb
        owed = info["to_call"]
        raise_word = "raise" if "raise" in legal else "bet" if "bet" in legal else None
        if info["street"] == "preflop":
            s = chen(info["hole_cards"])
            if stack_bb <= 12:
                need = 7 if owed <= bb else 9
                if s >= need and raise_word:
                    return {"action": raise_word, "amount": info["max_raise_to"]}
                if s >= need and "call" in legal:
                    return {"action": "call", "amount": 0}
            else:
                if s >= 10 and raise_word:
                    return {"action": raise_word, "amount": min(info["max_raise_to"], max(info["min_raise_to"], info["current_bet"] * 3))}
                if s >= 8 and "call" in legal and owed <= 4 * bb:
                    return {"action": "call", "amount": 0}
            return {"action": "check" if "check" in legal else "fold", "amount": 0}
        cards = info["hole_cards"] + info["board"]
        made = max(score5(list(c)) for c in itertools.combinations(cards, 5))
        board_made = max(score5(list(c)) for c in itertools.combinations(info["board"], 5)) if len(info["board"]) == 5 else 0
        strong = made >= 2 and made > board_made
        if strong and raise_word:
            return {"action": raise_word, "amount": max(info["min_raise_to"], min(info["max_raise_to"], info["pot"] * 2 // 3 + info["current_bet"]))}
        if made >= 1 and "call" in legal and owed <= info["pot"] // 2:
            return {"action": "call", "amount": 0}
        return {"action": "check" if "check" in legal else "fold", "amount": 0}
