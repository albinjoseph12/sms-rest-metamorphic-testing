# Paper 1 (SMS) — Empirical Upgrades Summary (2026-11-27)

All experiments were executed in fresh offline Docker containers (`--network none`) using the exact local SMS target images (`sms-eng:ba10042`, `sms-base:ba10042`, `sms-pg-realworld:latest`, `sms-pg-booking:latest`).

## 1. Synthetic Fault-Injection Study (`results/fault_injection_2026-11-27/v2/`)
Five realistic check-after-write / missing-rollback defects returning valid HTTP rejections (`401`/`403`/`404`) while mutating durable database state (seed `1234`):

| Fault | Target (DB) | Relation | Endpoint | Follow-up HTTP | SMS `full` Verdict | Response-Only (`no-state`) |
|---|---|---|---|---|---|---|
| **FI-1** | `realworld` (PostgreSQL) | `MR1_PRINCIPAL_SUBSTITUTION` | `PUT /api/articles/{slug}` | `403` | `state_changed` (`resp_ok=True, state_ok=False`) | Inexpressible / `403` valid refusal |
| **FI-2** | `realworld` (PostgreSQL) | `MR2_CREDENTIAL_REMOVAL` | `PUT /api/user` | `401` | `state_changed` (`resp_ok=True, state_ok=False`) | Missed (`0` violations) |
| **FI-3** | `booking` (PostgreSQL) | `MR6_DANGLING_REFERENCE` | `POST /api/v1/reservations/` | `404` | `state_changed` (`resp_ok=True, state_ok=False`) | Missed (`0` violations) |
| **FI-4** | `any-auto-register` (SQLite) | `MR5_DELETE_IDEMPOTENCE` | `DELETE /api/proxies/{proxy_id}` | `404` | `state_changed` (`7` total = 6 base + 1 new) | Missed (`6` base, `0` new) |
| **FI-5** | `any-auto-register` (SQLite) | `MR7_ABSENT_PATH_RESOURCE` | `DELETE /api/proxies/{proxy_id}` | `404` | `state_changed` (`7` total = 6 base + 1 new) | Missed (`6` base, `0` new) |

**Result:** SMS detected **5/5** injected faults as pure `state_changed` violations; response-only oracles missed all response-conformant rejections.

## 2. Multi-Seed Schemathesis Baseline (`results/multiseed_baseline_2026-11-27/`)
`any-auto-register`, 5 explicit pinned seeds (`1234, 2718, 3141, 4142, 5772`), 95% Student-$t$ CI ($df=4$, $t_{0.975,4}=2.7764$):
- **Failing tests:** `3,352.6 ± 148.9` (SD `119.9`, range `3,255–3,555`)
- **Root causes:** `31.4 ± 0.7` (range `31–32`)
  - Behavioural: `17.4 ± 0.7` (`17–18`)
  - Conformance: `14.0 ± 0.0` (`14–14`)
- **Wall-clock:** `91.7 ± 32.0 s` (`62.4–115.0 s`)

## 3. Quiescence-Window Sensitivity Sweep (`results/quiescence_sweep_2026-11-27/`)
`any-auto-register`, seed `1234`, fresh offline containers:

| Window | Wall-Clock | Failing Tests | MR5 BG-Writer FP Removed? | Classifications |
|---|---|---|---|---|
| `0.0 s` (off) | `~1 s` | `7` | No | `2 response_class`, `4 accepted_and_persisted`, `1 state_changed` (FP) |
| `0.25 s` | `127.9 s` | `6` | Yes | `2 response_class`, `4 accepted_and_persisted` |
| `0.5 s` | `252.1 s` | `6` | Yes | `3 response_class`, `3 accepted_and_persisted` |
| `1.0 s` (default) | `497.7 s` | `6` | Yes | `3 response_class`, `3 accepted_and_persisted` |
| `2.0 s` | `985.6 s` | `6` | Yes | `3 response_class`, `3 accepted_and_persisted` |
