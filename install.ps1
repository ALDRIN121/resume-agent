# resume-generator one-line installer for Windows (PowerShell)
# Usage: irm https://raw.githubusercontent.com/ALDRIN121/resume-agent/main/install.ps1 | iex

$ErrorActionPreference = "Stop"

$REPO_URL   = "https://github.com/ALDRIN121/resume-agent.git"
$INSTALL_DIR = if ($env:RESUME_GENERATOR_DIR) { $env:RESUME_GENERATOR_DIR } `
               else { "$env:LOCALAPPDATA\resume-generator" }

function Write-Step($msg)    { Write-Host "  -> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)      { Write-Host "  v  $msg" -ForegroundColor Green }
function Write-Warn($msg)    { Write-Host "  !  $msg" -ForegroundColor Yellow }
function Write-Fail($msg)    { Write-Host "  x  $msg" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "Installing resume-generator..." -ForegroundColor White -BackgroundColor DarkBlue
Write-Host ""

# ── 1. Check for git ──────────────────────────────────────────────────────────
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Fail "git is required but not found.
  Install git from: https://git-scm.com/download/win
  Or via winget:    winget install Git.Git"
}
Write-Ok "git found: $(git --version)"

# ── 2. Check for / install uv ─────────────────────────────────────────────────
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Step "uv not found — installing uv (Python package manager)..."
    try {
        irm https://astral.sh/uv/install.ps1 | iex
        # Reload PATH so uv is immediately available
        $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "User") + ";" + $env:PATH
    } catch {
        Write-Fail "uv installation failed: $_`nInstall manually: https://docs.astral.sh/uv/"
    }
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Fail "uv was installed but is not on PATH yet. Open a new terminal and re-run this script."
    }
}
Write-Ok "uv found: $(uv --version)"

# ── 3. Clone or update the repo ───────────────────────────────────────────────
if (Test-Path "$INSTALL_DIR\.git") {
    Write-Step "Existing installation found — updating..."
    git -C $INSTALL_DIR pull --ff-only
} else {
    Write-Step "Cloning repository to $INSTALL_DIR..."
    $parentDir = Split-Path $INSTALL_DIR -Parent
    if (-not (Test-Path $parentDir)) { New-Item -ItemType Directory -Path $parentDir | Out-Null }
    git clone $REPO_URL $INSTALL_DIR
}
Write-Ok "Repository ready."

# ── 4. Install the CLI with uv tool ───────────────────────────────────────────
Write-Step "Installing resume-generator CLI..."
Push-Location $INSTALL_DIR
try {
    uv tool install . --force
} finally {
    Pop-Location
}
Write-Ok "resume-generator installed."

# ── 5. PATH guidance ──────────────────────────────────────────────────────────
$uvToolBin = "$env:APPDATA\uv\bin"
$userPath  = [System.Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notlike "*$uvToolBin*") {
    Write-Warn "$uvToolBin is not in your PATH."
    Write-Host ""
    Write-Host "  To fix this, run the following in PowerShell:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "    `$env:PATH += `";$uvToolBin`"" -ForegroundColor White
    Write-Host "    [System.Environment]::SetEnvironmentVariable('PATH', `"`$env:PATH`", 'User')" -ForegroundColor White
    Write-Host ""
    Write-Host "  Then open a new terminal." -ForegroundColor Yellow
    Write-Host ""
}

$rgCmd = Get-Command resume-generator -ErrorAction SilentlyContinue
if ($rgCmd) {
    $RG_BIN = $rgCmd.Source
} else {
    $RG_BIN = "$uvToolBin\resume-generator.exe"
}

# ── 6. Install system dependencies (Tectonic + Poppler) ───────────────────────
Write-Step "Installing Tectonic and Poppler (PDF generation tools)..."
try {
    & $RG_BIN install-deps
} catch {
    Write-Warn "Some dependencies could not be installed automatically. You can retry later with: resume-generator install-deps"
}

# ── Done ──────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Installation complete!" -ForegroundColor Green
Write-Host ""

# ── 7. Launch the web UI ───────────────────────────────────────────────────────
if ((Test-Path $RG_BIN) -and [Environment]::UserInteractive) {
    Write-Host "  Starting the web UI at http://127.0.0.1:8000 ..."
    Write-Host "  Pick your AI provider and enter your API key on the Settings page."
    Write-Host "  Press Ctrl+C to stop the server."
    Write-Host ""
    Start-Job -ScriptBlock {
        Start-Sleep -Seconds 3
        Start-Process "http://127.0.0.1:8000"
    } | Out-Null
    & $RG_BIN serve
} else {
    Write-Host "  Next steps:"
    Write-Host "    1.  resume-generator serve   # launch the web UI at http://127.0.0.1:8000"
    Write-Host "    2.  resume-generator doctor  # verify Tectonic and Poppler are installed"
    Write-Host ""
    Write-Host "  To get future updates:  resume-generator update  (or re-run this installer)"
    Write-Host ""
}
