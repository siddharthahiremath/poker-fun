# Demo agent: random play with a personality. Copy agents/template.py for real entries.
import random
import time

AGGRESSION = 0.2  # chance to bet or raise when allowed
SLOWNESS = 0.4  # most of the time limit it will spend thinking
SHOVE = 0.08  # chance a raise is all-in


class Agent:
    def decide(self, info):
        hi = max(0.0, info["time_limit"] * SLOWNESS)
        time.sleep(random.uniform(0.0, hi))
        legal = info["legal_actions"]
        if ("bet" in legal or "raise" in legal) and random.random() < AGGRESSION:
            low, high = info["min_raise_to"], info["max_raise_to"]
            size = high if random.random() < SHOVE else random.randint(low, min(high, low * 3))
            return {"action": "raise" if "raise" in legal else "bet", "amount": size}
        if "check" in legal:
            return {"action": "check"}
        return {"action": "call" if random.random() < 0.7 else "fold"}
