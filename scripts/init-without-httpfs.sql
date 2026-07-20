-- Used only by HTTPFS autoloading tests.
-- DuckLake and TPC-DS remain loaded, while HTTPFS must start unloaded because that is what these tests verify.
LOAD tpcds;
LOAD ducklake;
