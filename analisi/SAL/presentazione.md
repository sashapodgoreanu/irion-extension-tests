# Presentazione SAL: validazione DuckDB ed estensioni

> Obiettivo: usare queste slide come traccia per una discussione, non come documento tecnico completo.

---

## Slide 1 — Titolo

# Processo di validazione DuckDB ed estensioni

Esigenza, processo proposto, risultati del POC e scelta della piattaforma di esecuzione.

Contesto:

- DuckDB viene utilizzato nell'Analytics Engine insieme a un insieme di estensioni;
- tramite un POC abbiamo verificato la fattibilità tecnica del processo;
- il SAL deve discutere se il processo è soddisfacente e dove deve essere eseguito stabilmente.

---

## Slide 2 — Perché siamo qui

# Perché serve un processo?

- Gli aggiornamenti DuckDB richiedono una validazione ripetibile, non soltanto prove manuali.
- Nel tempo abbiamo provato controlli diversi, ma erano limitati o legati alla singola macchina di sviluppo.
- Build di DuckDB, `unittest`, container e batterie di test possono occupare la postazione per molto tempo.
- Con l'aumento di estensioni, servizi e scenari, l'esecuzione completa può durare ore.
- Serve quindi un processo automatizzato, rieseguibile e spostato su infrastruttura dedicata.

Discussione:

- È condivisa l'esigenza di trasformare i controlli esistenti in un processo automatico e ripetibile?

---

## Slide 3 — Il problema osservato

# Aggiornare DuckDB non significa aggiornare tutto allo stesso modo

Ogni release DuckDB seleziona specifiche revisioni delle estensioni: una revisione può avanzare, restare invariata o essere semplicemente ricompilata per la nuova versione DuckDB e piattaforma.

La disponibilità del binario e il caricamento corretto non dimostrano che tutti gli scenari funzionali continuino a comportarsi correttamente: la combinazione effettiva deve essere registrata e sottoposta a test.

La compatibilità binaria è un prerequisito; l'esito funzionale deve essere dimostrato dal processo di test.

Discussione:

- Vogliamo registrare sempre versione DuckDB, pin upstream e versione effettiva di ogni estensione?

---

## Slide 4 — Il rischio reale: estensioni insieme

# Il rischio nasce dalla composizione

- Un'estensione può buildare per la nuova versione DuckDB senza introdurre modifiche funzionali reali.
- Un'estensione può funzionare isolatamente e fallire quando viene caricata insieme alle altre.
- Possibili collisioni su funzioni, impostazioni, secret provider, filesystem e cataloghi.
- Sequenze di `ATTACH` multiple possono dipendere dallo stato già inizializzato della sessione.
- Anche l'ordine di caricamento può avere effetti sul comportamento.

Esempio da raccontare:

> Problemi osservati in sequenze di `ATTACH`, ad esempio MSSQL dopo PostgreSQL.

---

## Slide 5 — Cosa deve fare il processo

# Processo proposto

Il processo deve produrre evidenze su tre livelli:

1. **Preparare un runtime ripetibile**: DuckDB, CLI, `unittest`, versioni, pin e set di estensioni di piattaforma.
2. **Verificare le estensioni nel contesto comune**: riusare i test originali dove disponibili, ma con la composizione caricata.
3. **Validare la composizione**: aggiungere scenari cross-extension mantenuti da noi e farli crescere come regressione.

Output atteso:

- report di compatibilità;
- test falliti, esclusi o non eseguibili;
- problemi noti e rischi residui;
- evidenze per decidere se l'aggiornamento è accettabile.

Discussione:

- Questo modello è sufficiente come base del processo SAL?

---

## Slide 6 — Cosa abbiamo dimostrato con il POC

# POC su GitHub Actions

Realizzato:

- configurazione centrale `config/extensions.yml`;
- DuckDB `v1.5.4` + `unittest`;
- build eseguita una sola volta;
- artifact condiviso tra le batterie;
- matrice di job paralleli;
- checkout upstream a pin immutabili o release;
- installazione e caricamento congiunto delle estensioni;
- container e servizi per batterie specifiche;
- ambienti isolati e raccolta dei log.

Perché GitHub:

- rapidità di realizzazione del POC;
- runner Ubuntu già disponibili;
- gestione semplice di job, container, artifact e log;
- repository DuckDB ed estensioni già presenti sulla piattaforma.

---

## Slide 7 — Perimetro delle estensioni

# Set di estensioni di piattaforma da validare

Il runtime di validazione deve caricare il set di estensioni utilizzato dalla piattaforma:

> Delta; DuckLake; HTTPFS; Iceberg; PostgreSQL Scanner; Azure; Unity Catalog; MSSQL; Virtual File Provider; BigQuery.

Stato del POC:

- sono già configurate batterie per HTTPFS, DuckLake, PostgreSQL Scanner, Delta, Iceberg, Azure, Unity Catalog e MSSQL;
- Virtual File Provider e BigQuery devono essere integrati nel processo;
- non tutte le estensioni richiedono una batteria dedicata: alcune devono essere caricate e verificate soprattutto nei test congiunti.

---

## Slide 8 — Cosa manca

# Da POC a processo ufficiale

Da completare:

- test cross-extension in una singola sessione;
- integrazione Virtual File Provider e BigQuery;
- report aggregato per il SAL;
- misurazione tempi, dimensione artifact e log;
- classificazione test esclusi, parziali o non eseguibili;
- accesso a piattaforme reali per i test oggi coperti solo in parte;
- spike Telemaco DevOps;
- decisione sulla piattaforma stabile.

Nota sui test parziali:

- alcune batterie, come Iceberg, Delta/Unity Catalog e HTTPFS, possono eseguire solo una parte dei test senza account o servizi esterni;
- MinIO copre scenari S3-like locali, ma non sostituisce completamente un provider cloud S3 reale;
- per completare la validazione serviranno credenziali, account o ambienti dedicati sulle piattaforme per cui le estensioni sono state create.

---

## Slide 9 — Domanda 1 al SAL

# Il processo è soddisfacente?

Proposta:

- test originali e upstream dove applicabili;
- estensioni di piattaforma caricate congiuntamente;
- pin immutabili e versioni effettive registrate;
- test cross-extension in singola sessione;
- suite di regressione incrementale;
- report con problemi, esclusioni e rischi.

Decisione richiesta:

> Confermiamo questo processo come base della validazione degli aggiornamenti DuckDB?

---

## Slide 10 — Dove far girare il processo?

# GitHub o Telemaco DevOps?

La domanda successiva è organizzativa e infrastrutturale.

Opzioni principali:

- continuare su GitHub Actions;
- portare il processo su Telemaco DevOps.

Valutato e scartato:

- GitHub Actions con runner self-hosted Irion.

Discussione:

- Quale piattaforma è più adatta per eseguire stabilmente il processo?

---

## Slide 11 — GitHub Actions

# GitHub: veloce e già dimostrato

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

Discussione:

- GitHub può essere piattaforma stabile o deve restare solamente l'ambiente del POC?

---

## Slide 12 — Telemaco DevOps

# Telemaco DevOps: interno ma da verificare

Vantaggi:

- resta nella rete Irion;
- accesso ai repository interni;
- accesso al repository interno del Virtual File Provider e ai log associati;
- controllo su log, retention e processo ufficiale;
- coerente con un processo aziendale interno.

Criticità:

- macchine runner da predisporre;
- Docker e Docker Compose da verificare;
- container Linux per build e test della prima fase;
- container e rete aziendale;
- IP, proxy e firewall;
- parallelizzazione da provare;
- adattamento del workflow rispetto al POC GitHub.

Discussione:

- Telemaco può garantire isolamento, rete e capacità di esecuzione sufficienti?

---

## Slide 13 — Container e rete

# Punto tecnico da chiarire

Il processo richiede servizi:

- MinIO/S3;
- Squid;
- PostgreSQL;
- SQL Server;
- eventuali cataloghi o servizi futuri.

Sulle macchine runner bisogna verificare:

- esecuzione dei container Linux di test;
- accesso alla rete aziendale dai container;
- IP registrati o non registrati;
- proxy e firewall;
- porte e nomi container quando più test sono eseguiti;
- agenti persistenti o effimeri;
- modalità di isolamento tra esecuzioni.

---

## Slide 14 — Virtual File Provider

# Il repository interno condiziona la scelta

Situazione:

- repository Virtual File Provider oggi interno;
- non raggiungibile dai runner GitHub-hosted;
- necessario per una validazione completa del set di piattaforma.

Opzioni realistiche:

1. portare o replicare il repository su GitHub private;
2. usare Telemaco DevOps end-to-end;

---

## Slide 15 — Criterio successo spike Telemaco

# Cosa deve dimostrare lo spike

Minimo richiesto:

- build DuckDB una volta;
- artifact riusato;
- almeno tre batterie;
- almeno una batteria con container Linux;
- almeno una batteria con repository interno;
- raccolta log anche in caso di errore;
- nessun conflitto di porte o runtime;
- parallelismo oppure serializzazione consapevole;
- tempi e consumo risorse misurati.

Decisione:

> Se lo spike passa, Telemaco diventa candidato concreto per il processo ufficiale.

---

## Slide 16 — Decisioni richieste

# Decisioni da chiudere

1. Il processo proposto è approvato come base?
2. Quali scenari cross-extension sono obbligatori?
3. GitHub resta piattaforma candidata o si procede verso Telemaco DevOps?
4. Facciamo uno spike su Telemaco DevOps?
5. Come includiamo il Virtual File Provider nel processo?
6. Chi verifica rete e container sulle macchine runner?
7. Quale report serve per approvare un aggiornamento DuckDB?

Messaggio finale:

> Il POC ha risposto alla domanda tecnica: è possibile. Ora dobbiamo approvare il processo e decidere dove farlo vivere.

---

## Slide 17 — Ambienti necessari e copertura Windows

# Lista della spesa per abilitare i test

**Infrastruttura runner**

- Macchine runner Windows o Linux; Docker/Compose; container Linux per build e test della prima fase; rete verso repository e provider; secret store; isolamento, log e cleanup.

**Servizi locali**

- MinIO + Squid + server HTTP; Azurite + Azure CLI; PostgreSQL 15/17; SQL Server 2022; catalogo REST Iceberg + MinIO; sidecar Quack; PgBouncer/TLS per la copertura estesa.

**Account cloud**

- AWS: S3, Glue e S3 Tables;
- Azure: Blob Storage, ADLS Gen2 e service principal;
- Databricks: workspace e Unity Catalog;
- per la matrice Iceberg completa: Cloudflare R2 e Snowflake Open Catalog;
- Azure SQL/Fabric per i test cloud MSSQL.

**Risorse e permessi**

- bucket, container, cataloghi, schemi e database dedicati, con permessi di lettura, scrittura, lista, cancellazione e cleanup.

**Copertura Windows**

- Fase 1: validazione Linux containerizzata, già dimostrata dal POC.
- Fase 2: smoke test e scenari cross-extension Windows nativi.
- I servizi di supporto possono restare in container Linux, ma DuckDB, `unittest` ed estensioni Windows devono essere eseguiti nativamente.

BigQuery è escluso da questo inventario.
