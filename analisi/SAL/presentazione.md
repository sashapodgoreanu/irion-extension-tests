# Presentazione SAL: validazione DuckDB ed estensioni

> Obiettivo: usare queste slide come traccia per una discussione, non come documento tecnico completo.

---

## Slide 1 — Titolo

# Processo di validazione DuckDB ed estensioni

Esigenza, processo proposto, risultati del POC e scelta della piattaforma di esecuzione.

Contesto:

- DuckDB viene utilizzato nell'Analytics Engine insieme a un insieme di estensioni;
- il POC ha verificato la fattibilità tecnica del processo;
- il SAL deve discutere se il processo è soddisfacente e dove deve essere eseguito stabilmente.

Messaggio orale:

> Non presentiamo solo un POC tecnico: presentiamo un processo da decidere e stabilizzare.

---

## Slide 2 — Perché siamo qui

# Perché serve un processo?

- Gli aggiornamenti DuckDB non sono sempre immediati.
- Nel tempo abbiamo provato a costruire diversi controlli e processi di test.
- Questi tentativi erano però limitati, poco ripetibili o legati alla singola macchina di sviluppo.
- La build di DuckDB e del runner `unittest` richiede risorse e tempo.
- Eseguire localmente tutte le batterie può occupare la macchina per molto tempo.
- Durante l'esecuzione lo sviluppatore non può usare normalmente la postazione per altre attività pesanti.
- Con l'aumento delle estensioni, dei servizi e dei test, l'esecuzione completa può durare ore.
- Il processo deve quindi essere automatizzato, ripetibile e spostato su un'infrastruttura dedicata.

Messaggio chiave:

> La validazione non deve dipendere dalla disponibilità di una postazione locale o da attività manuali difficili da ripetere.

Discussione:

- È condivisa l'esigenza di trasformare i controlli esistenti in un processo automatico e ripetibile?

---

## Slide 3 — Il problema osservato

# Aggiornare DuckDB non significa aggiornare tutto allo stesso modo

- Ogni release DuckDB seleziona specifiche revisioni delle estensioni.
- La revisione di un'estensione può avanzare oppure rimanere invariata rispetto alla release precedente.
- Lo stesso commit sorgente può essere ricompilato e distribuito per più versioni DuckDB.
- Anche quando lo SHA rimane uguale, il binario viene prodotto per la specifica versione DuckDB e piattaforma.
- La disponibilità del binario non dimostra che tutti gli scenari funzionali continuino a comportarsi correttamente.
- La combinazione effettiva deve quindi essere registrata e sottoposta a test.

Messaggio chiave:

> Dobbiamo qualificare la combinazione effettiva: versione DuckDB, revisioni delle estensioni e loro utilizzo congiunto.

Discussione:

- Vogliamo registrare sempre versione DuckDB, pin upstream e versione effettiva di ogni estensione?

---

## Slide 4 — Compatibilità binaria vs compatibilità funzionale

# Caricabile non significa funzionalmente verificato

- DuckDB lega le estensioni binarie a una specifica versione e piattaforma.
- Il loader può rifiutare binari costruiti per una versione o piattaforma incompatibile.
- Le estensioni possono però seguire cicli di rilascio indipendenti da DuckDB.
- Anche una patch DuckDB può utilizzare revisioni differenti delle estensioni.
- Il loader non verifica query, `ATTACH`, secret, cataloghi o interazioni tra estensioni.
- Questi comportamenti devono essere dimostrati dal processo di test.

Messaggio chiave:

> La compatibilità binaria è un prerequisito; l'esito funzionale deve essere verificato.

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

1. Preparare DuckDB, la CLI e `unittest` una sola volta.
2. Installare e caricare il set di estensioni di default utilizzato nell'Analytics Engine.
3. Eseguire un primo livello di test specifici per ciascuna estensione:
   - repository e pin originali;
   - test upstream della singola estensione;
   - tutte le estensioni di default comunque presenti nel runtime.
4. Eseguire un secondo livello di test cross-extension, simile a un end-to-end tecnico:
   - una singola sessione DuckDB;
   - più estensioni realmente utilizzate insieme;
   - `CREATE SECRET`, `ATTACH`, `SELECT`, `INSERT`, `UPDATE` e operazioni cross-catalog.
5. Conservare questi scenari come test di regressione e ampliarli ogni volta che viene individuato un nuovo problema.
6. Produrre un report di compatibilità con esiti, esclusioni, problemi noti e rischi residui.

Messaggio chiave:

> Un'unica build alimenta due livelli complementari: test originali delle estensioni e test congiunti della composizione.

Discussione:

- Questo modello a due livelli è soddisfacente come base del processo SAL?

---

## Slide 7 — Primo livello: test upstream

# Riutilizzare i test originali delle estensioni

Per ogni estensione:

- checkout del repository originale;
- pin immutabile o release pubblicata, mai `main`;
- esecuzione dei SQLLogicTest e degli altri test applicabili;
- fixture e path mantenuti nel repository upstream;
- tutte le estensioni di default installate e caricate prima della batteria;
- log, test falliti, esclusi o non eseguibili raccolti come evidenza.

Ogni batteria è separata, ma verifica la propria estensione mentre il resto della composizione è presente.

Domanda a cui risponde:

> I test originali dell'estensione passano ancora quando viene caricata insieme alle altre estensioni di piattaforma?

---

## Slide 8 — Secondo livello: test cross-extension

# I test che dobbiamo mantenere noi

Scenari in un'unica sessione DuckDB:

- caricamento dell'intero set di estensioni;
- più `CREATE SECRET` per provider differenti;
- più `ATTACH` nello stesso processo;
- MSSQL + PostgreSQL + DuckLake;
- HTTPFS, Azure, Delta, Iceberg e Unity Catalog;
- Virtual File Provider e BigQuery quando integrati;
- `SELECT`, `INSERT`, `UPDATE` e operazioni cross-catalog;
- verifica di collisioni, ordine di caricamento e stato globale.

Questa suite cresce nel tempo:

- ogni bug riproducibile diventa un test di regressione;
- ogni nuovo scenario critico viene aggiunto al processo;
- l'obiettivo non è coprire tutto subito, ma costruire progressivamente la confidenza necessaria.

Messaggio chiave:

> I test upstream verificano i componenti; i test cross-extension verificano che la composizione continui a funzionare insieme.

Discussione:

- Quali scenari congiunti sono obbligatori per dichiarare un aggiornamento accettabile?

---

## Slide 9 — Cosa abbiamo dimostrato con il POC

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

## Slide 10 — Perimetro delle estensioni

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

## Slide 11 — Cosa manca

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

## Slide 12 — Domanda 1 al SAL

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

## Slide 15 — Telemaco DevOps

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

## Slide 16 — Container e rete

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

## Slide 17 — Virtual File Provider

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

## Slide 18 — Proposta di percorso

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

## Slide 19 — Criterio successo spike Telemaco

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

## Slide 20 — Decisioni richieste

# Decisioni da chiudere

1. Il processo proposto a due livelli è approvato come base?
2. Quali scenari cross-extension sono obbligatori?
3. GitHub resta POC o piattaforma candidata?
4. Facciamo uno spike su Telemaco DevOps?
5. Come integriamo Virtual File Provider e BigQuery?
6. Chi verifica rete e container su Telemaco?
7. Quale report serve per approvare un aggiornamento DuckDB?

Messaggio finale:

> Il POC ha risposto alla domanda tecnica: è possibile. Ora dobbiamo approvare il processo e decidere dove farlo vivere.
