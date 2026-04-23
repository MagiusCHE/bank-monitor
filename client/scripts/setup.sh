#!/usr/bin/env bash
# Bank Monitor - Setup script for Linux
# Installs all required dependencies: Rust, Node.js, pnpm, system libraries
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

check_cmd() { command -v "$1" &>/dev/null; }

# Detect distro
detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo "$ID"
    else
        error "Cannot detect Linux distribution"
    fi
}

DISTRO=$(detect_distro)
info "Detected distribution: $DISTRO"

# ── System dependencies (Tauri v2 prerequisites) ──

install_system_deps() {
    case "$DISTRO" in
        arch|manjaro|endeavouros)
            info "Installing system dependencies (pacman)..."
            sudo pacman -S --needed --noconfirm \
                webkit2gtk-4.1 base-devel curl wget file openssl \
                appmenu-gtk-module gtk3 libappindicator-gtk3 librsvg
            ;;
        ubuntu|debian|linuxmint|pop)
            info "Installing system dependencies (apt)..."
            sudo apt-get update
            sudo apt-get install -y \
                libwebkit2gtk-4.1-dev build-essential curl wget file \
                libssl-dev libayatana-appindicator3-dev librsvg2-dev \
                libgtk-3-dev
            ;;
        fedora)
            info "Installing system dependencies (dnf)..."
            sudo dnf install -y \
                webkit2gtk4.1-devel openssl-devel curl wget file \
                libappindicator-gtk3-devel librsvg2-devel gcc-c++ \
                gtk3-devel
            ;;
        opensuse*|suse*)
            info "Installing system dependencies (zypper)..."
            sudo zypper install -y \
                webkit2gtk3-devel libopenssl-devel curl wget file \
                libappindicator3-devel librsvg-devel gcc-c++ \
                gtk3-devel
            ;;
        *)
            warn "Unknown distro '$DISTRO'. Install Tauri v2 prerequisites manually:"
            warn "https://v2.tauri.app/start/prerequisites/"
            ;;
    esac
}

install_system_deps

# ── Rust ──

if check_cmd rustc; then
    RUST_VER=$(rustc --version)
    info "Rust already installed: $RUST_VER"
else
    info "Installing Rust via rustup..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    source "$HOME/.cargo/env"
    info "Rust installed: $(rustc --version)"
fi

# ── Node.js ──

if check_cmd node; then
    NODE_VER=$(node --version)
    info "Node.js already installed: $NODE_VER"
    NODE_MAJOR=$(echo "$NODE_VER" | sed 's/v\([0-9]*\).*/\1/')
    if [ "$NODE_MAJOR" -lt 18 ]; then
        warn "Node.js $NODE_VER is too old (need >= 18). Please upgrade manually."
    fi
else
    info "Installing Node.js via nvm..."
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
    export NVM_DIR="$HOME/.nvm"
    [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
    nvm install --lts
    info "Node.js installed: $(node --version)"
fi

# ── pnpm ──

if check_cmd pnpm; then
    info "pnpm already installed: $(pnpm --version)"
else
    info "Installing pnpm..."
    if check_cmd corepack; then
        corepack enable
        corepack prepare pnpm@latest --activate
    else
        npm install -g pnpm
    fi
    info "pnpm installed: $(pnpm --version)"
fi

# ── Project dependencies ──

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLIENT_DIR="$(dirname "$SCRIPT_DIR")"

info "Installing project dependencies..."
cd "$CLIENT_DIR"
pnpm install

echo ""
info "Setup complete! You can now run:"
echo "  cd $CLIENT_DIR"
echo "  pnpm tauri dev"
