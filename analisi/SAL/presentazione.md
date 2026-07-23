# Presentazione SAL: validazione DuckDB ed estensioni

> Obiettivo: usare queste slide come traccia per una discussione, non come documento tecnico completo.

---

## Slide 1 — Titolo

# Processo di validazione DuckDB ed estensioni

Qualificazione aggiornamenti DuckDB per Analytics Engine.

Messaggio orale:

> Non presentiamo solo un POC tecnico: presentiamo un processo da decidere e stabilizzare.

---

## Slide 2 — Perché siamo qui

# Perché serve un processo?

- DuckDB non viene usato da solo.
- Analytics Engine usa DuckDB insieme a più estensioni.
- Gli aggiornamenti DuckDB non sono sempre immediati.
- L'esito non può essere valutato solo "a occhio".

Messaggio chiave:

> Dobbiamo qualificare la composizione reale: DuckDB + estensioni Irion.

Discussione:

- È condivisa l'esigenza di avere un processo ripetibile?

---

## Slide 3 — Il problema osservato

# Aggiornare DuckDB non significa aggiornare tutto

- DuckDB può avanzare di versione.
- Alcune estensioni possono restare su commit precedenti.
- Un'estensione installabile non è automaticamente una garanzia funzionale.
- Non abbiamo trovato una regola ufficiale chiara di compatibilità funzionale tra minor release.

Messaggio chiave:

> Se DuckDB passa a una nuova versione, non possiamo assumere che tutte le estensioni siano avanzate o siano compatibili nella composizione Irion.

Discussione:

- Vogliamo registrare sempre pin, commit e versione effettiva delle estensioni?

---

## Slide 4 — Compatibilità binaria vs compatibilità funzionale

# Il binario può caricarsi, ma il comportamento va dimostrato

- DuckDB lega le estensioni binarie a versione e piattaforma.
- Il loader può bloccare incompatibilità evidenti.
- Ma il loader non dimostra che tutti gli scenari Analytics Engine funzionino.
- La compatibilità funzionale va testata.

Messaggio chiave:

> La compatibilità binaria è necessaria, ma non sufficiente.

Discussione:

- Quale livello di evidenza serve per approvare un aggiornamento DuckDB?

---

## Slide 5 — Il rischio reale: estensioni insieme

# Il rischio nasce dalla composizione

- Funzioni o impostazioni con nomi in collisione.
- Secret provider diversi nella stessa sessione.
- Filesystem e cataloghi caricati insieme.
- Sequenze di `ATTACH` multiple.
- Inizializzazioni globali e ordine di caricamento.

Esempio da raccontare:

> Problemi osservati in sequenze di `ATTACH`, ad esempio MSSQL dopo PostgreSQL.

Messaggio chiave:

> Un'estensione può funzionare da sola e fallire quando entra nella composizione reale.

---

## Slide 6 — Cosa deve fare il processo

# Processo proposto

1. Preparare DuckDB e `unittest` una sola volta.
2. Installare e caricare il set estensioni Irion.
3. Eseguire le batterie dei test upstream.
4. Eseguire test Irion cross-extension in una singola sessione.
5. Produrre un report di compatibilità.

Messaggio chiave:

> Build una volta, test paralleli, estensioni sempre caricate insieme.

Discussione:

- Questo modello è soddisfacente come base del processo SAL?

---

## Slide 7 — Test upstream

# Riutilizzare i test originali delle estensioni

- Checkout del repository originale.
- Pin immutabile o release, mai `main`.
- Esecuzione dei SQLLogicTest originali.
- Fixture e path restano nel repository upstream.
- Tutte le estensioni Irion vengono caricate prima dei test.

Domanda a cui risponde:

> I test originali passano ancora quando l'estensione gira nella composizione Irion?

---

## Slide 8 — Test Irion cross-extension

# I test che dobbiamo aggiungere noi

Scenari in un'unica sessione DuckDB:

- più `ATTACH` insieme;
- MSSQL + PostgreSQL + DuckLake;
- HTTPFS, Azure, Delta, Iceberg, Unity Catalog;
- `CREATE SECRET` multipli;
- query cross-catalog;
- verifica collisioni e ordine di load.

Messaggio chiave:

> I test upstream sono necessari, ma i test Irion coprono l'uso reale dell'Analytics Engine.

Discussione:

- Quali scenari cross-extension sono obbligatori per dichiarare un aggiornamento accettabile?

---

## Slide 9 — Cosa abbiamo dimostrato con il POC

# POC su GitHub Actions

Realizzato:

- configurazione centrale `config/extensions.yml`;
- DuckDB `v1.5.4` + `unittest`;
- artifact condiviso;
- batterie parallele;
- checkout upstream pinning;
- install/load congiunto delle estensioni;
- container e servizi per batterie specifiche;
- raccolta log.

Messaggio chiave:

> Il POC dimostra che il processo è tecnicamente possibile.

---

## Slide 10 — Batterie attuali

# Estensioni coperte dal POC

Batterie configurate:

- HTTPFS;
- DuckLake;
- postgres_scanner;
- Delta;
- Iceberg;
- Azure;
- Unity Catalog;
- MSSQL.

Baseline comune:

- httpfs, mssql, ducklake, postgres_scanner, icu, azure, delta, iceberg, unity_catalog.

Messaggio chiave:

> Il POC non testa una singola estensione: testa un runtime con più estensioni caricate insieme.

---

## Slide 11 — Cosa manca

# Da POC a processo ufficiale

Da completare:

- test Irion cross-extension;
- report aggregato per il SAL;
- integrazione Virtual File System;
- misurazione tempi/artifact/log;
- classificazione test esclusi o non eseguibili;
- spike Telemaco DevOps;
- decisione su piattaforma stabile.

Messaggio chiave:

> Il POC è positivo, ma non è ancora il processo definitivo.

---

## Slide 12 — Domanda 1 al SAL

# Il processo è soddisfacente?

Proposta:

- test ufficiali e upstream dove applicabili;
- estensioni caricate congiuntamente;
- pin immutabili;
- test Irion in singola sessione;
- report con problemi, esclusioni e rischi.

Decisione richiesta:

> Confermiamo questo processo come base della qualificazione DuckDB?

---

## Slide 13 — Dove far girare il processo?

# GitHub o Telemaco DevOps?

La domanda successiva è organizzativa e infrastrutturale.

Opzioni:

- continuare su GitHub Actions;
- usare GitHub Actions con runner self-hosted Irion;
- portare il processo su Telemaco DevOps;
- mantenere GitHub come POC e Telemaco come target ufficiale.

Messaggio chiave:

> La scelta dipende da codice interno, rete, container, costi e governance.

---

## Slide 14 — GitHub Actions

# GitHub: veloce e già dimostrato

Vantaggi:

- POC già funzionante;
- runner pronti;
- job paralleli semplici;
- artifact e log immediati;
- repository DuckDB già su GitHub;
- ideale per iterare velocemente.

Criticità:

- repository private con quote/costi;
- log e artifact fuori rete Irion;
- Virtual File System interna non accessibile dai runner hosted;
- governance esterna.

Discussione:

- GitHub può essere piattaforma stabile o solo POC?

---

## Slide 15 — Telemaco DevOps

# Telemaco DevOps: interno ma da verificare

Vantaggi:

- resta nella rete Irion;
- accesso a repository interni;
- più adatto a VFS;
- controllo su artifact, log e retention;
- coerente con processo ufficiale interno.

Criticità:

- agenti Linux da predisporre;
- Docker e Docker Compose da verificare;
- container e rete aziendale;
- IP/proxy/firewall;
- parallelizzazione da provare;
- gestione artifact on-premises.

Discussione:

- Telemaco può garantire isolamento e parallelismo sufficienti?

---

## Slide 16 — Container e rete

# Punto tecnico da chiarire

Il processo richiede servizi:

- MinIO/S3;
- Squid;
- PostgreSQL;
- SQL Server;
- eventuali cataloghi o servizi futuri.

Su Telemaco bisogna verificare:

- accesso rete aziendale dai container;
- IP registrati o non registrati;
- proxy e firewall;
- porte e nomi container in parallelo;
- agenti persistenti o effimeri.

Messaggio chiave:

> Questa parte va validata con chi conosce l'infrastruttura, in particolare Gianni.

---

## Slide 17 — Virtual File System

# La VFS condiziona la scelta

Situazione:

- repository VFS oggi interno;
- non raggiungibile dai runner GitHub-hosted;
- necessario per una qualificazione completa.

Opzioni:

1. portare/mirror VFS su GitHub private;
2. GitHub self-hosted runner in rete Irion;
3. Telemaco DevOps end-to-end;
4. escludere VFS solo nel POC.

Messaggio chiave:

> Senza VFS possiamo dimostrare il modello, ma non qualificare tutta la composizione Analytics Engine.

---

## Slide 18 — Proposta di percorso

# Decisione pragmatica

Proposta:

1. mantenere GitHub come riferimento POC;
2. aggiungere test Irion cross-extension;
3. misurare tempi, log e artifact;
4. fare uno spike su Telemaco DevOps;
5. includere container e repository interno nello spike;
6. decidere la piattaforma dopo evidenze concrete.

Messaggio chiave:

> Non decidiamo solo sulla carta: facciamo uno spike mirato su Telemaco.

---

## Slide 19 — Criterio successo spike Telemaco

# Cosa deve dimostrare lo spike

Minimo richiesto:

- build DuckDB una volta;
- artifact riusato;
- almeno tre batterie;
- almeno una batteria con container;
- almeno una batteria con repository interno;
- raccolta log;
- nessun conflitto di porte;
- parallelismo o serializzazione consapevole.

Decisione:

> Se lo spike passa, Telemaco diventa candidato concreto per il processo ufficiale.

---

## Slide 20 — Decisioni richieste

# Decisioni da chiudere

1. Il processo proposto è approvato come base?
2. GitHub resta POC o piattaforma candidata?
3. Facciamo spike su Telemaco DevOps?
4. Come trattiamo la Virtual File System?
5. Chi verifica rete/container su Telemaco?
6. Quali scenari Irion sono obbligatori?
7. Quale report serve per approvare un aggiornamento DuckDB?

Messaggio finale:

> Il POC ha risposto alla domanda tecnica: è possibile. Ora dobbiamo decidere dove far vivere il processo.
