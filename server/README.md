# Bank Monitor — Server

API REST in Python (FastAPI + SQLite) per l'ingestione di estratti conto bancari
in formato `.xlsx` (oggi **Fineco**) e la loro classificazione tramite un sistema
di **tag** e **gruppi** configurabili dall'utente.

Fa parte del progetto [Bank Monitor](../README.md): questo modulo è la parte
server, pensata per girare in locale sulla macchina dell'utente oppure su un
Raspberry Pi in rete domestica. Il client desktop (Tauri) si collega via HTTP
all'indirizzo configurato.

## Concept

Un singolo utente carica gli estratti bancari scaricati dalla home banking. Il
server:

1. **Parsa** l'xlsx (template Fineco) ed estrae le transazioni normalizzate
   (data operazione, data valuta, importo, descrizione, stato).
2. **Deduplica** in modo idempotente tramite hash stabile: puoi ricaricare lo
   stesso file quante volte vuoi, entra solo ciò che non c'è già.
3. **Classifica** ogni transazione applicando tutte le tag-rules (regex sulla
   descrizione) e assegnandola al primo gruppo con `priority` più bassa
   compatibile con il segno della transazione e i suoi tag.
4. **Espone** endpoint per grafici temporali del saldo, aggregati per gruppo,
   drill-down sulle singole transazioni, CRUD su regole e gruppi.

La configurazione (tag-rules + groups) vive nel DB ed è editabile a caldo via
API. Il file [`app/seed.py`](app/seed.py) contiene solo i valori iniziali usati
al primo boot e dal factory reset `POST /api/seed`.

Dettagli di architettura, invarianti, convenzioni sulle regex e quirk del parser
Fineco → [AGENTS.md](AGENTS.md).

## Come si avvia il server

Requisiti: **Python 3.9+**. Non serve un compilatore: le dipendenze sono
installate solo da wheel binari (`pip install --only-binary=:all:`), così il
setup funziona anche su Raspberry Pi armhf senza toolchain C.

### Linux / macOS / Raspberry Pi

```bash
cd server
./run.sh
```

### Windows

```cmd
cd server
run.cmd
```

Al primo avvio lo script:

1. crea un virtualenv locale in `server/.venv`
2. installa [`requirements.txt`](requirements.txt) (FastAPI, uvicorn, openpyxl,
   python-multipart)
3. avvia uvicorn su `http://0.0.0.0:8765`

Dai lanci successivi salta i primi due step e parte subito.

### Variabili d'ambiente

| Variabile | Default | Descrizione |
|---|---|---|
| `BANK_MONITOR_HOST` | `0.0.0.0` | Interfaccia di ascolto |
| `BANK_MONITOR_PORT` | `8765` | Porta HTTP |
| `BANK_MONITOR_DB` | `server/data/bank.db` | Path del file SQLite |

### Verifica

```bash
curl http://127.0.0.1:8765/api/health
```

Il DB SQLite viene creato al primo boot in `data/bank.db`. Al primo avvio con DB
vuoto il server popola automaticamente tag-rules e gruppi dal seed.

## Endpoint principali

Elenco completo in [../README.md](../README.md#endpoint-rest-principali). Rotte
definite in [`app/routes/`](app/routes/).

## Reset configurazione

Per ripartire dai tag-rules e gruppi iniziali (wipe totale, non un merge):

```bash
curl -X POST http://127.0.0.1:8765/api/seed
```

Le transazioni già importate restano intatte.
