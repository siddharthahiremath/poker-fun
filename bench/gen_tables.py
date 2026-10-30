# Precomputes the preflop equity tables embedded in agents/sid.py.
# usage: python3 bench/gen_tables.py [trials]
import importlib.util
import multiprocessing
import pathlib
import random
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
AGENT = ROOT / "agents" / "sid.py"


def load():
    spec = importlib.util.spec_from_file_location("sid_gen", AGENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


m = load()


def share(mine, others):
    best = max(others)
    if mine > best:
        return 1.0
    if mine == best:
        return 1.0 / (1 + others.count(best))
    return 0.0


def eqv_row(args):
    cls, trials, seed = args
    rng = random.Random(seed)
    out = []
    for n in range(1, m.MAX_OPPONENTS_TABLE + 1):
        total = 0.0
        for _ in range(trials):
            a, b = rng.choice(m.CLASS_COMBOS[cls])
            deck = [c for c in range(52) if c != a and c != b]
            cards = rng.sample(deck, 2 * n + 5)
            board = cards[2 * n:]
            mine = m.evaluate([a, b] + board)
            others = [m.evaluate(cards[2 * i:2 * i + 2] + board) for i in range(n)]
            total += share(mine, others)
        out.append(total / trials)
    return cls, out


def eqr_row(args):
    cls, trials, seed, combo_order = args
    rng = random.Random(seed)
    out = []
    for p in m.P_BUCKETS:
        top = max(1, int(p * 1326 + 0.5))
        total = 0.0
        for _ in range(trials):
            a, b = rng.choice(m.CLASS_COMBOS[cls])
            while True:
                c, d = combo_order[rng.randrange(top)]
                if c not in (a, b) and d not in (a, b):
                    break
            deck = [x for x in range(52) if x not in (a, b, c, d)]
            board = rng.sample(deck, 5)
            total += share(m.evaluate([a, b] + board), [m.evaluate([c, d] + board)])
        out.append(total / trials)
    return cls, out


def pack(rows):
    return "".join("%03d" % min(999, int(round(v * 1000))) for row in rows for v in row)


def literal(name, data, width=96):
    chunks = [data[i:i + width] for i in range(0, len(data), width)]
    return name + " = (\n" + "".join('    "%s"\n' % c for c in chunks) + ")\n"


def main():
    trials = int(sys.argv[1]) if len(sys.argv) > 1 else 6000
    with multiprocessing.Pool() as pool:
        eqv = [[0.0] * 169 for _ in range(m.MAX_OPPONENTS_TABLE)]
        for cls, row in pool.imap_unordered(eqv_row, [(c, trials, 1000 + c) for c in m.CLASSES]):
            for n, v in enumerate(row):
                eqv[n][cls] = v
        eqv_data = pack(eqv)
        rounded = m._unpack(eqv_data, m.MAX_OPPONENTS_TABLE)
        _, combo_order, _ = m.build_order(rounded)
        eqr = [[0.0] * 169 for _ in m.P_BUCKETS]
        jobs = [(c, trials, 5000 + c, combo_order) for c in m.CLASSES]
        for cls, row in pool.imap_unordered(eqr_row, jobs):
            for b, v in enumerate(row):
                eqr[b][cls] = v
    block = "# --- tables (written by bench/gen_tables.py) ---\n"
    block += literal("EQV_DATA", eqv_data) + literal("EQR_DATA", pack(eqr)) + "# --- end tables ---\n"
    text = AGENT.read_text()
    text = re.sub(r"# --- tables \(written by bench/gen_tables\.py\) ---\n.*?# --- end tables ---\n", lambda _: block, text, flags=re.S)
    AGENT.write_text(text)
    print("wrote tables", len(eqv_data), "eqv chars")


if __name__ == "__main__":
    main()
