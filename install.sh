#!/usr/bin/env bash
# resume-generator one-line installer for macOS and Linux
# Usage: curl -sSL https://raw.githubusercontent.com/ALDRIN121/resume-agent/main/install.sh | bash

set -e

REPO_URL="https://github.com/ALDRIN121/resume-agent.git"
INSTALL_DIR="${RESUME_GENERATOR_DIR:-$HOME/.local/share/resume-generator}"
BIN_DIR="$HOME/.local/bin"

_bold="\033[1m"
_green="\033[32m"
_yellow="\033[33m"
_red="\033[31m"
_reset="\033[0m"

info()    { echo -e "${_bold}  →${_reset} $*"; }
success() { echo -e "${_green}  ✓${_reset} $*"; }
warn()    { echo -e "${_yellow}  ⚠${_reset} $*"; }
error()   { echo -e "${_red}  ✗${_reset} $*"; exit 1; }

echo ""
echo -e "${_bold}Installing resume-generator…${_reset}"
echo ""

# ── 1. Check for git ───────────────────────────────────────────────────────────
if ! command -v git &>/dev/null; then
    error "git is required but not found. Install git first:
  macOS:  brew install git
  Ubuntu: sudo apt install git
  Arch:   sudo pacman -S git"
fi
success "git found: $(git --version)"

# ── 2. Check for / install uv ─────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
    info "uv not found — installing uv (Python package manager)…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    if ! command -v uv &>/dev/null; then
        error "uv installation failed. Install manually: https://docs.astral.sh/uv/"
    fi
fi
success "uv found: $(uv --version)"

# ── 3. Clone or update the repo ───────────────────────────────────────────────
if [ -d "$INSTALL_DIR/.git" ]; then
    info "Existing installation found — updating…"
    git -C "$INSTALL_DIR" pull --ff-only
else
    info "Cloning repository to $INSTALL_DIR…"
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone "$REPO_URL" "$INSTALL_DIR"
fi
success "Repository ready."

# ── 4. Install the CLI with uv tool ───────────────────────────────────────────
info "Installing resume-generator CLI…"
cd "$INSTALL_DIR"
uv tool install . --force
success "resume-generator installed."

# ── 5. PATH guidance ──────────────────────────────────────────────────────────
mkdir -p "$BIN_DIR"

if ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
    warn "$HOME/.local/bin is not in your PATH."
    echo ""
    echo "  Add this line to your shell config (~/.bashrc, ~/.zshrc, etc.):"
    echo ""
    echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
    echo "  Then reload your shell:  source ~/.zshrc  (or open a new terminal)"
    echo ""
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${_bold}${_green}Installation complete!${_reset}"
echo ""
echo "  Next steps:"
echo "    1.  resume-generator doctor       # verify Tectonic and Poppler are installed"
echo "    2.  resume-generator install-deps # install missing tools automatically"
echo "    3.  resume-generator              # first-time setup (choose AI provider)"
echo ""
