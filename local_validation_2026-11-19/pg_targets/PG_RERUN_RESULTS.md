# PostgreSQL targets re-run (2026-11-19 19:34 to 2026-11-20 07:23 PST, local, no cost)

## Scope
- **Targets:** the four PostgreSQL-backed evaluable targets: realworld, booking, cloudrun and dispatch.
- **Configurations:** the campaign's 11 per target: `full` × seeds 1234/2718/3141/4142/5772, plus `no-state` and
  `no-contract` × seeds 1234/2718/3141.
- **Oracles:** each configuration ran twice, once with the original oracle and once with the quiescence control
  (`--quiet-window 1.0`).
- **Total:** 4 × 11 × 2 = **88 runs**. All 88 completed, with no setup failures and no timeouts.
- **Platform:** Apple M3 Max (arm64), Docker. Every run used a fresh container with `--network none`, pinned to CPUs 8–13.
- **Reset:** the harness's own reset (drop and create the database, then apply the manifest's migrations), as on the
  campaign VM.
- **Code:** `run_local_pg.py` is `run_sms.py` unchanged, apart from a no-op `prepare`, because dependencies are baked
  into the image.
- **Logs:** `all_pg.log`, plus `results/<target>/*.log`, `*.setup.log` and `*.server.log`.
- **Time:** 11.6 h of SMS wall-clock in total. Dispatch with the quiescence control took 36.0 ks of that.
- **Time limit:** the three Dispatch `no-contract` quiet runs send about 2,345 requests each and take about 5,330 s,
  more than the matrix's 3,600 s limit. `finish_dispatch_nocontract.sh` stopped the matrix just before them and ran
  them with the identical command and a 10,800 s limit. No run was cut off.

## Results (`compare_pg.py`, output in `compare_pg.json`)
1. **Original oracle vs campaign: 44 of 44 identical.**
   - Every deterministic statistic matches: instantiated, executed, source_ok, violations, source_failed, requests,
     per_relation, source_status and not_applicable. Wall time is excluded.
   - The per-record sequence of (relation, target operation, verdict) also matches.
2. **Quiescence control vs original oracle: 44 of 44 identical.**
   - The same statistics match, and the per-record verdict sequences are identical. The second check was computed
     separately from `compare_pg.py`, which compares only the statistics.

**Violations per configuration** (campaign = original oracle = quiescence control):

| Target | Configurations | Violations |
|---|---|---|
| realworld | all | 0 |
| booking | `no-contract` (3 seeds) | 3 |
| booking | all others | 0 |
| cloudrun | `no-contract` | 1 |
| cloudrun | all others | 0 |
| dispatch | `full` and `no-state` | 40 |
| dispatch | `no-contract`, seeds 1234 / 2718 / 3141 | 41 / 38 / 41 |

## What this changes
- The paper used to say the four PostgreSQL targets "were not re-run", and argued that their verdicts could not depend
  on the quiescence control. Both points are now **measured**:
  - the campaign results reproduce exactly on a different machine and architecture;
  - the control changes no verdict on these targets.
- Every published number for these targets still comes from the campaign and is unchanged. The paper's text was updated
  in Section V (the paragraph on the reset audit) and in Threats to validity (Internal); its 55 checks still pass.
