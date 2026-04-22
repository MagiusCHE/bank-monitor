# Client agent guide

App desktop [Tauri](https://tauri.app) — backend **Rust** minimo + frontend HTML+JS
vanilla (niente framework). Stile ispirato al repo `fabot` del medesimo utente
(path: `~/Sources/Personal/fabot`), stessa struttura `src/` + `src-tauri/` e stesso
meccanismo di persistenza config.

Il client parla con un server REST separato (vedi `server/`) all'indirizzo configurato
dall'utente via UI (pannello Impostazioni).

## Layout

```
client/
├── package.json              # @tauri-apps/api + @tauri-apps/cli + plugin dialog/http
├── src/                      # frontend (caricato da Tauri come frontendDist)
│   ├── index.html            # struttura UI statica
│   ├── main.js               # logica app (stato globale, rendering, fetch API)
│   └── style.css             # temi chiaro/scuro, layout, componenti
└── src-tauri/
    ├── Cargo.toml            # tauri, tauri-plugin-dialog, tauri-plugin-http, serde, dirs
    ├── build.rs
    ├── tauri.conf.json       # no window statica: creata a runtime in lib.rs
    ├── capabilities/default.json  # permessi: core, dialog, http (URL allow-list http/https)
    └── src/
        ├── main.rs           # solo entry point
        └── lib.rs            # get_config/set_config/save_window_size + window builder
```

Config utente (URL server + tema + dimensioni finestra) persistito in
`~/.config/bank-monitor/config.json` via backend Rust (`dirs::config_dir()`).

## Frontend (src/main.js)

- Stato globale in un unico oggetto `state`. Niente reattività, niente render tree
  virtuale: i render sono funzioni `render*()` che leggono da `state` e aggiornano
  il DOM direttamente.
- Due `loadConfig` **distinte** (attenzione a NON confonderle):
  - `loadConfig()` — legge URL server + tema dal file config locale (Rust) o localStorage
  - `reloadServerConfig()` — legge tag-rules e groups dal server REST (/api/*)
  Storicamente una shadowava l'altra quando le avevo chiamate entrambe `loadConfig` →
  tema + URL non si applicavano. Non rinominare a caso.
- Tre viste principali: `cumulative`, `per-account`, `groups`. La vista `groups`
  mostra un pannello con 3 sezioni collassabili: **Tag & regex**, **Gruppi**,
  **Movimenti non taggati**.
- Dirty tracking dei form di regole/gruppi: il bottone "Salva modifiche" è disabilitato
  finché non cambi qualcosa, poi chiama `POST /api/*/bulk` che sostituisce
  atomicamente l'intera lista.

## Dettagli del bar chart (vista Gruppi)

Non è un normale bar chart. Ogni gruppo ha 2 dataset stacked:

- Dataset 1 (`backgroundColor: red`): valore assoluto delle uscite (positivo)
- Dataset 2 (`backgroundColor: green`): entrate (positivo)

Entrambi vengono impilati **verso l'alto**. Un gruppo con 50€ entrate e 50€ uscite
→ barra alta 100 (rosso metà inferiore, verde metà superiore).

Il tooltip `afterBody` mostra le righe "↑ Entrate: … / ↓ Uscite: … / Netto: …" leggendo
dai metadati `groupMeta[dataIndex]`. La `label` callback ritorna `null` per evitare
che i due dataset mostrino due righe duplicate.

Il click su una barra apre il drill-down (`openDrill`) via `GET /api/transactions?group_id=X`.

## Interazione con server: chi ricarica quando

Le regole di tagging e i gruppi NON sono cachate lato client: vengono ricaricati con
`reloadServerConfig()` ogni volta che:

1. L'app parte (`init()` → `refreshAll()` → `reloadServerConfig()`)
2. L'utente clicca "Ricarica" nel pannello classificazione
3. L'utente salva modifiche a regole o gruppi
4. Si entra nella vista Gruppi da un'altra vista (indirettamente via `refreshChart`)

Questo garantisce che se il client A salva modifiche, il client B le vede al successivo
refresh (niente sync push, niente websocket — sono dati "slow-moving").

## Persistenza config client

`get_config` / `set_config` / `save_window_size` sono comandi Tauri esposti da
`src-tauri/src/lib.rs`. Salvano in `~/.config/bank-monitor/config.json`:

```json
{
  "server_url": "http://bank-monitor-server:8765",
  "theme": "dark",
  "window_width": 1042.0,
  "window_height": 905.0
}
```

### Persistenza dimensioni finestra su Wayland

Su GNOME/Wayland le decorazioni client-side (CSD) fanno sì che `inner_size()` includa
la barra di titolo/bordo. Per evitare che la finestra cresca a ogni riavvio è presente
in `lib.rs` lo stesso meccanismo di fabot:

- Dopo 300ms dal build window calcolo il delta tra `inner_size()` effettivo e quello
  richiesto (`CSD_DELTA`)
- Al `Resized` event sottraggo il delta prima di salvare
- Debounce di 1s (contatore atomico) per non scrivere sul disco a ogni pixel di drag

## Invocazione in development

```bash
cd client
pnpm install          # prima volta
pnpm tauri dev        # hot reload di src/; rebuild solo su cambi Rust
```

Al primo run Rust compila tutta la dependency tree (qualche minuto). Reload di
`src/*.html|js|css` non richiedono rebuild, F5 nella webview basta. Modifiche a
`src-tauri/**` richiedono restart del processo dev.

## Note di stile UI

- Tema tri-stato (sistema / light / dark), icone `◐ / ☀️ / 🌙`. `data-theme` viene
  sempre impostato a "light" o "dark" (valore *effettivo*); CSS definisce le variabili
  per entrambi. Ascolto `prefers-color-scheme` quando tema = "sistema".
- Contrasto WCAG AA sui bottoni con `background: var(--accent)`: il testo è
  `--on-accent` (bianco in light, quasi-nero in dark) invece di `white` fisso.
  Motivo: in dark il teal chiaro `#2dd4bf` su bianco dà contrasto 1.6:1.
- Icone SVG inline con `currentColor` → ereditano il colore del bottone.

## Cose da NON fare

- Non usare framework JS / build step complessi: lo stack resta vanilla per coerenza
  con fabot e per semplicità di debug nella webview.
- Non persistere i tag calcolati lato client (né lato server): sono una funzione
  pura delle regex + descrizioni, ricalcolarli è più rapido che invalidarli.
- Non chiamare il server con URL assoluti hard-coded: usa sempre `apiUrl(path)` che
  prepone `state.serverUrl`.
