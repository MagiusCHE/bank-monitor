# Bank Monitor — Client

App desktop in [Tauri](https://tauri.app) (Rust + frontend HTML/JS vanilla)
per visualizzare, analizzare e classificare i movimenti bancari gestiti dal
server REST di Bank Monitor.

Fa parte del progetto [Bank Monitor](../README.md): questo modulo è la GUI
locale dell'utente. Non contiene logica di dominio: parsing, dedup e
classificazione vivono nel [server](../server/README.md). Il client si limita
a fare fetch degli endpoint REST e a renderizzare grafici e tabelle.

## Concept

- **Upload** di file `.xlsx` Fineco verso il server (`POST /api/upload`) con
  dedup idempotente lato server.
- **Grafico del saldo** nel tempo, in due modalità: cumulativo su tutti i conti
  oppure una linea per conto. Toggle "escludi compravendite/titoli" per vedere
  il saldo al netto del trading.
- **Vista Gruppi**: bar chart impilato (rosso uscite, verde entrate) per
  categoria, con drill-down cliccabile sulla singola barra → tabella dei
  movimenti di quel gruppo in quel periodo.
- **Editor tag-rules e gruppi** direttamente dall'UI: le modifiche vengono
  salvate sul server e sono immediatamente visibili da qualunque altro client
  collegato allo stesso server.
- **Movimenti non taggati**: sezione dedicata per vedere cosa manca ancora da
  classificare e creare nuove regole al volo.
- **Tema** chiaro / scuro / sistema, dimensioni finestra persistite tra una
  sessione e l'altra.

Stack deliberatamente minimale: nessun framework JS, nessun build step del
frontend, [Chart.js](https://www.chartjs.org/) caricato come unica dipendenza
grafica. Dettagli di architettura, stato, quirk Wayland, ecc. in
[AGENTS.md](AGENTS.md).

## Prerequisiti

- **Node.js** + [pnpm](https://pnpm.io/) per il frontend e la CLI Tauri
- **Rust** (stable) via [rustup](https://rustup.rs/) per il backend Tauri
- Dipendenze di sistema per Tauri: vedi [guida ufficiale](https://tauri.app/start/prerequisites/)
  (su Linux tipicamente `webkit2gtk`, `libayatana-appindicator`, ecc.)

## Avvio in sviluppo

```bash
cd client
pnpm install          # solo la prima volta
pnpm tauri dev
```

La prima compilazione Rust/Tauri richiede qualche minuto (compila tutta la
dependency tree); le successive partono in pochi secondi. Modifiche a
`src/*.html|js|css` sono hot-reload nella webview; modifiche a `src-tauri/**`
richiedono il restart automatico del processo dev.

## Build di release

```bash
cd client
pnpm tauri build
```

Gli artefatti (eseguibile + bundle specifico per OS) finiscono in
`src-tauri/target/release/bundle/`.

## Configurazione del client dopo aver lanciato il server

Il client parte senza sapere dov'è il server: va configurato una volta sola.

1. **Avvia il server** — vedi [server/README.md](../server/README.md). Di default
   ascolta su `http://0.0.0.0:8765`.

2. **Avvia il client** (`pnpm tauri dev` oppure l'eseguibile di release).

3. Apri il pannello **Impostazioni** (icona ⚙ in alto a destra).

4. Inserisci l'URL del server nel campo **"URL server"**:
   - server sullo stesso PC → `http://127.0.0.1:8765`
   - server su un altro host in LAN (es. Raspberry Pi) →
     `http://<hostname-o-ip>:8765` (p.es. `http://bank-monitor-server:8765`
     oppure `http://192.168.1.42:8765`)

5. Clicca **"Test connessione"**. Se il server risponde su `/api/health` vedi
   un check verde; se fallisce controlla host/porta, firewall e che il server
   sia effettivamente avviato.

6. Clicca **"Salva"**. La configurazione viene scritta in
   `~/.config/bank-monitor/config.json` (su Linux; path equivalente su
   macOS/Windows via `dirs::config_dir()`).

7. Nella barra superiore clicca **"Carica file"** e seleziona un estratto
   `.xlsx` Fineco. Il server lo ingerisce e il grafico si popola.

Da qui in poi il client ricorda l'URL e si riconnette automaticamente a ogni
avvio. Per cambiare server basta tornare in Impostazioni.

### Note

- Se esponi il server in rete domestica, sostituisci `0.0.0.0` con l'IP
  corretto e assicurati che la porta `8765` sia raggiungibile.
- Il client **non** gira sul Raspberry Pi: gira sul PC dell'utente e si
  collega via rete al server sul Pi.
- Più client collegati allo stesso server vedono gli stessi dati e le stesse
  regole: modifiche a tag-rules/gruppi sono visibili agli altri al successivo
  refresh (pulsante "Ricarica" nel pannello classificazione).

## Dove finiscono le cose

| Cosa | Dove |
|---|---|
| Config locale (URL server, tema, dimensioni finestra) | `~/.config/bank-monitor/config.json` |
| Transazioni + tag-rules + gruppi | Sul server (SQLite) — il client non cacha |
| Frontend | [src/](src/) (HTML + JS + CSS vanilla) |
| Backend Tauri | [src-tauri/src/](src-tauri/src/) (`get_config`, `set_config`, `save_window_size`) |
