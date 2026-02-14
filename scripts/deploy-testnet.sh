#!/usr/bin/env bash
# ============================================================================
# DOIN Testnet — Deploy a multi-node test network on localhost
#
# Launches N nodes on different ports with quadratic reference plugins.
# No ML frameworks needed — purely for testing the protocol.
#
# Usage:
#   ./deploy-testnet.sh              # 3 nodes (default)
#   ./deploy-testnet.sh 5            # 5 nodes
#   ./deploy-testnet.sh 3 --clean    # Clean data dirs first
#
# Nodes:
#   Node 0: optimizer + evaluator on port 8470
#   Node 1: evaluator on port 8471
#   Node 2: evaluator on port 8472
#   ...
#
# Stop: Ctrl+C (kills all background nodes)
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

NUM_NODES=${1:-3}
CLEAN=false
BASE_PORT=8470
DATA_BASE="/tmp/doin-testnet"
LOG_DIR="$DATA_BASE/logs"
PIDS=()

for arg in "$@"; do
    case $arg in
        --clean) CLEAN=true ;;
        [0-9]*) NUM_NODES=$arg ;;
    esac
done

# ── Pre-flight ───────────────────────────────────────────────────────
if ! command -v doin-node &>/dev/null; then
    if ! python3 -c "import doin_node" &>/dev/null 2>&1; then
        echo "doin-node not found. Install first:"
        echo "  pip install git+https://github.com/harveybc/doin-core.git"
        echo "  pip install git+https://github.com/harveybc/doin-node.git"
        echo "  pip install git+https://github.com/harveybc/doin-plugins.git"
        exit 1
    fi
fi

# ── Cleanup handler ──────────────────────────────────────────────────
cleanup() {
    echo ""
    info "Shutting down testnet..."
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
    ok "All nodes stopped."
}
trap cleanup EXIT INT TERM

# ── Clean data dirs ──────────────────────────────────────────────────
if [ "$CLEAN" = true ]; then
    info "Cleaning data directories..."
    rm -rf "$DATA_BASE"
fi

mkdir -p "$DATA_BASE" "$LOG_DIR"

# ── Generate configs ─────────────────────────────────────────────────
info "Generating configs for $NUM_NODES nodes..."

# Build peer list
PEERS=""
for i in $(seq 0 $((NUM_NODES - 1))); do
    PORT=$((BASE_PORT + i))
    if [ -n "$PEERS" ]; then
        PEERS="$PEERS,"
    fi
    PEERS="$PEERS\"127.0.0.1:$PORT\""
done

for i in $(seq 0 $((NUM_NODES - 1))); do
    PORT=$((BASE_PORT + i))
    DATA_DIR="$DATA_BASE/node-$i"
    CONFIG="$DATA_BASE/node-$i.json"

    # First node optimizes, all nodes evaluate
    if [ "$i" -eq 0 ]; then
        OPTIMIZE="true"
    else
        OPTIMIZE="false"
    fi

    # Build peer list excluding self
    MY_PEERS=""
    for j in $(seq 0 $((NUM_NODES - 1))); do
        if [ "$j" -ne "$i" ]; then
            P=$((BASE_PORT + j))
            if [ -n "$MY_PEERS" ]; then
                MY_PEERS="$MY_PEERS,"
            fi
            MY_PEERS="$MY_PEERS\"127.0.0.1:$P\""
        fi
    done

    cat > "$CONFIG" << CONF
{
  "host": "127.0.0.1",
  "port": $PORT,
  "data_dir": "$DATA_DIR",
  "bootstrap_peers": [$MY_PEERS],
  "target_block_time": 30.0,
  "initial_threshold": 0.01,
  "quorum_min_evaluators": 2,
  "quorum_fraction": 0.67,
  "quorum_tolerance": 0.15,
  "eval_poll_interval": 2.0,
  "optimizer_loop_interval": 10.0,
  "domains": [
    {
      "domain_id": "quadratic",
      "optimize": $OPTIMIZE,
      "evaluate": true,
      "optimization_plugin": "quadratic",
      "inference_plugin": "quadratic",
      "synthetic_data_plugin": "quadratic",
      "has_synthetic_data": true
    }
  ]
}
CONF

    ok "Config generated: $CONFIG (port $PORT, optimize=$OPTIMIZE)"
done

# ── Launch nodes ─────────────────────────────────────────────────────
echo ""
info "Launching $NUM_NODES nodes..."

for i in $(seq 0 $((NUM_NODES - 1))); do
    PORT=$((BASE_PORT + i))
    CONFIG="$DATA_BASE/node-$i.json"
    LOG="$LOG_DIR/node-$i.log"

    doin-node --config "$CONFIG" > "$LOG" 2>&1 &
    PIDS+=($!)
    ok "Node $i started (port $PORT, PID ${PIDS[-1]}, log: $LOG)"
done

echo ""
echo "═══════════════════════════════════════════════════════════════"
ok "DOIN testnet running with $NUM_NODES nodes!"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  Nodes:"
for i in $(seq 0 $((NUM_NODES - 1))); do
    PORT=$((BASE_PORT + i))
    ROLE="evaluator"
    [ "$i" -eq 0 ] && ROLE="optimizer+evaluator"
    echo "    Node $i: http://127.0.0.1:$PORT ($ROLE)"
done
echo ""
echo "  Check status:  curl http://127.0.0.1:$BASE_PORT/status | python3 -m json.tool"
echo "  Chain status:   curl http://127.0.0.1:$BASE_PORT/chain/status"
echo "  View logs:      tail -f $LOG_DIR/node-*.log"
echo "  Stop:           Ctrl+C"
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ── Wait ─────────────────────────────────────────────────────────────
info "Press Ctrl+C to stop all nodes..."
wait
