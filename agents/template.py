# Copy this file, rename it to your name (alice.py), and leave it in agents/.
# Required: a class named Agent with decide(info).
#
# Return {"action": one of fold/check/call/bet/raise, "amount": int}
#   bet amount  = chips you put in this street
#   raise amount = your total chips in for this street after the raise
# You have info["time_limit"] seconds. Too slow, or a bad return, means
# check if you can, otherwise fold.

import random
import time
import math

class Agent:
    def decide(self, info):
        legal = list(info.get("legal_actions") or [])
        if not legal:
            return {"action": "fold", "amount": 0}

        action = random.choice(legal)
        amount = 0
        stack = int(info.get("stack") or 0)
        already = int(info.get("street_bet_self") or 0)

        if action == "bet":
            low = int(info.get("min_bet") or 0)
            if stack <= 0:
                action = "check" if "check" in legal else "fold"
            elif stack < low:
                amount = stack
            else:
                amount = random.randint(low, stack)
        elif action == "raise":
            low = int(info.get("min_raise_to") or 0)
            max_to = already + stack
            if max_to <= already:
                action = "call" if "call" in legal else "fold"
            elif max_to < low:
                amount = max_to
            else:
                amount = random.randint(low, max_to)

        return {"action": action, "amount": amount}
