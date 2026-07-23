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

Messaggio chiave:

> La validazione non deve dipendere dalla disponibilità di una postazione locale o da attività manuali difficili da ripetere.

Discussione:

- È condivisa l'esigenza di trasformare i controlli esistenti in un processo automatico e ripetibile?

---

## Slide 3 — Il problema osservato

# Aggiornare DuckDB non significa aggiornare tutto allo stesso modo

Ogni release DuckDB seleziona specifiche revisioni delle estensioni: una revisione può avanzare, restare invariata o essere semplicemente ricompilata per la nuova versione DuckDB e piattaforma.

La disponibilità del binario e il caricamento corretto non dimostrano che tutti gli scenari funzionali continuino a comportarsi correttamente: la combinazione effettiva deve essere registrata e sottoposta a test.

Messaggio chiave:

> Dobbiamo qualificare la combinazione effettiva: versione DuckDB, revisioni delle estensioni e loro utilizzo congiunto.

Discussione:

- Vogliamo registrare sempre versione DuckDB, pin upstream e versione effettiva di ogni estensione?

---

## Slide 4 — Compatibilità binaria vs compatibilità funzionale

# Caricabile non significa funzionalmente verificato

- DuckDB lega le estensioni binarie a una specifica versione e piattaforma.
- Il loader può rifiutare incompatibilità evidenti, ma non verifica query, `ATTACH`, secret, cataloghi o interazioni tra estensioni.
- Le estensioni possono seguire cicli indipendenti: anche una patch DuckDB può usare revisioni diverse o semplicemente ricompilare lo stesso sorgente.
- La compatibilità funzionale deve quindi essere dimostrata dai test.

Messaggio chiave:

> La compatibilità binaria è un prerequisito; l'esito funzionale deve essere verificato.

Discussione:

- Quale livello di evidenza serve per approvare un aggiornamento DuckDB?

---

## Slide 5 — Il rischio reale: estensioni insieme

# Il rischio nasce dalla composizione

- Un'estensione può buildare per la nuova versione DuckDB senza introdurre modifiche funzionali reali.
- Un'estensione può funzionare isolatamente e fallire quando viene caricata insieme alle altre.
- Possibili collisioni su funzioni, impostazioni, secret provider, filesystem e cataloghi.
- Sequenze di `ATTACH` multiple possono dipendere dallo stato già inizializzato della sessione.
- Anche l'ordine di caricamento può avere effetti sul comportamento.

Esempio da raccontare:

> Problemi osservati in sequenze di `ATTACH`, ad esempio MSSQL dopo PostgreSQL.

Messaggio chiave:

> Il rischio non è soltanto che un'estensione non si carichi: è che la composizione reale si comporti diversamente.

---

## Slide 6 — Cosa deve fare il processo

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

Messaggio chiave:

> Non stiamo proponendo solo nuovi test: stiamo proponendo una catena di evidenze per qualificare l'aggiornamento.

Discussione:

- Questo modello è sufficiente come base del processo SAL?

---

## Slide 7 — Cosa abbiamo dimostrato con il POC

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

Messaggio chiave:

> Il POC dimostra che il processo è tecnicamente possibile e che può essere automatizzato fuori dalla macchina locale.

---

## Slide 8 — Perimetro delle estensioni

# Set di estensioni di piattaforma da validare

Il runtime di validazione deve caricare il set di estensioni utilizzato dalla piattaforma:

- Delta;
- DuckLake;
- HTTPFS;
- Iceberg;
- PostgreSQL Scanner;
- Azure;
- Unity Catalog;
- MSSQL;
- Virtual File Provider;
- BigQuery.

Stato del POC:

- sono già configurate batterie per HTTPFS, DuckLake, PostgreSQL Scanner, Delta, Iceberg, Azure, Unity Catalog e MSSQL;
- Virtual File Provider e BigQuery devono essere integrati nel processo;
- non tutte le estensioni richiedono una batteria dedicata: alcune devono essere caricate e verificate soprattutto nei test congiunti.

Messaggio chiave:

> L'obiettivo non è testare dieci componenti separati, ma qualificare il set completo che verrà distribuito insieme.

---

## Slide 9 — Cosa manca

# Da POC a processo ufficiale

Da completare:

- test cross-extension in una singola sessione;
- integrazione Virtual File Provider e BigQuery;
- report aggregato per il SAL;
- misurazione tempi, dimensione artifact e log;
- classificazione test esclusi o non eseguibili;
- spike Telemaco DevOps;
- decisione sulla piattaforma stabile.

Messaggio chiave:

> Il POC è positivo, ma non è ancora il processo definitivo.

---

## Slide 10 — Domanda 1 al SAL

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

## Slide 11 — Dove far girare il processo?

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

## Slide 12 — GitHub Actions

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

## Slide 13 — Telemaco DevOps

# Telemaco DevOps: interno ma da verificare

Vantaggi:

- resta nella rete Irion;
- accesso ai repository interni;
- più adatto al Virtual File Provider;
- controllo su artifact, log e retention;
- coerente con un processo ufficiale interno.

Criticità:

- agenti Linux da predisporre;
- Docker e Docker Compose da verificare;
- container e rete aziendale;
- IP, proxy e firewall;
- parallelizzazione da provare;
- gestione artifact on-premises.

Discussione:

- Telemaco può garantire isolamento, rete e capacità di esecuzione sufficienti?

---

## Slide 14 — Container e rete

# Punto tecnico da chiarire

Il processo richiede servizi:

- MinIO/S3;
- Squid;
- PostgreSQL;
- SQL Server;
- eventuali cataloghi o servizi futuri.

Su Telemaco bisogna verificare:

- accesso alla rete aziendale dai container;
- IP registrati o non registrati;
- proxy e firewall;
- porte e nomi container quando più test sono eseguiti;
- agenti persistenti o effimeri;
- modalità di isolamento tra esecuzioni.

Messaggio chiave:

> Questa parte va validata con chi conosce l'infrastruttura, in particolare Gianni.

---

## Slide 15 — Virtual File Provider

# Il repository interno condiziona la scelta

Situazione:

- repository Virtual File Provider oggi interno;
- non raggiungibile dai runner GitHub-hosted;
- necessario per una validazione completa del set di piattaforma.

Opzioni:

1. portare o replicare il repository su GitHub private;
2. usare GitHub con runner self-hosted nella rete Irion;
3. usare Telemaco DevOps end-to-end;
4. escluderlo temporaneamente soltanto dal POC.

Messaggio chiave:

> Senza Virtual File Provider possiamo dimostrare il modello, ma non validare l'intera composizione distribuita.

---

## Slide 16 — Proposta di percorso

# Decisione pragmatica

Proposta:

1. mantenere GitHub come riferimento POC;
2. aggiungere test cross-extension;
3. integrare BigQuery e definire il percorso del Virtual File Provider;
4. misurare tempi, log e artifact;
5. fare uno spike su Telemaco DevOps;
6. includere container e repository interno nello spike;
7. decidere la piattaforma dopo evidenze concrete.

Messaggio chiave:

> Non decidiamo solo sulla carta: facciamo uno spike mirato su Telemaco.

---

## Slide 17 — Criterio successo spike Telemaco

# Cosa deve dimostrare lo spike

Minimo richiesto:

- build DuckDB una volta;
- artifact riusato;
- almeno tre batterie;
- almeno una batteria con container;
- almeno una batteria con repository interno;
- raccolta log anche in caso di errore;
- nessun conflitto di porte o runtime;
- parallelismo oppure serializzazione consapevole;
- tempi e consumo risorse misurati.

Decisione:

> Se lo spike passa, Telemaco diventa candidato concreto per il processo ufficiale.

---

## Slide 18 — Decisioni richieste

# Decisioni da chiudere

1. Il processo proposto è approvato come base?
2. Quali scenari cross-extension sono obbligatori?
3. GitHub resta POC o piattaforma candidata?
4. Facciamo uno spike su Telemaco DevOps?
5. Come integriamo Virtual File Provider e BigQuery?
6. Chi verifica rete e container su Telemaco?
7. Quale report serve per approvare un aggiornamento DuckDB?

Messaggio finale:

> Il POC ha risposto alla domanda tecnica: è possibile. Ora dobbiamo approvare il processo e decidere dove farlo vivere.
