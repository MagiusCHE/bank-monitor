#!/usr/bin/env bash
set -euo pipefail

# Release remota: allinea le versioni (package.json / Cargo.toml / tauri.conf.json),
# committa, pusha e crea/aggiorna il tag vX.Y.Z. La build degli artefatti avviene
# poi nel workflow GitHub (.github/workflows/release.yml) triggerato dal tag.

# Carica le variabili d'ambiente di direnv (es. GH_CONFIG_DIR per selezionare
# l'identità GitHub corretta) se direnv è disponibile.
if command -v direnv >/dev/null 2>&1; then
  eval "$(direnv export bash)"
fi

# Lo script vive in client/scripts/ ma il repo git ha root un livello sopra
# (client/). Operiamo sulla client dir per le modifiche ai file di versione,
# ma i comandi git toccano l'intero repo.
CLIENT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$CLIENT_DIR"

VERSION="v$(node -p "require('./package.json').version")"

# Verifica che non ci siano modifiche non committate (nell'intero repo)
if [ -n "$(git status --porcelain)" ]; then
  echo "Errore: ci sono modifiche non committate. Fai commit prima di lanciare la release."
  exit 1
fi

# Verifica che non ci siano commit non pushati
UPSTREAM=$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null) || true
if [ -n "$UPSTREAM" ]; then
  LOCAL=$(git rev-parse HEAD)
  REMOTE=$(git rev-parse "$UPSTREAM")
  if [ "$LOCAL" != "$REMOTE" ]; then
    echo "Errore: ci sono commit non pushati. Fai push prima di lanciare la release."
    exit 1
  fi
fi

# Allinea versione in tauri.conf.json e Cargo.toml
SEMVER="${VERSION#v}"
sed -i "s/\"version\": \"[^\"]*\"/\"version\": \"$SEMVER\"/" src-tauri/tauri.conf.json
sed -i "s/^version = \"[^\"]*\"/version = \"$SEMVER\"/" src-tauri/Cargo.toml
cargo generate-lockfile --manifest-path src-tauri/Cargo.toml

# Commit allineamento versioni (se ci sono differenze)
if [ -n "$(git diff --name-only)" ]; then
  git add .
  git commit -m "Bump version to $SEMVER"
  echo "Push commits..."
  git push
fi

# Crea o sovrascrive il tag
if git rev-parse "$VERSION" >/dev/null 2>&1; then
  echo "Tag $VERSION esiste, sovrascrivo..."
  git tag -f "$VERSION"
  git push origin "$VERSION" --force
else
  echo "Creo tag $VERSION..."
  git tag "$VERSION"
  git push origin "$VERSION"
fi

echo "Done. Il workflow GitHub creerà la release $VERSION."
