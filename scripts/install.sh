#!/usr/bin/env bash
# ============================================================================
# DOIN — Decentralized Optimization and Inference Network
# One-line installer for Linux (Ubuntu/Debian, Fedora/RHEL, Arch)
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/harveybc/doin-core/master/scripts/install.sh | bash
#
# Or clone and run:
#   git clone https://github.com/harveybc/doin-core.git && bash doin-core/scripts/install.sh
#
# Options:
#   --dev       Install in editable mode (for development)
#   --no-test   Skip running tests after install
#   --prefix    Install to a custom prefix (default: user)
# ============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[DOIN]${NC} $*"; }
ok()    { echo -e "${GREEN}[DOIN]${NC} $*"; }
warn()  { echo -e "${YELLOW}[DOIN]${NC} $*"; }
fail()  { echo -e "${RED}[DOIN]${NC} $*"; exit 1; }

# ── Parse args ───────────────────────────────────────────────────────
DEV_MODE=false
RUN_TESTS=true
INSTALL_DIR="$HOME/doin"

for arg in "$@"; do
    case $arg in
        --dev)      DEV_MODE=true ;;
        --no-test)  RUN_TESTS=false ;;
        --prefix=*) INSTALL_DIR="${arg#*=}" ;;
        *)          warn "Unknown option: $arg" ;;
    esac
done

# ── Pre-flight checks ───────────────────────────────────────────────
info "Checking prerequisites..."

# Python 3.10+
if ! command -v python3 &>/dev/null; then
    fail "Python 3 not found. Install with: sudo apt install python3 python3-pip python3-venv"
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]); then
    fail "Python 3.10+ required (found $PY_VERSION)"
fi
ok "Python $PY_VERSION ✓"

# pip
if ! python3 -m pip --version &>/dev/null; then
    fail "pip not found. Install with: sudo apt install python3-pip"
fi
ok "pip ✓"

# git
if ! command -v git &>/dev/null; then
    fail "git not found. Install with: sudo apt install git"
fi
ok "git ✓"

# ── Create virtual environment ───────────────────────────────────────
VENV_DIR="$INSTALL_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    info "Creating virtual environment at $VENV_DIR..."
    mkdir -p "$INSTALL_DIR"
    python3 -m venv "$VENV_DIR"
fi

# Activate venv
source "$VENV_DIR/bin/activate"
ok "Virtual environment activated ✓"

# Upgrade pip
pip install --upgrade pip setuptools wheel -q

# ── Install DOIN packages ────────────────────────────────────────────
PACKAGES=(doin-core doin-node doin-optimizer doin-evaluator doin-plugins)
GITHUB_BASE="https://github.com/harveybc"

if [ "$DEV_MODE" = true ]; then
    info "Installing in development mode (editable)..."
    cd "$INSTALL_DIR"

    for pkg in "${PACKAGES[@]}"; do
        if [ ! -d "$pkg" ]; then
            info "Cloning $pkg..."
            git clone "$GITHUB_BASE/$pkg.git"
        else
            info "Updating $pkg..."
            cd "$pkg" && git pull origin master && cd ..
        fi
    done

    # Install in order (core first)
    for pkg in "${PACKAGES[@]}"; do
        info "Installing $pkg (editable)..."
        pip install -e "$pkg" -q
    done

    # Install dev dependencies
    pip install pytest pytest-asyncio pytest-cov -q

else
    info "Installing from GitHub (release mode)..."
    for pkg in "${PACKAGES[@]}"; do
        info "Installing $pkg..."
        pip install "git+$GITHUB_BASE/$pkg.git" -q
    done
fi

ok "All DOIN packages installed ✓"

# ── Run tests ────────────────────────────────────────────────────────
if [ "$RUN_TESTS" = true ] && [ "$DEV_MODE" = true ]; then
    info "Running tests..."
    TOTAL=0
    ALL_PASS=true

    for pkg in "${PACKAGES[@]}"; do
        cd "$INSTALL_DIR/$pkg"
        RESULT=$(python3 -m pytest tests/ -q --tb=short 2>&1 || true)
        PASSED=$(echo "$RESULT" | grep -oP '^\d+(?= passed)' || echo "0")
        FAILED=$(echo "$RESULT" | grep -oP '\d+(?= failed)' || echo "0")

        if [ "$FAILED" != "0" ] && [ -n "$FAILED" ]; then
            warn "$pkg: $PASSED passed, $FAILED FAILED"
            ALL_PASS=false
        else
            ok "$pkg: $PASSED passed ✓"
        fi
        TOTAL=$((TOTAL + PASSED))
    done

    if [ "$ALL_PASS" = true ]; then
        ok "All $TOTAL tests passed ✓"
    else
        warn "Some tests failed — check output above"
    fi
fi

# ── Create convenience scripts ───────────────────────────────────────
BIN_DIR="$INSTALL_DIR/bin"
mkdir -p "$BIN_DIR"

cat > "$BIN_DIR/doin-activate" << 'EOF'
#!/usr/bin/env bash
# Source this to activate the DOIN environment
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOIN_DIR="$(dirname "$SCRIPT_DIR")"
source "$DOIN_DIR/.venv/bin/activate"
echo "DOIN environment activated ($(python3 --version))"
EOF
chmod +x "$BIN_DIR/doin-activate"

# ── Print summary ────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
ok "DOIN installed successfully!"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  Install dir:  $INSTALL_DIR"
echo "  Virtual env:  $VENV_DIR"
echo ""
echo "  To activate:  source $BIN_DIR/doin-activate"
echo "  To run node:  doin-node --config config.json"
echo "  To run tests: cd $INSTALL_DIR && pytest"
echo ""
echo "  Quick start:"
echo "    source $BIN_DIR/doin-activate"
echo "    doin-node --config $INSTALL_DIR/doin-node/examples/predictor_node_config.json"
echo ""
echo "═══════════════════════════════════════════════════════════════"
