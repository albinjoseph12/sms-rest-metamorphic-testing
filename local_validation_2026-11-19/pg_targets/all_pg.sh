#!/usr/bin/env bash
cd "$(dirname "$0")"
./run_pg_matrix.sh realworld realworld.json
./run_pg_matrix.sh booking booking.json
./run_pg_matrix.sh cloudrun cloudrun.json
until docker image inspect sms-pg-dispatch >/dev/null 2>&1; do sleep 30; done
./run_pg_matrix.sh dispatch auto_dispatch.json
echo "ALL PG TARGETS DONE"
