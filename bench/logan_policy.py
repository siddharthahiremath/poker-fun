"""Fast all-in EV from offline observations of ordinary opponent actions.

Only the acting player's normal info dict is used online. Class-level equities
and response estimates are precomputed from our tables and black-box matches.
"""

import math
from itertools import product, permutations


class ProfileTracker:
    """Infer identities from public actions; supports any seating order."""

    def __init__(self):
        self.assignments = list(permutations(("riaan", "sid", "will")))
        self.scores = [0.0] * 6
        self.key = None
        self.seen = 0
        self.others = None

    def observe(self, info, model):
        if len(info["stacks"]) != 4 or info["street"] != "preflop":
            return
        self.others = [j for j in range(4) if j != info["seat"]]
        key = (info["button"], tuple(info["hole_cards"]), tuple(info["blinds"]))
        if key != self.key:
            self.key, self.seen = key, 0
            self.scores = [s * .999 for s in self.scores]
        for index, action in enumerate(info["history"]):
            if index < self.seen or action["action"] == "blind" or action["seat"] == info["seat"]:
                continue
            partial = dict(info, history=info["history"][:index + 1])
            keys, _ = _range_keys(partial)
            context = keys.get(action["seat"])
            if context is None:
                continue
            position = self.others.index(action["seat"])
            for k, assignment in enumerate(self.assignments):
                entry = model.get(assignment[position] + ":" + context, model.get(context, {}))
                probability = entry.get("frequency", .25)
                self.scores[k] += .4 * math.log(max(.02, probability))
            maximum = max(self.scores)
            self.scores = [max(-30, s - maximum) for s in self.scores]
        self.seen = len(info["history"])

    def weights(self, j):
        if self.others is None or j not in self.others:
            return {"": 1.0}
        position = self.others.index(j)
        raw = [math.exp(s - max(self.scores)) for s in self.scores]
        total = sum(raw)
        result = {n: 0.0 for n in ("riaan", "sid", "will")}
        for assignment, weight in zip(self.assignments, raw):
            result[assignment[position]] += weight / total
        return result


def _depth_bucket(depth):
    return next((k for k, bound in enumerate((3, 6, 10, 16, 30, 60)) if depth <= bound), 6)


def _range_keys(info):
    seat = info["seat"]
    bets = info["street_bet"]
    starts = [s + b for s, b in zip(info["stacks"], bets)]
    live = {i for i, s in enumerate(starts) if s > 0}
    keys = {}
    raised = set()
    facing = False
    bb = info["blinds"][1]
    for a in info["history"]:
        if a["street"] != "preflop" or a["action"] == "blind":
            continue
        j = a["seat"]
        depth = min(starts[j], max((starts[i] for i in live if i != j), default=starts[j])) / bb
        n = min(3, len(live) - 1)
        kind = "shove" if a["action"] in ("bet", "raise") and a["to"] >= starts[j] else a["action"]
        keys[j] = f"range:{_depth_bucket(depth)}:{n}:{'facing' if facing else 'open'}:{kind}"
        if a["action"] == "fold":
            live.discard(j)
            continue
        if a["action"] in ("raise", "bet"):
            raised.add(j)
            facing = True
    return keys, raised


def _allin_ev(info, target, cls, model, keys, raised, conservatism=0, tracker=None):
    seat = info["seat"]
    bets = info["street_bet"]
    stacks = info["stacks"]
    live = [j for j, f in enumerate(info["folded"]) if not f and j != seat]
    responses = []
    for j in live:
        key = keys.get(j, "uniform")
        if key not in model:
            key = "uniform"
        entries = [(model.get(name + ":" + key, model[key]) if name else model[key], weight)
                   for name, weight in (tracker.weights(j) if tracker else {"": 1.0}).items()]
        goal = min(target, bets[j] + stacks[j])
        owed = max(0, goal - bets[j])
        if stacks[j] == 0 or owed == 0:
            equity = sum(entry["equity"][cls] * weight for entry, weight in entries)
            responses.append([(1.0, bets[j], equity, True)])
        else:
            price = owed / max(1, info["pot"] + target - bets[seat] + owed)
            bucket = min(4, int(price * 10))
            context = f"{bucket}:{int(j in raised)}"
            cont = sum(entry["response"][context][0] * weight for entry, weight in entries)
            won = sum(entry["response"][context][0] * entry["response"][context][1][cls] * weight
                      for entry, weight in entries)
            equity = max(0, won / max(1e-9, cont) - conservatism)
            responses.append([(1 - cont, bets[j], 0, False), (cont, goal, equity, True)])
    dead = [bets[j] for j, f in enumerate(info["folded"]) if f and j != seat]
    ev = 0.0
    for outcome in product(*responses):
        probability = 1.0
        for p, _, _, _ in outcome:
            probability *= p
        contrib = [target] + [o[1] for o in outcome] + dead
        previous = won = 0.0
        for level in sorted(set(contrib)):
            if level > target:
                break
            pot = (level - previous) * sum(c >= level for c in contrib)
            equity = 1.0
            for _, chips, e, active in outcome:
                if active and chips >= level:
                    equity *= e
            won += pot * equity
            previous = level
        ev += probability * (won - (target - bets[seat]))
    return ev


def empirical_preflop(info, reply, config, model, tracker=None):
    if info["street"] != "preflop":
        return reply
    seat = info["seat"]
    bb = info["blinds"][1]
    bets = info["street_bet"]
    stacks = info["stacks"]
    total = info["max_raise_to"]
    opps = [j for j, f in enumerate(info["folded"]) if not f and j != seat]
    depth = min(total, max((bets[j] + stacks[j] for j in opps), default=total)) / bb
    keys, raised = _range_keys(info)
    cls = _preflop_class(info["hole_cards"])
    legal = info["legal_actions"]
    cost = min(stacks[seat], info["to_call"])
    facing_shove = any(stacks[j] == 0 and bets[j] == info["current_bet"] for j in opps)
    if facing_shove and cost > 0:
        ev = _allin_ev(info, bets[seat] + cost, cls, model, keys, raised,
                       config.get("equity_penalty", 0), tracker)
        return {"action": "call" if ev > config.get("call_margin", 0) * cost else "fold", "amount": 0}
    if depth <= config.get("push_depth", 16) and "raise" in legal:
        ev = _allin_ev(info, total, cls, model, keys, raised,
                       config.get("equity_penalty", 0), tracker)
        margin = config.get("push_margin", 0) * min(stacks[seat], depth * bb)
        if ev > margin:
            return {"action": "raise", "amount": total}
        if reply["action"] == "raise" and reply["amount"] == total:
            return {"action": "check" if "check" in legal else "fold", "amount": 0}
    return reply

"""Public-info-only action adjustments around an opaque, unchanged base bot.

The base is used through Agent.decide/hand_over only. No implementation details,
private attributes, other players' cards, or engine state are accessed.
"""

def _preflop_class(cards):
    ranks = sorted(("23456789TJQKA".index(c[:-1].replace("10", "T")) for c in cards), reverse=True)
    a, b = ranks
    suited = cards[0][-1] == cards[1][-1]
    return a * 13 + b if suited or a == b else b * 13 + a


def _preflop_percentile(cards):
    return _PERCENTILES[_preflop_class(cards)]


class Agent:
    def __init__(self):
        self.base = _BaseAgent()
        self.own = _OwnAgent() if CONFIG.get("hybrid") else None
        self.profiles = ProfileTracker() if CONFIG.get("profiles") else None

    def decide(self, info):
        base_info = info
        if CONFIG.get("base_time_scale", 1) != 1:
            base_info = dict(base_info, time_limit=info["time_limit"] * CONFIG["base_time_scale"])
        if CONFIG.get("pot_scale", 1) != 1:
            base_info = dict(base_info, pot=round(info["pot"] * CONFIG["pot_scale"]))
        reply = self.base.decide(base_info)
        if self.own is not None:
            ours = self.own.decide(info)
            if (CONFIG["hybrid"] == "pre") == (info["street"] == "preflop"):
                reply = ours
        if CONFIG.get("empirical"):
            if self.profiles is not None:
                self.profiles.observe(info, _MODEL)
            reply = empirical_preflop(info, reply, CONFIG, _MODEL, self.profiles)
        legal = info.get("legal_actions") or []
        action = reply.get("action")
        amount = reply.get("amount", 0)
        owed = info["to_call"]
        pot = info["pot"]
        bb = max(1, info["blinds"][1])
        stack = info["stack"]
        own = info["street_bet_self"]
        hi = info["max_raise_to"]
        street = info["street"]
        seat = info["seat"]
        active = [i for i, f in enumerate(info["folded"]) if not f and i != seat]
        if "allin_gate" in CONFIG and street == "preflop" and owed > 0:
            raisers = [a for a in info["history"] if a["action"] in ("raise", "bet")]
            if raisers and info["stacks"][raisers[-1]["seat"]] == 0:
                cls = _preflop_class(info["hole_cards"])
                villain = raisers[-1]["seat"]
                depth = min(hi, info["street_bet"][villain]) / bb
                fraction = (1.0 if depth < 2 else .7 if depth < 5 else .5 if depth < 9
                            else .35 if depth < 16 else .2 if depth < 30 else .06)
                fraction = min(1, fraction * CONFIG.get("range_scale", 1))
                key = min(_EQUITIES, key=lambda f: abs(f - fraction))
                equity = _EQUITIES[key][cls]
                others = [j for j in active if j != villain and info["street_bet"][j] > bb]
                for j in others:
                    equity *= _EQUITIES[.2][cls]
                cost = min(stack, owed)
                need = cost / max(1, pot + cost) + CONFIG["allin_gate"]
                if equity > need:
                    return {"action": "call", "amount": 0}
                return {"action": "fold", "amount": 0}
        if street == "preflop" and action in ("fold", "check"):
            pct = _preflop_percentile(info["hole_cards"])
            raises = [a for a in info["history"] if a["action"] in ("bet", "raise")]
            depth = min(hi, max((info["stacks"][j] + info["street_bet"][j] for j in active), default=hi)) / bb
            if not raises:
                if CONFIG.get("wide_open", 0) and depth > CONFIG.get("wide_open_depth", 8) and "raise" in legal:
                    cutoff = min(1.0, {1: .9, 2: .6, 3: .4}.get(len(active), .2) * CONFIG["wide_open"])
                    if pct < cutoff:
                        target = min(hi, max(info["min_raise_to"], 2 * bb))
                        return {"action": "raise", "amount": target}
                scale = CONFIG.get("widen_push", 0)
                if scale and depth <= 16 and "raise" in legal:
                    cutoff = {1: 0.55, 2: 0.32, 3: 0.22}.get(len(active), 0.15)
                    cutoff = min(1.0, cutoff * scale * (10 / max(2, depth)) ** 0.35)
                    if pct < cutoff:
                        return {"action": "raise", "amount": hi}
                if CONFIG.get("limp_pct", 0) > pct and owed <= bb and "call" in legal:
                    return {"action": "call", "amount": 0}
            elif (CONFIG.get("flat_pct", 0) > pct and owed <= CONFIG.get("flat_bb", 3) * bb
                  and owed < 0.15 * stack and "call" in legal):
                return {"action": "call", "amount": 0}
        if action == "fold" and "check" in legal:
            return {"action": "check", "amount": 0}
        if (action == "fold" and street in ("flop", "turn") and "call" in legal
                and min(stack, owed) / max(1, pot + min(stack, owed)) < CONFIG.get("post_call_price", 0)):
            return {"action": "call", "amount": 0}
        probe = CONFIG.get("probe", 0)
        if (probe and street != "preflop" and action == "check" and owed == 0
                and street in CONFIG.get("probe_streets", ["flop", "turn", "river"])):
            acts = [a for a in info["history"] if a["street"] == street]
            checked = {a["seat"] for a in acts if a["action"] == "check"}
            if (len(active) <= CONFIG.get("probe_players", 1)
                    and (CONFIG.get("probe_first") or all(j in checked for j in active))
                    and not any(a["action"] in ("bet", "raise", "call") for a in acts)):
                kind = "bet" if "bet" in legal else "raise" if "raise" in legal else None
                if kind:
                    amount = min(hi, max(info["min_raise_to"], round(probe * pot)))
                    return {"action": kind, "amount": int(amount)}
        if action in ("bet", "raise"):
            if street == "preflop":
                if CONFIG.get("short_minraise") and amount == hi:
                    raises = [a for a in info["history"] if a["action"] in ("bet", "raise")]
                    effective = min(hi, max((info["stacks"][j] + info["street_bet"][j] for j in active), default=hi)) / bb
                    if (not raises and CONFIG["short_minraise"] < effective < 30
                            and _preflop_percentile(info["hole_cards"]) > CONFIG.get("premium_jam", .08)):
                        amount = min(hi, max(info["min_raise_to"], 2 * bb))
                # Scale ordinary opens without changing which hands the base plays.
                if amount < hi and CONFIG.get("open_scale", 1) != 1:
                    amount = round(amount * CONFIG["open_scale"])
            else:
                if CONFIG.get("post_scale", 1) != 1:
                    amount = info["current_bet"] + round((amount - info["current_bet"]) * CONFIG["post_scale"])
                cap = CONFIG.get("post_cap", 0)
                if cap and stack > cap * (pot + owed):
                    amount = min(amount, info["current_bet"] + round(cap * (pot + owed)))
            amount = min(hi, max(info["min_raise_to"], amount))
            return {"action": action, "amount": int(amount)}
        return reply

    def hand_over(self, result):
        if self.own is not None:
            self.own.hand_over(result)
        callback = getattr(self.base, "hand_over", None)
        if callback is not None:
            callback(result)
