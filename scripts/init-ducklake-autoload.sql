-- DuckLake autoloading test: DuckLake is available, but HTTPFS must start unloaded.
-- The test disables autoloading and verifies that an S3 DATA_PATH fails until HTTPFS is installed from LOCAL_EXTENSION_REPO.
LOAD json;
LOAD tpch;
LOAD tpcds;
LOAD icu;
LOAD ducklake;
