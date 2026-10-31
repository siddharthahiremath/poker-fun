# Benchmarking Sid

Run real freezeouts against the opponents without inspecting their implementations:

```sh
python3 bench/arena.py --games 3000 --procs 6 --time 0.01 --seed 907123 --diagnostics agents/sid.py agents/logan.py agents/will.py
python3 -m unittest discover -s bench -p 'test_*.py' -v
```

`--games` is exact, including when it is not divisible by `--procs`.
`--seed` controls worker random seeds. Agents can have independent randomness and
wall-clock sampling, so it does not guarantee identical replays.
`--json` emits machine-readable wins, action counts, and failure notes.
`--diagnostics` counts engine-reported timeouts, crashes, and illegal actions.
An agent that fails to load aborts the benchmark rather than earning misleading wins.

Test both heads-up matchups as well as the three-player table. Repeat on fresh
seeds, rotate the input order, and use the move limit actually used in the viewer.
Keep candidate files unchanged until every worker exits. Avoid running competing
CPU-heavy jobs when comparing short-clock results.

Tournament outcomes have substantial variance. Select changes on exploratory
runs, then check them on a separate, larger set of seeds. Report the game count
and failure notes with win rates; a small lead alone does not prove superiority.
