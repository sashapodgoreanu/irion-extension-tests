# Memory SAL: processo test DuckDB ed estensioni

Questo file è una memoria di lavoro. Serve a conservare il ragionamento completo emerso nella preparazione del SAL. Non è pensato per essere presentato integralmente.

## Obiettivo della memoria

Conservare:

- motivazione del processo;
- esperienza maturata con i precedenti tentativi di test;
- rischi osservati negli aggiornamenti DuckDB;
- analisi della compatibilità delle estensioni;
- struttura del processo proposto;
- risultati del POC;
- inventario degli ambienti necessari per abilitare le batterie;
- decisioni ancora aperte;
- punti da portare in discussione.

## Contesto

Irion utilizza DuckDB nell'Analytics Engine insieme a un set di estensioni. L'aggiornamento di DuckDB non può essere considerato soltanto come l'aggiornamento di una libreria isolata, perché il runtime usa estensioni caricate insieme, cataloghi diversi, `ATTACH` verso sorgenti differenti, secret provider, filesystem remoti e funzionalità specifiche.

Il POC nel repository `irion-extension-tests`, branch `001-httpfs-qa-infrastructure`, dimostra che è possibile preparare DuckDB e `unittest`, eseguire batterie di test delle estensioni e caricare il set comune delle estensioni in ogni batteria.

## Perché serve il processo

Nel tempo sono stati provati diversi controlli e processi di test, ma erano limitati, poco automatizzati o legati alla macchina locale dello sviluppatore.

Il principale limite dell'esecuzione locale è operativo:

- è necessario compilare DuckDB e il runner `unittest`;
- la build e le batterie consumano CPU, memoria e spazio disco;
- durante l'esecuzione la postazione rimane sostanzialmente dedicata ai test;
- con l'aumento delle estensioni, dei container e degli scenari, l'esecuzione completa può durare ore;
- una procedura manuale è più difficile da ripetere nello stesso modo e da trasformare in evidenza condivisibile.

Il processo deve quindi essere automatico, ripetibile, eseguibile su infrastruttura dedicata, capace di raccogliere log e risultati e progressivamente estendibile.

Motivazione tecnica principale:

> Non basta verificare che DuckDB parta o che una singola estensione funzioni da sola. Deve essere qualificata la combinazione effettiva di DuckDB e delle estensioni distribuite insieme.

Osservazioni alla base del processo:

- gli aggiornamenti DuckDB non sono sempre immediati;
- le estensioni possono non aggiornarsi nello stesso momento di DuckDB;
- alcune estensioni possono restare sullo stesso commit sorgente per più release DuckDB;
- un binario installabile e caricabile non garantisce il comportamento funzionale;
- i test upstream delle singole estensioni non coprono automaticamente la composizione completa;
- più estensioni caricate insieme possono collidere;
- operazioni reali come più `ATTACH`, `CREATE SECRET`, accessi a filesystem remoti e cataloghi multipli devono essere validate insieme.

Esempio osservato: sequenze di `ATTACH`, per esempio MSSQL dopo PostgreSQL, possono comportarsi diversamente in base allo stato già inizializzato della sessione.

## Compatibilità delle estensioni DuckDB

### Conclusione tecnica

> Lo stesso commit sorgente di un'estensione può essere riutilizzato e ricompilato per più versioni DuckDB, ma ogni binario rimane legato alla specifica versione DuckDB e piattaforma per cui è stato prodotto.

Questo significa che non si tratta di una garanzia generale di retrocompatibilità binaria.

```text
stesso commit sorgente dell'estensione
+ build contro DuckDB v1.5.1
= binario per v1.5.1 e piattaforma target

stesso commit sorgente dell'estensione
+ build contro DuckDB v1.5.4
= binario distinto per v1.5.4 e piattaforma target
```

Non significa:

```text
binario costruito per DuckDB v1.5.1
caricato direttamente e garantito su DuckDB v1.5.4
```

DuckDB documenta che:

- le estensioni binarie distribuite sono legate a una specifica versione DuckDB e piattaforma;
- il loader rileva incompatibilità binarie evidenti e rifiuta binari prodotti per altre versioni o piattaforme;
- la directory di installazione contiene versione DuckDB e piattaforma;
- le estensioni out-of-tree possono avere un ciclo di rilascio indipendente da DuckDB;
- la compatibilità con una nuova release deve comunque essere verificata.

Fonti ufficiali:

- DuckDB — Versioning of Extensions: https://duckdb.org/docs/extensions/versioning_of_extensions
- DuckDB — Extension Distribution / Binary Compatibility: https://duckdb.org/docs/current/extensions/extension_distribution
- DuckDB — Installing Extensions: https://duckdb.org/docs/stable/extensions/installing_extensions
- DuckDB Community Extensions — Development and maintenance across releases: https://duckdb.org/community_extensions/development
- DuckDB — Extensions Overview: https://duckdb.org/docs/stable/extensions/overview

Esempi dei pin selezionati dalle release DuckDB:

- HTTPFS v1.5.1–v1.5.4:
  - https://github.com/duckdb/duckdb/blob/v1.5.1/.github/config/extensions/httpfs.cmake
  - https://github.com/duckdb/duckdb/blob/v1.5.2/.github/config/extensions/httpfs.cmake
  - https://github.com/duckdb/duckdb/blob/v1.5.3/.github/config/extensions/httpfs.cmake
  - https://github.com/duckdb/duckdb/blob/v1.5.4/.github/config/extensions/httpfs.cmake
- Delta v1.5.1–v1.5.4:
  - https://github.com/duckdb/duckdb/blob/v1.5.1/.github/config/extensions/delta.cmake
  - https://github.com/duckdb/duckdb/blob/v1.5.2/.github/config/extensions/delta.cmake
  - https://github.com/duckdb/duckdb/blob/v1.5.3/.github/config/extensions/delta.cmake
  - https://github.com/duckdb/duckdb/blob/v1.5.4/.github/config/extensions/delta.cmake

Conclusione operativa:

> La compatibilità binaria è un prerequisito. Il processo deve dimostrare la compatibilità funzionale della specifica combinazione di DuckDB, revisioni delle estensioni e scenari di utilizzo.

## Set di estensioni di piattaforma

Il perimetro comunicato comprende:

Delta; DuckLake; HTTPFS; Iceberg; PostgreSQL Scanner; Azure; Unity Catalog; MSSQL; Virtual File Provider; BigQuery.

Le batterie oggi configurate nel POC sono:

- HTTPFS;
- DuckLake;
- PostgreSQL Scanner;
- Delta;
- Iceberg;
- Azure;
- Unity Catalog;
- MSSQL.

Virtual File Provider e BigQuery non sono ancora batterie configurate. BigQuery è escluso dall'inventario degli ambienti riportato più avanti, come richiesto.

## Strategia di test

Il processo produce evidenze su tre livelli:

1. **Preparare un runtime ripetibile**: DuckDB, CLI, `unittest`, versione, pin e set di estensioni.
2. **Verificare le estensioni nel contesto comune**: riusare i test originali dove disponibili, con la composizione caricata.
3. **Validare la composizione**: aggiungere scenari cross-extension mantenuti da Irion e farli crescere come regressione.

Ogni esecuzione deve registrare:

- versione e commit DuckDB;
- versione `extension-ci-tools`;
- artifact utilizzato;
- estensioni installate e caricate;
- origine e versione delle estensioni;
- repository e pin dei test upstream;
- test scoperti, eseguiti, passati e falliti;
- test esclusi con motivo;
- test eseguiti parzialmente;
- test non eseguibili per mancanza di servizi o credenziali;
- log dei servizi;
- problemi noti e rischi residui;
- valutazione finale.

Possibili esiti:

```text
compatibile
compatibile con limitazioni
non compatibile
non valutabile
```

## Test parziali e piattaforme esterne

Alcuni test originali possono essere eseguiti soltanto in parte nel POC, perché la validazione completa richiede l'accesso alla piattaforma per cui l'estensione è stata creata.

MinIO e Azurite sono utili per test deterministici locali, ma non sostituiscono integralmente AWS S3, Azure Blob Storage, ADLS Gen2, Databricks, AWS Glue, S3 Tables o altri servizi reali. Un test che passa contro un emulatore dimostra il comportamento verso quell'ambiente compatibile, non automaticamente verso tutti i provider reali.

Classificazione da mantenere nel report:

```text
eseguito
eseguito parzialmente
escluso con motivazione
non eseguibile per mancanza di ambiente o credenziali
```

## Inventario degli ambienti necessari

### Perimetro e criterio dell'analisi

L'inventario seguente è costruito sui repository e sui pin configurati in `config/extensions.yml`:

| Batteria | Repository | Pin |
|---|---|---|
| HTTPFS | `duckdb/duckdb-httpfs` | `c3f215ab360f04dc3d3d5305fa81849c0121f111` |
| DuckLake | `duckdb/ducklake` | `d318a545571d7d46eb751fa2aa5f6f4389285d3c` |
| PostgreSQL Scanner | `duckdb/duckdb-postgres` | `8f813f9b9c9e52a9074a050a0be60f49160a6baa` |
| Delta | `duckdb/duckdb-delta` | `45c40878601b54b4188b09e08732fe0d576ad222` |
| Iceberg | `duckdb/duckdb-iceberg` | `e6fe0a4b28ed13f4a1ae5c7e12bad338c6fc13c7` |
| Azure | `duckdb/duckdb-azure` | `563589b2f24290a4dcdd4247eaedf2b544f9dbcd` |
| Unity Catalog | `duckdb/unity_catalog` | `d52a7ee8678a23a8e0f950e955b9ffa1df0c3395` |
| MSSQL | `hugr-lab/mssql-extension` | `v0.2.1` |

Per ogni batteria vengono distinti:

- **ambiente base**: necessario per eseguire la batteria locale o il perimetro oggi previsto dal POC;
- **copertura completa**: account, servizi o credenziali aggiuntivi richiesti dai test upstream cloud o da scenari provider-real;
- **variabili**: nomi degli environment e dei secret rilevati nei workflow e negli script del pin.

### Requisiti comuni delle macchine runner

Le macchine runner devono disporre di:

- Linux x86-64, con Ubuntu 24.04 come riferimento del POC;
- Docker Engine e Docker Compose;
- possibilità di avviare e rimuovere container, reti e volumi;
- accesso in uscita HTTPS verso GitHub, repository DuckDB, registry delle immagini, package manager e API cloud;
- possibilità di installare tool di supporto o immagini equivalenti;
- secret store centralizzato, separato dai file di configurazione;
- directory `HOME` e temporanee isolate per batteria;
- raccolta di log e artifact anche in caso di errore;
- cleanup obbligatorio di container, database, bucket, container Azure, cataloghi e schemi temporanei;
- DNS o modifica controllata di `/etc/hosts` per gli endpoint MinIO virtual-host style;
- gestione delle porte per consentire parallelismo senza collisioni.

Porte e servizi rilevati:

| Porta | Servizio |
|---:|---|
| 8008 | server HTTP Python per HTTPFS |
| 3128 / 3129 | Squid, anche con autenticazione |
| 9000 / 9001 | MinIO API e console |
| 10000–10002 | Azurite Blob, Queue e Table |
| 5432 | PostgreSQL |
| 6432 | PgBouncer, copertura estesa PostgreSQL Scanner |
| 1433 | SQL Server |
| 8181 | catalogo REST Iceberg locale |
| 19999 | sidecar Quack per DuckLake |
| 8878 | mitmproxy per alcuni test Iceberg cloud |

Tool di supporto:

- Python 3;
- Node.js e Azurite;
- Azure CLI;
- client PostgreSQL (`psql`, `pg_isready`);
- PgBouncer e OpenSSL per i test TLS estesi;
- Databricks CLI;
- `mitmproxy` per i test proxy Iceberg;
- `sqlcmd`, già disponibile nelle immagini SQL Server usate dal pin;
- un sistema di gestione dei secret, senza credenziali persistenti nei repository.

### HTTPFS

**Ambiente base**

- MinIO;
- Squid;
- server HTTP Python;
- alias DNS/`hosts` per `duckdb-minio.com` e i bucket virtual-host;
- bucket locali `test-bucket`, `test-bucket-2` e `test-bucket-public`;
- versioning sul bucket principale;
- utenti MinIO con permessi di lettura e scrittura;
- directory per persistent secret.

Variabili locali rilevate:

```text
S3_TEST_SERVER_AVAILABLE=1
AWS_DEFAULT_REGION=eu-west-1
AWS_ACCESS_KEY_ID=minio_duckdb_user
AWS_SECRET_ACCESS_KEY=minio_duckdb_user_password
DUCKDB_S3_ENDPOINT=duckdb-minio.com:9000
DUCKDB_S3_USE_SSL=false
HTTP_PROXY_PUBLIC=localhost:3128
TEST_PERSISTENT_SECRETS_AVAILABLE=true
PYTHON_HTTP_SERVER_URL=http://localhost:8008
PYTHON_HTTP_SERVER_DIR=<directory temporanea>
```

**Copertura provider-real**

Per aggiungere una validazione reale AWS S3 servono:

- account AWS dedicato ai test;
- principal IAM o credenziali temporanee;
- bucket e prefisso dedicati;
- regione definita;
- permessi `ListBucket`, lettura, scrittura, cancellazione e gestione dei test di versioning;
- possibilità di generare e usare URL prefirmati;
- lifecycle/cleanup dei dati creati;
- eventuale bucket pubblico o fixture pubblica per i test anonimi.

Secret/env standard:

```text
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_DEFAULT_REGION
AWS_SESSION_TOKEN
```

Il pin non definisce un nome generico per il bucket cloud Irion: bucket e prefisso dovranno essere introdotti nella configurazione dei test provider-real.

Fonti del pin:

- https://github.com/duckdb/duckdb-httpfs/blob/c3f215ab360f04dc3d3d5305fa81849c0121f111/.github/workflows/IntegrationTests.yml
- https://github.com/duckdb/duckdb-httpfs/blob/c3f215ab360f04dc3d3d5305fa81849c0121f111/scripts/set_s3_test_server_variables.sh
- https://github.com/duckdb/duckdb-httpfs/blob/c3f215ab360f04dc3d3d5305fa81849c0121f111/scripts/minio_s3.yml

### DuckLake

**Ambiente base**

- profilo SQLite, senza servizio esterno;
- PostgreSQL 15 per il catalogo `ducklakedb`;
- database e utente dedicati;
- filesystem temporaneo per i dati;
- estensioni `postgres_scanner`, `sqlite_scanner`, `httpfs` e dipendenze caricate.

Variabili PostgreSQL rilevate:

```text
PGHOST=127.0.0.1
PGPORT=5432
PGUSER=postgres
PGPASSWORD=postgres
PGDATABASE=ducklakedb
PGSSLMODE=disable
DUCKLAKE_CONNECTION=postgres:dbname=ducklakedb
```

**Copertura aggiuntiva upstream**

- sidecar Quack su `localhost:19999`;
- token di test Quack;
- estensione Quack disponibile nello stesso runtime;
- ambiente MinIO condiviso per i test DuckLake con data path S3.

Variabili/configurazione:

```text
DUCKLAKE_CONNECTION=quack:localhost:19999
QUACK_TEST_TOKEN=ducklake-test-token
S3_TEST_SERVER_AVAILABLE=1
```

`QUACK_TEST_TOKEN` è un nome consigliato per il processo Irion: nel pin upstream il token è espresso direttamente nella configurazione di test.

Fonti del pin:

- https://github.com/duckdb/ducklake/blob/d318a545571d7d46eb751fa2aa5f6f4389285d3c/.github/workflows/Catalogs.yml
- https://github.com/duckdb/ducklake/blob/d318a545571d7d46eb751fa2aa5f6f4389285d3c/test/configs/postgres.json
- https://github.com/duckdb/ducklake/blob/d318a545571d7d46eb751fa2aa5f6f4389285d3c/test/configs/quack.json
- https://github.com/duckdb/ducklake/blob/d318a545571d7d46eb751fa2aa5f6f4389285d3c/scripts/run_quack_tests.py

### PostgreSQL Scanner

**Ambiente base**

- PostgreSQL 17;
- utente e password di test;
- database iniziale `postgres`;
- database e fixture `postgresscanner` creati dagli script upstream;
- client `psql` e `pg_isready`.

Variabili:

```text
PGHOST=localhost
PGPORT=5432
PGUSER=postgres
PGPASSWORD=postgres
PGDATABASE=postgres
POSTGRES_TEST_DATABASE_AVAILABLE=1
POSTGRES_TEST_SLOW=1
PGSCANNERTMP_ABS_DIR_PREFIX=<directory temporanea>
LOCAL_EXTENSION_REPO=<repository locale delle estensioni>
```

**Copertura completa upstream**

- PostgreSQL con TLS;
- PgBouncer sulla porta 6432;
- certificato e chiave di test;
- `PGSSLMODE=require`;
- eventuale matrice PostgreSQL 14/17/18, se si vuole riprodurre l'intero perimetro upstream e non soltanto il profilo del POC.

Fonte del pin:

- https://github.com/duckdb/duckdb-postgres/blob/8f813f9b9c9e52a9074a050a0be60f49160a6baa/.github/workflows/IntegrationTests.yml

### Delta

**Ambiente base locale**

- MinIO condiviso con HTTPFS;
- Azurite;
- Azure CLI per popolare i container locali;
- container Azurite `delta-testing-private` e `delta-testing-public`;
- dati generati e golden table necessari alle suite applicabili.

Variabili MinIO:

```text
S3_TEST_SERVER_AVAILABLE=1
DUCKDB_MINIO_TEST_SERVER_AVAILABLE=1
AWS_ACCESS_KEY_ID=minio_duckdb_user
AWS_SECRET_ACCESS_KEY=minio_duckdb_user_password
AWS_DEFAULT_REGION=eu-west-1
AWS_ENDPOINT=http://duckdb-minio.com:9000
```

Variabili Azurite:

```text
AZURE_STORAGE_CONNECTION_STRING=<connection string Azurite>
AZ_STORAGE_ACCOUNT=devstoreaccount1
AZ_DATA_DIR=delta-testing-private
AZ_TEMP_DIR=<prefisso scrivibile>
```

Fixture opzionali:

```text
GENERATED_DATA_AVAILABLE=1
GOLDEN_TABLES_PATH=<directory delle golden table>
```

**Copertura Azure reale**

- subscription Azure dedicata ai test;
- Storage Account Blob e, se richiesto dagli scenari, account ADLS Gen2;
- container privato scrivibile;
- container pubblico per i test anonimi;
- service principal con permessi di lettura, scrittura, lista e cancellazione;
- Azure CLI o access token;
- cleanup dei blob e dei prefissi temporanei.

Secret/env:

```text
AZURE_TENANT_ID
AZURE_CLIENT_ID
AZURE_CLIENT_SECRET
AZURE_ACCESS_TOKEN
AZURE_STORAGE_ACCOUNT
DUCKDB_AZ_CLI_LOGGED_IN=1
DUCKDB_AZURE_PUBLIC_CONTAINER_AVAILABLE=1
```

Fonti del pin:

- https://github.com/duckdb/duckdb-delta/blob/45c40878601b54b4188b09e08732fe0d576ad222/.github/workflows/LocalTesting.yml
- https://github.com/duckdb/duckdb-delta/blob/45c40878601b54b4188b09e08732fe0d576ad222/.github/workflows/CloudTesting.yml
- https://github.com/duckdb/duckdb-delta/blob/45c40878601b54b4188b09e08732fe0d576ad222/scripts/env_minio
- https://github.com/duckdb/duckdb-delta/blob/45c40878601b54b4188b09e08732fe0d576ad222/scripts/upload_test_files_to_azurite.sh

### Iceberg

La batteria del POC esegue oggi `test/sql/local/*`. La copertura completa del repository è molto più ampia.

**Ambiente locale completo**

- catalogo Apache Iceberg REST fixture sulla porta 8181;
- MinIO sulla porta 9000;
- bucket/warehouse `s3://warehouse/`;
- credenziali locali;
- rete Docker condivisa tra catalogo REST e MinIO.

Configurazione locale rilevata:

```text
AWS_ACCESS_KEY_ID=admin
AWS_SECRET_ACCESS_KEY=password
AWS_REGION=us-east-1
CATALOG_WAREHOUSE=s3://warehouse/
CATALOG_IO__IMPL=org.apache.iceberg.aws.s3.S3FileIO
CATALOG_S3_ENDPOINT=http://minio:9000
```

**Copertura AWS reale**

Servono:

- account AWS dedicato;
- bucket S3 per dati e metadata;
- catalogo AWS Glue Iceberg;
- bucket/catalogo AWS S3 Tables;
- IAM con permessi di lista, lettura, scrittura, cancellazione, creazione/rimozione namespace e tabelle;
- regioni coerenti con i cataloghi;
- risorse dedicate che possano essere create, modificate e ripulite dai test.

Secret/env:

```text
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_DEFAULT_REGION
ICEBERG_REMOTE_INSERT_READY=1
ICEBERG_AWS_REMOTE_AVAILABLE=1
```

Nel workflow upstream i secret sono denominati:

```text
S3_ICEBERG_TEST_USER_KEY_ID
S3_ICEBERG_TEST_USER_SECRET
S3_ICEBERG_TEST_USER_REGION
```

**Copertura Cloudflare R2**

- account R2;
- catalogo/bucket di test;
- token con permessi di creazione, lettura, scrittura e cancellazione.

```text
R2_TOKEN
```

**Copertura Snowflake Open Catalog**

- account Snowflake;
- Open Catalog o catalogo REST Iceberg dedicato;
- endpoint catalogo;
- credenziali client;
- utente, ruolo, database e PAT;
- storage sottostante S3 e/o GCS con credenziali dedicate;
- permessi di creare, modificare e rimuovere namespace e tabelle.

Variabili rilevate:

```text
SNOWFLAKE_KEY_ID_GCS
SNOWFLAKE_SECRET_KEY_GCS
SNOWFLAKE_KEY_ID_S3
SNOWFLAKE_SECRET_KEY_S3
SNOWFLAKE_CATALOG_URI_GCS
ICEBERG_CATALOG_CLIENT_ID
ICEBERG_CATALOG_CLIENT_SECRET
ICEBERG_CATALOG_ENDPOINT
SNOWFLAKE_USER
SNOWFLAKE_ROLE
SNOWFLAKE_DATABASE
SNOWFLAKE_ACCOUNT
SNOWFLAKE_PAT
ICEBERG_CATALOG_NAME
ICEBERG_CATALOG_REGION
ICEBERG_SNOWFLAKE_REMOTE_AVAILABLE=1
```

Per alcuni test serve anche `mitmproxy` sulla porta 8878.

Fonti del pin:

- https://github.com/duckdb/duckdb-iceberg/blob/e6fe0a4b28ed13f4a1ae5c7e12bad338c6fc13c7/scripts/docker-compose.yml
- https://github.com/duckdb/duckdb-iceberg/blob/e6fe0a4b28ed13f4a1ae5c7e12bad338c6fc13c7/.github/workflows/CloudTestingReusable.yml
- https://github.com/duckdb/duckdb-iceberg/blob/e6fe0a4b28ed13f4a1ae5c7e12bad338c6fc13c7/scripts/create_s3_insert_table.py

### Azure

**Ambiente locale**

- Azurite;
- Node.js;
- Azure CLI;
- Squid senza autenticazione sulla porta 3128;
- Squid con autenticazione sulla porta 3129;
- container/prefissi privati e scrivibili;
- persistent secret DuckDB.

Variabili Azurite rilevate:

```text
AZURE_STORAGE_CONNECTION_STRING=<connection string Azurite>
HTTP_PROXY_RUNNING=1
AZ_STORAGE_ACCOUNT=devstoreaccount1
AZ_DATA_DIR=testing-private
AZ_TEMP_DIR=writes
DUCKDB_AZURE_PERSISTENT_SECRET_AVAILABLE=1
```

**Copertura Azure reale**

- subscription e tenant Azure;
- service principal;
- Storage Account Blob;
- account ADLS Gen2 con hierarchical namespace per i test ABFSS;
- container privato per letture e scritture;
- container pubblico per accesso anonimo;
- prefisso temporaneo per ogni esecuzione;
- Azure CLI e possibilità di emettere access token;
- permessi di lettura, scrittura, lista e cancellazione.

Secret/env:

```text
AZURE_TENANT_ID
AZURE_CLIENT_ID
AZURE_CLIENT_SECRET
AZURE_ACCESS_TOKEN
AZURE_AUTH_ENV=1
AZURE_PROVIDER=cloud
DUCKDB_AZ_CLI_LOGGED_IN=1
DUCKDB_AZURE_PUBLIC_CONTAINER_AVAILABLE=1
PUBLIC_AZ_STORAGE_ACCOUNT
DUCKDB_AZURE_PERSISTENT_SECRET_AVAILABLE=1
ABFSS_STORAGE_ACCOUNT
ABFSS_DATA_DIR
ABFSS_TEMP_DIR
AZ_STORAGE_ACCOUNT
AZ_DATA_DIR
AZ_TEMP_DIR
```

Fonti del pin:

- https://github.com/duckdb/duckdb-azure/blob/563589b2f24290a4dcdd4247eaedf2b544f9dbcd/.github/workflows/LocalTesting.yml
- https://github.com/duckdb/duckdb-azure/blob/563589b2f24290a4dcdd4247eaedf2b544f9dbcd/.github/workflows/CloudTesting.yml
- https://github.com/duckdb/duckdb-azure/blob/563589b2f24290a4dcdd4247eaedf2b544f9dbcd/scripts/env_azure

### Unity Catalog

La copertura effettiva richiede una piattaforma Databricks reale con Unity Catalog.

**Ambiente richiesto**

- workspace Databricks;
- Unity Catalog abilitato;
- endpoint del workspace;
- token personale o credenziale equivalente per un service principal;
- regione;
- Databricks CLI;
- Python 3.12–3.14 e dipendenze per la generazione dei dati;
- catalogo con fixture leggibili;
- catalogo dedicato ai write test;
- schema temporaneo per esecuzione;
- permessi di creazione, lettura, scrittura e rimozione di schema e tabelle;
- possibilità di ripulire i dati al termine;
- accesso allo storage sottostante gestito da Databricks.

Secret/env:

```text
DATABRICKS_TOKEN
DATABRICKS_ENDPOINT
DATABRICKS_REGION
DATABRICKS_WRITE_TEST_CATALOG=duckdb_write_testing
DATABRICKS_WRITE_TEST_SCHEMA=<schema casuale per esecuzione>
RUN_WRITE_TESTS=1
```

Il dataset upstream usa anche cataloghi e schemi di fixture, per esempio `duckdb_testing.main` e un catalogo sorgente per copiare le tabelle dei write test.

Fonti del pin:

- https://github.com/duckdb/unity_catalog/blob/d52a7ee8678a23a8e0f950e955b9ffa1df0c3395/.github/workflows/CloudTesting.yml
- https://github.com/duckdb/unity_catalog/blob/d52a7ee8678a23a8e0f950e955b9ffa1df0c3395/Makefile
- https://github.com/duckdb/unity_catalog/blob/d52a7ee8678a23a8e0f950e955b9ffa1df0c3395/scripts/run_databricks_env

### MSSQL

**Ambiente base**

- container SQL Server 2022 Linux;
- accettazione EULA;
- password SA di test;
- porta 1433;
- database `master`;
- database e fixture `TestDB`;
- certificato server accettato dal client di test;
- cleanup del volume dopo l'esecuzione.

Variabili:

```text
ACCEPT_EULA=Y
MSSQL_SA_PASSWORD=<password di test>
MSSQL_TEST_HOST=localhost
MSSQL_TEST_PORT=1433
MSSQL_TEST_USER=sa
MSSQL_TEST_PASS=<password di test>
MSSQL_TEST_DB=master
MSSQL_TEST_DSN=<connection string>
MSSQL_TEST_URI=<URI>
MSSQL_TESTDB_DSN=<connection string TestDB>
MSSQL_TESTDB_URI=<URI TestDB>
MSSQL_TEST_SERVER=<connection string>
MSSQL_TEST_CONNECTION_STRING=<connection string>
```

**Copertura cloud opzionale del pin**

Il repository contiene anche test per Azure SQL Database e Fabric. Per abilitarli servono:

- server/database Azure SQL o ambiente Fabric dedicato;
- Entra ID application/service principal;
- DSN e host del database;
- permessi sul database di test.

Secret/env:

```text
AZURE_SQL_TEST_DSN
AZURE_APP_ID
AZURE_DIRECTORY_ID
AZURE_APP_SECRET
AZURE_SQL_DB_HOST
AZURE_SQL_DB
```

Fonti del pin:

- https://github.com/hugr-lab/mssql-extension/blob/v0.2.1/docker/docker-compose.yml
- https://github.com/hugr-lab/mssql-extension/blob/v0.2.1/docker/docker-compose.linux-ci.yml
- https://github.com/hugr-lab/mssql-extension/blob/v0.2.1/.github/workflows/ci.yml

## Lista della spesa consolidata

### Livello 1 — servizi locali riproducibili

Da predisporre sulle macchine runner:

- MinIO, riusabile da HTTPFS, Delta, DuckLake e Iceberg;
- Squid e server HTTP locale per HTTPFS;
- Azurite e Azure CLI per Azure e Delta;
- PostgreSQL 15 per DuckLake;
- PostgreSQL 17 per PostgreSQL Scanner;
- PgBouncer e TLS, se si vuole la copertura estesa PostgreSQL Scanner;
- SQL Server 2022 per MSSQL;
- catalogo REST Iceberg con MinIO warehouse;
- sidecar Quack per la copertura DuckLake aggiuntiva;
- gestione dinamica di porte, reti, volumi, nomi container e cleanup.

### Livello 2 — account cloud prioritari

Per validare i provider realmente utilizzati:

1. **AWS**
   - account di test;
   - IAM principal;
   - bucket S3 dedicato;
   - AWS Glue Iceberg;
   - AWS S3 Tables;
   - chiavi o credenziali temporanee e regione.

2. **Azure**
   - tenant/subscription;
   - service principal;
   - Blob Storage;
   - ADLS Gen2;
   - container privati, pubblici e prefissi temporanei;
   - eventuale Azure SQL/Fabric per la copertura MSSQL cloud.

3. **Databricks**
   - workspace;
   - Unity Catalog;
   - token/service principal;
   - catalogo fixture e catalogo scrivibile;
   - schema temporaneo per esecuzione.

### Livello 3 — matrice Iceberg estesa

Se si vuole riprodurre l'intera copertura cloud upstream:

- Cloudflare R2;
- Snowflake Open Catalog;
- storage S3/GCS associato;
- account, endpoint, token, ruoli e cataloghi dedicati.

### Requisiti trasversali di governance

- risorse dedicate esclusivamente ai test;
- privilegi minimi ma sufficienti per creare, leggere, scrivere e cancellare;
- segreti centralizzati e ruotabili;
- nessun secret nei repository o negli artifact;
- allowlist di rete, proxy e DNS definiti;
- prefisso/schema casuale per ogni esecuzione parallela;
- cleanup sempre eseguito, anche in caso di fallimento;
- retention di log e artifact;
- budget e alert sui costi cloud;
- proprietario nominativo per ogni account e piattaforma.

## Cosa è stato fatto nel POC

Il POC è stato realizzato su GitHub Actions per rapidità e disponibilità immediata delle risorse.

Dimostrato:

- configurazione centrale in `config/extensions.yml`;
- DuckDB `v1.5.4`;
- `extension-ci-tools` `v1.5.4`;
- build comune DuckDB + CLI + `unittest`;
- artifact condiviso;
- job paralleli;
- checkout upstream a pin;
- installazione e caricamento congiunto delle estensioni;
- isolamento di `HOME` e runtime;
- servizi per HTTPFS, PostgreSQL e SQL Server;
- raccolta log;
- repository configurabili senza hardcodare la matrice nel workflow.

## Cosa manca

- batteria cross-extension in singola sessione;
- integrazione Virtual File Provider;
- integrazione BigQuery;
- report aggregato per il SAL;
- misura reale di tempi, artifact, log e spazio;
- classificazione di test esclusi, parziali e non eseguibili;
- predisposizione degli ambienti locali mancanti;
- accesso alle piattaforme reali e gestione completa delle credenziali cloud;
- spike Telemaco DevOps;
- policy di retention;
- decisione su dove far girare il processo.

## GitHub: memoria argomenti

### Perché è stato usato

- POC veloce;
- workflow semplici;
- runner pronti ed effimeri;
- container e servizi facili;
- artifact e log gestiti;
- repository DuckDB già su GitHub;
- parallelizzazione immediata.

### Problemi

- se la repository diventa privata: quote o costi;
- repository pubblico non adatto a tutto il codice;
- Virtual File Provider interno non accessibile ai runner GitHub-hosted;
- log e artifact fuori dalla rete Irion;
- governance esterna.

### Runner self-hosted GitHub

Opzione valutata ma scartata:

- il progetto e la pipeline restano comunque su GitHub;
- l'esecuzione gira su macchine Irion;
- i runner dovrebbero essere configurati per accedere alla rete interna;
- senza configurazione di rete adeguata non potrebbero accedere al repository del Virtual File Provider o ad altre risorse interne;
- avrebbe comunque richiesto gestione infrastrutturale interna, senza spostare davvero il processo fuori da GitHub.

## Telemaco DevOps: memoria argomenti

### Perché considerarlo

- è interno;
- accede ai repository Irion;
- può accedere al repository del Virtual File Provider e ai log associati;
- è coerente con un processo ufficiale aziendale;
- consente controllo su retention, log e rete.

### Problemi e incertezze

- agenti Linux da predisporre;
- Docker e Docker Compose da verificare;
- container e rete aziendale;
- IP dei container forse non registrati;
- proxy e firewall;
- parallelizzazione;
- isolamento tra esecuzioni;
- gestione porte e nomi container;
- differenze tra GitHub Actions e Telemaco YAML;
- necessità di coinvolgere Gianni.

## Container e rete

Sulle macchine runner bisogna definire:

- accesso alla rete aziendale dai container;
- IP registrati o non registrati;
- proxy e firewall;
- porte e nomi container quando più test sono eseguiti;
- agenti persistenti o effimeri;
- modalità di isolamento tra esecuzioni;
- accesso ai repository interni;
- accesso alle API dei provider cloud.

Punto da verificare con chi gestisce l'infrastruttura:

> Qual è il modello corretto per far girare container di test che devono accedere alla rete aziendale dalle macchine runner di Telemaco DevOps?

## Virtual File Provider

Punto decisionale:

- oggi il repository è interno;
- GitHub-hosted non può raggiungerlo;
- per includerlo bisogna scegliere una strategia.

Opzioni realistiche:

1. portare o replicare il repository su GitHub private;
2. creare un mirror controllato su GitHub;
3. usare Telemaco DevOps end-to-end;
4. escluderlo temporaneamente solamente dal POC.

GitHub Actions con runner self-hosted in rete Irion è stato valutato ma scartato.

## Domande principali del SAL

### Prima domanda

> Il processo proposto è soddisfacente?

### Seconda domanda

> Dove deve girare questo processo?

Opzioni principali:

- GitHub Actions;
- Telemaco DevOps.

Opzione valutata ma scartata:

- GitHub Actions con runner self-hosted Irion.

## Decisioni da ottenere

- approvare o correggere il processo di validazione;
- definire gli scenari cross-extension obbligatori;
- approvare la lista degli ambienti e degli account da predisporre;
- definire quali provider reali sono obbligatori nella prima fase;
- nominare i responsabili degli account, dei secret e del cleanup;
- decidere se fare uno spike Telemaco DevOps;
- stabilire se GitHub resta piattaforma candidata o se si procede verso Telemaco;
- decidere come includere il Virtual File Provider;
- identificare chi verifica rete e container sulle macchine runner;
- definire il criterio minimo di successo dello spike.

## Criterio minimo di successo per Telemaco DevOps

Uno spike Telemaco è utile se dimostra:

- build DuckDB una volta;
- artifact riusato;
- almeno tre batterie;
- almeno una batteria con container;
- almeno una batteria con repository interno;
- log raccolti anche in caso di errore;
- nessun conflitto di porte o stato residuo;
- comportamento ripetibile;
- parallelizzazione oppure serializzazione consapevole;
- tempi e consumo risorse misurati.

## Formula conclusiva

> Il POC ha già risposto alla domanda tecnica: il processo è possibile. Il SAL deve ora approvare il modello di validazione, gli ambienti necessari e la piattaforma su cui renderlo stabile.
