# Sid validation, 2026-10-30

Only Sid's source was unpacked. Opponents were exercised through normal matches,
not inspected or deobfuscated. Engine rules and opponent files were unchanged.

## Primary-clock follow-up: 1 ms

The user clarified that the usual setting is **option 1, 0.001 seconds**, with
0.01 and 0.1 seconds also used. One second was not the intended target.

The fast path now values each side pot separately and accounts for multiway
ties correctly. The betting thresholds, opponent sampling, and preflop policy
are unchanged. Broader strategy experiments that lost ground were rejected.

Isolated correction against `48203fa`, at 1 ms, all six seat orders,
1,000 games per order:

| Version | Games | Sid wins | Logan wins | Will wins | Action notes |
| --- | ---: | ---: | ---: | ---: | --- |
| Before fast-path correction | 6,000 | 2,167 (36.1%) | 2,063 | 1,770 | None |
| Corrected fast path | 6,000 | 2,184 (36.4%) | 2,121 | 1,695 | None |

Base seed: 831551, with 7,919 added per seat-order job; two workers.
The 0.3-percentage-point improvement is too small to establish a strength gain.
Sid led this three-player run, but the margin over Logan does not establish
consistent dominance. The verified improvement is avoiding incorrect folds in
profitable side pots and guaranteed multiway chops.

### Preserving the newer upstream update

Upstream commit `c053b5b` arrived during testing. Its bluff reads and calibrated
flop/turn equity were preserved in the merge, rather than replaced by the older
Sid implementation. On the river the fast path uses explicit win/tie probabilities;
before the river it retains upstream's calibrated runout equity.

Fresh comparison of that upstream version and the merged bot, using base seed
991603, the same six seat orders, and 6,000 games per version:

| Version | Games | Sid wins | Logan wins | Will wins | Action notes |
| --- | ---: | ---: | ---: | ---: | --- |
| Upstream `c053b5b`, seed 991603 | 6,000 | 2,232 (37.2%) | 2,000 | 1,768 | None |
| Merged bot, seed 991603 | 6,000 | 2,205 (36.8%) | 2,002 | 1,793 | None |
| Merged bot, independent seed 702971 | 6,000 | 2,183 (36.4%) | 2,018 | 1,799 | None |
| Merged bot, combined | 12,000 | 4,388 (36.6%) | 4,020 (33.5%) | 3,592 (29.9%) | None |

The small difference is not evidence of a strength gain over the upstream update.
Both versions led this three-player run. The merge retains the verified side-pot
and tie fixes without discarding that update.
The merged bot led both independent 6,000-game batches. These are measurements
against the current opponents at 1 ms, not a guarantee against future bot updates.

The merged bot's 10 ms compatibility run (600 games, seed 911004, one worker)
finished with Sid 229, Logan 186, and Will 185 wins, with no action notes.
The 100 ms compatibility run (180 games, seed 911005, one worker) finished with
Sid 63, Logan 51, and Will 66 wins, also with no action notes. These smaller runs
check compatibility, not a reliable strength edge at those clocks.

### Merged bot, heads-up at 1 ms

| Opponent | Games | Sid wins | Win rate | Action notes |
| --- | ---: | ---: | ---: | --- |
| Logan | 3,000 | 1,556 | 51.9% | None |
| Will | 3,000 | 1,727 | 57.6% | None |

```sh
python3 bench/arena.py --games 3000 --procs 1 --time 0.001 --seed 714601 --diagnostics --json agents/sid.py agents/logan.py
python3 bench/arena.py --games 3000 --procs 1 --time 0.001 --seed 714602 --diagnostics --json agents/sid.py agents/will.py
```

The heads-up margin against Logan is modest. Do not read it as a guarantee of
dominance, or compare it directly with the older results at a different clock.

The regression suite now has **24 passing tests**, including a check that the
merge still uses upstream's runout-equity calibration. Only Sid's code was unpacked.

## Earlier 10 ms heads-up checks

At **0.01 seconds per move**, with the final side-pot, range, and table-cache changes:

| Opponent | Games | Sid wins | Win rate | Sid action notes |
| --- | ---: | ---: | ---: | --- |
| Will | 1,500 | 846 | 56.4% | 1 timeout |
| Logan | 1,500 | 722 | 48.1% | None |

Commands, run from the repository root:

```sh
python3 bench/arena.py --games 1500 --procs 2 --time 0.01 --seed 849310 --diagnostics agents/sid.py agents/will.py
python3 bench/arena.py --games 1500 --procs 2 --time 0.01 --seed 849311 --diagnostics agents/sid.py agents/logan.py
```

These results support an advantage over Will at this clock, **not a consistent
advantage over Logan**. They do not establish win rates at the viewer's default
10-second clock. Agent randomness and timing mean seeded runs are not exact replays.

## Controlled comparisons

- Deadline fix, 360 three-player games per version at 0.1 seconds: original Sid
  won 119 games and timed out 1,093 times; fixed Sid won 125 and had no action
  notes. Logan also timed out in both runs. The win-rate difference alone is
  inconclusive; eliminating Sid's timeouts is the clear improvement.
- Side-pot and depth-aware range changes, 1,800 three-player games per version at
  0.01 seconds: the deadline-only bot won 608 (33.8%); the second-round bot won
  640 (35.6%), versus Logan's 646 and Will's 514. This comparison preceded the
  behavior-preserving shove-table cache. Sid had seven timeouts before that
  optimization. Do not treat this small win-rate increase as proof of superiority.
- Comparisons used all six three-player seat orders, with 60 or 300 games per
  order and worker seeds spaced by 7,919. Base seeds were 882105 and 226017.
  Earlier unsuccessful strategy experiments were not shipped.

## Regression checks

`python3 -m unittest discover -s bench -p 'test_*.py' -v` passes 18 tests:
evaluator agreement, legal actions, partial raise reopening, covered pots,
side-pot eligibility and profitable calls, depth-aware shove estimates, exact
cached table values, deadline-bounded scoring, and benchmark failure handling.
Contract tests cover move limits from 0.001 to 10 seconds; these are not
tournament-strength measurements.

Final 0.1-second smoke check: 180 three-player games, seed 901442, two workers.
Logan won 65, Will 61, and Sid 54 (30.0%). No player had an action error or
timeout. This confirms the final bot runs cleanly at that clock, but does not
show a playing-strength advantage there.
