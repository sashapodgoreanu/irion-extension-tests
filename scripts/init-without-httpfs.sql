-- Used only by HTTPFS autoloading tests.
-- DuckLake and its catalog dependencies remain loaded, while HTTPFS must start unloaded.
LOAD tpcds;
LOAD ducklake;
LOAD postgres_scanner;
LOAD sqlite_scanner;
