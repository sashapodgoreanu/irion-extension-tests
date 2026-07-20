#define DUCKDB_EXTENSION_MAIN

#include "qa_test_extension.hpp"

namespace duckdb {

static void LoadInternal(ExtensionLoader &) {
}

void QaTestExtension::Load(ExtensionLoader &loader) {
    LoadInternal(loader);
}

std::string QaTestExtension::Name() {
    return "qa_test";
}

std::string QaTestExtension::Version() const {
#ifdef EXT_VERSION_QA_TEST
    return EXT_VERSION_QA_TEST;
#else
    return "";
#endif
}

} // namespace duckdb

extern "C" {

DUCKDB_CPP_EXTENSION_ENTRY(qa_test, loader) {
    duckdb::LoadInternal(loader);
}
}
