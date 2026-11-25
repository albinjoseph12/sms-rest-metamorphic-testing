#!/usr/bin/env bash
# Provision the services the harness requires: a PostgreSQL cluster with a superuser role the
# targets can use, and password-free local access for the harness itself.
set -e
service postgresql start || true
HBA=$(ls /etc/postgresql/*/main/pg_hba.conf)
grep -q "postgres        127.0.0.1/32            trust" "$HBA" || \
  sed -i '124i host    all             postgres        127.0.0.1/32            trust' "$HBA"
service postgresql reload
until psql -U postgres -h localhost -c 'select 1' >/dev/null 2>&1; do sleep 1; done
psql -U postgres -h localhost -tc "select 1 from pg_roles where rolname='acb'" | grep -q 1 || \
  psql -U postgres -h localhost -c "CREATE ROLE acb LOGIN SUPERUSER PASSWORD 'acb'"
