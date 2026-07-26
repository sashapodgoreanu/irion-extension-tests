# Presentazione SAL — validazione DuckDB ed estensioni

Questo file è la **source of truth** della presentazione. Ogni sezione `## Slide N` descrive una slide. Il titolo `#` è già il risultato del merge semantico di titolo e sottotitolo: non va ulteriormente concatenato dal generatore.

---

## Slide 1 — preservata nel modello

# Processo di validazione DuckDB ed estensioni

Esigenza, processo proposto, risultati del POC e scelta della piattaforma di esecuzione.

Contesto:

- DuckDB viene utilizzato nell'Analytics Engine insieme a un insieme di estensioni;
- tramite un POC abbiamo verificato la fattibilità tecnica del processo;
- il SAL deve valutare se il processo è soddisfacente e dove deve essere eseguito stabilmente.

---

## Slide 2

# Perché serve un processo di validazione DuckDB

- Gli aggiornamenti DuckDB richiedono una validazione ripetibile, non soltanto prove manuali.
- Nel tempo abbiamo provato controlli diversi, ma erano limitati o legati alla singola macchina di sviluppo.
- Build di DuckDB, `unittest`, container e batterie di test possono occupare la postazione per molto tempo.
- Con l'aumento di estensioni, servizi e scenari, l'esecuzione completa può durare ore.
- Serve quindi un processo automatizzato, rieseguibile e spostato su infrastruttura dedicata.

---

## Slide 3

# DuckDB ed estensioni non si aggiornano in blocco

Ogni release DuckDB seleziona specifiche revisioni delle estensioni: una revisione può avanzare, restare invariata o essere semplicemente ricompilata per la nuova versione DuckDB e piattaforma.

La disponibilità del binario e il caricamento corretto non dimostrano che tutti gli scenari funzionali continuino a comportarsi correttamente: la combinazione effettiva deve essere registrata e sottoposta a test.

La compatibilità binaria è un prerequisito; l'esito funzionale deve essere dimostrato dal processo di test.

---

## Slide 4

# La composizione delle estensioni crea il rischio

- Un'estensione può buildare per la nuova versione DuckDB senza introdurre modifiche funzionali reali.
- Un'estensione può funzionare isolatamente e fallire quando viene caricata insieme alle altre.
- Possibili collisioni su funzioni, impostazioni, secret provider, filesystem e cataloghi.
- Sequenze di `ATTACH` di cataloghi diversi possono causare problemi, ad esempio `ATTACH MSSQL` dopo PostgreSQL.
- Anche l'ordine di caricamento può avere effetti sul comportamento.

---

## Slide 5

# Il processo testa runtime e composizione

Il processo deve produrre evidenze su tre livelli:

1. **Preparare un runtime ripetibile**: DuckDB CLI, `unittest`, pin a commit specifico e set di estensioni della piattaforma.
2. **Verificare le estensioni nel contesto comune**: riusare i test originali dove disponibili, ma con il set di estensioni caricate.
3. **Validare la composizione**: aggiungere scenari cross-extension mantenuti da noi e farli crescere quando emergono regressioni o bug.

Output atteso:

- report di compatibilità;
- test falliti, esclusi o non eseguibili;
- problemi noti e rischi residui;
- evidenze per decidere se l'aggiornamento è accettabile.

---

## Slide 6

# Il POC GitHub Actions è fattibile

POC realizzato.

Perché GitHub Actions:

- rapidità di realizzazione del POC;
- runner Ubuntu già disponibili;
- gestione semplice di job, container, artifact e log;
- repository DuckDB ed estensioni già presenti sulla piattaforma.

---

## Slide 7

# Estensioni di piattaforma da validare

Il runtime di validazione deve caricare il set di estensioni utilizzato dalla piattaforma:

Delta; DuckLake; HTTPFS; Iceberg; PostgreSQL Scanner; Azure; Unity Catalog; MSSQL; Virtual File Provider; BigQuery.

Stato del POC:

- sono già configurate batterie per HTTPFS, DuckLake, PostgreSQL Scanner, Delta, Iceberg, Azure, Unity Catalog e MSSQL;
- Virtual File Provider e BigQuery devono essere integrati nel processo;
- non tutte le estensioni richiedono una batteria dedicata: alcune devono essere caricate e verificate soprattutto nei test congiunti, inclusa ICU.

---

## Slide 8

# Dal POC al processo ufficiale: cosa manca

- test cross-extension in una singola sessione;
- integrazione Virtual File Provider e BigQuery;
- report aggregato per il SAL;
- misurazione di tempi, dimensione degli artifact e log;
- classificazione dei test esclusi, parziali o non eseguibili;
- accesso a piattaforme reali per i test oggi coperti solo in parte;
- spike Telemaco DevOps;
- decisione sulla piattaforma stabile.

Alcune batterie, come Iceberg, Delta/Unity Catalog e HTTPFS, possono eseguire solo una parte dei test senza account o servizi esterni. Per completare la validazione serviranno credenziali, account o ambienti dedicati.

---

## Slide 9

# Dove eseguire il processo?

La domanda successiva è organizzativa e infrastrutturale.

Opzioni principali:

- continuare su GitHub Actions;
- portare il processo su Telemaco DevOps.

Valutato e scartato: GitHub Actions con runner self-hosted Irion.

---

## Slide 10

# GitHub Actions è veloce e già dimostrato dal POC

Vantaggi:

- POC già funzionante;
- runner pronti ed effimeri;
- job paralleli semplici;
- artifact e log immediati;
- repository DuckDB già su GitHub;
- ideale per iterare velocemente.

Criticità:

- repository private con quote o costi;
- log e artifact fuori dalla rete Irion;
- Virtual File Provider interna non accessibile dai runner hosted;
- governance esterna.

---

## Slide 11

# Telemaco DevOps mantiene il processo interno

Vantaggi:

- resta nella rete Irion;
- accesso ai repository interni;
- accesso al repository interno del Virtual File Provider e ai log associati;
- controllo su log, retention e processo ufficiale;
- coerente con un processo aziendale interno.

---

## Slide 12

# Verifiche operative per Telemaco DevOps

Criticità:

- macchine runner da predisporre;
- Docker e Docker Compose da verificare;
- container Linux per build e test della prima fase;
- container e rete aziendale;
- IP, proxy e firewall;
- parallelizzazione da provare;
- adattamento del workflow rispetto al POC GitHub.

---

## Slide 13

# I runner devono garantire rete e isolamento

Il processo richiede servizi quali MinIO/S3, Squid, PostgreSQL, SQL Server ed eventuali cataloghi o servizi futuri.

Sulle macchine runner bisogna verificare:

- esecuzione dei container Linux di test;
- accesso alla rete aziendale dai container;
- IP registrati o non registrati;
- proxy e firewall;
- porte e nomi container quando più test sono eseguiti;
- agenti persistenti o effimeri;
- modalità di isolamento tra esecuzioni.

---

## Slide 14

# Il Virtual File Provider condiziona la scelta

Situazione:

- repository Virtual File Provider oggi interno;
- non raggiungibile dai runner GitHub-hosted;
- necessario per una validazione completa del set di piattaforma.

Opzioni realistiche:

1. portare o replicare il repository su GitHub private;
2. usare Telemaco DevOps end-to-end.

---

## Slide 15

# Servizi, account e permessi per i test

**Infrastruttura runner**

- macchine runner Windows o Linux; Docker/Compose; container Linux per build e test della prima fase;
- rete verso repository e provider; secret store; isolamento, log e cleanup.

**Servizi locali**

- MinIO, Squid e server HTTP; Azurite e Azure CLI; PostgreSQL 15/17; SQL Server 2022;
- catalogo REST Iceberg con MinIO; sidecar Quack; PgBouncer/TLS per la copertura estesa.

**Account cloud e permessi**

- AWS: S3, Glue e S3 Tables; Azure: Blob Storage, ADLS Gen2 e service principal; Databricks: workspace e Unity Catalog;
- per Iceberg: Cloudflare R2 e Snowflake Open Catalog; per MSSQL: Azure SQL/Fabric;
- bucket, container, cataloghi, schemi e database dedicati con permessi di lettura, scrittura, lista, cancellazione e cleanup.

---

## Slide 16

# La copertura Windows completa la validazione

- **Fase 1**: validazione Linux containerizzata, già dimostrata dal POC.
- **Fase 2**: smoke test e scenari cross-extension Windows nativi.
- I servizi di supporto possono restare in container Linux, ma DuckDB, `unittest` ed estensioni Windows devono essere eseguiti nativamente.
- BigQuery è escluso da questo inventario.
