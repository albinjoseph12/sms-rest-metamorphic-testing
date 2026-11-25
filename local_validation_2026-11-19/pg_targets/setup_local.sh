#!/usr/bin/env bash
# Same provisioning as corrected_sms/setup_env.sh (PostgreSQL superuser role acb/acb, password-free local access
# for the harness's `psql -U postgres -h localhost`), but the trust line is inserted at the top of pg_hba.conf:
# setup_env.sh inserts it at line 124, and the stock Ubuntu file is shorter, so its insert never happens.
set -e
HBA=$(ls /etc/postgresql/*/main/pg_hba.conf)
grep -q "sms-local" "$HBA" || sed -i '1i # sms-local\nhost all postgres 127.0.0.1/32 trust\nhost all postgres ::1/128 trust' "$HBA"
service postgresql start >/dev/null
for i in $(seq 1 30); do psql -U postgres -h localhost -c 'select 1' >/dev/null 2>&1 && break; sleep 1; done
psql -U postgres -h localhost -tc "select 1 from pg_roles where rolname='acb'" | grep -q 1 || \
  psql -U postgres -h localhost -c "CREATE ROLE acb LOGIN SUPERUSER PASSWORD 'acb'" >/dev/null
redis-server --daemonize yes >/dev/null
psql -U postgres -h localhost -tAc "select version()" | cut -c1-30
