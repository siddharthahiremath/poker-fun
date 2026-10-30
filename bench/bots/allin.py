# Shoves every hand.
class Agent:
    def decide(self, info):
        legal = info["legal_actions"]
        if "raise" in legal or "bet" in legal:
            return {"action": "raise" if "raise" in legal else "bet", "amount": info["max_raise_to"]}
        return {"action": "call" if "call" in legal else "check", "amount": 0}
