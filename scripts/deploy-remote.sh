#!/usr/bin/env bash
# ============================================================================
# DOIN Remote Deployment — Install and launch a DOIN node on a remote machine
#
# Usage:
#   ./deploy-remote.sh user@host [--optimize] [--port 8470] [--peers host1:8470,host2:8470]
#
# This script:
#   1. SSHs into the remote machine
#   2. Installs DOIN (if not already installed)
#   3. Generates a config
#   4. Launches the node
#
# Requirements on remote:
#   - SSH access (key-based recommended)
#   - Python 3.10+, pip, git
# ============================================================================

set -euo pipefail

usage() {
    echo "Usage: $0 user@host [options]"
    echo ""
    echo "Options:"
    echo "  --optimize          Enable optimizer role"
    echo "  --port PORT         Node port (default: 8470)"
    echo "  --peers HOST:PORT   Comma-separated list of peer addresses"
    echo "  --domain DOMAIN     Domain ID (default: quadratic)"
    echo "  --install-dir DIR   Remote install directory (default: ~/doin)"
    echo "  --dry-run           Print commands without executing"
    exit 1
}

# ── Parse args ───────────────────────────────────────────────────────
[ $# -lt 1 ] && usage

REMOTE="$1"; shift
OPTIMIZE=false
PORT=8470
PEERS=""
DOMAIN="quadratic"
INSTALL_DIR='$HOME/doin'
DRY_RUN=false

while [ $# -gt 0 ]; do
    case $1 in
        --optimize)     OPTIMIZE=true ;;
        --port)         PORT="$2"; shift ;;
        --peers)        PEERS="$2"; shift ;;
        --domain)       DOMAIN="$2"; shift ;;
        --install-dir)  INSTALL_DIR="$2"; shift ;;
        --dry-run)      DRY_RUN=true ;;
        *)              echo "Unknown option: $1"; usage ;;
    esac
    shift
done

# Build peers JSON array
PEERS_JSON="[]"
if [ -n "$PEERS" ]; then
    PEERS_JSON=$(echo "$PEERS" | tr ',' '\n' | awk '{printf "\"%s\",", $1}' | sed 's/,$//')
    PEERS_JSON="[$PEERS_JSON]"
fi

# ── Build remote script ─────────────────────────────────────────────
SCRIPT=$(cat << REMOTE_SCRIPT
#!/bin/bash
set -euo pipefail

echo "=== DOIN Remote Deployment ==="
INSTALL_DIR="$INSTALL_DIR"

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "ERROR: Python 3 not found"
    exit 1
fi

# Create venv if needed
if [ ! -d "\$INSTALL_DIR/.venv" ]; then
    echo "Creating virtual environment..."
    mkdir -p "\$INSTALL_DIR"
    python3 -m venv "\$INSTALL_DIR/.venv"
fi

source "\$INSTALL_DIR/.venv/bin/activate"
pip install --upgrade pip setuptools -q

# Install DOIN packages
echo "Installing DOIN packages..."
pip install git+https://github.com/harveybc/doin-core.git -q
pip install git+https://github.com/harveybc/doin-node.git -q
pip install git+https://github.com/harveybc/doin-plugins.git -q

echo "DOIN packages installed."

# Generate config
CONFIG="\$INSTALL_DIR/node-config.json"
cat > "\$CONFIG" << 'CONF'
{
  "host": "0.0.0.0",
  "port": $PORT,
  "data_dir": "$INSTALL_DIR/data",
  "bootstrap_peers": $PEERS_JSON,
  "target_block_time": 600.0,
  "initial_threshold": 1.0,
  "quorum_min_evaluators": 3,
  "quorum_fraction": 0.67,
  "quorum_tolerance": 0.10,
  "eval_poll_interval": 5.0,
  "optimizer_loop_interval": 30.0,
  "domains": [
    {
      "domain_id": "$DOMAIN",
      "optimize": $OPTIMIZE,
      "evaluate": true,
      "has_synthetic_data": true
    }
  ]
}
CONF

echo "Config written to \$CONFIG"

# Launch node
echo "Launching DOIN node on port $PORT..."
mkdir -p "\$INSTALL_DIR/logs"
nohup doin-node --config "\$CONFIG" > "\$INSTALL_DIR/logs/node.log" 2>&1 &
NODE_PID=\$!
echo "\$NODE_PID" > "\$INSTALL_DIR/node.pid"
echo "Node started (PID \$NODE_PID)"
echo "Log: \$INSTALL_DIR/logs/node.log"
echo "Stop: kill \$(cat \$INSTALL_DIR/node.pid)"
REMOTE_SCRIPT
)

# ── Execute ──────────────────────────────────────────────────────────
if [ "$DRY_RUN" = true ]; then
    echo "=== DRY RUN — would execute on $REMOTE: ==="
    echo "$SCRIPT"
else
    echo "Deploying to $REMOTE..."
    echo "$SCRIPT" | ssh "$REMOTE" 'bash -s'
    echo ""
    echo "Node deployed to $REMOTE:$PORT"
    echo "Check: ssh $REMOTE 'curl -s http://localhost:$PORT/status | python3 -m json.tool'"
fi
