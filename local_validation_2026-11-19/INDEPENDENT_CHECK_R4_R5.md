# Independent check of R4 and R5 (2026-11-19, local, no cost)

Target: `lxf746/any-auto-register` @ `ba1004241f4be7b0bb11b705b7c88a684e42b3db`, cloned from GitHub,
run in Docker (`python:3.11-slim`, arm64, **no network**), dependencies resolved with
`uv --exclude-newer 2026-09-12` because `requirements.txt` is unpinned. Image: `sms-aar:ba10042`
(`target/Dockerfile`). Each experiment ran on a freshly started container.

Method: `independent_check_r4_r5.py` uses only `httpx` and `sqlite3` (`SELECT rowid, *` from every
table of `/app/account_manager.db`). It imports nothing from the SMS engine. Raw output is in `results/`.

Why Stage 9 could not query the database: this target stores its data in a **SQLite file**
(`account_manager.db`; the campaign records `db: sqlite`), not in the `sms_any_auto_register`
PostgreSQL database that was searched. That is why the query found no tables.

## R4 (MR7, `PUT /api/platforms/{name}/capabilities`): confirmed independently

- **Control.** `PUT /api/platforms/anything/capabilities` returns 200 `{"ok":true}` and updates that platform's row.
- **Absent name.** `PUT /api/platforms/sms-absent-platform-7f3a/capabilities` also returns 200 `{"ok":true}`. It inserts a
  `platform_capability_overrides` row with `platform_name = 'sms-absent-platform-7f3a'`.
- **The name really is absent.** It is not in `GET /api/platforms` before or after the PUT. Another endpoint on the
  same name (`GET /api/actions/{name}/capabilities`) fails with an unhandled 500 (`KeyError: platform not registered`).
- **Code.** `PlatformCapabilitiesRepository.update` upserts a row without checking that the platform exists.
- **DELETE on an absent name.** It returns 200 `{"ok":true}`. It changes no state if no row was ever written, and
  deletes the orphan row if the absent-name PUT created one. The campaign's second MR7 test is the second case.

**Verdict: R4 confirmed, fully independently (HTTP and database).**

## R5 (MR5, repeated `DELETE /api/accounts/{id}` "has side effects"): NOT confirmed. It is a false positive.

| Condition | Second delete | State change in the second delete's window |
|---|---|---|
| No background tasks (`results/r5_quiet.json`) | 404 | none, and 0 of 10 repeats |
| After task registration, runtime idle again (`r5_tasks.json`) | 404 | none, and 0 of 10 repeats |
| Background tasks running (`r5_active.json`, 30 trials of each kind) | 404 | 1 of 30 missing-account deletes, 1 of 30 read-only `GET /api/platforms` |

- **Rows the app writes with no request at all.** With registration tasks queued, the app wrote 3 `task_events` rows
  and modified 1 `tasks` row during 1 s in which no request was sent (`r5_tasks.json`, `idle_1s_no_request`).
- **Who writes them.** The app's background `task_runtime` (started at startup; polls every 0.5 s). The rows are
  registration tasks failing because no e-mail provider is configured: messages "任务已开始执行" (task started) and
  "任务结束: failed" (task finished: failed). None of the rows refers to the deleted account.
- **The delete path.** `AccountsRepository.delete` returns `False` before any write when the account does not exist,
  and the route then raises 404.
- **What the campaign recorded.** The second-delete delta (3 `task_events` inserted, 2 `tasks` modified, seeds 1234 and
  5772) has exactly this signature. The SMS bootstrap itself creates the background work: its `register_ops` include
  `POST /api/tasks/register`.

**Verdict: R5 is an oracle false positive.** Concurrent background writes landed inside the snapshot window, and the
oracle attributed them to the request. The engine has no quiescence control, and the paper does not mention this threat.

## Knock-on effects

The MR5 test is not a violation. An earlier draft of this note also proposed reclassifying an MR4 test. That was
wrong: the MR4 test with a `task_events`/`tasks` delta is `POST /api/tasks/register`, which really does insert a task.
The two lifecycle MR4 tests were already `response_class`. (`results/lifecycle_check.json` shows that
`POST /api/lifecycle/check` writes nothing.)

## Harness defect found while setting up the re-run: SQLite files were not reset between runs

`boot.reset` removed only the database the manifest named. Seven targets created their own SQLite file instead:
agentops, any-auto-register, dreamserver, fastapi-course, fastapi-scaf, gcli2api and sie. Their files were never removed.

For any-auto-register, state carried over across all 11 campaign runs. The highest `task_events` id seen in each run's
records rises from 74 to 1,896. The other six targets had a single run each and no failing tests.

Fix: `harness/boot.py` now removes every SQLite file that git does not track in the target tree, and restores tracked ones.

## Engine fix and paired local re-run

`sms/engine.py` now has an opt-in quiescence control (`run_sms.py --quiet-window SEC`):
1. Wait until the database is unchanged for one window, then take the "before" snapshot.
2. After the request, watch one more window.
3. Exclude from the delta any table that changed with no request in flight, and record each exclusion.

Without the flag the engine behaves exactly as in the campaign.

`run_matrix_local.sh` re-runs the campaign's 11 any-auto-register configurations with both oracles. Each run uses a
fresh offline container. The results are in `results/engine/`; see `RERUN_RESULTS.md`.
