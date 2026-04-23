#!/usr/bin/env bash
set -euo pipefail

# Build APK Android per Bank Monitor.
# Gestisce:
# - rilevamento/esportazione di ANDROID_HOME e NDK_HOME
# - installazione NDK via sdkmanager se assente
# - selezione di un JDK 17/21 compatibile con Gradle
# - init del progetto Android (src-tauri/gen/android) se assente
# - firma release con bank-monitor-release.jks (credenziali in .env.signing)
# - build finale dell'APK firmato
#
# NB: la keystore e il file .env.signing vivono nella ROOT del repo (un livello
# sopra client/), così i secret non si duplicano se domani arrivano altri
# sottoprogetti firmati.

CLIENT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$CLIENT_DIR/.." && pwd)"
cd "$CLIENT_DIR"

# --- Android SDK ---------------------------------------------------------
if [ -z "${ANDROID_HOME:-}" ]; then
  for candidate in "$HOME/Android/Sdk" "$HOME/Android/sdk" "$HOME/.local/share/Android/Sdk"; do
    if [ -d "$candidate" ]; then
      export ANDROID_HOME="$candidate"
      break
    fi
  done
fi

if [ -z "${ANDROID_HOME:-}" ] || [ ! -d "$ANDROID_HOME" ]; then
  echo "Errore: ANDROID_HOME non impostato e SDK non trovato."
  echo "Installa Android SDK e/o esporta ANDROID_HOME verso la tua installazione."
  echo "Guida: https://tauri.app/start/prerequisites/#android"
  exit 1
fi
echo "ANDROID_HOME=$ANDROID_HOME"

SDKMANAGER=""
for candidate in \
  "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" \
  "$ANDROID_HOME/cmdline-tools/bin/sdkmanager" \
  "$ANDROID_HOME/tools/bin/sdkmanager"; do
  if [ -x "$candidate" ]; then
    SDKMANAGER="$candidate"
    break
  fi
done

if [ -z "$SDKMANAGER" ]; then
  echo "Errore: sdkmanager non trovato in $ANDROID_HOME (cmdline-tools mancante)."
  exit 1
fi

# --- NDK -----------------------------------------------------------------
# Se NDK_HOME punta a una dir inesistente, lo azzeriamo per riscoprirlo.
if [ -n "${NDK_HOME:-}" ] && [ ! -d "$NDK_HOME" ]; then
  echo "Avviso: NDK_HOME=$NDK_HOME non esiste, lo ignoro."
  unset NDK_HOME
fi

if [ -z "${NDK_HOME:-}" ]; then
  if [ -d "$ANDROID_HOME/ndk" ]; then
    LATEST_NDK="$(ls -1 "$ANDROID_HOME/ndk" 2>/dev/null | sort -V | tail -n1 || true)"
    if [ -n "$LATEST_NDK" ] && [ -d "$ANDROID_HOME/ndk/$LATEST_NDK" ]; then
      export NDK_HOME="$ANDROID_HOME/ndk/$LATEST_NDK"
    fi
  fi
fi

if [ -z "${NDK_HOME:-}" ]; then
  NDK_VERSION="${NDK_VERSION:-29.0.13846066}"
  echo "NDK non installato, installo ndk;$NDK_VERSION via sdkmanager..."
  yes | "$SDKMANAGER" --sdk_root="$ANDROID_HOME" --licenses >/dev/null || true
  "$SDKMANAGER" --sdk_root="$ANDROID_HOME" --install "ndk;$NDK_VERSION"
  export NDK_HOME="$ANDROID_HOME/ndk/$NDK_VERSION"
fi

if [ ! -d "$NDK_HOME" ]; then
  echo "Errore: installazione NDK fallita, $NDK_HOME non esiste."
  exit 1
fi
echo "NDK_HOME=$NDK_HOME"

# --- Java ----------------------------------------------------------------
# Gradle 8.x supporta Java fino alla 24. Se la JDK di default è più nuova
# (es. Java 25 su Manjaro), forziamo JAVA_HOME su una JDK 17/21 disponibile.
pick_jdk() {
  # Gradle buildSrc richiede un JDK completo (serve `javac`), non un semplice JRE.
  for candidate in \
    "${JAVA_HOME:-}" \
    "/usr/lib/jvm/java-21-openjdk" \
    "/usr/lib/jvm/java-21-openjdk-amd64" \
    "/usr/lib/jvm/jdk-21" \
    "/usr/lib/jvm/java-17-openjdk" \
    "/usr/lib/jvm/java-17-openjdk-amd64" \
    "/usr/lib/jvm/jdk-17"; do
    if [ -n "$candidate" ] && [ -x "$candidate/bin/javac" ]; then
      VER="$("$candidate/bin/java" -version 2>&1 | head -n1 | sed -E 's/.*"([0-9]+)[.".].*/\1/')"
      if [ -n "$VER" ] && [ "$VER" -le 24 ] 2>/dev/null; then
        echo "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

JAVA_MAJOR=""
if command -v java >/dev/null 2>&1; then
  JAVA_MAJOR="$(java -version 2>&1 | head -n1 | sed -E 's/.*"([0-9]+)[.".].*/\1/')"
fi

if [ -z "$JAVA_MAJOR" ] || [ "$JAVA_MAJOR" -gt 24 ] 2>/dev/null; then
  if PICKED="$(pick_jdk)"; then
    export JAVA_HOME="$PICKED"
    export PATH="$JAVA_HOME/bin:$PATH"
    echo "JDK di sistema non compatibile (Java ${JAVA_MAJOR:-assente}), uso JAVA_HOME=$JAVA_HOME"
  else
    echo ""
    echo "======================================================================"
    echo " Errore: nessun JDK 17/21 utilizzabile trovato."
    echo "======================================================================"
    echo ""
    echo " Gradle non supporta Java ${JAVA_MAJOR:-?} (serve <= 24) e richiede un"
    echo " JDK COMPLETO con 'javac' (non basta un JRE)."
    echo ""
    # Diagnostica: elenca cosa è presente in /usr/lib/jvm per dare contesto
    if [ -d /usr/lib/jvm ]; then
      echo " JDK/JRE rilevati in /usr/lib/jvm:"
      for d in /usr/lib/jvm/*/; do
        [ -d "$d" ] || continue
        name="$(basename "$d")"
        if [ -x "$d/bin/javac" ]; then
          ver="$("$d/bin/java" -version 2>&1 | head -n1 | sed -E 's/.*"([0-9]+)[.".].*/\1/')"
          echo "   - $name (JDK, Java $ver)"
        elif [ -x "$d/bin/java" ]; then
          echo "   - $name (solo JRE, manca javac)"
        fi
      done
      echo ""
    fi
    echo " Cosa fare (Manjaro/Arch):"
    echo "   sudo pacman -S jdk21-openjdk"
    echo ""
    echo " Viene installato in parallelo, non sostituisce la tua Java di default."
    echo " Lo script lo userà solo durante il build (JAVA_HOME temporanea)."
    echo "======================================================================"
    exit 1
  fi
fi

# --- Android project init ------------------------------------------------
if [ ! -d "src-tauri/gen/android" ]; then
  echo "Progetto Android assente, eseguo tauri android init..."
  pnpm exec tauri android init
fi

# --- Signing -------------------------------------------------------------
# L'APK deve essere firmato con bank-monitor-release.jks (in root repo).
# Così gli update sul device non richiedono disinstallazione.
KEYSTORE_FILE="$REPO_ROOT/bank-monitor-release.jks"

if [ ! -f "$KEYSTORE_FILE" ]; then
  echo ""
  echo "======================================================================"
  echo " Errore: keystore di release mancante."
  echo "======================================================================"
  echo ""
  echo " Atteso: $KEYSTORE_FILE"
  echo ""
  echo " Senza questa keystore l'APK non può essere firmato con il certificato"
  echo " di release, e Android non accetterebbe aggiornamenti sull'APK già"
  echo " installato (obbligando a disinstallare ogni volta)."
  echo ""
  echo " Per generarne una nuova (una tantum):"
  echo "   keytool -genkeypair -v -keystore bank-monitor-release.jks \\"
  echo "     -keyalg RSA -keysize 2048 -validity 10000 -alias bank-monitor"
  echo ""
  echo " NON committare il file: *.jks è già in .gitignore."
  echo "======================================================================"
  exit 1
fi

# Carica credenziali da .env.signing nella root del repo (non committato).
# Un template è in .env.signing.example.
SIGNING_ENV="$REPO_ROOT/.env.signing"
if [ -f "$SIGNING_ENV" ]; then
  # shellcheck disable=SC1090
  set -a; . "$SIGNING_ENV"; set +a
fi

missing=()
[ -z "${KEY_ALIAS:-}" ] && missing+=("KEY_ALIAS")
[ -z "${KEYSTORE_PASSWORD:-}" ] && missing+=("KEYSTORE_PASSWORD")
[ -z "${KEY_PASSWORD:-}" ] && missing+=("KEY_PASSWORD")

if [ "${#missing[@]}" -gt 0 ]; then
  echo ""
  echo "======================================================================"
  echo " Errore: credenziali di firma mancanti: ${missing[*]}"
  echo "======================================================================"
  echo ""
  echo " Copia .env.signing.example in .env.signing e compila i valori:"
  echo "   cp .env.signing.example .env.signing"
  echo "   \$EDITOR .env.signing"
  echo ""
  echo " Il file .env.signing non viene committato (già in .gitignore)."
  echo " (o esporta le variabili nell'ambiente prima di lanciare lo script)"
  echo "======================================================================"
  exit 1
fi

# Inietta il blocco signingConfig in build.gradle.kts in modo idempotente.
GRADLE_APP="src-tauri/gen/android/app/build.gradle.kts"
if [ -f "$GRADLE_APP" ]; then
  if ! grep -q "BANK_MONITOR_SIGNING_BEGIN" "$GRADLE_APP"; then
    python3 - "$GRADLE_APP" "$KEYSTORE_FILE" <<'PY'
import sys, pathlib
path = pathlib.Path(sys.argv[1])
keystore_abs = sys.argv[2]
src = path.read_text()

signing_block = f'''    // BANK_MONITOR_SIGNING_BEGIN (injected by scripts/build-apk.sh — do not edit)
    signingConfigs {{
        create("release") {{
            storeFile = file(System.getenv("KEYSTORE_PATH") ?: "{keystore_abs}")
            storePassword = System.getenv("KEYSTORE_PASSWORD")
            keyAlias = System.getenv("KEY_ALIAS")
            keyPassword = System.getenv("KEY_PASSWORD")
        }}
    }}
    // BANK_MONITOR_SIGNING_END
'''

# Inserisci signingConfigs subito prima di `buildTypes {`
marker = "    buildTypes {"
if marker not in src:
    raise SystemExit("marker 'buildTypes {' non trovato in build.gradle.kts")
src = src.replace(marker, signing_block + "\n" + marker, 1)

# Aggiungi signingConfig al blocco release
old_release = 'getByName("release") {'
new_release = 'getByName("release") {\n            signingConfig = signingConfigs.getByName("release")'
if old_release in src and 'signingConfigs.getByName("release")' not in src:
    src = src.replace(old_release, new_release, 1)

path.write_text(src)
print("Signing config iniettato in build.gradle.kts")
PY
  else
    echo "Signing config già presente in build.gradle.kts"
  fi
fi

export KEYSTORE_PATH="$KEYSTORE_FILE"
export KEY_ALIAS KEYSTORE_PASSWORD KEY_PASSWORD

# --- Stop eventuali daemon Gradle con JVM vecchia -----------------------
# Se un build precedente ha lasciato un daemon agganciato a una JAVA_HOME
# diversa, Gradle ignora il nuovo JAVA_HOME e fallisce con
# "Toolchain ... does not provide JAVA_COMPILER". Meglio partire puliti.
GRADLEW="src-tauri/gen/android/gradlew"
if [ -x "$GRADLEW" ]; then
  "$GRADLEW" --stop >/dev/null 2>&1 || true
fi

# --- Build ---------------------------------------------------------------
echo "Avvio build APK..."
pnpm exec tauri android build --apk "$@"

echo ""
echo "Build completato. Cerca l'APK in:"
echo "  src-tauri/gen/android/app/build/outputs/apk/"
