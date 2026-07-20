# FTS compatibility POC

Questa prova costruisce soltanto DuckDB e il relativo executable `unittest`.

L'estensione FTS **non viene compilata da questo repository** e non viene collegata staticamente. Il binario ufficiale compatibile con DuckDB `v1.5.4` viene scaricato durante i test tramite:

```sql
INSTALL fts;
LOAD fts;
```

I SQLLogicTest originali restano nel repository `duckdb-fts` e vengono passati al runner tramite `--test-dir`.

## Versioni fissate

- DuckDB: `v1.5.4`
- extension-ci-tools: `v1.5.4`
- checkout dei test duckdb-fts: `4fd54aa70a5079be7e9b6fab3b810ed90699b511`
- piattaforma: `linux_amd64`
- runner GitHub: `ubuntu-24.04`
- container: `extension-ci-tools/docker/linux_amd64`

## Flusso verificato

```text
checkout DuckDB v1.5.4
        +
checkout duckdb-fts soltanto per test e fixture
        ↓
build DuckDB + unittest
        ↓
INSTALL fts
LOAD fts
        ↓
unittest --test-dir upstream/fts "test/sql/fts/*"
```

## Cosa verifica

1. La CI scarica DuckDB, i test di duckdb-fts ed extension-ci-tools ai riferimenti fissati.
2. Costruisce il container Linux ufficiale usato dalla pipeline delle estensioni DuckDB.
3. Configura e compila soltanto DuckDB e `unittest`.
4. Non passa a CMake alcun `SOURCE_DIR` relativo a FTS.
5. Non usa `DUCKDB_EXTENSION_CONFIGS` per FTS.
6. Non usa `LINK_FTS_STATICALLY`.
7. Non usa `LOAD_FTS_TESTS`.
8. Non usa `TEST_WITH_LOADABLE_EXTENSION=fts`.
9. Non costruisce il target `fts_loadable_extension`.
10. Fallisce se nella directory di build compare un file `fts.duckdb_extension` prodotto localmente.
11. Usa una HOME isolata per non riutilizzare estensioni già presenti sulla macchina.
12. Verifica che FTS non sia caricata prima dell'installazione.
13. Esegue `INSTALL fts; LOAD fts;` dal repository ufficiale DuckDB.
14. Controlla in `duckdb_extensions()` che FTS risulti installata, caricata e con `install_mode = repository`.
15. Conta i file `.test` e `.test_slow` presenti nel checkout upstream.
16. Esegue i test con:

```bash
build/release/test/unittest \
  --test-config configs/fts_all_loaded.json \
  --test-dir upstream/fts \
  "test/sql/fts/*"
```

La configurazione dei test esegue:

```sql
INSTALL fts;
LOAD fts;
```

prima dell'esecuzione di ogni test.

## Avvio

Il workflow parte automaticamente a ogni push sul branch:

```text
fts-ci-v1.5.4
```

## Artifact

La CI pubblica l'artifact `fts-compatibility-report` contenente:

- metadati e SHA effettivi;
- log CMake;
- log della build DuckDB;
- risultato del pre-flight `INSTALL/LOAD`;
- inventario dei test upstream;
- output completo di `unittest`.

## Passo successivo

Dopo la validazione di FTS, il file JSON potrà eseguire `INSTALL` e `LOAD` di più estensioni ufficiali. Le cartelle dei test upstream verranno quindi passate separatamente allo stesso executable `unittest` tramite `--test-dir`, senza compilare le estensioni nel repository Irion.
