# Build duckdb-fts as part of the same DuckDB binaries used by the test runner.
#
# duckdb-fts exposes two switches in its extension_config.cmake:
# - LINK_FTS_STATICALLY: removes DONT_LINK so FTS is linked into duckdb/unittest.
# - LOAD_FTS_TESTS: forwards LOAD_TESTS to duckdb_extension_load so the original
#   upstream SQLLogicTests are registered in the same unittest executable.

set(LINK_FTS_STATICALLY ON)
set(LOAD_FTS_TESTS LOAD_TESTS)

include("${CMAKE_CURRENT_LIST_DIR}/../upstream/fts/extension_config.cmake")
