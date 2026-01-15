#!/usr/bin/env python3
"""
UKMSDN 4-Network Topology Creator
==================================

TOPOLOGY OVERVIEW:
This script creates a simple 4-network topology with 3 switches and 6 hosts
using Mininet and connects them to a Ryu SDN controller.

NETWORK TOPOLOGY:
                 Controller (Ryu)
                      |
    h1 ──── sw1 ──── sw2 ──── sw3 ──── h6
              │       │       │
              │    h2 h3 h4 h5 │
              │               │
           Network         Network

DETAILED LAYOUT:
- Switch sw1: Connected to host h1 (10.0.0.1/24)
- Switch sw2: Connected to hosts h2, h3, h4, h5 (10.0.0.2-5/24)
- Switch sw3: Connected to host h6 (10.0.0.6/24)
- Inter-switch links: sw1 <-> sw2 <-> sw3
- All hosts are in the same subnet (10.0.0.0/24)

WHAT THIS SCRIPT DOES:
1. Environment Setup:
   - Cleans up existing Mininet processes
   - Restarts OpenVSwitch service
   - Ensures custom Ryu controller (simple_switch_13.py) is available
   - Starts Ryu controller with the custom simple switch application

2. Topology Creation:
   - Creates a custom Mininet topology with 3 switches and 6 hosts
   - Configures proper IP addressing and routing
   - Connects all switches to the remote Ryu controller

3. Controller Features:
   - Uses custom simple_switch_13.py for enhanced L2 switching
   - Automatic MAC address learning
   - Flow rule installation for efficient packet forwarding
   - Fallback mechanisms for reliability

4. Testing Environment:
   - Launches interactive Mininet CLI
   - Provides test commands (pingall, individual pings, dump)
   - Enables network experimentation and verification

USE CASES:
- Learning basic SDN concepts with OpenFlow
- Testing L2 switching and MAC learning
- Understanding Mininet topology creation
- Experimenting with flow rules and packet forwarding
- Educational demonstrations of software-defined networking

REQUIREMENTS:
- Podman containers: ukm_mininet, ukm_ryu
- Custom Ryu application: examples/ryu/simple_switch_13.py
- Working OpenVSwitch installation
"""

import subprocess
import sys
import time

def run_command(cmd, timeout=30):
    """Run command with timeout"""
    try:
        result = subprocess.run(cmd, shell=True, timeout=timeout,
                              capture_output=True, text=True)
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"

def get_controller_ip():
    """Get the dynamic IP address of the Ryu controller container"""
    cmd = "podman inspect ukm_ryu --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'"
    success, stdout, stderr = run_command(cmd)
    if success and stdout.strip():
        return stdout.strip()
    return None

def setup_environment():
    """Setup and clean environment before testing"""
    print("🧹 Preparing Environment for 4-Network Topology")
    print("===============================================")

    # Step 1: Clean up any existing Mininet processes and interfaces
    print("1. Cleaning up existing Mininet processes...")
    cleanup_cmd = 'podman exec ukm_mininet mn -c'
    success, stdout, stderr = run_command(cleanup_cmd)
    if success:
        print("   ✅ Mininet cleanup completed")
    else:
        print("   ⚠️  Mininet cleanup had warnings (normal)")

    # Step 2: Restart OpenVSwitch service
    print("2. Restarting OpenVSwitch service...")
    ovs_cmd = 'podman exec ukm_mininet /opt/ukmsdn/scripts/start_ovs.sh'
    success, stdout, stderr = run_command(ovs_cmd, timeout=60)
    output = stdout + stderr
    if success and ("OpenVSwitch is ready for use" in output or "OpenVSwitch started successfully" in output):
        print("   ✅ OpenVSwitch service restarted successfully")
    else:
        print("   ❌ OpenVSwitch restart failed")
        print("   Error:", stderr[-300:] if stderr else "Unknown error")
        return False

    # Step 3: Check and setup Ryu controller with correct file
    print("3. Checking Ryu controller...")

    # First, check if our custom simple_switch_13.py exists
    target_ryu_file = "/opt/ukmsdn/examples/ryu/simple_switch_13.py"
    check_file_cmd = f'podman exec ukm_ryu test -f {target_ryu_file}'
    file_exists, _, _ = run_command(check_file_cmd)

    if not file_exists:
        print(f"   ⚠️  Target Ryu file {target_ryu_file} not found")
        print("   📂 Creating directory structure and copying custom simple_switch_13.py...")

        # Create the directory structure first
        mkdir_cmd = 'podman exec ukm_ryu mkdir -p /opt/ukmsdn/examples/ryu'
        success, stdout, stderr = run_command(mkdir_cmd)
        if not success:
            print(f"   ❌ Failed to create directory: {stderr}")
            return False

        # Now copy the file
        copy_cmd = f'podman cp examples/ryu/simple_switch_13.py ukm_ryu:{target_ryu_file}'
        success, stdout, stderr = run_command(copy_cmd)
        if not success:
            print(f"   ❌ Failed to copy Ryu file: {stderr}")
            return False
        print("   ✅ Custom Ryu file copied successfully")

    # Check if Ryu controller is running with the correct file
    cmd = f'podman exec ukm_ryu pgrep -f "ryu-manager.*{target_ryu_file}"'
    success, stdout, stderr = run_command(cmd)

    if not success:
        print("   ⚠️  Ryu controller not running with correct file. Starting it...")
        # Stop any existing Ryu processes first
        stop_cmd = 'podman exec ukm_ryu pkill -f ryu-manager'
        run_command(stop_cmd)
        time.sleep(2)

        # Start Ryu with our custom file
        cmd = f'podman exec -d ukm_ryu bash -c "cd /opt/ukmsdn && ryu-manager {target_ryu_file} --verbose"'
        success, stdout, stderr = run_command(cmd)
        if not success:
            print(f"   ❌ Failed to start Ryu controller: {stderr}")
            return False
        time.sleep(3)
        print(f"   ✅ Ryu controller started with {target_ryu_file}")
    else:
        print(f"   ✅ Ryu controller is running with correct file ({target_ryu_file})")

    return True

def create_4_network_topology():
    """
    Create custom 4-network topology using mn command:
    - 1 Ryu controller
    - 3 switches (sw1, sw2, sw3)
    - 6 hosts: h1 on sw1, h2-h5 on sw2, h6 on sw3
    """

    # Get dynamic controller IP
    controller_ip = get_controller_ip()
    if not controller_ip:
        print("❌ Failed to get controller IP address")
        return False

    print(f"📍 Using controller IP: {controller_ip}")
    print("\n🌐 Creating 4-Network Topology")
    print("==============================")
    print("Topology: h1-sw1-sw2-sw3-h6")
    print("          h2,h3,h4,h5 on sw2")

    # Create custom topology file inside container
    topo_script = '''
from mininet.topo import Topo

class FourNetworkTopo(Topo):
    def build(self):
        # Add switches
        sw1 = self.addSwitch('sw1')
        sw2 = self.addSwitch('sw2')
        sw3 = self.addSwitch('sw3')

        # Add hosts
        h1 = self.addHost('h1', ip='10.0.0.1/24')
        h2 = self.addHost('h2', ip='10.0.0.2/24')
        h3 = self.addHost('h3', ip='10.0.0.3/24')
        h4 = self.addHost('h4', ip='10.0.0.4/24')
        h5 = self.addHost('h5', ip='10.0.0.5/24')
        h6 = self.addHost('h6', ip='10.0.0.6/24')

        # Connect hosts to switches
        self.addLink(h1, sw1)  # h1 -> sw1
        self.addLink(h2, sw2)  # h2 -> sw2
        self.addLink(h3, sw2)  # h3 -> sw2
        self.addLink(h4, sw2)  # h4 -> sw2
        self.addLink(h5, sw2)  # h5 -> sw2
        self.addLink(h6, sw3)  # h6 -> sw3

        # Inter-switch links
        self.addLink(sw1, sw2)  # sw1 <-> sw2
        self.addLink(sw2, sw3)  # sw2 <-> sw3

topos = {'fournet': (lambda: FourNetworkTopo())}
'''

    # Write topology to container
    cmd = f'podman exec ukm_mininet bash -c "cat > /tmp/fournet_topo.py << \'EOF\'\n{topo_script}\nEOF"'
    success, stdout, stderr = run_command(cmd)
    if not success:
        print("❌ Failed to create topology file")
        return False

    # Run Mininet with custom topology
    print("\n🚀 Starting Mininet with 4-Network topology...")
    cmd = f'podman exec -it ukm_mininet mn --custom /tmp/fournet_topo.py --topo fournet --controller=remote,ip={controller_ip},port=6633 --switch ovs,datapath=user'

    print(f"Running: {cmd}")
    print("\n💡 In Mininet CLI, try:")
    print("   mininet> pingall")
    print("   mininet> h1 ping h6")
    print("   mininet> dump")
    print("   mininet> exit")

    # Execute directly with os.system for interactive mode
    import os
    print("\n🎯 Launching interactive Mininet session...")
    result = os.system(cmd)
    return result == 0

def main():
    """Main function"""
    print("🌐 UKMSDN 4-Network Topology Creator")
    print("====================================")

    # Setup environment first
    if not setup_environment():
        print("❌ Environment setup failed. Exiting.")
        return

    # Create and run topology
    create_4_network_topology()

    print("\n🎉 4-Network topology session completed!")

if __name__ == "__main__":
    main()