# UKMSDN Auto-Start Architecture

## Overview

As of this update, UKMSDN containers now feature **automatic service startup** with built-in process supervision. This eliminates the manual steps previously required to start OpenVSwitch and the Ryu controller.

## What Changed?

### Before (Manual Service Management)
```
1. Start containers → Running but services idle
2. Manually start OVS: podman exec ukm_mininet /opt/ukmsdn/scripts/start_ovs.sh
3. Manually start Ryu: podman exec -d ukm_ryu ryu-manager ...
4. Now ready to use
```

**Problem**: If containers restarted or services crashed, you had to manually restart them again.

### After (Automatic Service Management)
```
1. Start containers → Services auto-start automatically
2. Ready to use immediately!
```

**Benefit**: Services auto-start on container startup and auto-restart if they crash.

## Architecture Components

### 1. Entry Point Scripts

Two entry point scripts manage service lifecycle:

#### `/opt/ukmsdn/container_scripts/mininet_entrypoint.sh`
- **Container**: ukm_mininet
- **Responsibilities**:
  - Auto-starts OpenVSwitch (ovsdb-server and ovs-vswitchd)
  - Configures userspace datapath mode for container compatibility
  - Supervises OVS processes and restarts if they fail
  - Logs to: `/var/log/ukmsdn/mininet_entrypoint.log`

#### `/opt/ukmsdn/container_scripts/ryu_entrypoint.sh`
- **Container**: ukm_ryu
- **Responsibilities**:
  - Auto-starts Ryu SDN controller
  - Default app: `/opt/ukmsdn/ryu/ryu/app/simple_switch_13.py`
  - Supervises Ryu process and restarts if it crashes
  - Logs to: `/var/log/ukmsdn/ryu_entrypoint.log`
  - Controller logs: `/var/log/ukmsdn/ryu_controller.log`

### 2. Process Supervision

Both entry points include supervision loops that:
- Check service health every 30 seconds
- Auto-restart services if they crash or become unresponsive
- Log all restart events for debugging

### 3. Health Monitoring

Services are monitored via:
- Process checks (pgrep for ryu-manager, ovsdb-server, ovs-vswitchd)
- Port listening verification (Ryu on port 6633)
- Functional tests (ovs-vsctl show for OVS)

## Container Lifecycle

### Container Creation
```bash
# Old way
podman run -d --name ukm_mininet ... sleep infinity

# New way
podman run -d --name ukm_mininet ... /opt/ukmsdn/container_scripts/mininet_entrypoint.sh
```

### On Container Start
1. Entry point script executes
2. Sets up logging directories
3. Starts the service (OVS or Ryu)
4. Verifies service is running
5. Launches supervision loop
6. Keeps container running

### On Service Crash
1. Supervision loop detects missing process
2. Logs warning message
3. Attempts to restart service
4. Logs success or failure
5. Continues monitoring

## Configuration

### Customizing Ryu Application

Set the `RYU_APP` environment variable when creating the container:

```bash
podman run -d --name ukm_ryu --privileged --network ukmsdn-network \
  -e RYU_APP=/opt/ukmsdn/examples/ryu/custom_app.py \
  ukm-ubuntu:24.04-updated /opt/ukmsdn/container_scripts/ryu_entrypoint.sh
```

### Customizing OpenFlow Port

Set the `RYU_PORT` environment variable (default: 6633):

```bash
podman run -d --name ukm_ryu --privileged --network ukmsdn-network \
  -e RYU_PORT=6653 \
  ukm-ubuntu:24.04-updated /opt/ukmsdn/container_scripts/ryu_entrypoint.sh
```

## Troubleshooting

### Check Service Status

```bash
# Check if OVS is running
podman exec ukm_mininet pgrep -f ovsdb-server

# Check if Ryu is running
podman exec ukm_ryu pgrep -f ryu-manager

# Check Ryu port
podman exec ukm_ryu netstat -tlnp | grep 6633
```

### View Entry Point Logs

```bash
# Mininet entry point log
podman exec ukm_mininet cat /var/log/ukmsdn/mininet_entrypoint.log

# Ryu entry point log
podman exec ukm_ryu cat /var/log/ukmsdn/ryu_entrypoint.log

# Ryu controller log
podman exec ukm_ryu cat /var/log/ukmsdn/ryu_controller.log
```

### View Real-Time Logs

```bash
# Follow Mininet entry point
podman exec ukm_mininet tail -f /var/log/ukmsdn/mininet_entrypoint.log

# Follow Ryu controller
podman exec ukm_ryu tail -f /var/log/ukmsdn/ryu_controller.log
```

### Manual Service Restart

If you need to manually restart a service:

```bash
# Restart OVS (the old start_ovs.sh still exists for manual use)
podman exec ukm_mininet /opt/ukmsdn/scripts/start_ovs.sh

# Restart Ryu (supervision will detect and manage it)
podman exec ukm_ryu pkill -f ryu-manager
# Supervision loop will auto-restart within 30 seconds
```

### Container Logs

```bash
# View container stdout/stderr
podman logs ukm_mininet
podman logs ukm_ryu
```

## Benefits

### 1. **No Manual Intervention**
- Services start automatically when containers start
- No need to remember startup commands
- Works after system reboots

### 2. **Automatic Recovery**
- Services auto-restart if they crash
- Reduces downtime
- Improves reliability

### 3. **Better Logging**
- Centralized logs in `/var/log/ukmsdn/`
- Entry point logs track supervision events
- Service logs separate for debugging

### 4. **Consistency**
- Same service state every time
- Predictable behavior
- Easier to debug issues

### 5. **Container Best Practices**
- Proper entry point usage
- Process supervision
- Graceful shutdown handling

## Testing

The test suite (`test_ukmsdn.py`) has been updated to:
- Verify services auto-started correctly
- Check entry point logs if services fail
- No longer manually starts services

Run tests:
```bash
python3 test_ukmsdn.py
```

## Backward Compatibility

### Scripts Still Available
The old manual startup scripts remain for debugging:
- `/opt/ukmsdn/scripts/start_ovs.sh` - Manual OVS restart
- Can still manually start Ryu if needed

### Examples Updated
All example scripts have been updated to expect auto-started services.

## Migration Notes

If you have existing containers from before this update:

1. **Rebuild containers**:
   ```bash
   sudo python3 setup_container.py
   ```

2. **Or manually restart**:
   ```bash
   podman stop ukm_mininet ukm_ryu
   podman rm ukm_mininet ukm_ryu
   sudo python3 setup_container.py
   ```

## Technical Details

### Entry Point Execution
- Entry points run as PID 1 in containers
- Handle SIGTERM/SIGINT for graceful shutdown
- Spawn supervision as background process
- Keep main process alive with sleep loop

### Supervision Implementation
- 30-second check interval
- Non-blocking process checks
- Automatic restart on failure
- Logged restart attempts

### OVS Userspace Mode
- Required for containers (kernel datapath needs special privileges)
- Configured automatically by entry point
- Mode indicator: `/opt/ukmsdn/scripts/.ovs_mode`

## Future Enhancements

Potential improvements:
- [ ] Configurable supervision interval
- [ ] Health check HTTP endpoint
- [ ] Metrics collection
- [ ] Email/webhook alerts on restart
- [ ] Service dependency management
- [ ] Graceful rolling restarts

## Summary

The auto-start architecture transforms UKMSDN from a manually-managed system to a self-healing, production-ready SDN environment. Services start automatically, recover from failures, and provide comprehensive logging - all without user intervention.

**Key Takeaway**: You no longer need to manually start OVS or Ryu. Just run `setup_container.py` and start using your SDN environment immediately!
