#!/bin/bash
#
# UKMSDN Ryu Controller Container Entry Point
# ===========================================
# This script automatically starts and supervises the Ryu SDN controller
# when the ukm_ryu container starts, eliminating manual startup.
#
# Features:
# - Auto-starts Ryu controller on container startup
# - Supervises Ryu process and restarts if it crashes
# - Configurable Ryu application (default: simple_switch_13.py)
# - Provides health monitoring and logging
# - Keeps container running indefinitely
#

set -e

LOG_FILE="/var/log/ukmsdn/ryu_entrypoint.log"
RYU_LOG_FILE="/var/log/ukmsdn/ryu_controller.log"
mkdir -p /var/log/ukmsdn /opt/ukmsdn/logs

# Default Ryu application (can be overridden by environment variable)
RYU_APP="${RYU_APP:-/opt/ukmsdn/ryu/ryu/app/simple_switch_13.py}"
RYU_PORT="${RYU_PORT:-6633}"

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "========================================="
log "UKMSDN Ryu Controller Container Starting"
log "========================================="
log "Ryu Application: $RYU_APP"
log "OpenFlow Port: $RYU_PORT"

# Function to start Ryu controller
start_ryu() {
    log "Starting Ryu SDN controller..."

    # Clean up any existing Ryu processes
    pkill -TERM -f ryu-manager 2>/dev/null || true
    sleep 2
    pkill -KILL -f ryu-manager 2>/dev/null || true
    sleep 1

    # Verify Ryu application exists
    if [ ! -f "$RYU_APP" ]; then
        log "ERROR: Ryu application not found: $RYU_APP"
        log "Available apps in /opt/ukmsdn/ryu/ryu/app/:"
        ls -la /opt/ukmsdn/ryu/ryu/app/*.py 2>/dev/null || log "No apps found"
        return 1
    fi

    # Set PATH to include Ryu binaries
    export PATH="/opt/ukmsdn/ryu/bin:$PATH"

    # Start Ryu controller
    log "Launching ryu-manager with $RYU_APP..."
    cd /opt/ukmsdn/ryu

    # Start Ryu in background with logging
    nohup ryu-manager "$RYU_APP" \
        --verbose \
        --ofp-tcp-listen-port "$RYU_PORT" \
        >> "$RYU_LOG_FILE" 2>&1 &

    RYU_PID=$!
    echo $RYU_PID > /var/run/ryu.pid

    # Wait a moment and verify it's running
    sleep 3

    if ps -p $RYU_PID > /dev/null 2>&1; then
        log "✅ Ryu controller started successfully (PID: $RYU_PID)"

        # Verify port is listening
        local timeout=10
        local count=0
        while [ $count -lt $timeout ]; do
            if netstat -tlnp 2>/dev/null | grep -q ":$RYU_PORT"; then
                log "✅ Ryu listening on port $RYU_PORT"
                return 0
            fi
            sleep 1
            count=$((count + 1))
        done

        log "⚠️  Ryu started but port $RYU_PORT not detected yet"
        return 0
    else
        log "ERROR: Ryu process failed to start"
        log "Last 20 lines of Ryu log:"
        tail -n 20 "$RYU_LOG_FILE" | tee -a "$LOG_FILE"
        return 1
    fi
}

# Function to check if Ryu is running
check_ryu() {
    if [ -f /var/run/ryu.pid ]; then
        local pid=$(cat /var/run/ryu.pid)
        if ps -p $pid > /dev/null 2>&1; then
            return 0
        fi
    fi
    return 1
}

# Function to supervise Ryu
supervise_ryu() {
    log "Starting Ryu supervision loop..."

    while true; do
        if ! check_ryu; then
            log "⚠️  Ryu controller not running, restarting..."
            if ! start_ryu; then
                log "ERROR: Failed to restart Ryu, will retry in 30 seconds..."
            fi
        fi
        sleep 30  # Check every 30 seconds
    done
}

# Initial Ryu startup
if ! start_ryu; then
    log "ERROR: Initial Ryu startup failed"
    log "Container will continue running for debugging"
    log "Check logs: $RYU_LOG_FILE"
fi

log "Starting background supervision..."
supervise_ryu &
SUPERVISOR_PID=$!

log "✅ Ryu controller container fully initialized"
log "Ryu supervisor PID: $SUPERVISOR_PID"
log "Container ready for SDN operations"
log "========================================="

# Handle graceful shutdown
trap 'log "Shutting down..."; pkill -P $SUPERVISOR_PID; pkill -f ryu-manager; exit 0' SIGTERM SIGINT

# Keep container running
while true; do
    sleep 3600
done
