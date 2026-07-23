# Memory SAL: processo test DuckDB ed estensioni

Questo file è una memoria di lavoro. Serve a conservare il ragionamento completo emerso nella preparazione del SAL. Non è pensato per essere presentato integralmente.

## Obiettivo della memoria

Conservare:

- motivazione del processo;
- rischi osservati negli aggiornamenti DuckDB;
- ipotesi sulla compatibilità delle estensioni;
- struttura del POC;
- decisioni ancora aperte;
- punti da portare in discussione;
- messaggi chiave da trasferire in `presentazione.md`.

## Contesto

Irion utilizza DuckDB nell'Analytics Engine insieme a un set di estensioni. L'aggiornamento di DuckDB non può essere considerato solo come aggiornamento di una libreria isolata, perché la piattaforma usa estensioni caricate insieme, cataloghi diversi, attach verso sorgenti differenti, secret provider, filesystem remoti e funzionalità specifiche.

Il POC nel repository `irion-extension-tests`, branch `001-httpfs-qa-infrastructure`, dimostra che è possibile preparare DuckDB e `unittest`, eseguire batterie di test delle estensioni e caricare il set comune delle estensioni Irion in ogni batteria.

## Perché serve il processo

Motivazione principale:

> DuckDB può essere aggiornabile, ma l'insieme DuckDB + estensioni Irion deve essere qualificato come composizione.

Osservazioni alla base del processo:

- gli aggiornamenti DuckDB non sono immediati;
- le estensioni possono non aggiornarsi nello stesso momento di DuckDB;
- alcune estensioni possono restare su commit precedenti;
- la presenza di un binario installabile non garantisce comportamento funzionale corretto;
- i test upstream delle singole estensioni non coprono automaticamente la composizione Irion;
- più estensioni caricate insieme possono collidere;
- operazioni reali come più `ATTACH`, `CREATE SECRET`, accessi a filesystem remoti e cataloghi multipli devono essere validate insieme.

Esempio da ricordare in call:

- caso osservato di problemi con sequenze di `ATTACH`, per esempio MSSQL dopo PostgreSQL;
- questo mostra che non basta sapere che MSSQL funziona da solo e PostgreSQL funziona da solo;
- serve testare la sessione reale con più estensioni presenti.

Frase breve:

> Il rischio non è solo che un'estensione non funzioni: il rischio è che funzioni da sola ma non funzioni più nella composizione reale Irion.

## Compatibilità estensioni DuckDB

Punto da comunicare con attenzione:

- DuckDB documenta che le estensioni binarie sono legate a una specifica versione DuckDB e piattaforma;
- DuckDB installa estensioni in cartelle versionate per DuckDB e piattaforma;
- DuckDB dovrebbe rifiutare il caricamento di binari incompatibili;
- però la documentazione non fornisce una garanzia chiara del tipo "compatibile su tutta la minor";
- nella pratica si osserva che una versione DuckDB più recente può risolvere un'estensione verso lo stesso SHA/commit usato da una versione precedente;
- quindi non si può dedurre che tutte le estensioni siano state aggiornate solo perché DuckDB è stato aggiornato.

Conclusione di memoria:

> La compatibilità binaria è necessaria ma non sufficiente. Il nostro processo deve dimostrare la compatibilità funzionale della composizione.

## Strategia test

Il processo deve avere tre livelli principali.

### 1. Test runtime

Verificare:

- versione DuckDB;
- build CLI;
- build `unittest`;
- artifact;
- installazione estensioni;
- load estensioni;
- origine/versione delle estensioni.

### 2. Test upstream delle estensioni

Per ogni estensione:

- checkout repository originale;
- pin immutabile o release;
- mai `main`;
- esecuzione dei test originali;
- caricamento di tutte le estensioni Irion prima della batteria;
- raccolta log e test esclusi.

Domanda a cui risponde:

> I test originali dell'estensione passano ancora quando l'estensione viene caricata dentro la composizione Irion?

### 3. Test Irion cross-extension

Test scritti da Irion, in un'unica sessione DuckDB, per coprire:

- più `ATTACH`;
- MSSQL + PostgreSQL;
- DuckLake;
- HTTPFS;
- Azure;
- Delta;
- Iceberg;
- Unity Catalog;
- ICU;
- `CREATE SECRET`;
- collisioni di funzioni/configurazioni;
- sequenze di load;
- query cross-catalog.

Domanda a cui risponde:

> La sessione reale usata dall'Analytics Engine è stabile quando carichiamo e usiamo insieme tutte le estensioni?

## Cosa è stato fatto nel POC

POC su GitHub Actions per rapidità.

Dimostrato:

- configurazione centrale in `config/extensions.yml`;
- DuckDB `v1.5.4`;
- `extension-ci-tools` `v1.5.4`;
- build comune DuckDB + CLI + `unittest`;
- artifact condiviso;
- job paralleli;
- checkout upstream a pin;
- install/load congiunto delle estensioni;
- isolamento di `HOME` e runtime;
- servizi per HTTPFS, PostgreSQL, SQL Server;
- raccolta log;
- repository configurabili senza hardcodare la matrice nel workflow.

Estensioni/batterie attuali da ricordare:

- HTTPFS;
- DuckLake;
- postgres_scanner;
- Delta;
- Iceberg;
- Azure;
- Unity Catalog;
- MSSQL.

Estensioni comuni nel baseline:

- httpfs;
- mssql;
- ducklake;
- postgres_scanner;
- icu;
- azure;
- delta;
- iceberg;
- unity_catalog.

## Cosa manca

- batteria Irion cross-extension in singola sessione;
- report aggregato per il SAL;
- integrazione Virtual File System;
- misura reale di artifact/log/tempi;
- spike Telemaco DevOps;
- gestione completa di credenziali cloud;
- policy di retention;
- decisione su dove far girare il processo.

## GitHub: memoria argomenti

Perché è stato usato:

- POC veloce;
- workflow semplici;
- runner pronti;
- container e servizi facili;
- artifact e log gestiti;
- repository DuckDB già su GitHub;
- parallelizzazione immediata.

Problemi:

- se repository privata: quote/costi;
- repository pubblico non adatto a tutto;
- Virtual File System interna non accessibile;
- log/artifact fuori dalla rete Irion;
- governance esterna.

Domanda:

> Accettiamo GitHub come piattaforma stabile oppure solo come POC?

## Telemaco DevOps: memoria argomenti

Perché considerarlo:

- è interno;
- accede ai repository Irion;
- migliore per codice non pubblico;
- migliore per processo ufficiale aziendale;
- controllo su artifact, retention e rete.

Problemi/incertezze:

- agenti Linux da predisporre;
- Docker e Docker Compose da verificare;
- container e rete aziendale;
- IP container forse non registrati;
- proxy/firewall;
- parallelizzazione;
- gestione porte;
- artifact on-premises;
- differenza tra GitHub Actions e Telemaco YAML;
- necessità di coinvolgere Gianni.

Domanda:

> Telemaco DevOps può garantire lo stesso livello di isolamento e parallelizzazione di GitHub Actions?

## Container e rete

Da non dimenticare:

- su GitHub ogni job gira su VM effimera;
- su Telemaco gli agenti potrebbero essere persistenti;
- se più batterie girano sullo stesso host, possono confliggere su porte e nomi container;
- bisogna rendere dinamici porte, reti Docker e nomi container oppure usare agenti isolati;
- alcuni container devono accedere alla rete aziendale o a repository interni;
- se l'IP del container non è riconosciuto, alcuni servizi potrebbero non essere raggiungibili.

Punto per Gianni:

> Qual è il modello corretto per far girare container di test che devono accedere alla rete aziendale da Telemaco DevOps?

## Virtual File System

Punto decisionale:

- oggi il repository VFS è interno;
- GitHub-hosted non può raggiungerlo;
- per includerlo bisogna scegliere una strategia.

Opzioni:

1. portare VFS su GitHub private;
2. mirror controllato su GitHub;
3. GitHub Actions con runner self-hosted in rete Irion;
4. Telemaco DevOps end-to-end;
5. esclusione temporanea solo per POC.

Messaggio:

> Senza VFS possiamo dimostrare il modello, ma non qualificare davvero tutta la composizione Analytics Engine.

## Domande principali del SAL

### Prima domanda

> Il processo proposto è soddisfacente?

Da far emergere:

- non stiamo creando test casuali;
- stiamo creando un processo di qualificazione;
- il processo usa test originali;
- aggiunge test Irion mirati;
- produce evidenze;
- evita aggiornamenti manuali basati su confidenza soggettiva.

### Seconda domanda

> Dove deve girare questo processo?

Opzioni:

- GitHub Actions;
- GitHub Actions + runner self-hosted Irion;
- Telemaco DevOps;
- modello ibrido POC su GitHub e processo ufficiale su Telemaco.

## Flusso desiderato della presentazione

1. Esigenza: perché serve il processo.
2. Rischio: DuckDB + estensioni non è aggiornabile a occhio.
3. Problema compatibilità estensioni: pin, versioni, SHA, test.
4. Problema composizione: estensioni insieme, attach, secret, cataloghi.
5. Processo proposto: build once, test batteries, all extensions loaded.
6. Cosa ha dimostrato il POC.
7. Cosa manca.
8. Dove farlo girare: GitHub vs Telemaco DevOps.
9. Problemi specifici Telemaco: container, rete, parallelismo, artifact.
10. Decisioni richieste.

## Messaggi chiave per slide

- Non validiamo DuckDB da solo: validiamo DuckDB nella composizione Irion.
- Un'estensione può essere installabile ma non sufficiente per dichiararla funzionalmente compatibile.
- I test upstream sono necessari ma non bastano: servono test Irion cross-extension.
- Il POC dimostra che il modello è fattibile.
- La domanda ora è dove rendere stabile il processo.
- GitHub è veloce e già dimostrato; Telemaco è più adatto a codice interno e governance.
- La VFS e la rete aziendale sono fattori decisivi.
- Il SAL deve decidere processo e piattaforma, non dettagli implementativi minori.

## Decisioni da ottenere

- Approvare o correggere il processo di validazione.
- Decidere se fare uno spike Telemaco DevOps.
- Stabilire se GitHub resta solo POC o diventa piattaforma candidata.
- Decidere come trattare la Virtual File System.
- Identificare chi verifica rete/container su Telemaco.
- Definire il criterio minimo di successo dello spike.

## Criterio minimo di successo per Telemaco DevOps

Uno spike Telemaco è utile se dimostra:

- build DuckDB una volta;
- artifact riusato;
- almeno tre batterie;
- almeno una batteria con container;
- almeno una batteria con repository interno;
- log raccolti;
- nessun conflitto di porte;
- comportamento ripetibile;
- parallelizzazione o serializzazione consapevole.

## Formula conclusiva

> Il POC ha già risposto alla domanda tecnica: il processo è possibile. Il SAL deve ora rispondere alla domanda organizzativa: dove deve vivere questo processo e quali vincoli aziendali deve rispettare?
