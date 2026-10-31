# Logan: four-player validation at 1 ms

Logan now combines Riaan's unchanged opaque agent with a public-info action
coach. The target lineup is Logan, Riaan, Sid, and Will at **0.001 seconds per
move**, on upstream commit `9b3ad131cf0d358ce71084c26e1738338ae63733`.

The three opponents were executed normally as black boxes. Their implementations
were not reverse engineered, and their files and the engine are unchanged.

## Fresh validation

The candidate was frozen before the first two holdouts. Both kept the same
agents alive for all 5,000 tournaments, with seats ordered Logan/Riaan/Sid/Will.
Those two holdouts rotated each tournament's starting button for balance. The
additional live-mode run carried the button between games exactly as the viewer
does. All runs used the real engine's move enforcement and a 1,000-hand cap;
every tournament finished with one surviving player.

| Run | Seed | Games | Logan | Riaan | Sid | Will | Action failure notes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Holdout A, balanced starts | 68112073 | 5,000 | **1,483** | 1,274 | 1,258 | 985 | None |
| Holdout B, balanced starts | 79123087 | 5,000 | **1,426** | 1,328 | 1,240 | 1,006 | None |
| Viewer button behavior | 88172459 | 5,000 | **1,458** | 1,324 | 1,249 | 969 | None |
| Combined | | **15,000** | **4,367 (29.11%)** | 3,926 (26.17%) | 3,747 (24.98%) | 2,960 (19.73%) | **None** |

Logan's live-mode lead over Riaan was **134 wins / 2.68 percentage points**;
the approximate 95% interval for that gap is **0.61–4.75 points**. Holdout A's
lead was 209 wins / 4.18 points. Holdout B's smaller lead, 98 wins / 1.96 points,
is individually inconclusive against Riaan at 95% confidence.

Across all three runs, Logan led Riaan by 441 wins / 2.94 points. Approximate
simultaneous 99% intervals for the three pairwise gaps remain positive. These
use a multinomial normal approximation with a Bonferroni critical value of
2.935; they are estimates, not a guarantee for every future 5,000-game race.
Bot randomness and wall-clock sampling also mean seeds are not exact replays.

The prior upstream Logan won 1,364 of a separate 5,000-game baseline, versus
Riaan's 1,402. Exploratory tuning games and the 12,000 training games are excluded
from the validation totals above.

## Policy and build

The fixed configuration:

- Uses Riaan through `Agent.decide` / `hand_over`, preserving its opaque bytes.
- Estimates preflop ranges and responses from numeric summaries of normal
  offline matches, combined with our precomputed 169-class equity tables.
- Scores short-stack shoves at up to 8 effective big blinds and calls against
  all-ins, requiring the call EV to exceed 5% of the additional chips at risk.
- Accounts for contribution layers, folded money, covered pots, and returned
  excess. Multiway showdown shares use products of pairwise class equities.
- Adds minimum-sized heads-up probes when the base checks an unbet street.
- Gives the internal base a budgeting factor of 2. The **actual engine clock
  stays at 1 ms for every player**. The input engine info is not mutated, and
  no watchdog, decision, clock, or opponent is bypassed in evaluation.

The online policy uses only the acting agent's legitimate info. Offline training
records each simulated actor's own cards and actions; no other player's cards
are read by the deployed policy. The learned response model is pooled across
the three opponents, and the selected configuration does not require identifying
players or knowing their seat order.

`agents/logan.py` is a single standard-library-only submission. Its readable
policy is `bench/logan_policy.py`; the numeric model and hashes are in
`bench/logan_data/`. The model's training seed, game count, configuration, and
opponent/engine hashes are recorded in `metadata.json`.

```sh
python3 scripts/build_blackbox.py --check
python3 -m unittest bench.test_logan bench.test_arena -v
```

The standalone build is byte-identical to the validated submission:

`aa18c44b6220b78988d822827586492bff2838a4dba43c8ff21751b402ce0ebe`

The 14 targeted tests cover reproducible packaging, unchanged opaque base bytes,
legal probes and wager totals, the unchanged real clock, and all-in/side-pot
accounting. They do not inspect opponent internals.

## Reproduce a full viewer-mode race

```sh
python3 bench/logan_four_player.py \
  --bot agents/logan.py --games 5000 --jobs 1 --batch 5000 \
  --time 0.001 --seed 88172459 --live-button \
  --output /tmp/logan-live-5000.json
```

For the first two holdouts, omit `--live-button` and use their respective seeds.
`--jobs 1 --batch 5000` preserves all agent instances across the entire race.
The runner rejects failed loads, records every winner in JSONL, counts engine
failure notes, and includes file hashes. The checked-in `bench/logan_runs/`
contains all 15,000 raw outcomes and the corresponding reports.
