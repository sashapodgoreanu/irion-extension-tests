# Register duckdb-fts in the DuckDB build without linking it statically.
#
# duckdb-fts sets DONT_LINK by default in its extension_config.cmake. We keep
# that default intentionally: the compatibility runner must test the generated
# fts.duckdb_extension through INSTALL/LOAD, exactly as a deployed extension.
#
# We also do not use LOAD_FTS_TESTS. The original tests remain in the upstream
# repository and are supplied to DuckDB unittest through --test-dir.

include("${CMAKE_CURRENT_LIST_DIR}/../upstream/fts/extension_config.cmake")
