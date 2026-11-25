#!/usr/bin/env bash
# dispatch no-contract sends ~2,345 requests per run (full: 1,113); with the 1 s quiet window a run takes ~5,000 s,
# over run_pg_matrix.sh's 3,600 s limit. Stop the matrix right after dispatch no-state s3141 quiet, then run the
# three no-contract quiet runs with the identical command and a 10,800 s limit (run_pg_matrix_long.sh).
cd "$(dirname "$0")"
until grep -q "done dispatch no-state s3141 quiet" all_pg.log; do sleep 20; done
pkill -f all_pg.sh; pkill -f 'run_pg_matrix.sh dispatch'; sleep 2; docker rm -f sms-pg >/dev/null 2>&1
echo "$(date +%H:%M:%S) matrix stopped before no-contract quiet; continuing with 10800 s limit" >> all_pg.log
for s in 1234 2718 3141; do ./run_pg_matrix_long.sh dispatch auto_dispatch.json no-contract $s quiet >> all_pg.log 2>&1; done
echo "ALL PG TARGETS DONE" >> all_pg.log
