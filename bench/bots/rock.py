# Plays only big pairs and big aces, and shoves them.
RANKS = "2 3 4 5 6 7 8 9 10 J Q K A".split()


class Agent:
    def decide(self, info):
        legal = info["legal_actions"]
        a, b = sorted((RANKS.index(c[:-1]) for c in info["hole_cards"]), reverse=True)
        premium = (a == b and a >= 7) or (a == 12 and b >= 10) or (a == 11 and b == 10)
        if premium and ("raise" in legal or "bet" in legal):
            return {"action": "raise" if "raise" in legal else "bet", "amount": info["max_raise_to"]}
        if premium and "call" in legal:
            return {"action": "call", "amount": 0}
        return {"action": "check" if "check" in legal else "fold", "amount": 0}
