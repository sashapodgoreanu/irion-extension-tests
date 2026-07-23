# Analisi di fattibilità: processo di validazione DuckDB ed estensioni

## Scopo del documento

Questo documento raccoglie l'analisi estesa a supporto del SAL. Il file `sal.md` rimane volutamente sintetico; questo file contiene il materiale di memoria e di approfondimento da cui ricavare `presentazione.md` e, successivamente, le slide PowerPoint.

L'obiettivo è valutare se il processo proposto sia adeguato per qualificare una nuova versione di DuckDB nell'Analytics Engine Irion e decidere dove far girare stabilmente tale processo: GitHub Actions oppure Telemaco DevOps.

## 1. Perché serve questo processo

L'esperienza sugli aggiornamenti DuckDB mostra che non è sicuro aggiornare "a occhio" basandosi solo sul fatto che DuckDB abbia pubblicato una nuova release. L'Analytics Engine non usa DuckDB isolatamente: lo usa insieme a un insieme di estensioni che devono essere installate, caricate e usate nello stesso runtime.

I rischi principali osservati sono:

- una nuova versione di DuckDB può essere disponibile prima che tutte le estensioni siano state aggiornate;
- un'estensione può rimanere ferma a un commit precedente e continuare comunque a essere distribuita per una versione DuckDB successiva;
- non esiste una garanzia funzionale esplicita che l'insieme delle estensioni usate da Irion funzioni correttamente in combinazione;
- il CI upstream delle singole estensioni tende a validare l'estensione nel proprio contesto, non necessariamente dentro la composizione completa Irion;
- più estensioni caricate insieme possono entrare in conflitto su funzioni, secret, filesystem, cataloghi, impostazioni o inizializzazioni globali;
- operazioni come `ATTACH`, `CREATE SECRET`, caricamento di filesystem remoti e uso di cataloghi multipli possono produrre problemi solo quando combinate.

Esempio concreto: è stato osservato che alcune sequenze di `ATTACH`, come MSSQL dopo PostgreSQL, possono rompersi o comportarsi in modo diverso in base all'ordine e al runtime già inizializzato. Questo riduce la confidenza nell'aggiornamento manuale e rende necessario un processo automatico e ripetibile.

Frase sintetica per la presentazione:

> Non dobbiamo validare solo DuckDB: dobbiamo validare la composizione DuckDB + tutte le estensioni Irion, caricata e usata come avviene realmente nell'Analytics Engine.

## 2. Compatibilità delle estensioni DuckDB: cosa risulta dalle fonti ufficiali

La documentazione DuckDB indica che le estensioni binarie sono legate sia alla versione specifica di DuckDB sia alla piattaforma. DuckDB dovrebbe rilevare automaticamente incompatibilità binarie e rifiutare il caricamento di un'estensione compilata per una versione o piattaforma differente.

La documentazione sulla versioning delle estensioni specifica inoltre che, quando le estensioni sono compilate, sono legate a una specifica versione DuckDB; per gli sviluppatori di estensioni questo implica la necessità di produrre nuovi binari quando viene rilasciata una nuova versione DuckDB.

La documentazione sull'installazione mostra anche che le estensioni vengono installate sotto una directory che include la versione DuckDB e la piattaforma, ad esempio:

```text
~/.duckdb/extensions/<duckdb_version>/<platform>/
```

Quindi, dal punto di vista ufficiale, l'unità di compatibilità binaria è la coppia:

```text
versione DuckDB + piattaforma
```

Quello che invece non emerge chiaramente dalla documentazione ufficiale è una regola di compatibilità semantica del tipo:

```text
un'estensione pubblicata per DuckDB 1.5.1 è sempre compatibile con DuckDB 1.5.4
```

L'osservazione pratica fatta nel POC è diversa e importante: in alcuni casi, per una versione DuckDB più recente, si ritrova lo stesso SHA/commit di estensione già usato da una versione precedente. Questo suggerisce che il repository delle estensioni può pubblicare, nella cartella della nuova versione DuckDB, un binario o una revisione dell'estensione non necessariamente avanzata rispetto alla release DuckDB precedente.

Conclusione operativa:

- non possiamo dedurre che tutte le estensioni siano avanzate solo perché DuckDB è avanzato;
- non possiamo dedurre compatibilità funzionale solo dalla presenza del binario nel repository;
- dobbiamo registrare per ogni release DuckDB il pin effettivo dei test upstream e la versione/commit effettiva dell'estensione installata;
- il processo deve testare la combinazione reale, non una combinazione teorica.

Per il SAL questa distinzione è centrale: DuckDB può installare un binario compatibile dal punto di vista del loader, ma resta da dimostrare che quel binario funzioni correttamente insieme alle altre estensioni Irion.

Fonti consultate:

- DuckDB, Installing Extensions: `https://duckdb.org/docs/stable/extensions/installing_extensions`
- DuckDB, Extension Distribution / Binary Compatibility: `https://duckdb.org/docs/current/extensions/extension_distribution`
- DuckDB, Versioning of Extensions: `https://duckdb.org/docs/extensions/versioning_of_extensions`
- DuckDB, Extensions Overview: `https://duckdb.org/docs/stable/extensions/overview`

## 3. Che cosa deve validare il processo

Il processo deve produrre evidenze su quattro livelli.

### 3.1 Runtime DuckDB

Verificare che la versione candidata di DuckDB sia compilabile e utilizzabile con:

- DuckDB CLI;
- runner `unittest`;
- piattaforma target;
- impostazioni di installazione e caricamento estensioni;
- artifact riproducibile.

Nel POC il runner `unittest` viene compilato perché non è distribuito come binario ufficiale ordinario; è necessario per eseguire i SQLLogicTest originali delle estensioni.

### 3.2 Test originali delle estensioni

Per ogni estensione usata da Irion, il processo deve:

1. fare checkout del repository originale dell'estensione;
2. usare un commit immutabile o una release taggata, mai `main`;
3. eseguire i SQLLogicTest originali o i test applicabili;
4. mantenere fixture e path relativi nel repository upstream;
5. installare e caricare tutte le estensioni Irion prima di eseguire la batteria;
6. raccogliere log, test saltati, test esclusi e test falliti.

Questo serve a rispondere alla domanda:

> I test originali dell'estensione continuano a passare quando l'estensione viene caricata insieme a tutte le altre estensioni Irion?

### 3.3 Test Irion cross-extension

Oltre ai test upstream, servono test scritti da Irion che usino in un'unica sessione più estensioni insieme.

Scenari minimi da coprire:

- più `ATTACH` nello stesso runtime;
- MSSQL + PostgreSQL + DuckLake;
- filesystem remoti e cataloghi;
- `CREATE SECRET` per provider differenti;
- sequenze di load intenzionali, per esempio Delta prima di Unity Catalog;
- query che attraversano cataloghi differenti;
- verifica di collisioni tra funzioni, impostazioni e nomi;
- test di apertura, chiusura, detach e riutilizzo.

Questa è la parte che più si avvicina all'uso reale dell'Analytics Engine.

### 3.4 Report finale

Ogni esecuzione deve produrre un rapporto con:

- versione DuckDB;
- commit DuckDB;
- versione `extension-ci-tools`;
- elenco estensioni installate;
- origine dei binari;
- versioni/commit rilevate con `duckdb_extensions()`;
- repository e pin dei test upstream;
- test scoperti;
- test eseguiti;
- test passati;
- test falliti;
- test esclusi con motivo;
- test non eseguibili per mancanza di servizi o credenziali;
- log dei servizi;
- problemi noti;
- valutazione finale: compatibile, compatibile con limitazioni, non compatibile, non valutabile.

## 4. Cosa dimostra il POC attuale

Il branch `001-httpfs-qa-infrastructure` dimostra che l'approccio è fattibile.

Il POC implementa:

- configurazione centrale in `config/extensions.yml`;
- build di DuckDB `v1.5.4` e `unittest`;
- artifact condiviso della build;
- matrice dinamica di batterie;
- checkout dei repository upstream a pin immutabili o release;
- installazione e caricamento congiunto delle estensioni;
- job separati e paralleli per le batterie;
- isolamento di `HOME`, temporanei e directory runtime;
- setup di servizi per alcune batterie;
- raccolta dei log come artifact.

Il set comune attualmente configurato comprende:

- `httpfs`;
- `mssql` da repository Community;
- `ducklake`;
- `postgres_scanner`;
- `icu`;
- `azure`;
- `delta`;
- `iceberg`;
- `unity_catalog`.

Le batterie presenti nel POC comprendono:

- HTTPFS;
- DuckLake;
- postgres_scanner;
- Delta;
- Iceberg;
- Azure;
- Unity Catalog;
- MSSQL.

Il POC è stato realizzato su GitHub Actions perché GitHub offre un ambiente rapido per:

- creare pipeline;
- generare job paralleli;
- usare runner Ubuntu pronti;
- scaricare repository GitHub upstream;
- pubblicare artifact;
- avviare container e servizi;
- iterare velocemente sul proof of concept.

## 5. Limiti del POC attuale

Il POC non è ancora il processo definitivo.

Mancano o sono da consolidare:

- test Irion cross-extension in una singola sessione DuckDB;
- report aggregato finale leggibile dal SAL;
- classificazione formale dei test esclusi o non eseguibili;
- integrazione dell'estensione Virtual File System interna;
- misurazione stabile di tempi, artifact, log e spazio richiesto;
- porting o spike su Telemaco DevOps;
- verifica della parallelizzazione on-premises;
- gestione completa delle credenziali e dei test cloud;
- policy di retention per build di qualificazione.

## 6. GitHub Actions: valutazione

### Vantaggi

- Il POC è già funzionante su GitHub.
- La creazione di pipeline e job paralleli è semplice.
- I runner sono effimeri e riducono il rischio di contaminazione tra esecuzioni.
- Il checkout dei repository DuckDB e delle estensioni è naturale.
- Artifact e log sono immediati.
- Per repository pubbliche i minuti standard sono gratuiti.

### Problemi

- Se il repository diventa privato, entrano in gioco quote e costi del piano GitHub.
- Il codice interno non accessibile da GitHub, come la Virtual File System, richiede una decisione specifica.
- I runner GitHub-hosted non vedono la rete Irion.
- I log e gli artifact finiscono su GitHub e devono essere valutati dal punto di vista della riservatezza.
- GitHub è una piattaforma esterna, quindi non è completamente sotto controllo Irion.

### Quote indicative da verificare contrattualmente

Dalla documentazione GitHub corrente:

- i repository pubblici possono usare GitHub Actions standard senza consumo di minuti a pagamento;
- per repository private sono previste quote mensili di minuti e storage in base al piano;
- il piano Free include 2.000 minuti/mese;
- i runner `ubuntu-24.04` standard per repository private hanno 2 CPU, 8 GB RAM e 14 GB SSD;
- la cache Actions è separata dagli artifact e ha propri limiti.

Questi dati devono comunque essere verificati rispetto al piano GitHub effettivo dell'organizzazione.

## 7. Telemaco DevOps: valutazione

Telemaco DevOps è la piattaforma interna e rappresenta l'opzione naturale per un processo stabile di qualificazione, soprattutto se devono essere inclusi repository e servizi non pubblici.

### Vantaggi

- Rimane tutto nella rete e nell'infrastruttura Irion.
- Può accedere ai repository interni, inclusa la Virtual File System.
- Non dipende da quote GitHub per repository private.
- Permette maggiore controllo su retention, artifact, log e sicurezza.
- È più coerente con un processo ufficiale interno di qualificazione.

### Problemi e incertezze

- Serve predisporre agenti Linux con Ubuntu 24.04 o equivalente.
- Bisogna verificare se e come eseguire Docker e Docker Compose sugli agenti.
- I container potrebbero non avere accesso corretto alla rete aziendale se l'IP non è registrato o se esistono policy interne.
- La gestione delle porte può essere problematica su agenti condivisi.
- La parallelizzazione deve essere verificata sulla versione installata di Telemaco DevOps.
- Su Azure DevOps Server on-premises non sono supportati i Pipeline Artifacts moderni: bisogna usare Build Artifacts o file share.
- Potrebbe essere necessario adattare il workflow GitHub a YAML/step di Telemaco DevOps.

### Parallelizzazione

Azure Pipelines supporta strategie `matrix` e `maxParallel`, ma la possibilità concreta dipende da:

- versione di Telemaco DevOps;
- numero di agenti disponibili;
- configurazione dell'agent pool;
- capacità degli host;
- possibilità di eseguire container e servizi in parallelo;
- isolamento delle porte e delle reti Docker.

La domanda pratica non è solo "si può scrivere una matrice?", ma:

> Possiamo eseguire in parallelo più batterie che avviano container, servizi e porte senza contaminarsi?

Se la risposta è sì, il porting è realistico. Se la risposta è no, il processo può comunque funzionare, ma con batterie serializzate e tempi più lunghi.

## 8. Container e rete aziendale

Il processo richiede container o servizi per alcune batterie, ad esempio:

- MinIO/S3 per HTTPFS;
- Squid per HTTPFS;
- PostgreSQL per `postgres_scanner` e DuckLake;
- SQL Server per MSSQL;
- eventuali servizi futuri per Iceberg, Unity Catalog, cataloghi REST o VFS.

Su GitHub questi servizi funzionano in runner effimeri isolati.

Su Telemaco DevOps bisogna capire:

- se Docker è disponibile sugli agenti;
- se i container possono raggiungere la rete aziendale;
- se gli IP dei container devono essere registrati;
- se serve proxy aziendale;
- se ci sono firewall o ACL;
- se i container possono esporre porte localmente;
- se più job paralleli possono usare porte diverse;
- se è preferibile usare agenti effimeri o agenti dedicati per job.

Questa parte deve essere validata con chi conosce l'infrastruttura, in particolare con Gianni.

## 9. Estensione Virtual File System

La Virtual File System è il punto più importante per la scelta della piattaforma.

Se il repository resta solo sui server Irion, GitHub-hosted non può accedervi. Le opzioni sono:

1. portare o replicare il codice VFS su GitHub private;
2. usare GitHub Actions con runner self-hosted nella rete Irion;
3. portare tutto il processo su Telemaco DevOps;
4. escludere temporaneamente la VFS dal POC, ma non dal processo definitivo.

Per una qualificazione completa dell'Analytics Engine, la VFS deve essere inclusa. Escluderla può andare bene solo nella fase POC.

## 10. Domande da portare al SAL

Il flusso della discussione deve portare a due domande principali.

### Domanda 1

> Il processo proposto è soddisfacente per qualificare DuckDB e le estensioni dell'Analytics Engine?

Punti da chiarire:

- validiamo la composizione completa, non solo singole estensioni;
- usiamo test upstream originali;
- aggiungiamo test Irion in singola sessione;
- produciamo un report ripetibile;
- trattiamo esplicitamente test esclusi e non eseguibili.

### Domanda 2

> Dove deve girare stabilmente questo processo: GitHub oppure Telemaco DevOps?

Punti da discutere:

- GitHub è più veloce e già dimostrato;
- Telemaco DevOps è più coerente con codice interno e rete aziendale;
- GitHub privato ha quote/costi;
- Telemaco richiede spike tecnico su container, rete, artifact e parallelismo;
- la VFS condiziona la scelta.

## 11. Raccomandazione operativa

La raccomandazione è non decidere solo in astratto.

Percorso suggerito:

1. mantenere GitHub come POC e implementazione di riferimento;
2. aggiungere i test Irion cross-extension;
3. misurare tempi, log, artifact e problemi reali;
4. fare uno spike Telemaco DevOps con 2-3 batterie rappresentative;
5. includere almeno una batteria con container e una con accesso a repository interno;
6. decidere la piattaforma definitiva dopo lo spike.

Criterio di successo dello spike Telemaco:

- build DuckDB una volta sola;
- artifact riusato dalle batterie;
- checkout dei pin upstream;
- almeno tre batterie eseguite;
- almeno un container avviato;
- log raccolti;
- accesso a repository interno verificato;
- parallelismo o serializzazione consapevole;
- nessun conflitto di porte o rete.

## 12. Messaggio finale per la presentazione

Il punto non è dimostrare che GitHub o Telemaco siano "migliori" in assoluto.

Il punto è decidere dove Irion vuole far vivere un processo di qualificazione che diventerà necessario ogni volta che si aggiorna DuckDB.

Messaggio chiave:

> Il POC dimostra che il processo è tecnicamente possibile. Ora dobbiamo decidere se renderlo un processo interno su Telemaco DevOps o mantenerlo su GitHub, sapendo che la scelta dipende soprattutto da codice interno, rete, container, costi e governance.
