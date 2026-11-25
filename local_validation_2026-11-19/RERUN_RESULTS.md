# any-auto-register re-run and follow-up checks (2026-11-19, local, no cost)

Machine: Apple M3 Max, Docker, arm64, every run in a fresh container with `--network none`. The target is pinned at
`ba1004241f4be7b0bb11b705b7c88a684e42b3db`, with dependencies resolved by `uv --exclude-newer 2026-09-12`. The engine
code is `corrected_sms/` as of today: the SQLite reset fix plus the opt-in quiescence control (`--quiet-window 1.0`).
Driver: `run_matrix_local.sh`; tabulation: `analyse_rerun.py` → `results/rerun_summary.json`.

## 1. SMS: campaign vs local original oracle vs local quiet oracle

| Config | Campaign (GCP, state carried over) | Local, original oracle | Local, quiet oracle |
|---|---|---|---|
| full s1234 | 14 executed / 7 violations | 15 / 7 | 14 / 6 |
| full s2718 | 18 / 7 | 15 / 6 | 14 / 6 |
| full s3141 | 19 / 7 | 14 / 6 | 14 / 6 |
| full s4142 | 18 / 7 | 14 / 7 | 14 / 6 |
| full s5772 | 19 / 8 | 15 / 6 | 14 / 6 |
| no-state ×3 | 18–19 / 7 | 14–15 / 6 | 14 / 6 (all three) |
| no-contract ×3 | 60–61 / 46 | 57–58 / 46 | 59 / 47 (all three) |

Violation kinds, full variant, summed over the 5 seeds:

| Instance | Campaign | Original | Quiet |
|---|---|---|---|
| MR4 `POST /api/tasks/register` | 5 a&p | 5 a&p | 5 response_class (see below) |
| MR4 lifecycle refresh / check | 4 rc + 1 a&p / 5 rc | 5 rc / 5 rc | 5 rc / 5 rc |
| MR5 `DELETE /api/accounts/{id}` (R5) | 2 state_changed | 0 | 0 |
| MR6 `POST /api/accounts` (R3) | 5 a&p | 5 a&p | 5 a&p |
| MR6 `PATCH /api/accounts/{id}` | 4 a&p | 0 | 0 |
| MR7 platform capabilities PUT / DELETE (R4) | 5 + 5 a&p | 5 + 5 a&p | 5 + 5 a&p |
| MR7 `GET /api/tasks/{id}`, `.../logs/stream` | 0 | 1 + 1 state_changed (false positives) | 0 |

Readings:
- **Fresh database.** With a fresh database the quiet oracle is exactly reproducible across seeds. The campaign's
  variation, and its MR6 PATCH instances, came from state carried over between runs: the PATCH source needs an
  existing account, and only leftover accounts supplied one.
- **Original oracle.** Its verdicts depend on timing. It loses the R5 instance by chance and gains false `state_changed`
  verdicts on two GETs. The quiet oracle removes all of these.
- **Table-level exclusion.** Because the quiet oracle excludes whole tables, the register-task MR4 verdict becomes
  `response_class`: the task insert is real, but the background runtime writes the same table. This trades precision
  for classification.
- **Quiescence statistics** (full s1234): 245 executions, 19 with an excluded table, 0 timeouts, 249.0 s of waiting,
  499.8 s wall.
- **New in no-contract.** MR4 negates the `id` of `/api/provider-definitions` (POST/PUT). The app raises an unhandled
  `ValueError("provider definition 不存在")` ("provider definition does not exist"), which surfaces as 500. The
  failure is real, but it is reached only because the ablation treats `id` as a quantity, and it is counted in
  "not flagged by full". The campaign never reached it because its sources failed on the leftover database.

## 2. Independent checks (no SMS code)

- **R4** — `results/r4.json`. Confirmed over HTTP and in the database (see `INDEPENDENT_CHECK_R4_R5.md`).
- **R5** — `results/r5_*.json`. Withdrawn as an oracle false positive caused by background task writes.
- **R2** — `r2_check.py` → `results/r2_check.json`. Confirmed on a fresh instance with 12 accounts:
  - `limit` 5 checks 5 accounts; 0 checks none; −5 checks all 12.
  - `core/lifecycle.py` passes the value to SQL `LIMIT` unchecked, and SQLite reads a negative `LIMIT` as no limit.
  - The earlier evidence (error 205) had been gathered on the accumulated database.
- **R3** — `r3_check.py` → `results/r3_check.json`. Behaviour reproduced: `user_id` "999999999" is stored, and the row
  was read from SQLite. **But R3 is not judged a defect.**
  - The API has no user resource: no `/users` path and no user table.
  - The FOREIGN_REFERENCE witness matched `user_id` only through the fallback in `sms/contract.py`
    `find_foreign_refs`, which uses the name's stem when no collection matches.
  - That fallback was already in the original frozen code (`original_archive/sms_replication.tar.gz`). The paper's
    witness definition ("where the resource model contains a matching collection") misdescribed it and has been
    corrected.
  - In the target's own code, `user_id` is the account's ID on the external platform.
  - This judgement is the author's (AI-assisted) and should go to the second, blinded adjudicator.

## 3. Schemathesis baseline for any-auto-register, re-run on a fresh instance

`Dockerfile.baseline` (Schemathesis 4.27.0, the version every campaign run recorded) and `run_baseline_local.py` run
`run_baseline.py` unchanged, with the campaign's computed budget (`--budget 120`).

| | wall | timed out | failing tests | causes | behavioural | conformance |
|---|---|---|---|---|---|---|
| Campaign, on the un-reset database | 120.1 s | yes | 1,040 | 28 | 15 | 13 |
| Fresh instance | 50.4 s | no | 3,293 | 31 | 17 | 14 |

Schemathesis draws its own seed per run and records it in `events.ndjson`; that seed is not pinned.

## 4. Pre-existing errors in the manuscript found today

- **Version.** The baseline was described as "Schemathesis 4.25.2 with a configured budget of 900 s per target". Every
  event stream records 4.27.0.
- **Budget.** The budget was in fact `max(120 s, 3 × SMS wall + 60 s)`: 120 s on four targets and 1,559.4 s on Dispatch.
  The pre-registration (`PREREGISTRATION.md`) states this formula correctly.
- **Witness definition.** The FOREIGN_REFERENCE definition did not match the frozen code (see R3 above).

## 5. Integration into `corrected_sms/` (done)

**Results**
- The 11 campaign files moved to `results/archived_campaign_any-auto-register/`.
- The 11 quiet-oracle files installed under the standard names. Checksums are in `results/any-auto-register_local_rerun.sha256`.
- The original-oracle local runs are kept in `results/local_rerun_original_oracle/`.
- The campaign baseline moved to `results/baseline/archived_campaign_any-auto-register/`, and the fresh baseline installed.

**Validation**
- `validation.json` is now R1–R4: all confirmed independently, and R3 carries `defect_assessment.judged_defect = false`.
- R5 is in `validation_withdrawn.json`.
- Applied by `update_validation.py` and `amend_r3.py`.

**Paper**
- `numbers.json` and the figures were regenerated.
- The manuscript was rewritten in the affected sections, and `check_paper.py` updated: 55/55 checks pass.
- The pre-change state is in `corrected_sms/backup_pre_local_rerun_2026-11-19/`.

Headline change: 47 failing tests / 5 root causes → **46 / 4**, of which **3 are judged defects**. State-only detections
fall from 1 to **0**, so the persistence oracle detected nothing beyond the response check on this corpus, and its
contribution is reframed as evidential.

## 6. The four PostgreSQL targets re-run as well (2026-11-19 19:34 → 2026-11-20 07:23)
realworld, booking, cloudrun and dispatch were re-run: all 11 configurations, each with the original oracle and with
the quiescence control, in fresh offline containers (88 runs, all completed).
- **Original oracle vs campaign:** identical in 44 of 44 configurations. Every deterministic statistic matches, and so
  does the per-record verdict sequence.
- **Quiescence control vs original oracle:** identical in 44 of 44.

The paper's results for these targets remain the campaign's. Its text no longer says they were not re-run. Detail:
`pg_targets/PG_RERUN_RESULTS.md`.
