-- Default DuckLake suite: keep catalog scanners unloaded.
-- Dedicated SQLite and PostgreSQL suites load their scanner through upstream configs.
LOAD json;
LOAD tpch;
LOAD tpcds;
LOAD icu;
LOAD httpfs;
LOAD ducklake;
