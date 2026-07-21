-- Install the compatibility set once in the isolated HOME used by each CI job.
INSTALL json;
INSTALL tpch;
INSTALL tpcds;
INSTALL icu;
INSTALL httpfs;
INSTALL ducklake;
INSTALL postgres_scanner;
INSTALL sqlite_scanner;

-- MSSQL is a DuckDB Community extension, not a core extension.
-- Its release tag is pinned separately in config/extensions.yml and the workflow.
INSTALL mssql FROM community;
