-- Shared initialization for every upstream test database.
-- These are official repository extensions; none is compiled by this project.
INSTALL json;
INSTALL tpch;
INSTALL icu;
INSTALL httpfs;
INSTALL ducklake;

LOAD json;
LOAD tpch;
LOAD icu;
LOAD httpfs;
LOAD ducklake;
