# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

UKMSDN is a containerized Software-Defined Networking (SDN) environment for DDoS dataset generation and network research. It uses:
- **Mininet** for network topology emulation
- **Ryu** SDN controller with OpenFlow 1.3 protocol
- **OpenVSwitch** for software-defined switching in userspace datapath mode
- **Podman** for container orchestration with custom networking
- **CICFlowMeter** for network traffic analysis

The project is designed for educational and research purposes related to SDN, network security, and DDoS research.

## Architecture Overview

### Container Structure
The system runs two primary containers connected via a custom Podman network (`ukmsdn-network`):

1. **ukm_mininet**: Network emulation container
   - Runs Mininet for topology simulation
   - Contains OpenVSwitch with userspace datapath
   - Hosts network testing tools (scapy, tshark, hping3, iperf3, slowhttptest)
   - Installs CICFlowMeter for flow analysis

2. **ukm_ryu**: SDN controller container
   - Runs Ryu manager and OpenFlow apps
   - Listens on port 6633 for OpenFlow connections
   - Executes custom Ryu applications from `/opt/ukmsdn/ryu/ryu/app/`

### Key Design Pattern
- Both containers are built from a single base image (`ukm-ubuntu:24.04-updated`) to ensure consistency
- Containers communicate via the `ukmsdn-network` (custom Podman network)
- OpenVSwitch uses **userspace datapath mode** (`datapath=user`) for container compatibility - kernel datapath requires special capabilities
- Dynamic IP address discovery is essential since container IPs are assigned at runtime
- **Services auto-start via entry point scripts** with built-in process supervision and auto-restart capabilities

### Auto-Start Architecture (NEW!)
As of the latest update, UKMSDN features **automatic service startup**:

#### Entry Point Scripts
1. **`/opt/ukmsdn/container_scripts/mininet_entrypoint.sh`** (ukm_mininet)
   - Auto-starts OpenVSwitch (ovsdb-server and ovs-vswitchd)
   - Supervises OVS processes with 30-second health checks
   - Auto-restarts OVS if it crashes
   - Logs to `/var/log/ukmsdn/mininet_entrypoint.log`

2. **`/opt/ukmsdn/container_scripts/ryu_entrypoint.sh`** (ukm_ryu)
   - Auto-starts Ryu SDN controller with default app
   - Supervises Ryu process with health monitoring
   - Auto-restarts Ryu if it crashes
   - Logs to `/var/log/ukmsdn/ryu_entrypoint.log` and `/var/log/ukmsdn/ryu_controller.log`

#### Benefits
- **No manual service startup required** - services start automatically when containers start
- **Automatic recovery** - services restart if they crash
- **Always ready** - works after container restarts or system reboots
- **Better logging** - centralized logs for debugging
- **Production-ready** - built-in process supervision

See `AUTO_START_ARCHITECTURE.md` for detailed documentation.

## Setup and Initialization

### Main Setup Script: `setup_container.py`
This is the primary entry point for environment setup:

```bash
sudo python3 setup_container.py
```

**Key Setup Functions**:
- `check_podman()`: Verifies/installs Podman
- `build_base_image()`: Creates Ubuntu 24.04 base image with all dependencies and entry point scripts
- `cleanup_containers()`: Removes existing containers and network
- `create_network()`: Creates `ukmsdn-network`
- `create_containers()`: Instantiates containers with auto-start entry points and verifies services started
- `install_mininet_container()`: Installs Mininet-specific tools (OVS now auto-starts via entry point)
- `install_ryu_container()`: Clones Ryu from GitHub and installs it (Ryu now auto-starts via entry point)
- `create_start_ovs_script()`: Generates `/opt/ukmsdn/scripts/start_ovs.sh` for manual OVS restart if needed
- `show_final_status()`: Displays setup completion and usage instructions

**Critical Implementation Detail**: The script dynamically retrieves the Ryu controller's IP at runtime because container IPs are assigned by Podman. Any code using the controller should call `podman inspect ukm_ryu --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'` to get the current IP.

## Testing and Validation

### Test Suite: `test_ukmsdn.py`
Validates the containerized environment after setup:

```bash
python3 test_ukmsdn.py
```

**Test Functions**:
- `setup_environment()`: Cleans up Mininet state, **verifies** auto-started OVS and Ryu services
- `test_mininet_basic()`: Runs 2-host and standard SDN topology tests with pingall
- `show_usage_examples()`: Displays practical usage patterns

**Important**: Tests verify:
1. OVS service auto-started and running in userspace mode
2. Ryu controller auto-started and listening on port 6633
3. Basic pingall connectivity between hosts works
4. Controller can manage flows
5. Entry point logs are accessible for debugging if services fail to start

## Common Development Commands

### Container Access
```bash
# Access Mininet container
podman exec -it ukm_mininet /bin/bash

# Access Ryu controller container
podman exec -it ukm_ryu /bin/bash
```

### Testing Topologies
Always use `datapath=user` flag for container compatibility:
```bash
# 2-host test (quick validation)
podman exec -it ukm_mininet timeout 30 mn --controller=remote,ip=<RYU_IP>,port=6633 --topo=single,2 --switch ovs,datapath=user --test pingall

# Linear topology (3 switches)
podman exec -it ukm_mininet timeout 45 mn --controller=remote,ip=<RYU_IP>,port=6633 --topo=linear,3 --switch ovs,datapath=user --test pingall

# Interactive mode with timeout
timeout 120 podman exec -it ukm_mininet mn --controller=remote,ip=<RYU_IP>,port=6633 --topo=single,2 --switch ovs,datapath=user
```

Replace `<RYU_IP>` with the dynamic controller IP retrieved via:
```bash
podman inspect ukm_ryu --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'
```

### Monitoring and Debugging
```bash
# Check container status
podman ps

# View container logs
podman logs ukm_mininet
podman logs ukm_ryu

# NEW: View auto-start entry point logs
podman exec ukm_mininet cat /var/log/ukmsdn/mininet_entrypoint.log
podman exec ukm_ryu cat /var/log/ukmsdn/ryu_entrypoint.log
podman exec ukm_ryu cat /var/log/ukmsdn/ryu_controller.log

# Follow logs in real-time
podman exec ukm_mininet tail -f /var/log/ukmsdn/mininet_entrypoint.log
podman exec ukm_ryu tail -f /var/log/ukmsdn/ryu_controller.log

# Check service status (services auto-start)
podman exec ukm_mininet pgrep -f ovsdb-server
podman exec ukm_ryu pgrep -f ryu-manager

# Monitor OVS flows
podman exec ukm_mininet ovs-vsctl show
podman exec ukm_mininet ovs-ofctl dump-flows s1

# Clean up stuck Mininet state
podman exec ukm_mininet mn -c

# Manual OVS restart (if needed - normally auto-restarts via supervision)
podman exec ukm_mininet /opt/ukmsdn/scripts/start_ovs.sh

# Manual Ryu restart (supervision will detect and restart automatically)
podman exec ukm_ryu pkill -f ryu-manager
# Wait 30 seconds for supervision to auto-restart
```

### Code Formatting and Linting
The project includes Black and Flake8 tools:
```bash
# Format code
podman exec ukm_mininet black script.py

# Lint code
podman exec ukm_mininet flake8 script.py
```

## Directory Structure

```
ukmsdn/
├── setup_container.py          # Primary setup orchestration
├── test_ukmsdn.py              # Test and validation suite
├── setup.py                    # Legacy host installation (not container-based)
├── LICENSE                     # Project license
├── README.md                   # User documentation
├── CLAUDE.md                   # This file
├── AUTO_START_ARCHITECTURE.md  # NEW: Auto-start architecture documentation
├── container_scripts/          # NEW: Container entry point scripts
│   ├── mininet_entrypoint.sh   # OVS auto-start and supervision
│   └── ryu_entrypoint.sh       # Ryu auto-start and supervision
├── backup_container/           # Container state backup utilities
│   ├── backup_image.py         # Saves image and container metadata
│   └── restore_backup.py       # Restores from backups
├── examples/                   # Usage examples and Ryu applications
│   ├── 4-network.py            # 4-switch network topology example
│   ├── 4-internetwork.py       # Inter-network topology example
│   ├── quick_ryu_check.py      # Quick controller verification
│   ├── check_ryu_controller.py # Controller health checks
│   └── ryu/                    # Ryu SDN applications
│       ├── simple_switch_13.py # Basic L2 switching (OpenFlow 1.3)
│       ├── ryu_controller_app.py       # Custom controller application
│       └── ryu_l3_router_app.py        # L3 routing application
└── mininet_test.png, setup.png # Setup documentation images
```

## Key Code Patterns

### Dynamic IP Discovery Pattern
When working with Ryu controller IP across files:
```python
def get_controller_ip():
    cmd = "podman inspect ukm_ryu --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'"
    success, stdout, stderr = run_command(cmd)
    if success and stdout.strip():
        return stdout.strip()
    return None
```

This pattern is used in both `setup_container.py` and `test_ukmsdn.py`.

### Container Command Execution Pattern
All Mininet/OVS commands go through Podman:
```bash
podman exec ukm_mininet <mininet_command>
podman exec ukm_ryu <ryu_command>
```

Timeout wrappers are recommended to prevent hanging:
```bash
timeout 60 podman exec -it ukm_mininet <command>
```

### Topology Creation Pattern (from examples)
Examples create custom topologies with:
1. Clean up existing Mininet state: `mn -c`
2. Restart OVS: `/opt/ukmsdn/scripts/start_ovs.sh`
3. Get dynamic controller IP
4. Create topology with `--controller=remote,ip=<IP>,port=6633 --switch ovs,datapath=user`
5. Run interactive CLI or tests

## Dependencies and Tools

### System Level
- Podman (container runtime)
- Python 3.8+
- Ubuntu 24.04.3 LTS (recommended)

### In-Container Tools
- **Network**: Mininet, OpenVSwitch, Scapy, Tshark, hping3, iperf3, slowhttptest
- **Development**: Python 3, Pytest, Black, Flake8, isort
- **Analysis**: CICFlowMeter for flow analysis
- **Control**: Ryu from GitHub (custom fork at github.com/nqmn/ryu)

### Python Packages (in both containers)
Core SDN/Network: scapy, ryu
Data analysis: pandas, numpy
Testing: pytest, pytest-cov
Code quality: black, flake8, isort
Security: cryptography, pycryptodome, pyOpenSSL
Networking: webob, requests, psutil
OpenFlow support: Routes, eventlet, greenlet, msgpack, netaddr, oslo.*, stevedore, tinyrpc

## Development Workflow

### When Modifying Setup Scripts
- Test changes in the setup process by running: `sudo python3 setup_container.py`
- Verify container creation and networking: `podman ps` and `podman network ls`
- Check container IPs are assigned correctly: `podman inspect <container_name>`

### When Creating New Ryu Applications
- Place custom apps in `/opt/ukmsdn/ryu/ryu/app/` or mount them from host
- Start controller with: `podman exec -d ukm_ryu bash -c "cd /opt/ukmsdn/ryu && ryu-manager ryu/app/your_app.py --verbose"`
- Use `simple_switch_13.py` as the base example (Ryu license: Apache 2.0)

### When Testing Network Topologies
- Always include `--switch ovs,datapath=user` flag
- Always use `timeout <seconds>` wrapper to prevent hanging
- Get dynamic controller IP before building topology
- Clean up with `podman exec ukm_mininet mn -c` if tests hang

### When Debugging Container Issues
1. Check if containers exist: `podman ps -a`
2. View container logs: `podman logs <container_name>`
3. Access container shell: `podman exec -it <container_name> /bin/bash`
4. Verify network connectivity: `podman exec <container_name> ping <other_container_name>`
5. Check OVS specifically: `podman exec ukm_mininet ovs-vsctl show`

## Container Network Details

- **Network Name**: `ukmsdn-network` (custom Podman bridge network)
- **DNS**: Enabled by default, containers can reach each other by name
- **Ryu Port**: 6633 (OpenFlow)
- **Mode**: All containers run with `--privileged` flag for namespace access

## Important Notes for Future Development

1. **Userspace Datapath**: The `datapath=user` flag is mandatory in containers. Kernel datapath won't work without special kernel module access.

2. **Dynamic IPs**: Never hardcode container IP addresses. Always query them at runtime.

3. **Process Management**: Use Podman's `exec` not SSH for running commands in containers.

4. **Cleanup State**: OVS and Mininet can leave residual state. Use `mn -c` and restart_ovs.sh frequently during development.

5. **Timeout Protection**: Network operations can hang. Always use timeout wrappers around container commands.

6. **Image Caching**: The base image is only built once. Subsequent setup runs reuse it for speed.

7. **Backup Utilities**: Use `backup_container/` scripts before major changes to save state (especially custom Ryu apps and topology definitions).

8. **Testing Philosophy**: The `test_ukmsdn.py` validates end-to-end connectivity. Use it as a litmus test after modifications.
