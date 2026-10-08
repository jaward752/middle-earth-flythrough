# FPL Data Pipeline — Stage 1

Ingests the [FPL-Core-Insights](https://github.com/olbauday/FPL-Core-Insights)
dataset into a single DuckDB file, cleaned and shaped for expected-points
modelling.

```bash
pip install duckdb pandas requests
python ingest.py      # download + load (~2 min, ~25MB of CSVs)
python verify.py      # sanity checks — run after every ingest
```

Output: `fpl.duckdb` (~13MB).

## Why DuckDB

The workload is analytical and single-writer: bulk loads, then wide aggregate
scans over a few hundred thousand rows. DuckDB is columnar, needs no server,
lives in one file you can copy or commit, and reads CSV natively. Postgres
would add operational overhead for no gain at this scale.

The SQL is standard, so migrating later — when you add user accounts and
concurrent web traffic — is mostly a connection-string change. Keep the model
layer talking to views, not tables, and that migration stays cheap.

## Data traps this pipeline corrects

Three things silently corrupt naive ingestion of this dataset. Each is handled
in `ingest.py` and asserted in `verify.py`.

**1. `matches` joins teams on `code`, not `id`.** The upstream README says
`home_team` links to `teams.id`. It does not — it links to `teams.code`. Both
are small integers, so joining on `id` produces a fully populated table with
systematically *wrong* teams attached to every fixture, and nothing errors.
Check 2 in `verify.py` fails loudly if this regresses.

**2. `matches.csv` mixes competitions.** It contains Champions League, Europa,
Conference, EFL Cup and friendlies alongside league games. Non-Premier-League
opponents have no FPL team, so their team reference is NULL. Fitting team
strength on the unfiltered table blends a Real Madrid fixture into a club's
league record. Every row is tagged with `competition` and a boolean `is_pl`.
Filter with `WHERE is_pl` for model fitting; the cup and European rows are
still useful as fatigue and rotation features.

**3. The league's slug is `prem`, not `premier-league`.** Parsing competition
from `match_id` with the obvious string silently classifies all 380 league
fixtures as "other". Verified by asserting exactly 380 league fixtures per
season.

## Schema

Raw tables mirror the source (`teams`, `players`, `matches`,
`player_match_stats`, `player_gw_stats`, `gameweeks`), each with a `season`
column and deduplicated on natural keys — gameweek snapshots are cumulative,
so the same match appears in many folders.

Four views are the actual interface:

| View | Grain | Purpose |
|---|---|---|
| `v_matches` | match | Correct team names, competition tag, Elo, team xG |
| `v_player_match` | player × match | **The modelling table.** Minutes, xG/xA, defensive actions, CBIT/CBIRT, DefCon outcome, opponent Elo, home/away |
| `v_team_match` | team × match | Long-format team record — feeds the Poisson clean-sheet model |
| `v_defcon_rates` | player × season | Empirical DefCon hit rate — prior for the threshold model |

`v_player_match` computes `cbit`, `cbirt`, `hit_defcon` (boolean) and
`defcon_points` per row. `hit_defcon` is your training target for the DefCon
component — a binary outcome, not a rate.

## What the data shows

Run `verify.py` for the full output. Three results that shape Stage 2:

**DefCon is a threshold, and linear models get it badly wrong.** Across 3,026
defender-matches of 60+ minutes in 2025-26, mean CBIT was 7.45 and the true
expected DefCon return was 0.54 points. Scaling linearly — the approach in
`thomaszwagerman/fpl-solver` — gives 1.49, overvaluing defenders by 2.8x. The
error is worst exactly where it matters: a defender recording 19 CBIT scores 2
points, but a linear model awards 3.8.

**The Poisson clean-sheet model is almost exactly right, and the sigmoid is
not.** Actual league clean-sheet rate was 0.257 against a mean 1.372 goals
conceded. `exp(-λ)` predicts 0.254 — within 0.003. The sigmoid used by
fpl-solver predicts 0.408, a 59% relative overestimate that would inflate
every defender and goalkeeper in the solver.

**Binary 60-minute assumptions discard real uncertainty.** Only 50.5% of
forward appearances reached 60 minutes; 43.8% fell in the 1–59 band. Treating
appearance points as a coin-flip threshold rather than a distribution is the
single largest avoidable error source for attacking players.

Validation: the top DefCon scorers computed from raw actions — Anderson (52),
Senesi (52), Tarkowski (44) — match publicly reported 2025-26 figures of 52,
50 and 44. The 2-point gap on Senesi is worth investigating before trusting
the column to the decimal; it is likely one match where a substitution or
scoring edge case differs, but it has not been chased down.

## Known limitations

- **2026-27 has fixtures but no results yet** (season starts 2026-08-15), so
  `player_match_stats` is empty for it. All model fitting uses 2025-26.
- **One season of DefCon data.** 2025-26 is the first season with both the rule
  and per-match action counts, so DefCon priors rest on a single season and
  should be shrunk toward positional means for low-appearance players.
- **No live FPL API calls.** Prices, injury news and
  `chance_of_playing_next_round` move within hours of a deadline; twice-daily
  CSVs will not catch a late press conference. Add a thin
  `fantasy.premierleague.com/api/bootstrap-static/` fetch at prediction time.
- **The upstream match stats are third-party scraped, not official Opta.**
  Treat `verify.py` as a standing regression test, not a one-off.

## Next

Stage 2 is the model layer, fitted on `v_player_match`:

1. Minutes — multinomial P(0) / P(1–59) / P(60+)
2. Clean sheets — Poisson on Elo-derived team λ
3. Goals & assists — xG/xA per 90 scaled by minutes and fixture
4. DefCon — negative binomial on action counts, then P(count ≥ threshold)
5. Bonus — rank model for P(top-3 BPS in match)
6. Saves & goals conceded — Poisson expectations over their thresholds

Then a LightGBM model predicting points directly, as a benchmark for the
component model to beat.
