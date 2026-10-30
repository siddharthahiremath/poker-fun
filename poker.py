# Texas hold'em tournament. Each friend drops agents/<name>.py with an Agent class (see template.py).
import importlib.util
import itertools
import json
import pathlib
import random
import sys
import threading
import time

# usage: python3 poker.py [--agents DIR] [--json] [--time SECONDS] [--wins]
# --json streams a table snapshot per line for the web viewer in web/
# --wins keeps playing and counts hands won, with busted agents buying back in
LIVE = "--json" in sys.argv
EVENTS = sys.stdout
if LIVE:
    sys.stdout = sys.stderr  # agent prints must not corrupt the event stream

def option(flag, default=None):
    if flag in sys.argv[:-1]:
        return sys.argv[sys.argv.index(flag) + 1]
    return default

TIME_MIN, TIME_MAX = 0.001, 30.0

def clamp_time(value, default=10.0):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    if value != value or value in (float("inf"), float("-inf")):
        return default
    return min(TIME_MAX, max(TIME_MIN, round(value, 3)))

def read_time():
    return clamp_time(option("--time", "10"))

# the limit can change while a hand is in progress; pending waits for the next hand
clock_lock = threading.Lock()
clock = {"limit": read_time(), "pending": None}
write_lock = threading.Lock()

def clock_state():
    with clock_lock:
        return clock["limit"], clock["pending"]

def current_limit():
    return clock_state()[0]

def announce_clock():
    if not LIVE:
        return
    limit, pending = clock_state()
    line = json.dumps({"event": "clock", "time_limit": limit, "time_pending": pending}) + "\n"
    with write_lock:
        EVENTS.write(line)
        EVENTS.flush()

def set_clock(seconds, when):
    seconds = clamp_time(seconds, current_limit())
    with clock_lock:
        if when == "hand":
            clock["pending"] = seconds
        else:
            clock["limit"] = seconds
            clock["pending"] = None
    announce_clock()

def apply_pending():
    with clock_lock:
        if clock["pending"] is None:
            return False
        clock["limit"] = clock["pending"]
        clock["pending"] = None
        return True

def listen_commands():
    while True:
        line = sys.stdin.readline()
        if not line:
            return
        line = line.strip()
        if not line:
            continue
        try:
            command = json.loads(line)
            when = "now" if command.get("when") == "now" else "hand"
            set_clock(command["time"], when)
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

if LIVE:
    threading.Thread(target=listen_commands, daemon=True).start()
WINS_MODE = "--wins" in sys.argv
HANDS = 1000 if LIVE else 20
WINS_HANDS = 100_000
START_STACK = 1000
BLINDS_DOUBLE_EVERY = 3  # hands
PAUSES = {"hand": 2.0, "street": 1.8, "action": 1.2, "showdown": 5.0}  # seconds, so viewers can follow
AGENTS_DIR = pathlib.Path(__file__).resolve().parent / (
    sys.argv[sys.argv.index("--agents") + 1] if "--agents" in sys.argv[:-1] else "agents"
)
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
DECK = [rank + suit for suit in "♠♥♦♣" for rank in RANKS]

# hand categories by the shape of rank counts, e.g. (3, 2) is a full house
STRAIGHT_FLUSH, QUADS, FULL_HOUSE, FLUSH, STRAIGHT, TRIPS, TWO_PAIR, PAIR, HIGH = 8, 7, 6, 5, 4, 3, 2, 1, 0
SHAPES = {(4, 1): QUADS, (3, 2): FULL_HOUSE, (3, 1, 1): TRIPS, (2, 2, 1): TWO_PAIR, (2, 1, 1, 1): PAIR}
HAND_NAMES = ["High card", "Pair", "Two pair", "Three of a kind", "Straight", "Flush",
              "Full house", "Four of a kind", "Straight flush"]


def score_five(cards):
    values = sorted((RANKS.index(card[:-1]) for card in cards), reverse=True)
    if values == [12, 3, 2, 1, 0]:
        values = [3, 2, 1, 0, -1]  # A-2-3-4-5: the ace plays low
    counts = sorted(((values.count(v), v) for v in set(values)), reverse=True)
    flush = len({card[-1] for card in cards}) == 1
    straight = len(counts) == 5 and values[0] - values[4] == 4

    if straight and flush:
        category = STRAIGHT_FLUSH
    elif flush:
        category = FLUSH
    elif straight:
        category = STRAIGHT
    else:
        category = SHAPES.get(tuple(count for count, _ in counts), HIGH)
    return category, [value for _, value in counts]


def best_hand(cards):
    return max(score_five(five) for five in itertools.combinations(cards, 5))


def win_odds(hands, board, deck, samples=600):
    # every runout of the board when few cards are left, a random sample before the flop
    missing = 5 - len(board)
    runouts = itertools.combinations(deck, missing) if missing <= 2 else (random.sample(deck, missing) for _ in range(samples))
    wins, total = dict.fromkeys(hands, 0.0), 0
    for runout in runouts:
        scores = {i: best_hand(cards + board + list(runout)) for i, cards in hands.items()}
        best = max(scores.values())
        winners = [i for i, score in scores.items() if score == best]
        for i in winners:
            wins[i] += 1 / len(winners)
        total += 1
    return {i: wins[i] / total for i in hands}


class Dealer:
    def __init__(self, players, stack=1000, small_blind=5, big_blind=10):
        self.n = players
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.stacks = [stack] * players
        self.button = 0

    def has_chips(self, i):
        return self.stacks[i] > 0

    def in_hand(self, i):
        return not self.folded[i]

    def can_act(self, i):
        return self.in_hand(i) and self.has_chips(i)

    def next_seat(self, seat, wanted):
        for step in range(1, self.n + 1):
            candidate = (seat + step) % self.n
            if wanted(candidate):
                return candidate
        return None

    def start_hand(self):
        if not self.has_chips(self.button):
            self.button = self.next_seat(self.button, self.has_chips)
        self.deck = random.sample(DECK, len(DECK))
        self.hands = [[self.deck.pop(), self.deck.pop()] for _ in range(self.n)]
        self.board = []
        self.history = []
        self.invested = [0] * self.n  # chips each seat put in this whole hand
        self.folded = [not self.has_chips(i) for i in range(self.n)]
        self.new_street("preflop")

        heads_up = sum(map(self.has_chips, range(self.n))) == 2
        small = self.button if heads_up else self.next_seat(self.button, self.has_chips)
        self.big_blind_seat = self.next_seat(small, self.has_chips)
        for seat, blind in ((small, self.small_blind), (self.big_blind_seat, self.big_blind)):
            self.pay(seat, blind)
            self.log(seat, "blind")
        self.bet = max(self.street_bets)

    def new_street(self, name):
        self.street = name
        self.street_bets = [0] * self.n
        self.bet = 0
        self.min_raise = self.big_blind
        self.raising_open = True
        self.acted = [False] * self.n

    def pay(self, i, chips):
        chips = min(chips, self.stacks[i])
        self.stacks[i] -= chips
        self.street_bets[i] += chips
        self.invested[i] += chips

    def log(self, i, action):
        self.history.append({"seat": i, "street": self.street, "action": action, "to": self.street_bets[i]})

    def to_call(self, i):
        return max(0, self.bet - self.street_bets[i])

    def legal_actions(self, i):
        if not self.can_act(i):
            return []
        owed = self.to_call(i)
        actions = ["fold", "call" if owed else "check"]
        # after a short all-in, only players who haven't acted yet may raise
        if self.stacks[i] > owed and (self.raising_open or not self.acted[i]):
            actions.append("raise" if self.bet else "bet")
        return actions

    def act(self, i, action, amount=None):
        # bet and raise amounts are the seat's total for this street
        if action not in self.legal_actions(i):
            raise ValueError(action)
        if action == "fold":
            self.folded[i] = True
        elif action == "call":
            self.pay(i, self.to_call(i))
        elif action in ("bet", "raise"):
            all_in = self.street_bets[i] + self.stacks[i]
            minimum = min(all_in, self.bet + self.min_raise)
            if type(amount) is not int or not minimum <= amount <= all_in or amount <= self.bet:
                raise ValueError(amount)
            self.pay(i, amount - self.street_bets[i])
            raised_by = amount - self.bet
            if raised_by >= self.min_raise:
                self.min_raise = raised_by
                self.raising_open = True
                self.acted = [False] * self.n
            else:
                self.raising_open = False
            self.bet = amount
        self.acted[i] = True
        self.log(i, action)

    def street_done(self):
        if sum(map(self.in_hand, range(self.n))) < 2:
            return True
        actors = [i for i in range(self.n) if self.can_act(i)]
        if any(self.street_bets[i] < self.bet for i in actors):
            return False
        return len(actors) < 2 or all(self.acted[i] for i in actors)

    def view(self, i):
        all_in = self.street_bets[i] + self.stacks[i]
        return {
            "seat": i,
            "street": self.street,
            "time_limit": current_limit(),
            "hole_cards": list(self.hands[i]),
            "board": list(self.board),
            "pot": sum(self.invested),
            "stack": self.stacks[i],
            "stacks": list(self.stacks),
            "street_bet": list(self.street_bets),
            "street_bet_self": self.street_bets[i],
            "current_bet": self.bet,
            "to_call": self.to_call(i),
            "min_bet": self.big_blind,
            "min_raise_to": min(all_in, self.bet + self.min_raise),
            "max_raise_to": all_in,
            "legal_actions": self.legal_actions(i),
            "folded": list(self.folded),
            "button": self.button,
            "blinds": (self.small_blind, self.big_blind),
            "history": [dict(entry) for entry in self.history],
        }

    def award(self):
        # pay out layer by layer so an all-in player only wins what they covered
        contenders = [i for i in range(self.n) if self.in_hand(i)]
        contenders.sort(key=lambda i: (i - self.button - 1) % self.n)  # odd chips go left of the button
        showdown = len(contenders) > 1
        scores = {i: best_hand(self.hands[i] + self.board) if showdown else 0 for i in contenders}
        remaining = list(self.invested)
        won = dict.fromkeys(contenders, 0)
        while any(remaining):
            layer = min(chips for chips in remaining if chips)
            pot = sum(min(chips, layer) for chips in remaining)
            eligible = [i for i in contenders if remaining[i]] or contenders
            best = max(scores[i] for i in eligible)
            winners = [i for i in eligible if scores[i] == best]
            share, odd = divmod(pot, len(winners))
            for rank, i in enumerate(winners):
                won[i] += share + (rank < odd)
            remaining = [max(0, chips - layer) for chips in remaining]
        for i, chips in won.items():
            self.stacks[i] += chips
        return won


def run_limited(fn, limit=None):
    # daemon thread so a hung agent can't keep the process alive
    # limit=None follows the live clock, so a shorter limit can cut off a move already in progress
    result = [False, "timeout"]

    def guarded():
        try:
            result[:] = True, fn()
        except BaseException:
            result[:] = False, "crash"

    thread = threading.Thread(target=guarded, daemon=True)
    thread.start()
    started = time.monotonic()
    while thread.is_alive():
        allowed = current_limit() if limit is None else limit
        remaining = allowed - (time.monotonic() - started)
        if remaining <= 0:
            return False, "timeout"
        thread.join(min(remaining, 0.02))
    return tuple(result)


def parse_reply(reply):
    # accept only exact builtin types so an agent's objects can't run code on the table's thread
    if type(reply) is dict:
        action, amount = reply.get("action"), reply.get("amount")
    else:
        action, amount = reply, None
    action = action.strip().lower() if type(action) is str else None
    if type(amount) is str and amount.strip().isdecimal() and len(amount) < 16:
        amount = int(amount)
    if type(amount) is float and amount.is_integer():
        amount = int(amount)
    return action, amount if type(amount) is int else None


class Seat:
    def __init__(self, name, path, index):
        self.name = name

        def load():
            spec = importlib.util.spec_from_file_location(f"agent_{index}", path)
            module = sys.modules[spec.name] = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.Agent()

        ok, self.bot = run_limited(load, 10)
        if not ok:
            print(f"{name} sits out ({self.bot})")
            self.bot = None

    def take_turn(self, dealer, i):
        broadcast("thinking", dealer, actor=i)
        info = dealer.view(i)
        ok, reply = run_limited(lambda: parse_reply(self.bot.decide(info)))
        action, amount = reply if ok else (None, None)
        note = "" if ok else "sitting out" if self.bot is None else reply
        try:
            dealer.act(i, action, amount)
        except ValueError:
            note = note or "illegal"
            dealer.act(i, "check" if "check" in dealer.legal_actions(i) else "fold")
        last = dealer.history[-1]
        size = f" {last['to']}" if last["action"] in ("bet", "raise") else ""
        print(f"  {self.name} {last['action']}{size}{f' ({note})' if note else ''}")
        broadcast("action", dealer, actor=i, action={**last, "note": note})

    def hand_over(self, dealer, won, shown):
        result = {
            "board": list(dealer.board),
            "won": dict(won),
            "stacks": list(dealer.stacks),
            "shown": {i: list(cards) for i, cards in shown.items()},
            "history": [dict(entry) for entry in dealer.history],
        }
        run_limited(lambda: self.bot.hand_over(result), 1)


def broadcast(event, dealer, **extra):
    if not LIVE:
        return
    live = tuple(i for i in range(dealer.n) if dealer.in_hand(i))
    key = dealer.hand_number, live, len(dealer.board)
    if dealer.odds_key != key:  # odds only move when the board or the field changes
        dealer.odds_key = key
        dealer.odds = win_odds({i: dealer.hands[i] for i in live}, dealer.board, dealer.deck) if len(live) > 1 else {}
    seats = []
    for i, name in enumerate(dealer.names):
        status = "active"
        if dealer.folded[i]:
            status = "out" if dealer.invested[i] == 0 and dealer.stacks[i] == 0 else "folded"
        elif dealer.stacks[i] == 0:
            status = "all-in"
        hand_name = None
        if status not in ("out", "folded") and len(dealer.board) >= 3:
            hand_name = HAND_NAMES[best_hand(dealer.hands[i] + dealer.board)[0]]
        seats.append({
            "name": name,
            "stack": dealer.stacks[i],
            "bet": dealer.street_bets[i],
            "cards": dealer.hands[i],
            "status": status,
            "hand_name": hand_name,
            "win_odds": dealer.odds.get(i),
        })
    limit, pending = clock_state()
    snapshot = {
        "event": event,
        "hand": dealer.hand_number,
        "street": dealer.street,
        "board": dealer.board,
        "pot": sum(dealer.invested),
        "button": dealer.button,
        "blinds": [dealer.small_blind, dealer.big_blind],
        "blinds_double_in": 0 if WINS_MODE else BLINDS_DOUBLE_EVERY - (dealer.hand_number - 1) % BLINDS_DOUBLE_EVERY,
        "current_bet": dealer.bet,
        "time_limit": limit,
        "time_pending": pending,
        "wins": list(getattr(dealer, "wins", [0] * dealer.n)),
        "seats": seats,
        **extra,
    }
    with write_lock:
        EVENTS.write(json.dumps(snapshot) + "\n")
        EVENTS.flush()
    time.sleep(PAUSES.get(event, 0))


def play_hand(dealer, seats):
    dealer.start_hand()
    broadcast("hand", dealer)
    for street, new_cards in (("preflop", 0), ("flop", 3), ("turn", 1), ("river", 1)):
        if sum(map(dealer.in_hand, range(dealer.n))) < 2:
            break
        if new_cards:
            dealer.new_street(street)
            dealer.board += [dealer.deck.pop() for _ in range(new_cards)]
            print(f"  {street}: {' '.join(dealer.board)}")
            broadcast("street", dealer)
        start = dealer.big_blind_seat if street == "preflop" else dealer.button
        i = dealer.next_seat(start, dealer.can_act)
        while not dealer.street_done():
            seats[i].take_turn(dealer, i)
            i = dealer.next_seat(i, dealer.can_act)

    pot = sum(dealer.invested)
    won = dealer.award()
    shown = {i: dealer.hands[i] for i in won} if len(won) > 1 else {}
    for i, cards in shown.items():
        print(f"  {seats[i].name} shows {' '.join(cards)}")
    print("  " + ", ".join(f"{seats[i].name} wins {chips}" for i, chips in won.items() if chips))
    if not hasattr(dealer, "wins"):
        dealer.wins = [0] * dealer.n
    for i, chips in won.items():
        if chips:
            dealer.wins[i] += 1
    winners = [{"seat": i, "chips": chips} for i, chips in won.items() if chips]
    for winner in winners:
        winner["hand_name"] = HAND_NAMES[best_hand(dealer.hands[winner["seat"]] + dealer.board)[0]] if shown else None
    broadcast("showdown", dealer, pot=pot, winners=winners, shown=list(shown))
    for seat in seats:
        seat.hand_over(dealer, won, shown)
    dealer.button = dealer.next_seat(dealer.button, dealer.has_chips)


def main():
    paths = [p for p in sorted(AGENTS_DIR.glob("*.py")) if not p.name.startswith(("_", "template"))]
    paths += [AGENTS_DIR / "template.py"] * max(0, 2 - len(paths))
    paths = paths[:22]  # one deck can't deal more than 22 seats
    seats = [Seat(p.stem if p not in paths[:i] else f"{p.stem}-{i}", p, i) for i, p in enumerate(paths)]

    print("lineup:", ", ".join(seat.name for seat in seats))
    dealer = Dealer(len(seats), stack=START_STACK)
    dealer.names = [seat.name for seat in seats]
    dealer.wins = [0] * len(seats)
    dealer.odds_key = None
    for hand in range(1, (WINS_HANDS if WINS_MODE else HANDS) + 1):
        if WINS_MODE:
            for i in range(dealer.n):
                if not dealer.has_chips(i):
                    dealer.stacks[i] = START_STACK
        elif sum(map(dealer.has_chips, range(dealer.n))) < 2:
            break
        dealer.hand_number = hand
        if apply_pending():
            announce_clock()
        if WINS_MODE:
            dealer.small_blind, dealer.big_blind = 5, 10
        else:
            level = (hand - 1) // BLINDS_DOUBLE_EVERY
            dealer.small_blind, dealer.big_blind = 5 << level, 10 << level
        print(f"\nhand {hand}")
        play_hand(dealer, seats)

    print("\nstandings")
    for i in sorted(range(len(seats)), key=lambda i: -dealer.stacks[i]):
        print(f"  {seats[i].name}: {dealer.stacks[i]}")
    broadcast("final", dealer)


if __name__ == "__main__":
    main()
