# Calls everything, never raises.
class Agent:
    def decide(self, info):
        return {"action": "call" if "call" in info["legal_actions"] else "check", "amount": 0}
