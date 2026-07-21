-- Used only by HTTPFS autoloading tests.
-- DuckLake and its catalog dependencies remain loaded, while HTTPFS must start unloaded.
-- MSSQL remains loaded because the compatibility contract covers coexistence with the selected extensions.
LOAD tpcds;
LOAD ducklake;
LOAD postgres_scanner;
LOAD sqlite_scanner;
LOAD mssql;
