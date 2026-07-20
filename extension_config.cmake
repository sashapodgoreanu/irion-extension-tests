# Only the local no-op QA extension is compiled.
duckdb_extension_load(qa_test
    SOURCE_DIR ${CMAKE_CURRENT_LIST_DIR}
)
