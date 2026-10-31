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
        print(legal)
        print(info)
        return {"action": "bet", "amount": info["max_raise_to"]}
        #always go all in
