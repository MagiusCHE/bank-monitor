# Server agent guide

FastAPI + SQLite per l'ingestione di estratti bancari xlsx e la loro classificazione
tramite tag-rules e gruppi configurabili. Target runtime: Python 3.9+ su Raspberry Pi
`armhf` (solo wheel binari, niente compilazione).

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
- `app/filters.py` — clausola SQL `LIKE` per `exclude_trading` (filtro alternativo
  ai tag, usato su `/api/series`, `/api/group-stats`, `/api/transactions`)
- `app/parsers/` — parser per i template xlsx. Oggi solo `fineco.py`; il
  `__init__.py` contiene il registry con `detect()`/`parse()`.
- `app/services/ingest.py` — insert idempotente delle transazioni (dedup-hash con
  ordinale per righe identiche: una tx "VISA DEBIT 46,28 EUR" che appare 2 volte
  nello stesso giorno non viene deduplicata)
- `app/services/grouping.py` — tre funzioni:
  - `dewrap()` compensa gli spazi spuri di Fineco a posizione 40 (vedi sotto)
  - `compute_tags()` applica tutte le `tag_rules`, restituisce lista ordinata di tag
  - `match_group()` trova il primo gruppo compatibile (kind + tag-overlap) per una tx
- `app/routes/*` — route FastAPI (vedi README del repo per elenco endpoint)

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

`dewrap()` rimuove questi spazi *solo* in posizione 40 e solo se sono tra due lettere
(per non rompere date, numeri, punteggiatura). Non modifica il DB: viene applicata al
volo quando si testa una regex. Il tooltip e la tabella drill-down mostrano sempre
la descrizione originale.

Limiti:
- Spazi spuri dopo la posizione 40 non sono deterministici (non a intervalli regolari)
  e non vengono rimossi. Se una keyword cade lì (es. `SUPER MERCATO`, `NAZIO NALE`)
  bisogna accettarla o aggiungere keyword-varianti.
- Il wrap si applica solo a `full_description`; `description` (corta) non lo subisce.

## Convenzioni sulla scrittura delle regex

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
- Lo stesso vale per il filtro SQL `exclude_trading` in `app/filters.py`: niente
  keyword `compravendita` da sola.

## Movimenti "Autorizzato"

Le righe con `status='Autorizzato'` sono pre-contabilizzazioni (tipicamente duplicate
da una riga "Contabilizzato" pochi giorni dopo). Sono salvate in DB ma escluse di
default dalle query (toggle client: "Includi movimenti autorizzati"). Vengono
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

- **"Non vedo un movimento che mi aspetto"** → controlla il filtro `exclude_trading`
  (ON di default) e `include_authorized` (OFF di default). In alternativa interroga
  `GET /api/transactions?date=YYYY-MM-DD&limit=50` per vedere cosa c'è e quali tag
  vengono assegnati.
- **"Una tx è nel gruppo sbagliato"** → i tag vengono decisi dalle regole (`/api/tag-rules`),
  il gruppo dall'ordine di `priority` su `/api/groups`. Due cose da verificare:
  (a) la tx ha i tag che ti aspetti? (b) c'è un gruppo con `priority` più bassa che
  la cattura prima di quello voluto?
- **"Dopo un reset ho perso le mie regole custom"** → `POST /api/seed` è un wipe
  **totale** di tag_rules+groups+group_tags, non un "merge". Nota nel README/UI.
