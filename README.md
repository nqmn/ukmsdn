# UKMSDN - Self-Healing SDN Container Environment

A containerized Software-Defined Networking (SDN) environment for DDoS dataset generation and network research with **automatic service startup** and **built-in process supervision**.

## Overview

UKMSDN provides a production-ready, self-healing SDN environment with:
- **Mininet** for network emulation
- **Ryu** SDN controller for OpenFlow-based network control
- **OpenVSwitch** for software-defined switching (userspace datapath)
- **CICFlowMeter** for network traffic analysis
- **Auto-start services** - OVS and Ryu start automatically
- **Auto-recovery** - Services restart automatically if they crash
- Pre-configured tools for network testing and DDoS research

## System Requirements

- Ubuntu 24.04.3 LTS (recommended)
- Podman container runtime
- Root/sudo privileges (required for network namespaces)
- Python 3.8+

## Quick Start (3 Steps!)

### 1. Setup Environment

```bash
# One command sets up everything with auto-starting services
sudo python3 setup_container.py
```

**That's it!** Services auto-start and are ready to use immediately.

### 2. Test Your Environment

```bash
# Run automated tests (services already running)
python3 test_ukmsdn.py
```

### 3. Start Using SDN

```bash
# Get controller IP (containers use dynamic IPs)
RYU_IP=$(podman inspect ukm_ryu --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')

# Run a simple 2-host topology test
podman exec ukm_mininet mn --controller=remote,ip=$RYU_IP,port=6633 \
  --topo=single,2 --switch ovs,datapath=user --test pingall
```

**No manual service startup required!** OVS and Ryu are already running.

---

## 🆕 What's New - Auto-Start Architecture

**Your "cannot connect to controller" issues are now solved!**

Previous versions required manual service startup and had no auto-recovery. This version includes:

✅ **Automatic Service Startup** - OVS and Ryu start when containers start
✅ **Auto-Recovery** - Services restart if they crash (30-second supervision)
✅ **Always Ready** - Works after container restarts, reboots, crashes
✅ **Better Logging** - Centralized logs in `/var/log/ukmsdn/`
✅ **Zero Manual Intervention** - No need to manually start or monitor services

See `AUTO_START_ARCHITECTURE.md` for technical details.

---

### Alternative: Host Installation (Legacy)

For direct host installation without containers:

```bash
# Install directly on Ubuntu host (no auto-start features)
sudo python3 setup.py
```

**Note**: Container environment is recommended for isolation and auto-start features.

## Architecture

### Container Structure with Auto-Start

```
┌──────────────────────┐    ┌──────────────────────┐
│   ukm_mininet        │    │     ukm_ryu          │
│                      │    │                      │
│  ✅ Auto-Start:      │◄──►│  ✅ Auto-Start:      │
│    • OpenVSwitch     │    │    • Ryu Controller  │
│    • Supervision     │    │    • Supervision     │
│                      │    │                      │
│  📦 Includes:        │    │  📦 Includes:        │
│    • Mininet         │    │    • OpenFlow Apps   │
│    • CICFlowMeter    │    │    • Flow Analysis   │
│    • Test Tools      │    │                      │
└──────────────────────┘    └──────────────────────┘
          │                           │
          └──── ukmsdn-network ───────┘
              (Custom Podman Network)
```

### Key Features

- **Always Ready**: Services start automatically when containers start
- **Self-Healing**: Automatic restart if services crash (30s supervision)
- **Production-Ready**: Built-in health monitoring and logging
- **No Manual Steps**: No need to manually start OVS or Ryu

## Features

### 🚀 Auto-Start & Self-Healing (NEW!)
- **Automatic Service Startup**: OVS and Ryu start when containers start
- **Process Supervision**: Built-in health checks every 30 seconds
- **Auto-Recovery**: Services restart automatically if they crash
- **Always Ready**: Works after container restarts, system reboots, crashes
- **Centralized Logging**: All logs in `/var/log/ukmsdn/` for easy debugging

### 🌐 Networking Tools
- **Mininet**: Network topology emulation
- **OpenVSwitch**: Software-defined switching with userspace datapath
- **Ryu Controller**: OpenFlow 1.3 SDN controller
- **CICFlowMeter**: Real-time network flow analysis

### 🔬 Testing & Analysis
- **Scapy**: Packet crafting and analysis
- **Tshark**: Network protocol analyzer
- **slowhttptest**: HTTP DoS testing tool
- **hping3**: Network testing utility
- **iperf3**: Network performance testing

### 🛠️ Development Tools
- **Python 3**: Primary development environment
- **Pytest**: Testing framework
- **Black/Flake8**: Code formatting and linting

## Usage Examples

### Get Controller IP (Needed for All Commands)

Containers use dynamic IPs, so always get the current IP first:

```bash
# Get Ryu controller IP
RYU_IP=$(podman inspect ukm_ryu --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
echo "Controller IP: $RYU_IP"
```

### Basic Network Testing

```bash
# Quick 2-host pingall test
podman exec ukm_mininet timeout 30 mn \
  --controller=remote,ip=$RYU_IP,port=6633 \
  --topo=single,2 \
  --switch ovs,datapath=user \
  --test pingall

# Interactive mode with 3 hosts
podman exec -it ukm_mininet mn \
  --controller=remote,ip=$RYU_IP,port=6633 \
  --topo=single,3 \
  --switch ovs,datapath=user
```

### Advanced Topologies

```bash
# Linear topology (3 switches in a line)
podman exec ukm_mininet timeout 45 mn \
  --controller=remote,ip=$RYU_IP,port=6633 \
  --topo=linear,3 \
  --switch ovs,datapath=user \
  --test pingall

# Tree topology (hierarchical network)
podman exec ukm_mininet timeout 60 mn \
  --controller=remote,ip=$RYU_IP,port=6633 \
  --topo=tree,2 \
  --switch ovs,datapath=user \
  --test pingall

# Custom topology from examples/
python3 examples/4-network.py
```

### Monitoring & Debugging

```bash
# Check service status (auto-started services)
podman exec ukm_mininet pgrep -f ovsdb-server    # OVS running?
podman exec ukm_ryu pgrep -f ryu-manager         # Ryu running?

# Check OpenVSwitch status
podman exec ukm_mininet ovs-vsctl show

# View flow tables on switch s1
podman exec ukm_mininet ovs-ofctl dump-flows s1

# View auto-start entry point logs (NEW!)
podman exec ukm_mininet cat /var/log/ukmsdn/mininet_entrypoint.log
podman exec ukm_ryu cat /var/log/ukmsdn/ryu_entrypoint.log
podman exec ukm_ryu cat /var/log/ukmsdn/ryu_controller.log

# Follow Ryu controller logs in real-time
podman exec ukm_ryu tail -f /var/log/ukmsdn/ryu_controller.log

# View container logs
podman logs ukm_mininet
podman logs ukm_ryu
```

## File Structure

```
ukmsdn/
├── setup_container.py          # Container environment setup (primary)
├── test_ukmsdn.py              # Testing and validation suite
├── setup.py                    # Legacy host installation
├── README.md                   # This file
├── CLAUDE.md                   # Developer documentation
├── AUTO_START_ARCHITECTURE.md  # Auto-start architecture guide
├── container_scripts/          # Entry point scripts (auto-start)
│   ├── mininet_entrypoint.sh   # OVS auto-start + supervision
│   └── ryu_entrypoint.sh       # Ryu auto-start + supervision
├── backup_container/           # Container backup utilities
│   ├── backup_image.py         # Create container backups
│   └── restore_backup.py       # Restore from backups
└── examples/                   # Usage examples and topologies
    ├── 4-network.py            # Custom 4-network topology
    ├── ddos_detection.py       # DDoS detection example
    └── ryu/                    # Custom Ryu applications
```

## Container Management

### Available Containers

| Container | Purpose | Auto-Start Services |
|-----------|---------|---------------------|
| `ukm_mininet` | Network emulation | ✅ OpenVSwitch (OVS) |
| `ukm_ryu` | SDN controller | ✅ Ryu controller |

### Common Commands

```bash
# Check container and service status
podman ps                                           # Container status
podman exec ukm_mininet pgrep -f ovsdb-server      # OVS running?
podman exec ukm_ryu pgrep -f ryu-manager           # Ryu running?

# Access containers (services already running!)
podman exec -it ukm_mininet /bin/bash
podman exec -it ukm_ryu /bin/bash

# View logs
podman logs ukm_mininet                            # Container logs
podman logs ukm_ryu                                # Container logs
podman exec ukm_ryu tail -f /var/log/ukmsdn/ryu_controller.log  # Ryu logs

# Restart containers (services auto-start on restart!)
podman restart ukm_mininet ukm_ryu

# Stop/start containers
podman stop ukm_mininet ukm_ryu
podman start ukm_mininet ukm_ryu
# Services auto-start when containers start!

# Complete cleanup
podman stop ukm_mininet ukm_ryu
podman rm ukm_mininet ukm_ryu
podman network rm ukmsdn-network
```

## Backup & Restore

```bash
# Create backup
python3 backup_container/backup_image.py

# Restore from backup
python3 backup_container/restore_backup.py
```

## Troubleshooting

### Common Issues

#### Services Not Running

Services should auto-start, but if they're not running:

```bash
# Check if services are running
podman exec ukm_mininet pgrep -f ovsdb-server      # Should return PID
podman exec ukm_ryu pgrep -f ryu-manager           # Should return PID

# If not running, check entry point logs
podman exec ukm_mininet cat /var/log/ukmsdn/mininet_entrypoint.log
podman exec ukm_ryu cat /var/log/ukmsdn/ryu_entrypoint.log

# Services should auto-restart within 30 seconds (supervision)
# If they don't, restart the container:
podman restart ukm_mininet   # or ukm_ryu
```

#### OpenVSwitch Connection Errors

```bash
# Check OVS status
podman exec ukm_mininet ovs-vsctl show

# Check entry point logs for errors
podman exec ukm_mininet cat /var/log/ukmsdn/mininet_entrypoint.log

# Manual OVS restart (normally not needed - auto-restarts)
podman exec ukm_mininet /opt/ukmsdn/scripts/start_ovs.sh
```

#### Controller Not Responding

```bash
# Check if Ryu is running
podman exec ukm_ryu pgrep -f ryu-manager

# Check controller logs
podman exec ukm_ryu cat /var/log/ukmsdn/ryu_controller.log

# If needed, kill Ryu (supervision will auto-restart within 30s)
podman exec ukm_ryu pkill -f ryu-manager
# Wait 30 seconds for auto-restart
```

#### Mininet State Issues

```bash
# Clean up stuck Mininet state
podman exec ukm_mininet mn -c
```

#### Container IP Changed

```bash
# Containers use dynamic IPs - always get current IP
RYU_IP=$(podman inspect ukm_ryu --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
echo "Current controller IP: $RYU_IP"
```

### Log Locations

| Component | Log Location |
|-----------|--------------|
| **Mininet Entry Point** | `/var/log/ukmsdn/mininet_entrypoint.log` |
| **Ryu Entry Point** | `/var/log/ukmsdn/ryu_entrypoint.log` |
| **Ryu Controller** | `/var/log/ukmsdn/ryu_controller.log` |
| **OpenVSwitch** | `/var/log/openvswitch/` |
| **Container Logs** | `podman logs <container_name>` |

### Health Check Commands

```bash
# Quick health check script
echo "=== Container Status ==="
podman ps | grep ukm

echo -e "\n=== Service Status ==="
echo -n "OVS: "
podman exec ukm_mininet pgrep -f ovsdb-server > /dev/null && echo "✅ Running" || echo "❌ Not running"
echo -n "Ryu: "
podman exec ukm_ryu pgrep -f ryu-manager > /dev/null && echo "✅ Running" || echo "❌ Not running"

echo -e "\n=== Controller IP ==="
RYU_IP=$(podman inspect ukm_ryu --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
echo "Ryu IP: $RYU_IP"
```

## Research Applications

This environment is designed for:
- DDoS attack simulation and dataset generation
- SDN protocol research and development
- Network security testing
- Educational networking labs
- OpenFlow application development

## Dependencies

### System Packages
- git, curl, wget
- mininet, openvswitch-switch
- python3-pip, python3-dev
- build-essential
- tshark, slowhttptest, hping3
- iperf3, tcpdump

### Python Packages
- scapy, pandas, numpy
- requests, psutil
- pytest, pytest-cov
- cryptography, pycryptodome
- ryu (from GitHub)
- cicflowmeter (from GitHub)

## Contributing

1. Test changes in container environment first
2. Follow Python coding standards (Black + Flake8)
3. Add tests for new functionality
4. Update documentation as needed

## License

This project is part of the UKMSDN lab framework for academic and research purposes.

## Frequently Asked Questions

**Q: Do I need to manually start OVS or Ryu?**
A: No! They auto-start when containers start. Just run `setup_container.py` and you're ready.

**Q: What if a service crashes?**
A: Services auto-restart within 30 seconds via built-in supervision. No manual intervention needed.

**Q: How do I check if services are running?**
A: `podman exec ukm_mininet pgrep -f ovsdb-server` and `podman exec ukm_ryu pgrep -f ryu-manager`

**Q: Where are the logs?**
A: Entry point logs in `/var/log/ukmsdn/`, service logs available via `podman exec` commands. See Troubleshooting section.

**Q: Why do I get "cannot connect to controller" errors?**
A: This was a common issue in previous versions. With auto-start architecture, this should no longer happen. If it does, check the troubleshooting section.

**Q: Can I use my own Ryu application?**
A: Yes! Set `RYU_APP` environment variable when creating containers, or modify the entry point script to use your custom app.

**Q: Do containers need to be privileged?**
A: Yes, `--privileged` flag is required for network namespace access and OVS operations.

## Documentation

- **README.md** (this file): User guide and quick start
- **AUTO_START_ARCHITECTURE.md**: Technical details of auto-start system
- **CLAUDE.md**: Developer documentation and code patterns

## Support

For issues and questions:
1. **Check service status**: See "Health Check Commands" in Troubleshooting
2. **Review logs**: Entry point logs in `/var/log/ukmsdn/`
3. **Run test suite**: `python3 test_ukmsdn.py`
4. **Check documentation**: See AUTO_START_ARCHITECTURE.md for details