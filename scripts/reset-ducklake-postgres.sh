#!/usr/bin/env bash
set -Eeuo pipefail

: "${PGHOST:?PGHOST is required}"
: "${PGPORT:?PGPORT is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGPASSWORD:?PGPASSWORD is required}"
: "${PGDATABASE:?PGDATABASE is required}"

if [[ "${PGDATABASE}" != "ducklakedb" ]]; then
  echo "Unexpected DuckLake PostgreSQL database: ${PGDATABASE}" >&2
  exit 1
fi

command -v psql >/dev/null 2>&1 || {
  echo "psql is required for DuckLake PostgreSQL test isolation" >&2
  exit 1
}

# PostgreSQL is infrastructure for the native Windows DuckLake battery. Reset
# the catalog before every SQLLogicTest file, matching the Linux runner's
# isolation contract without launching DuckDB or unittest from WSL.
for attempt in $(seq 1 60); do
  if PGDATABASE=postgres psql --no-psqlrc --set=ON_ERROR_STOP=1 --quiet <<'SQL'
DROP DATABASE IF EXISTS ducklakedb WITH (FORCE);
CREATE DATABASE ducklakedb OWNER postgres;
\connect ducklakedb
CREATE SCHEMA main AUTHORIZATION postgres;
SQL
  then
    exit 0
  fi
  sleep 1
done

echo "PostgreSQL did not become stable enough to recreate ducklakedb" >&2
exit 1
