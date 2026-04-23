# Bank Monitor - Setup script for Windows
# Installs all required dependencies: Rust, Node.js, pnpm
# Run: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

$ErrorActionPreference = "Stop"

function Write-Info  { Write-Host "[INFO] $args" -ForegroundColor Green }
function Write-Warn  { Write-Host "[WARN] $args" -ForegroundColor Yellow }
function Write-Err   { Write-Host "[ERROR] $args" -ForegroundColor Red; exit 1 }

function Test-Command { param($Name) $null -ne (Get-Command $Name -ErrorAction SilentlyContinue) }

# Check winget
if (-not (Test-Command "winget")) {
    Write-Err "winget not found. Install App Installer from the Microsoft Store."
}

# ── Rust ──

if (Test-Command "rustc") {
    $rustVer = rustc --version
    Write-Info "Rust already installed: $rustVer"
} else {
    Write-Info "Installing Rust via winget..."
    winget install --id Rustlang.Rustup -e --accept-source-agreements --accept-package-agreements
    # rustup-init runs automatically; refresh PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    if (Test-Command "rustup") {
        rustup default stable
        Write-Info "Rust installed: $(rustc --version)"
    } else {
        Write-Warn "Rust installed but not in PATH yet. Restart your terminal after setup."
    }
}

# ── Node.js ──

if (Test-Command "node") {
    $nodeVer = node --version
    Write-Info "Node.js already installed: $nodeVer"
    $major = [int]($nodeVer -replace 'v(\d+)\..*', '$1')
    if ($major -lt 18) {
        Write-Warn "Node.js $nodeVer is too old (need >= 18). Upgrading..."
        winget install --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements
    }
} else {
    Write-Info "Installing Node.js LTS via winget..."
    winget install --id OpenJS.NodeJS.LTS -e --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
}

# ── pnpm ──

if (Test-Command "pnpm") {
    Write-Info "pnpm already installed: $(pnpm --version)"
} else {
    Write-Info "Installing pnpm..."
    if (Test-Command "corepack") {
        corepack enable
        corepack prepare pnpm@latest --activate
    } else {
        npm install -g pnpm
    }
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
    if (Test-Command "pnpm") {
        Write-Info "pnpm installed: $(pnpm --version)"
    } else {
        Write-Warn "pnpm installed but not in PATH yet. Restart your terminal."
    }
}

# ── WebView2 (required by Tauri on Windows) ──

$webview2 = Get-ItemProperty -Path "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" -ErrorAction SilentlyContinue
if ($webview2) {
    Write-Info "WebView2 Runtime already installed"
} else {
    Write-Info "Installing WebView2 Runtime..."
    winget install --id Microsoft.EdgeWebView2Runtime -e --accept-source-agreements --accept-package-agreements
}

# ── Project dependencies ──

$clientDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Write-Info "Installing project dependencies..."
Push-Location $clientDir
try {
    if (Test-Command "pnpm") {
        pnpm install
    } else {
        Write-Warn "pnpm not in PATH yet. Run 'pnpm install' after restarting the terminal."
    }
} finally {
    Pop-Location
}

Write-Host ""
Write-Info "Setup complete! Restart your terminal, then run:"
Write-Host "  cd $clientDir"
Write-Host "  pnpm tauri dev"
