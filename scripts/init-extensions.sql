-- Shared initialization for normal upstream test databases.
-- Installation is performed once before the test runner starts.
LOAD json;
LOAD tpch;
LOAD tpcds;
LOAD icu;
LOAD httpfs;
LOAD ducklake;
LOAD postgres_scanner;
LOAD sqlite_scanner;
LOAD mssql;
