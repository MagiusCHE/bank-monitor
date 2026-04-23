#!/usr/bin/env bash
set -euo pipefail

# Carica le variabili d'ambiente di direnv (es. GH_CONFIG_DIR per selezionare
# l'identità GitHub corretta) se direnv è disponibile.
if command -v direnv >/dev/null 2>&1; then
  eval "$(direnv export bash)"
fi

# Release locale: replica quello che fa il workflow GitHub, senza consumare
# minuti CI. Flusso:
#   1) verifica working tree pulito e commit pushati
#   2) bumpa la versione in tauri.conf.json / Cargo.toml se serve
#   3) crea/aggiorna il tag e lo pusha
#   4) buildda gli artefatti Linux (deb/rpm/AppImage) e l'APK Android firmato
#   5) elimina la release esistente (se presente) e ne crea una nuova su GitHub
#   6) carica tutti gli artefatti come asset
#
# NB: produce solo gli artefatti che puoi generare dalla tua macchina (Linux).
# Windows/macOS sono skip-pati: serviva il workflow CI per compilarli.

CLIENT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$CLIENT_DIR/.." && pwd)"
cd "$CLIENT_DIR"

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run|-n) DRY_RUN=1 ;;
  esac
done

VERSION="v$(node -p "require('./package.json').version")"
SEMVER="${VERSION#v}"

if [ "$DRY_RUN" -eq 1 ]; then
  echo "*** DRY RUN: niente commit, tag, push o release GitHub. Solo build+stage."
fi

# --- Pre-flight git ------------------------------------------------------
if [ "$DRY_RUN" -eq 0 ]; then
  if [ -n "$(git status --porcelain)" ]; then
    echo "Errore: ci sono modifiche non committate. Fai commit prima di lanciare la release."
    exit 1
  fi

  UPSTREAM=$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null) || true
  if [ -n "$UPSTREAM" ]; then
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse "$UPSTREAM")
    if [ "$LOCAL" != "$REMOTE" ]; then
      echo "Errore: ci sono commit non pushati. Fai push prima di lanciare la release."
      exit 1
    fi
  fi
fi

# --- gh CLI --------------------------------------------------------------
if ! command -v gh >/dev/null 2>&1; then
  echo "Errore: gh CLI non installato. Installa con: sudo pacman -S github-cli"
  exit 1
fi
if ! gh auth status >/dev/null 2>&1; then
  echo "Errore: gh non autenticato. Esegui: gh auth login"
  exit 1
fi

# --- Allineamento versioni -----------------------------------------------
if [ "$DRY_RUN" -eq 0 ]; then
  sed -i "s/\"version\": \"[^\"]*\"/\"version\": \"$SEMVER\"/" src-tauri/tauri.conf.json
  sed -i "s/^version = \"[^\"]*\"/version = \"$SEMVER\"/" src-tauri/Cargo.toml
  cargo generate-lockfile --manifest-path src-tauri/Cargo.toml

  if [ -n "$(git diff --name-only)" ]; then
    git add .
    git commit -m "Bump version to $SEMVER"
    echo "Push commits..."
    git push
  fi

  # --- Tag ---------------------------------------------------------------
  if git rev-parse "$VERSION" >/dev/null 2>&1; then
    echo "Tag $VERSION esiste, sovrascrivo..."
    git tag -f "$VERSION"
    git push origin "$VERSION" --force
  else
    echo "Creo tag $VERSION..."
    git tag "$VERSION"
    git push origin "$VERSION"
  fi
else
  echo "[dry-run] skip bump/commit/push/tag"
fi

# --- Build Linux ---------------------------------------------------------
echo ""
echo "=== Build bundle Linux (deb, rpm, AppImage) ==="
NO_STRIP=1 pnpm exec tauri build --bundles deb,rpm,appimage

# --- Build Android APK ---------------------------------------------------
echo ""
echo "=== Build APK Android firmato ==="
./scripts/build-apk.sh

# --- Raccolta artefatti --------------------------------------------------
STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT

echo ""
echo "=== Raccolta artefatti ==="
shopt -s nullglob
# Filtra per versione corrente: i naming di tauri sono
#   deb:      Bank Monitor_<semver>_amd64.deb
#   rpm:      Bank Monitor-<semver>-1.x86_64.rpm
#   appimage: Bank Monitor_<semver>_amd64.AppImage
# così evitiamo di includere artefatti di build precedenti rimasti in target/
for f in src-tauri/target/release/bundle/deb/*_"${SEMVER}"_*.deb \
         src-tauri/target/release/bundle/rpm/*-"${SEMVER}"-*.rpm \
         src-tauri/target/release/bundle/appimage/*_"${SEMVER}"_*.AppImage; do
  cp -v "$f" "$STAGING/"
done

# APK: rinomina come fa il workflow (bank-monitor-<semver>.apk)
APK_SRC=""
for candidate in \
  src-tauri/gen/android/app/build/outputs/apk/universal/release/*.apk \
  src-tauri/gen/android/app/build/outputs/apk/release/*.apk; do
  if [ -f "$candidate" ]; then
    APK_SRC="$candidate"
    break
  fi
done
if [ -z "$APK_SRC" ]; then
  APK_SRC="$(find src-tauri/gen/android -name "*.apk" -path "*/release/*" 2>/dev/null | head -1 || true)"
fi
if [ -n "$APK_SRC" ] && [ -f "$APK_SRC" ]; then
  cp -v "$APK_SRC" "$STAGING/bank-monitor-$SEMVER.apk"
else
  echo "Avviso: nessun APK trovato, skip"
fi
shopt -u nullglob

if [ -z "$(ls -A "$STAGING")" ]; then
  echo "Errore: nessun artefatto raccolto, interrompo."
  exit 1
fi

echo ""
echo "Artefatti pronti:"
ls -la "$STAGING"

# --- Release GitHub ------------------------------------------------------
if [ "$DRY_RUN" -eq 1 ]; then
  echo ""
  echo "[dry-run] Avrei pubblicato la release $VERSION con questi asset:"
  for f in "$STAGING"/*; do
    echo "  - $(basename "$f") ($(du -h "$f" | cut -f1))"
  done
  # Sposto lo staging fuori dalla tmp così puoi ispezionarlo
  OUT_DIR="$REPO_ROOT/release-dry-run"
  rm -rf "$OUT_DIR"
  mkdir -p "$OUT_DIR"
  cp "$STAGING"/* "$OUT_DIR"/
  echo ""
  echo "Artefatti copiati in: $OUT_DIR"
  exit 0
fi

echo ""
echo "=== Release GitHub $VERSION ==="

# Elimina la release precedente con lo stesso tag (senza cancellare il tag,
# che abbiamo appena pushato)
if gh release view "$VERSION" >/dev/null 2>&1; then
  echo "Release $VERSION esiste, la elimino..."
  gh release delete "$VERSION" --yes
fi

# Crea la release e carica gli asset. --generate-notes lascia a GitHub il
# changelog automatico sui commit dall'ultimo tag.
gh release create "$VERSION" \
  --title "Bank Monitor $VERSION" \
  --generate-notes \
  --latest \
  "$STAGING"/*

echo ""
echo "Release $VERSION pubblicata."
gh release view "$VERSION" --web >/dev/null 2>&1 || true
