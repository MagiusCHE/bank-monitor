# Bank Monitor

Strumento per monitorare l'andamento di uno o più conti correnti nel tempo e analizzare
le spese per categoria. Composto da due parti:

- **server/**: API REST in Python (FastAPI + SQLite) che ingerisce estratti conto in formato
  Excel (oggi `.xlsx` di **Fineco**) e classifica i movimenti tramite un sistema di
  tag e gruppi configurabile dall'utente via API.
- **client/**: applicazione desktop in [Tauri](https://tauri.app) (Rust + frontend
  HTML/JS vanilla + [Chart.js](https://www.chartjs.org/)) che si collega al server REST
  configurato dall'utente. Stile ispirato a `fabot`: no framework JS, HTML statico.

Il server è pensato per girare su un Raspberry Pi (userland armhf 32-bit, Python 3.9).
Il client si collega via `http://<hostname>:8765` (porta configurabile dall'UI).

## Funzionalità principali

- Upload di file xlsx Fineco → dedup idempotente (puoi ricaricare lo stesso file, inserisce
  solo le nuove transazioni)
- Grafico temporale del saldo, sia cumulativo sia per conto, con ricostruzione del
  saldo iniziale dal periodo più vecchio presente fra i file caricati
- Vista **Gruppi**: bar chart impilato (rosso uscite, verde entrate) per categoria,
  con drill-down cliccabile sulla singola barra → tabella dei movimenti
- Tag e gruppi completamente configurabili via UI, persistiti nel DB del server:
  un client che apporta modifiche le rende disponibili a tutti gli altri al prossimo
  refresh
- Toggle "Escludi compravendite/titoli" (ON di default) per vedere il saldo "al netto
  del trading"
- Tooltip dei grafici con le singole transazioni del punto (line) o i totali
  entrate/uscite/netto (bar)
- Sezione **"Movimenti non taggati"** per vedere cosa manca da classificare

## Avvio in sviluppo

### Server

```bash
cd server
./run.sh
```

Al primo avvio lo script crea un `.venv` locale con FastAPI + uvicorn + openpyxl +
python-multipart (solo wheel binari, nessuna compilazione). Ascolta su `http://0.0.0.0:8765`.

Variabili opzionali:
- `BANK_MONITOR_HOST` (default `0.0.0.0`)
- `BANK_MONITOR_PORT` (default `8765`)
- `BANK_MONITOR_DB` (default `server/data/bank.db`)

Il DB SQLite viene creato al primo boot. Al primo boot con DB vuoto vengono inseriti
i **tag-rules e gruppi seed** (vedi `server/app/seed.py`).

### Client

```bash
cd client
pnpm install          # solo la prima volta
pnpm tauri dev
```

La prima compilazione di Rust/Tauri richiede qualche minuto; le successive sono istantanee.

Al primo avvio del client:
1. Apri Impostazioni (⚙), inserisci `http://127.0.0.1:8765` (o l'indirizzo del Pi)
2. "Test connessione" → "Salva"
3. "Carica file" → seleziona l'estratto xlsx Fineco

## Architettura tag/gruppi (importante)

Il sistema di classificazione è in due livelli:

1. **Tag rules**: regex sulla descrizione dei movimenti. Tutte le regole vengono
   applicate a ogni transazione, in parallelo: un movimento può ricevere più tag.
2. **Gruppi**: aggregati di tag con un `priority`. Una transazione viene catturata
   dal primo gruppo con `kind` compatibile (income/expense/any) che ha almeno un
   tag in comune con la transazione.

Vantaggi rispetto al vecchio design "una regex per gruppo":
- Un ristorante chiamato `CONAD BAR-RISTORANTE` può avere tag `bar` e `ristorante` insieme
- Cambi un tag in un posto solo, tutti i gruppi che lo usano si aggiornano
- I non classificati sono gestiti come categoria distinta (barre separate entrate/uscite)

Dettagli implementativi in [server/AGENTS.md](server/AGENTS.md).

## Struttura del repository

```
bank-monitor/
├── README.md                   # questo file
├── .gitignore
├── movements_*.xlsx            # file di test locale (gitignored)
├── server/
│   ├── AGENTS.md               # guida tecnica server (invarianti, deploy, ecc.)
│   ├── CLAUDE.md               # alias per @AGENTS.md
│   ├── requirements.txt
│   ├── run.sh
│   ├── app/
│   │   ├── main.py             # FastAPI + CORS + include route
│   │   ├── db.py               # schema SQLite, init/seed
│   │   ├── seed.py             # TAG_RULES + GROUPS iniziali
│   │   ├── filters.py          # clausola SQL per exclude_trading
│   │   ├── parsers/
│   │   │   ├── __init__.py     # registry template (detect/parse)
│   │   │   └── fineco.py       # parser xlsx Fineco
│   │   ├── services/
│   │   │   ├── ingest.py       # dedup + insert transazioni
│   │   │   └── grouping.py     # dewrap(), compute_tags(), match_group()
│   │   └── routes/
│   │       ├── upload.py       # POST /api/upload
│   │       ├── accounts.py     # conti + transactions (con filtri tags/group_id/untagged)
│   │       ├── series.py       # saldo nel tempo
│   │       └── groups.py       # CRUD tag-rules + groups + /api/tags + /api/seed + /api/group-stats
│   └── data/                   # DB SQLite (gitignored)
└── client/
    ├── AGENTS.md               # guida tecnica client
    ├── CLAUDE.md               # alias per @AGENTS.md
    ├── package.json
    ├── src/                    # frontend vanilla HTML+JS+CSS
    │   ├── index.html
    │   ├── main.js
    │   └── style.css
    └── src-tauri/              # backend Rust (persistenza config locale, finestra)
        ├── Cargo.toml
        ├── src/
        │   ├── main.rs
        │   └── lib.rs          # get_config/set_config/save_window_size
        ├── capabilities/default.json
        └── tauri.conf.json
```

## Endpoint REST principali

| Endpoint | Descrizione |
|---|---|
| `GET  /api/health` | Liveness |
| `POST /api/upload` | Upload file xlsx (multipart) → inserisce solo nuove tx |
| `GET  /api/accounts` | Lista conti |
| `DELETE /api/accounts/{id}` | Elimina conto + transazioni |
| `GET  /api/transactions` | Con filtri `accounts`, `date`, `date_from`, `date_to`, `include_authorized`, `exclude_trading`, `group_id`, `uncategorized_kind`, `untagged`, `limit` |
| `GET  /api/series` | Saldo cumulativo / per-conto nel tempo |
| `GET  /api/group-stats` | Aggregati per gruppo (income/expense split, uncategorized) |
| `GET  /api/tag-rules` / `POST` / `PUT {id}` / `DELETE {id}` / `POST /bulk` | CRUD regole |
| `GET  /api/groups` / `POST` / `PUT {id}` / `DELETE {id}` / `POST /bulk` | CRUD gruppi |
| `GET  /api/tags` | Tag distinti referenziati |
| `POST /api/seed` | Wipe tag_rules+groups e re-inserisce i valori hardcoded in `seed.py` |

## Deploy su Raspberry Pi (checklist minima)

1. `rsync` della cartella `server/` sul Pi
2. Sul Pi: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
3. Opzionale: systemd unit per autostart su `pi@box-sala` (vedi `server/AGENTS.md`)

Il client NON gira sul Pi: si collega via rete all'indirizzo configurato.
