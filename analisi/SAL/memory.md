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
- decisioni ancora aperte;
- punti da portare in discussione;
- messaggi chiave da trasferire in `presentazione.md`.

## Contesto

Irion utilizza DuckDB nell'Analytics Engine insieme a un set di estensioni. L'aggiornamento di DuckDB non può essere considerato solo come l'aggiornamento di una libreria isolata, perché il runtime usa estensioni caricate insieme, cataloghi diversi, attach verso sorgenti differenti, secret provider, filesystem remoti e funzionalità specifiche.

Il POC nel repository `irion-extension-tests`, branch `001-httpfs-qa-infrastructure`, dimostra che è possibile preparare DuckDB e `unittest`, eseguire batterie di test delle estensioni e caricare il set comune delle estensioni in ogni batteria.

## Perché serve il processo

Nel tempo sono stati provati diversi controlli e processi di test, ma erano limitati, poco automatizzati o legati alla macchina locale dello sviluppatore.

Il principale limite dell'esecuzione locale è operativo:

- è necessario compilare DuckDB e il runner `unittest`;
- la build e le batterie consumano CPU, memoria e spazio disco;
- durante l'esecuzione la postazione rimane sostanzialmente dedicata ai test;
- lo sviluppatore non può usare normalmente la macchina per altre attività pesanti;
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

Esempio da ricordare in call:

- caso osservato di problemi con sequenze di `ATTACH`, per esempio MSSQL dopo PostgreSQL;
- questo mostra che non basta sapere che MSSQL funziona da solo e PostgreSQL funziona da solo;
- serve verificare il comportamento della stessa sessione con più estensioni già caricate e inizializzate.

Frase breve:

> Un'estensione può funzionare isolatamente e fallire quando entra nella composizione reale.

## Compatibilità delle estensioni DuckDB

### Conclusione tecnica

La formulazione corretta è:

> Lo stesso commit sorgente di un'estensione può essere riutilizzato e ricompilato per più versioni DuckDB, ma ogni binario rimane legato alla specifica versione DuckDB e piattaforma per cui è stato prodotto.

Questo significa che non si tratta di una garanzia generale di retrocompatibilità binaria.

Esempio concettuale:

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

### Che cosa documenta DuckDB

DuckDB documenta che:

- le estensioni binarie distribuite sono legate a una specifica versione DuckDB e piattaforma;
- il loader rileva incompatibilità binarie evidenti e rifiuta binari prodotti per altre versioni o piattaforme;
- la directory di installazione contiene versione DuckDB e piattaforma;
- le estensioni out-of-tree possono avere un ciclo di rilascio indipendente da DuckDB;
- le estensioni unstable possono modificare API e comportamento a ogni release;
- le estensioni Community vengono testate rispetto alla release stabile e, in preparazione della release successiva, anche rispetto al ramo DuckDB successivo;
- la compatibilità con il ramo successivo permette di anticipare i problemi, ma non costituisce una garanzia assoluta sulla futura release stabile.

Fonti ufficiali da mantenere:

- DuckDB — Versioning of Extensions: https://duckdb.org/docs/extensions/versioning_of_extensions
- DuckDB — Extension Distribution / Binary Compatibility: https://duckdb.org/docs/current/extensions/extension_distribution
- DuckDB — Installing Extensions: https://duckdb.org/docs/stable/extensions/installing_extensions
- DuckDB Community Extensions — Development and maintenance across releases: https://duckdb.org/community_extensions/development
- DuckDB — Extensions Overview: https://duckdb.org/docs/stable/extensions/overview

### Evidenza dai pin delle release DuckDB

Ogni release DuckDB può selezionare una specifica revisione sorgente di un'estensione out-of-tree.

Esempi ufficiali HTTPFS:

- DuckDB v1.5.1: https://github.com/duckdb/duckdb/blob/v1.5.1/.github/config/extensions/httpfs.cmake
- DuckDB v1.5.2: https://github.com/duckdb/duckdb/blob/v1.5.2/.github/config/extensions/httpfs.cmake
- DuckDB v1.5.3: https://github.com/duckdb/duckdb/blob/v1.5.3/.github/config/extensions/httpfs.cmake
- DuckDB v1.5.4: https://github.com/duckdb/duckdb/blob/v1.5.4/.github/config/extensions/httpfs.cmake

Esempi ufficiali Delta:

- DuckDB v1.5.1: https://github.com/duckdb/duckdb/blob/v1.5.1/.github/config/extensions/delta.cmake
- DuckDB v1.5.2: https://github.com/duckdb/duckdb/blob/v1.5.2/.github/config/extensions/delta.cmake
- DuckDB v1.5.3: https://github.com/duckdb/duckdb/blob/v1.5.3/.github/config/extensions/delta.cmake
- DuckDB v1.5.4: https://github.com/duckdb/duckdb/blob/v1.5.4/.github/config/extensions/delta.cmake

Questi file mostrano che il commit sorgente può cambiare tra release DuckDB, restare invariato in alcuni casi oppure essere ricompilato per la nuova versione DuckDB.

### Che cosa non dimostra il loader

Il caricamento corretto non dimostra automaticamente:

- che tutti i test originali passino nel nostro ambiente;
- che il comportamento sia identico alla release precedente;
- che tutte le funzioni utilizzate siano compatibili;
- che più estensioni non entrino in conflitto;
- che sequenze di `ATTACH`, secret, cataloghi e filesystem funzionino insieme;
- che una estensione Community o unstable sia funzionalmente stabile tra release.

Conclusione di memoria:

> La compatibilità binaria è un prerequisito. Il processo deve dimostrare la compatibilità funzionale della specifica combinazione di DuckDB, revisioni delle estensioni e scenari di utilizzo.

## Set di estensioni di piattaforma

Il perimetro comunicato per il processo comprende:

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

Non tutte le estensioni devono necessariamente avere una batteria upstream dedicata. Tutte devono però essere incluse nel runtime di validazione quando disponibili e devono comparire negli scenari cross-extension applicabili.

## Strategia di test

Il processo deve avere livelli distinti ma complementari.

### 1. Preparazione del runtime

Verificare:

- versione DuckDB;
- commit DuckDB;
- build CLI;
- build `unittest`;
- piattaforma;
- artifact condiviso;
- installazione delle estensioni;
- caricamento delle estensioni;
- origine, versione e commit effettivi.

DuckDB e `unittest` devono essere preparati una sola volta e riutilizzati dalle batterie successive.

### 2. Primo livello: test upstream delle estensioni

Per ogni estensione:

- checkout del repository originale;
- pin immutabile o release pubblicata;
- mai il branch `main`;
- esecuzione dei SQLLogicTest e degli altri test applicabili;
- mantenimento di fixture e path nel checkout originale;
- caricamento delle estensioni di default prima della batteria;
- raccolta di log, test falliti, saltati, esclusi o non eseguibili.

Ogni batteria verifica una specifica estensione, ma lo fa mentre il resto del set di piattaforma è presente nel runtime.

Domanda a cui risponde:

> I test originali dell'estensione passano ancora quando l'estensione viene caricata insieme alle altre estensioni di piattaforma?

### 3. Secondo livello: test cross-extension

Test mantenuti da Irion, nella stessa sessione DuckDB, per coprire:

- caricamento dell'intero set di estensioni;
- più `CREATE SECRET` per provider differenti;
- più `ATTACH` nello stesso processo;
- MSSQL + PostgreSQL + DuckLake;
- HTTPFS;
- Azure;
- Delta;
- Iceberg;
- Unity Catalog;
- Virtual File Provider;
- BigQuery;
- query cross-catalog;
- `SELECT`, `INSERT` e `UPDATE` dove supportati;
- sequenze di load;
- collisioni di funzioni, impostazioni o stato globale;
- apertura, detach e riutilizzo dei cataloghi.

Questi test sono assimilabili a end-to-end tecnici della composizione, pur rimanendo eseguiti a livello DuckDB.

La suite deve crescere nel tempo:

- ogni bug riproducibile diventa un test di regressione;
- ogni nuovo scenario critico viene aggiunto;
- non è necessario coprire tutto nella prima versione;
- l'obiettivo è aumentare progressivamente la confidenza negli aggiornamenti.

Domanda a cui risponde:

> Le estensioni continuano a funzionare quando vengono caricate e utilizzate insieme nello stesso runtime?

### 4. Report finale

Ogni esecuzione deve produrre evidenze su:

- versione e commit DuckDB;
- versione `extension-ci-tools`;
- artifact utilizzato;
- estensioni installate e caricate;
- origine e versione delle estensioni;
- repository e pin dei test upstream;
- test scoperti;
- test eseguiti;
- test passati;
- test falliti;
- test esclusi con motivo;
- test parziali;
- test non eseguibili per mancanza di servizi o credenziali;
- log dei servizi;
- problemi noti;
- rischi residui;
- valutazione finale.

Possibili esiti:

```text
compatibile
compatibile con limitazioni
non compatibile
non valutabile
```

## Test parziali e piattaforme esterne

Alcuni test originali delle estensioni possono essere eseguiti solo parzialmente nel POC, perché la validazione completa richiede l'accesso alla piattaforma per cui l'estensione è stata creata.

Esempi:

- HTTPFS può usare MinIO per scenari S3-like locali, ma alcuni test richiedono un vero provider S3 cloud;
- Iceberg può richiedere cataloghi o ambienti specifici;
- Delta e Unity Catalog possono richiedere accesso a piattaforme o cataloghi reali;
- altri provider cloud richiedono account, credenziali, secret e policy dedicate.

Questi test devono essere classificati chiaramente come:

```text
eseguito
eseguito parzialmente
escluso con motivazione
non eseguibile per mancanza di ambiente o credenziali
```

Per completare la validazione serviranno credenziali, account o ambienti dedicati sulle piattaforme reali.

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

Batterie già configurate nel POC:

- HTTPFS;
- DuckLake;
- PostgreSQL Scanner;
- Delta;
- Iceberg;
- Azure;
- Unity Catalog;
- MSSQL.

Da integrare nel perimetro:

- Virtual File Provider;
- BigQuery.

Il POC è stato realizzato su GitHub perché offre:

- pipeline rapide da creare;
- runner Ubuntu pronti;
- container e servizi semplici da avviare;
- artifact e log già gestiti;
- repository DuckDB già presenti;
- parallelizzazione immediata;
- possibilità di spostare l'esecuzione fuori dalla macchina locale.

## Cosa manca

- batteria cross-extension in singola sessione;
- integrazione Virtual File Provider;
- integrazione BigQuery;
- report aggregato per il SAL;
- misura reale di tempi, artifact, log e spazio;
- classificazione di test esclusi, parziali e non eseguibili;
- accesso a piattaforme reali per i test che oggi richiedono account esterni;
- spike Telemaco DevOps;
- gestione completa delle credenziali cloud;
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

Questa opzione può essere citata come valutata ma non portata avanti.

Domanda:

> GitHub deve essere una piattaforma stabile oppure solamente l'ambiente del POC?

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

Domanda:

> Telemaco DevOps può garantire isolamento, rete e capacità di esecuzione adeguati al processo?

## Container e rete

Da non dimenticare:

- su GitHub ogni job gira su una VM effimera;
- su Telemaco gli agenti potrebbero essere persistenti;
- se più batterie girano sullo stesso host, possono confliggere su porte e nomi container;
- bisogna rendere dinamici porte, reti Docker e nomi container oppure usare agenti isolati;
- alcuni container devono accedere alla rete aziendale o a repository interni;
- se l'IP del container non è riconosciuto, alcuni servizi potrebbero non essere raggiungibili;
- la reale possibilità di parallelizzazione deve essere verificata con l'infrastruttura disponibile.

Punto per Gianni:

> Qual è il modello corretto per far girare container di test che devono accedere alla rete aziendale dalle macchine runner di Telemaco DevOps?

## Virtual File Provider

Punto decisionale:

- oggi il repository è interno;
- GitHub-hosted non può raggiungerlo;
- per includerlo bisogna scegliere una strategia.

Opzioni realistiche:

1. portare il repository su GitHub private;
2. creare un mirror controllato su GitHub;
3. usare Telemaco DevOps end-to-end;
4. escluderlo temporaneamente solamente dal POC.

Nota: GitHub Actions con runner self-hosted in rete Irion è stato valutato ma scartato.

Messaggio:

> Senza Virtual File Provider possiamo dimostrare il modello, ma non validare l'intera composizione distribuita.

## Domande principali del SAL

### Prima domanda

> Il processo proposto è soddisfacente?

Da far emergere:

- il processo ha due livelli di test;
- riutilizza i test originali;
- mantiene tutte le estensioni presenti nel runtime;
- aggiunge test congiunti mirati;
- cresce con i bug osservati;
- produce evidenze condivisibili;
- elimina la dipendenza dalla macchina locale.

### Seconda domanda

> Dove deve girare questo processo?

Opzioni principali:

- GitHub Actions;
- Telemaco DevOps.

Opzione valutata ma scartata:

- GitHub Actions con runner self-hosted Irion.

## Flusso desiderato della presentazione

1. Perché serve un processo dedicato.
2. Limiti dei test locali e dei tentativi precedenti.
3. Come funzionano realmente versioni, pin e binari delle estensioni.
4. Rischio della composizione: attach, secret, cataloghi e stato globale.
5. Processo proposto.
6. Cosa ha dimostrato il POC.
7. Perimetro delle estensioni di piattaforma.
8. Cosa manca.
9. Prima decisione: il processo è soddisfacente?
10. Seconda decisione: GitHub o Telemaco DevOps?
11. Problemi specifici Telemaco: container, rete, isolamento.
12. Decisioni richieste.

## Messaggi chiave per slide

- L'esecuzione non deve dipendere dalla macchina locale dello sviluppatore.
- Lo stesso SHA sorgente non significa lo stesso binario tra versioni DuckDB.
- Il caricamento corretto dimostra compatibilità binaria, non funzionale.
- I test upstream sono necessari ma non bastano.
- Servono test cross-extension nella stessa sessione.
- Alcuni test sono parziali finché non si accede alle piattaforme reali.
- La suite deve crescere con i problemi osservati.
- Il POC dimostra che il modello è fattibile.
- La domanda ora è dove rendere stabile il processo.
- GitHub è veloce e già dimostrato; Telemaco consente accesso ai repository interni e maggiore controllo aziendale.
- GitHub self-hosted runner è stato valutato ma scartato.
- Virtual File Provider e rete aziendale sono fattori decisivi.
- Il SAL deve discutere processo e piattaforma, non dettagli implementativi minori.

## Decisioni da ottenere

- Approvare o correggere il processo di validazione.
- Definire gli scenari cross-extension obbligatori.
- Decidere se fare uno spike Telemaco DevOps.
- Stabilire se GitHub resta piattaforma candidata o se si procede verso Telemaco.
- Decidere come includere il Virtual File Provider.
- Identificare chi verifica rete e container sulle macchine runner.
- Definire il criterio minimo di successo dello spike.

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

> Il POC ha già risposto alla domanda tecnica: il processo è possibile. Il SAL deve ora approvare il modello di validazione e decidere dove deve vivere stabilmente.
