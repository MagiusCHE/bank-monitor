# Server agent guide

FastAPI + SQLite per l'ingestione di estratti bancari xlsx/CSV e la persistenza
di tag-rules e gruppi configurabili. Target runtime: Python 3.9+ su Raspberry Pi
`armhf` (solo wheel binari, niente compilazione).

**Architettura: il server è "dumb storage"**. Espone l'ingest dei file e il CRUD
di accounts/tag-rules/groups, e fornisce due endpoint di lettura "bulk"
(`/api/config`, `/api/transactions/all`) che scaricano tutto. Tutto il calcolo
(filtri, tagging, matching gruppi, serie temporali, statistiche) avviene **lato
client** in JavaScript. Vedi `client/AGENTS.md`.

Storicamente esistevano endpoint server-side per il calcolo (`/api/series`,
`/api/group-stats`, `/api/transactions` con filtri, `/api/trading-transactions`):
sono stati eliminati perché su Raspberry Pi armhf erano il collo di bottiglia.

## Layout

- `app/main.py` — FastAPI app, CORS aperto, include le route
- `app/db.py` — SQLite (WAL), schema, `init_db()`, `reset_to_seed()`
- `app/seed.py` — `TAG_RULES` e `GROUPS` generici (brand nazionali, categorie
  universali). Configurazione iniziale al primo boot *e* quando l'utente chiama
  `POST /api/seed`. **Sorgente di verità per il factory reset** (vedi invariante).
- `app/local_seed.py` (opzionale, **gitignored**) — estensione privata della seed
  per regex/gruppi specifici del singolo utente (cognomi, commercianti locali, ecc.).
  Vedi `app/local_seed.py.example` per il formato. Se il file esiste, `apply_seed()`
  lo carica e lo unisce: regole appese, gruppi merge-by-name (append tag).
- `app/parsers/` — parser per i template xlsx. Oggi solo `fineco.py`; il
  `__init__.py` contiene il registry con `detect()`/`parse()`. Per i CSV PayPal,
  `app/parsers/paypal.py`.
- `app/services/ingest.py` — insert idempotente delle transazioni (dedup-hash con
  ordinale per righe identiche: una tx "VISA DEBIT 46,28 EUR" che appare 2 volte
  nello stesso giorno non viene deduplicata)
- `app/services/paypal.py` — ingest e match del CSV PayPal (riempie
  `transactions.enriched_description` con il merchant reale)
- `app/routes/bootstrap.py` — `/api/config` e `/api/transactions/all` (i due
  endpoint di lettura bulk consumati al boot dal client)
- `app/routes/accounts.py` — `DELETE /api/accounts/{id}`
- `app/routes/groups.py` — CRUD tag-rules + groups + `/api/tags` + `/api/seed`.
  **Nota:** il server NON valida i pattern regex (delegato al client JS che è
  l'unico consumatore e li compila per davvero).
- `app/routes/upload.py` — `POST /api/upload`

## Schema DB

- `accounts(id, account_number, holder_name, initial_balance, initial_balance_date)`
  - Il saldo iniziale viene aggiornato da ogni upload **solo se il periodo del file
    è più vecchio** di `initial_balance_date` corrente. Così se ricarichi un estratto
    più esteso nel passato, il grafico si estende; altrimenti resta ancorato al punto
    più vecchio già visto.
- `transactions(id, account_id, op_date, value_date, amount, description,
  full_description, status, seq, dedup_hash)`
  - `dedup_hash = sha256(account|value_date|amount|desc|full_desc|status|seq)`
  - `seq` è un ordinale all'interno del gruppo `(account, value_date, amount, desc, status)`:
    permette di inserire N transazioni identiche senza scartarle come duplicate.
- `tag_rules(id, name, pattern, tag, priority)` — `pattern` è una regex Python.
  Tutte le regole vengono applicate a ogni tx, in ordine di `priority`. Se più regole
  assegnano lo stesso tag, è solo un tag (set).
- `groups(id, name, kind, priority)` + `group_tags(group_id, tag)` — gruppi come
  aggregati di tag. `kind ∈ {income, expense, any}`. La regola di matching è:
  scorri i gruppi in `ORDER BY priority, id`, il primo con `kind` compatibile con il
  segno della tx **e** almeno un tag in comune la cattura.

Non esiste una tabella `transaction_tags` persistita: i tag sono ricalcolati al volo
a ogni query. Con 1500 tx × ~40 regole compilate una sola volta è istantaneo.

## Invariante fondamentale — seed ↔ DB

La configurazione (tag-rules + groups) **vive nel DB** ed è editabile dall'utente via API.
`seed.py` è solo il punto di partenza per un DB vuoto **e** il contenuto di
`POST /api/seed` (factory reset). Non c'è più il vecchio meccanismo di "migrazione
automatica al boot" basato su `DEFAULT_GROUPS_VERSION`: l'utente è il padrone dei dati.

**Regola operativa: quando modifichi una tag-rule o un gruppo via codice, aggiorna
sempre in parallelo `seed.py` *e* il DB attuale.**

- Se modifichi solo il DB (via `PUT /api/tag-rules/{id}`, `POST /bulk`, ecc.) e non
  `seed.py`, al primo "Reimposta a iniziale" la modifica sparisce.
- Se modifichi solo `seed.py` e non il DB, l'utente non vede il cambio finché non fa
  `POST /api/seed` (o cancella `data/bank.db*` e riavvia).
- Per applicare immediatamente al DB attuale una modifica già fatta nel seed:
  `curl -X POST http://127.0.0.1:8765/api/seed` (wipe + re-insert).

Se modifichi il seed senza far girare il server, l'effetto si vedrà al prossimo
reset chiamato dall'utente (il wipe+re-seed è un'operazione esplicita).

## Note specifiche per il parser Fineco

Le descrizioni complete Fineco (`full_description`) vengono wrappate a larghezza fissa
con uno spazio spurio **esattamente a posizione 40 dell'offset**. Esempi:

- `CONA D SUPERSTORE` → `CONAD SUPERSTORE`
- `MARK ET` → `MARKET`
- `PROF UMERIA` → `PROFUMERIA`
- `Nes suna Commissione` → `Nessuna Commissione`

Il `dewrap()` rimuove questi spazi *solo* in posizione 40 e solo se sono tra due
lettere (per non rompere date, numeri, punteggiatura). **Implementato lato
client** (`client/src/main.js`): viene applicato al volo quando si testa una
regex contro `full_description`/`enriched_description`. Non modifica mai il DB.
Il tooltip e la tabella drill-down mostrano sempre la descrizione originale.

Limiti:
- Spazi spuri dopo la posizione 40 non sono deterministici (non a intervalli regolari)
  e non vengono rimossi. Se una keyword cade lì (es. `SUPER MERCATO`, `NAZIO NALE`)
  bisogna accettarla o aggiungere keyword-varianti.
- Il wrap si applica solo a `full_description`; `description` (corta) non lo subisce.

## Convenzioni sulla scrittura delle regex

Le regex stanno in `seed.py` / `local_seed.py` in stile Python ma vengono usate
**solo dal client JS**. Il client le compila con un piccolo shim
(`compilePyRegex` in `main.js`) che strippa i flag inline `(?i)`/`(?m)`/`(?s)` e
li rimette come flag JS. Tutti gli altri costrutti usati (`\b`, `(?:…)`, `(?=…)`,
`(?<!…)`) sono già compatibili JS — verificare che eventuali pattern nuovi non
introducano costrutti Python-only (named groups `(?P<…>…)` ecc.).

- Usare `\b` per le parole comuni che potrebbero essere sottostringhe: `\bpub\b`,
  `\bconad\b`, `\bbar[-\s]+[a-z]`
- Case-insensitive con `(?i)` all'inizio
- Attenzione a "false positives" dentro le causali dei bonifici. Una parola che compare
  nel campo `Cau:` (testo libero scritto dall'ordinante) non deve essere trattata come
  se fosse nel beneficiario. Quando si scrivono regex famiglia/conoscenti, ancorarle al
  campo strutturato: `(?:Ord|Ben|Beneficiario)\s*:\s*[^:]*?(<keyword>)`.
- Il tag `trading` NON deve matchare `compravendita` da sola: `"SALDO IMMOBILE OGGETTO
  DI COMPRAVENDITA"` fu un falso positivo. Oggi la regex richiede `compravendita\s+titoli`
  o parole tipicamente da trading.
- Lo stesso vale per il filtro `excludeTrading` lato client (`isTrading()` in
  `main.js`, vedi `TRADING_KEYWORDS`): niente keyword `compravendita` da sola.

## Movimenti "Autorizzato"

Le righe con `status='Autorizzato'` sono pre-contabilizzazioni (tipicamente duplicate
da una riga "Contabilizzato" pochi giorni dopo). Sono salvate in DB e **scaricate
sempre dal client** via `/api/transactions/all`. Il filtro è applicato lato client
(toggle "Includi movimenti autorizzati" → `state.includeAuthorized`). Vengono
**sempre** dedupate tramite `dedup_hash` anche tra Autorizzato e Contabilizzato.

## Run / deploy

```bash
cd server
./run.sh                      # crea .venv al primo lancio (--only-binary=:all:)
# Vars: BANK_MONITOR_HOST (default 0.0.0.0), BANK_MONITOR_PORT (8765), BANK_MONITOR_DB
```

Lo script usa `pip install --only-binary=:all:` per assicurarsi che non servano
compilatori. Sul Raspberry Pi (armhf) senza gcc la compilazione di pydantic-core
fallirebbe; con i wheel armv7l esistenti su PyPI va tutto liscio.

## Troubleshooting

- **"Non vedo un movimento che mi aspetto"** → la lista che il client ha in
  memoria contiene tutte le tx (tutte le date, tutti gli stati). Se manca:
  controlla in DB direttamente (`SELECT * FROM transactions WHERE …`). Se è in
  DB ma non nel grafico, sono i filtri client `excludeTrading` (ON di default) o
  `includeAuthorized` (OFF di default) o il range date.
- **"Una tx è nel gruppo sbagliato"** → i tag vengono decisi dalle regole, il
  gruppo dall'ordine di `priority`. Tutto il calcolo è in `client/src/main.js`
  (`computeTags`, `matchGroup`). Verifica: (a) la tx ha i tag che ti aspetti?
  (b) c'è un gruppo con `priority` più bassa che la cattura prima di quello
  voluto?
- **"Dopo un reset ho perso le mie regole custom"** → `POST /api/seed` è un wipe
  **totale** di tag_rules+groups+group_tags, non un "merge". Nota nel README/UI.
- **"Una regex funziona in seed.py ma il client non la rispetta"** → controlla
  che il client riesca a compilarla in JS (apri DevTools sulla console: il
  porting JS logga `[regex] pattern non compilabile in JS: …`). Costrutti
  Python-only come `(?P<…>…)` non sono supportati.
