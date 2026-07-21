-- Default DuckLake suite: keep catalog scanners unloaded.
-- Dedicated SQLite and PostgreSQL suites load their scanner through upstream configs.
-- MSSQL remains loaded because the compatibility contract covers coexistence of all selected extensions.
LOAD json;
LOAD tpch;
LOAD tpcds;
LOAD icu;
LOAD httpfs;
LOAD ducklake;
LOAD mssql;
