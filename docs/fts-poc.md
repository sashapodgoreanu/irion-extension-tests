# FTS compatibility POC

Questa prima prova costruisce un solo DuckDB test runner e vi registra i test SQLLogicTest originali di `duckdb/duckdb-fts`.

## Versioni fissate

- DuckDB: `v1.5.4`
- extension-ci-tools: `v1.5.4`
- duckdb-fts: `4fd54aa70a5079be7e9b6fab3b810ed90699b511`
- piattaforma: `linux_amd64`
- runner GitHub: `ubuntu-24.04`
- container: `extension-ci-tools/docker/linux_amd64`

## Cosa verifica

1. La CI scarica DuckDB, duckdb-fts ed extension-ci-tools ai riferimenti fissati.
2. Costruisce il container Linux ufficiale usato dalla pipeline delle estensioni DuckDB.
3. Configura DuckDB con `cmake/fts_all_loaded.cmake`.
4. Imposta `LINK_FTS_STATICALLY=ON` per collegare FTS a `duckdb` e `unittest`.
5. Imposta `LOAD_FTS_TESTS=LOAD_TESTS` per registrare i test upstream nel medesimo `unittest`.
6. Disabilita autoinstall e autoload, così la rete non può nascondere un'estensione mancante.
7. Esegue un pre-flight che carica insieme ICU e FTS e verifica `duckdb_extensions()`.
8. Elenca i test registrati e fallisce se non trova test sotto `test/sql/fts/`.
9. Esegue tutti i test upstream FTS usando `configs/fts_all_loaded.json`.
10. La configurazione esegue `LOAD icu; LOAD fts;` sia in `on_init` sia in `on_new_connection`.

## Avvio

Il workflow parte automaticamente quando viene effettuato un push sul branch:

```text
fts-ci-v1.5.4
```

Può anche essere avviato manualmente dalla scheda Actions tramite `workflow_dispatch`.

## Artifact

La CI pubblica l'artifact `fts-compatibility-report` contenente:

- metadati e SHA effettivi;
- log CMake;
- log della build;
- risultato del pre-flight;
- elenco dei test FTS registrati;
- output completo dei test.

## Passo successivo

Dopo la validazione di FTS, la stessa configurazione CMake verrà estesa con una seconda estensione. A quel punto i test originali di entrambe saranno eseguiti con entrambe caricate nello stesso processo DuckDB.
