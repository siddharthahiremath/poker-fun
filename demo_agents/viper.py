# Demo agent: random play with a personality. Copy agents/template.py for real entries.
import random
import time

AGGRESSION = 0.7  # chance to bet or raise when allowed
SLOWNESS = 0.6  # most of the time limit it will spend thinking
SHOVE = 0.15  # chance a raise is all-in


class Agent:
    def decide(self, info):
        time.sleep(random.uniform(0.2, info["time_limit"] * SLOWNESS))
        legal = info["legal_actions"]
        if ("bet" in legal or "raise" in legal) and random.random() < AGGRESSION:
            low, high = info["min_raise_to"], info["max_raise_to"]
            size = high if random.random() < SHOVE else random.randint(low, min(high, low * 3))
            return {"action": "raise" if "raise" in legal else "bet", "amount": size}
        if "check" in legal:
            return {"action": "check"}
        return {"action": "call" if random.random() < 0.7 else "fold"}
