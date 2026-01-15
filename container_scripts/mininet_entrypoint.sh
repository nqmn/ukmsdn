#!/bin/bash
#
# UKMSDN Mininet Container Entry Point
# ====================================
# This script automatically starts and supervises OpenVSwitch service
# when the ukm_mininet container starts, eliminating manual startup.
#
# Features:
# - Auto-starts OVS on container startup
# - Supervises OVS processes and restarts if they crash
# - Provides health monitoring and logging
# - Keeps container running indefinitely
#

set -e

LOG_FILE="/var/log/ukmsdn/mininet_entrypoint.log"
mkdir -p /var/log/ukmsdn /var/run/openvswitch /var/log/openvswitch /etc/openvswitch

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "========================================="
log "UKMSDN Mininet Container Starting"
log "========================================="

# Function to start OpenVSwitch
start_ovs() {
    log "Starting OpenVSwitch services..."

    # Clean up any stale processes
    pkill -TERM -f ovsdb-server 2>/dev/null || true
    pkill -TERM -f ovs-vswitchd 2>/dev/null || true
    sleep 2
    pkill -KILL -f ovsdb-server 2>/dev/null || true
    pkill -KILL -f ovs-vswitchd 2>/dev/null || true
    sleep 1

    # Clean runtime files
    rm -rf /var/run/openvswitch/*
    rm -f /var/log/openvswitch/*.log

    # Create database if needed
    if [ ! -f /etc/openvswitch/conf.db ]; then
        log "Creating OVS database..."
        ovsdb-tool create /etc/openvswitch/conf.db /usr/share/openvswitch/vswitch.ovsschema
    fi

    # Start ovsdb-server
    log "Starting ovsdb-server..."
    ovsdb-server /etc/openvswitch/conf.db \
        --remote=punix:/var/run/openvswitch/db.sock \
        --remote=db:Open_vSwitch,Open_vSwitch,manager_options \
        --pidfile=/var/run/openvswitch/ovsdb-server.pid \
        --detach \
        --log-file=/var/log/openvswitch/ovsdb-server.log \
        --unixctl=/var/run/openvswitch/ovsdb-server.ctl

    # Wait for socket
    local timeout=30
    local count=0
    while [ ! -S /var/run/openvswitch/db.sock ] && [ $count -lt $timeout ]; do
        sleep 1
        count=$((count + 1))
    done

    if [ ! -S /var/run/openvswitch/db.sock ]; then
        log "ERROR: OVS database socket not created within timeout"
        return 1
    fi

    # Initialize database
    log "Initializing OVS database..."
    ovs-vsctl --no-wait init || true

    # Start ovs-vswitchd with userspace datapath
    log "Starting ovs-vswitchd (userspace mode)..."
    ovs-vswitchd \
        --pidfile=/var/run/openvswitch/ovs-vswitchd.pid \
        --detach \
        --log-file=/var/log/openvswitch/ovs-vswitchd.log \
        --unixctl=/var/run/openvswitch/ovs-vswitchd.ctl

    sleep 3

    # Verify OVS is working
    if ovs-vsctl show >/dev/null 2>&1; then
        log "✅ OpenVSwitch started successfully (userspace mode)"
        echo 'USERSPACE' > /opt/ukmsdn/scripts/.ovs_mode
        return 0
    else
        log "ERROR: OVS verification failed"
        return 1
    fi
}

# Function to check if OVS is running
check_ovs() {
    pgrep -f ovsdb-server >/dev/null && pgrep -f ovs-vswitchd >/dev/null && ovs-vsctl show >/dev/null 2>&1
}

# Function to supervise OVS
supervise_ovs() {
    log "Starting OVS supervision loop..."

    while true; do
        if ! check_ovs; then
            log "⚠️  OVS not running or unhealthy, restarting..."
            start_ovs || log "ERROR: Failed to restart OVS"
        fi
        sleep 30  # Check every 30 seconds
    done
}

# Initial OVS startup
if ! start_ovs; then
    log "ERROR: Initial OVS startup failed"
    exit 1
fi

log "Starting background supervision..."
supervise_ovs &
SUPERVISOR_PID=$!

log "✅ Mininet container fully initialized"
log "OVS supervisor PID: $SUPERVISOR_PID"
log "Container ready for SDN operations"

# Handle graceful shutdown
trap 'log "Shutting down..."; pkill -P $SUPERVISOR_PID; pkill -f ovsdb-server; pkill -f ovs-vswitchd; exit 0' SIGTERM SIGINT

# Keep container running
while true; do
    sleep 3600
done
