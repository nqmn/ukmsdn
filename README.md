# UKMSDN - Mininet Ryu Container Environment

A containerized Software-Defined Networking (SDN) environment for DDoS dataset generation and network research using Mininet and Ryu controller in isolated containers.

## Overview

UKMSDN provides a complete SDN environment running in containers with:
- **Mininet** for network emulation
- **Ryu** SDN controller for OpenFlow-based network control
- **CICFlowMeter** for network traffic analysis
- **OpenVSwitch** for software-defined switching
- Pre-configured tools for network testing and DDoS research

## System Requirements

- Ubuntu 24.04.3 LTS (recommended)
- Podman container runtime
- Root/sudo privileges (required for network namespaces)
- Python 3.8+

## Quick Start

### Option 1: Container Environment (Recommended)

```bash
# Setup containerized environment
sudo python3 setup_container.py

# Access containers
podman exec -it ukm_mininet /bin/bash    # Mininet container
podman exec -it ukm_ryu /bin/bash        # Ryu controller container

# Run basic test
python3 test_ukmsdn.py
```

### Option 2: Host Installation

```bash
# Install directly on Ubuntu host
sudo python3 setup.py
```

## Architecture

```
┌─────────────────┐    ┌─────────────────┐
│  ukm_mininet    │    │    ukm_ryu      │
│                 │    │                 │
│  • Mininet      │◄──►│ • Ryu Controller│
│  • OpenVSwitch  │    │ • OpenFlow Apps │
│  • CICFlowMeter │    │ • Web Interface │
│  • Test Tools   │    │                 │
└─────────────────┘    └─────────────────┘
        │                       │
        └───── ukmsdn-network ──┘
           (Custom Pod Network)
```

## Features

### Networking Tools
- **Mininet**: Network topology emulation
- **OpenVSwitch**: Software-defined switching with userspace datapath
- **Ryu Controller**: OpenFlow 1.3 SDN controller
- **CICFlowMeter**: Real-time network flow analysis

### Testing & Analysis
- **Scapy**: Packet crafting and analysis
- **Tshark**: Network protocol analyzer
- **slowhttptest**: HTTP DoS testing tool
- **hping3**: Network testing utility
- **iperf3**: Network performance testing

### Development Tools
- **Python 3**: Primary development environment
- **Pytest**: Testing framework
- **Black/Flake8**: Code formatting and linting

## Usage Examples

### Basic Network Testing

```bash
# Start simple topology with 2 hosts
podman exec ukm_mininet mn --controller=remote,ip=<RYU_IP>,port=6633 --topo=single,2 --switch ovs,datapath=user --test pingall

# Interactive mode
podman exec -it ukm_mininet mn --controller=remote,ip=<RYU_IP>,port=6633 --topo=single,3 --switch ovs,datapath=user
```

### Advanced Topologies

```bash
# Linear topology (3 switches)
mn --controller=remote,ip=<RYU_IP>,port=6633 --topo=linear,3 --switch ovs,datapath=user

# Tree topology
mn --controller=remote,ip=<RYU_IP>,port=6633 --topo=tree,2 --switch ovs,datapath=user
```

### Monitoring Commands

```bash
# Check OpenVSwitch status
podman exec ukm_mininet ovs-vsctl show

# View flow tables
podman exec ukm_mininet ovs-ofctl dump-flows s1

# Monitor controller logs
podman logs ukm_ryu
```

## File Structure

```
ukmsdn/
├── setup.py                 # Host installation script
├── setup_container.py       # Container environment setup
├── test_ukmsdn.py          # Testing and validation suite
├── backup_container/       # Container backup utilities
│   ├── backup_image.py     # Create container backups
│   └── restore_backup.py   # Restore from backups
└── README.md               # This file
```

## Container Management

### Available Containers
- `ukm_mininet`: Network emulation environment
- `ukm_ryu`: SDN controller container

### Common Commands

```bash
# Container status
podman ps

# Access containers
podman exec -it ukm_mininet /bin/bash
podman exec -it ukm_ryu /bin/bash

# View logs
podman logs ukm_mininet
podman logs ukm_ryu

# Stop/start containers
podman stop ukm_mininet ukm_ryu
podman start ukm_mininet ukm_ryu

# Cleanup
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

**OpenVSwitch connection errors:**
```bash
# Restart OVS in container
podman exec ukm_mininet /opt/ukmsdn/scripts/start_ovs.sh
```

**Controller not responding:**
```bash
# Check if Ryu is running
podman exec ukm_ryu pgrep -f ryu-manager

# Restart controller
podman exec -d ukm_ryu bash -c "cd /opt/ukmsdn/ryu && ryu-manager ryu/app/simple_switch_13.py --verbose"
```

**Network cleanup:**
```bash
# Clean up Mininet state
podman exec ukm_mininet mn -c
```

### Log Locations
- Container logs: `/opt/ukmsdn/logs/`
- OpenVSwitch logs: `/var/log/openvswitch/`
- Ryu logs: Container stdout/stderr

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

## Support

For issues and questions:
- Check container logs: `podman logs <container_name>`
- Verify network connectivity between containers
- Ensure OpenVSwitch is running in userspace mode
- Use test suite: `python3 test_ukmsdn.py`