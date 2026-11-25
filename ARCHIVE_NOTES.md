# SMS replication package — archive notes (rebuilt 2026-11-18)
Contents: `sms/` (engine), `harness/`, `manifests/`, `results/` (all runs, baseline, ablations, validation), `analysis/` (incl. `check_paper.py`), `tests/`, `paper/` (final manuscript source, PDF, DOCX).
Verify the manuscript's numbers: `SMS_HOME=$PWD python3 analysis/check_paper.py` (47 checks).
Compared with the first archive, only `paper/` changed (final manuscript text); no result file or code changed. See `AUDIT_STAGE*.md` / `*_MANIFEST.md` if included alongside.

Update (2026-11-18, later): the manuscript text was corrected (violation-kind breakdown, Table III executed counts, citation order and cross-references); `analysis/check_paper.py` now has 49 checks, including the violation kinds and Table III. No result file or engine code changed.

Update (2026-11-19, submission version for Software: Practice and Experience): `paper/` holds the final manuscript.

Update (2026-11-19, local re-run): an audit found that the harness reset did not remove SQLite files a target created
itself, so any-auto-register carried state across all campaign runs; and the state oracle attributed a background
writer's rows to a request (former root cause R5, now withdrawn). `harness/boot.py` now removes such files and
`sms/engine.py` has an opt-in quiescence control (`run_sms.py --quiet-window`). any-auto-register (all 11
configurations) and its Schemathesis baseline were re-run on fresh offline containers locally; the campaign files are
kept under `results/archived_campaign_any-auto-register/` and `results/baseline/archived_campaign_any-auto-register/`.
Scripts, Dockerfiles, raw outputs and independent checks are in `local_validation_2026-11-19/`
(start with `RERUN_RESULTS.md`; the target's source is not included — clone it at the pinned commit).
`analysis/check_paper.py` now has 55 checks.

Update (2026-11-20): the four PostgreSQL targets (realworld, booking, cloudrun, dispatch) were also re-run locally in
all 11 configurations, with the original oracle and with the quiescence control (88 runs, fresh offline containers).
Original oracle vs campaign: identical in 44/44 configurations (statistics and per-record verdicts); quiescence control
vs original: identical in 44/44. The paper's numbers for these targets remain the campaign's. Scripts, Dockerfile, logs
and raw outputs: `local_validation_2026-11-19/pg_targets/` (start with `PG_RERUN_RESULTS.md`; `compare_pg.py`).
