# FTS compatibility POC

Questa prima prova costruisce DuckDB e il relativo executable `unittest`, ma mantiene FTS come estensione **dinamica**. I test SQLLogicTest originali restano nel repository `duckdb-fts` e vengono passati al runner tramite `--test-dir`.

## Versioni fissate

- DuckDB: `v1.5.4`
- extension-ci-tools: `v1.5.4`
- duckdb-fts: `4fd54aa70a5079be7e9b6fab3b810ed90699b511`
- piattaforma: `linux_amd64`
- runner GitHub: `ubuntu-24.04`
- container: `extension-ci-tools/docker/linux_amd64`

## Flusso reale verificato

```text
build DuckDB unittest
        +
build fts.duckdb_extension senza link statico
        ↓
pubblicazione nel repository locale build/release/repository
        ↓
INSTALL fts FROM '<repository locale>'
LOAD fts
        ↓
unittest --test-dir upstream/fts "test/sql/fts/*"
```

## Cosa verifica

1. La CI scarica DuckDB, duckdb-fts ed extension-ci-tools ai riferimenti fissati.
2. Costruisce il container Linux ufficiale usato dalla pipeline delle estensioni DuckDB.
3. Include `duckdb-fts/extension_config.cmake` lasciando attivo il suo `DONT_LINK` predefinito.
4. Non usa `LINK_FTS_STATICALLY`.
5. Non usa `LOAD_FTS_TESTS`: i test non vengono incorporati nel runner.
6. Compila `fts.duckdb_extension` e crea il repository locale DuckDB.
7. Compila `unittest` con `TEST_WITH_LOADABLE_EXTENSION=fts`, il supporto DuckDB per i test delle estensioni loadable.
8. Disabilita autoinstall e autoload dalla rete.
9. Verifica che FTS non sia già caricata prima di `INSTALL/LOAD`.
10. Esegue `INSTALL fts FROM '<repository locale>'; LOAD fts;` e controlla `duckdb_extensions()`.
11. Conta i file `.test` e `.test_slow` presenti nella cartella upstream.
12. Esegue i test con:

```bash
build/release/test/unittest \
  --test-config configs/fts_all_loaded.json \
  --test-dir upstream/fts \
  "test/sql/fts/*"
```

La configurazione dei test esegue esplicitamente:

```sql
INSTALL fts FROM '/duckdb_build_dir/build/release/repository';
LOAD fts;
```

prima dell'esecuzione di ogni test e dopo ogni riapertura della connessione gestita dal runner.

## Avvio

Il workflow parte automaticamente quando viene effettuato un push sul branch:

```text
fts-ci-v1.5.4
```

Può anche essere avviato manualmente dalla scheda Actions tramite `workflow_dispatch`.

## Artifact

La CI pubblica l'artifact `fts-compatibility-report` contenente:

- metadati e SHA effettivi;
- percorso della `.duckdb_extension` compilata;
- log CMake;
- log della build;
- risultato del pre-flight dinamico;
- inventario dei test upstream;
- output completo di `unittest`.

## Passo successivo

Dopo la validazione di FTS, la configurazione CMake potrà registrare altre estensioni con `DONT_LINK`. Il file JSON eseguirà `INSTALL` e `LOAD` di tutte le estensioni dinamiche, quindi ogni cartella di test upstream verrà passata separatamente allo stesso executable `unittest` tramite `--test-dir`.
