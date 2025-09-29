#!/usr/bin/env python3
"""
UKMSDN 4-Internetwork Topology Creator (Multi-Subnet L3 Routing)
=================================================================

TOPOLOGY OVERVIEW:
This script creates an advanced multi-subnet internetwork topology with Layer 3 routing
capabilities, demonstrating inter-subnet communication using a sophisticated Ryu L3
router controller with REST API monitoring.

NETWORK TOPOLOGY:
                    L3 Router Controller (Ryu)
                    with REST API (:8080)
                            |
    [10.0.0.0/24] ── sw1 ── sw2 ── sw3 ── [192.168.0.0/24]
         │                  │              │
        h1              [172.16.0.0/24]   h6
    (10.0.0.1)         h2 h3 h4 h5    (192.168.0.6)
                    (.2 .3 .4 .5)

DETAILED SUBNET LAYOUT:
┌─────────────────┬──────────────────┬─────────────────┬─────────────────┐
│ Subnet          │ Gateway          │ Hosts           │ Switch          │
├─────────────────┼──────────────────┼─────────────────┼─────────────────┤
│ 10.0.0.0/24     │ 10.0.0.254       │ h1 (10.0.0.1)   │ sw1             │
│ 172.16.0.0/24   │ 172.16.0.254     │ h2-h5 (.2-.5)   │ sw2             │
│ 192.168.0.0/24  │ 192.168.0.254    │ h6 (192.168.0.6)│ sw3             │
└─────────────────┴──────────────────┴─────────────────┴─────────────────┘

WHAT THIS SCRIPT DOES:
1. Advanced Environment Setup:
   - Cleans up existing Mininet processes and interfaces
   - Restarts OpenVSwitch with proper configuration
   - Copies and deploys advanced L3 router application (ryu_l3_router_app.py)
   - Sets up fallback to simple_switch_13.py if needed

2. L3 Router Controller Features:
   - Multi-subnet routing between 10.0.0.0/24, 172.16.0.0/24, 192.168.0.0/24
   - ARP proxy functionality for gateway IPs (.254 addresses)
   - ICMP gateway response (ping gateway functionality)
   - Advanced flow rule installation for inter-subnet routing
   - Real-time activity logging and statistics collection

3. REST API Monitoring:
   - Health check endpoint verification (/hello)
   - Live monitoring endpoints available at port 8080:
     * /activity - View controller activity logs
     * /flows - Examine installed flow rules
     * /subnets - Check subnet configuration
     * /routing_table - View routing decisions
     * /stats - Controller performance statistics

4. Multi-Subnet Topology Creation:
   - Creates internetwork with 3 different IP subnets
   - Configures hosts with proper default routes via respective gateways
   - Establishes inter-switch links for routing paths
   - Connects all switches to remote L3 controller

5. Advanced Testing Capabilities:
   - Cross-subnet connectivity testing (h1 ↔ h6 across 3 hops)
   - Same-subnet communication verification
   - Gateway ping testing for each subnet
   - Network troubleshooting and flow analysis

ROUTING EXAMPLES:
- h1 (10.0.0.1) → h6 (192.168.0.6): Routes via 10.0.0.254 → 172.16.0.254 → 192.168.0.254
- h2 (172.16.0.2) → h5 (172.16.0.5): Direct L2 switching on sw2
- Any host → gateway (.254): ARP proxy response from controller

USE CASES:
- Advanced SDN learning with Layer 3 routing
- Multi-subnet network design and testing
- Inter-VLAN routing simulation
- OpenFlow L3 forwarding experiments
- REST API integration for network monitoring
- Enterprise network topology modeling
- Network troubleshooting and flow analysis

CONTROLLER FEATURES:
- Sophisticated L3 packet processing
- Dynamic host discovery across subnets
- Intelligent ARP handling and proxy responses
- RESTful API for real-time monitoring
- Comprehensive logging and statistics
- Automatic fallback mechanisms

REQUIREMENTS:
- Podman containers: ukm_mininet, ukm_ryu
- Advanced controller: examples/ryu/ryu_l3_router_app.py
- Fallback controller: examples/ryu/simple_switch_13.py
- OpenVSwitch with OpenFlow 1.3 support
- curl (optional, for REST API verification)

MONITORING ENDPOINTS (when REST API is active):
- curl http://<controller-ip>:8080/hello
- curl http://<controller-ip>:8080/flows
- curl http://<controller-ip>:8080/activity
- curl http://<controller-ip>:8080/subnets
- curl http://<controller-ip>:8080/stats
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
    print("🧹 Preparing Environment for 4-Internetwork Topology")
    print("==================================================")

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

    # Step 3: Setup custom Ryu L3 router files
    print("3. Setting up custom Ryu L3 router controller...")

    # Check and copy required Ryu files
    target_l3_file = "/opt/ukmsdn/examples/ryu/ryu_l3_router_app.py"
    target_simple_file = "/opt/ukmsdn/examples/ryu/simple_switch_13.py"

    # Create directory structure first
    mkdir_cmd = 'podman exec ukm_ryu mkdir -p /opt/ukmsdn/examples/ryu'
    success, stdout, stderr = run_command(mkdir_cmd)
    if not success:
        print(f"   ❌ Failed to create directory: {stderr}")
        return False

    # Copy L3 router app
    check_l3_cmd = f'podman exec ukm_ryu test -f {target_l3_file}'
    l3_exists, _, _ = run_command(check_l3_cmd)

    if not l3_exists:
        print("   📂 Copying L3 router application...")
        copy_l3_cmd = f'podman cp examples/ryu/ryu_l3_router_app.py ukm_ryu:{target_l3_file}'
        success, stdout, stderr = run_command(copy_l3_cmd)
        if not success:
            print(f"   ❌ Failed to copy L3 router app: {stderr}")
            return False
        print("   ✅ L3 router application copied successfully")

    # Copy simple_switch_13.py as fallback
    check_simple_cmd = f'podman exec ukm_ryu test -f {target_simple_file}'
    simple_exists, _, _ = run_command(check_simple_cmd)

    if not simple_exists:
        print("   📂 Copying fallback simple_switch_13.py...")
        copy_simple_cmd = f'podman cp examples/ryu/simple_switch_13.py ukm_ryu:{target_simple_file}'
        success, stdout, stderr = run_command(copy_simple_cmd)
        if not success:
            print(f"   ❌ Failed to copy simple switch: {stderr}")
            return False
        print("   ✅ Fallback simple_switch_13.py copied successfully")

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
    print("\n🌐 Creating 4-Internetwork Topology")
    print("===================================")
    print("Network topology with 3 different subnets:")
    print("  sw1: h1 (10.0.0.1/24)")
    print("  sw2: h2-h5 (172.16.0.2-5/24)")
    print("  sw3: h6 (192.168.0.6/24)")
    print("Switch connections: sw1 <-> sw2 <-> sw3")

    # Create custom topology file (keeping existing topology)
    topo_script = '''
from mininet.topo import Topo

class FourNetworkTopo(Topo):
    def build(self):
        # Add switches that will act as L3 routers
        sw1 = self.addSwitch('sw1')
        sw2 = self.addSwitch('sw2')
        sw3 = self.addSwitch('sw3')

        # Add hosts with different subnets and gateway routes
        # Network 1: 10.0.0.0/24 (connected to sw1)
        h1 = self.addHost('h1', ip='10.0.0.1/24', defaultRoute='via 10.0.0.254')

        # Network 2: 172.16.0.0/24 (connected to sw2)
        h2 = self.addHost('h2', ip='172.16.0.2/24', defaultRoute='via 172.16.0.254')
        h3 = self.addHost('h3', ip='172.16.0.3/24', defaultRoute='via 172.16.0.254')
        h4 = self.addHost('h4', ip='172.16.0.4/24', defaultRoute='via 172.16.0.254')
        h5 = self.addHost('h5', ip='172.16.0.5/24', defaultRoute='via 172.16.0.254')

        # Network 3: 192.168.0.0/24 (connected to sw3)
        h6 = self.addHost('h6', ip='192.168.0.6/24', defaultRoute='via 192.168.0.254')

        # Connect hosts to their respective switches
        self.addLink(h1, sw1)  # h1 -> sw1 (10.0.0.0/24 network)
        self.addLink(h2, sw2)  # h2 -> sw2 (172.16.0.0/24 network)
        self.addLink(h3, sw2)  # h3 -> sw2
        self.addLink(h4, sw2)  # h4 -> sw2
        self.addLink(h5, sw2)  # h5 -> sw2
        self.addLink(h6, sw3)  # h6 -> sw3 (192.168.0.0/24 network)

        # Inter-switch links for routing between networks
        self.addLink(sw1, sw2)  # Connect 10.0.0.0/24 <-> 172.16.0.0/24
        self.addLink(sw2, sw3)  # Connect 172.16.0.0/24 <-> 192.168.0.0/24

topos = {'fournet': (lambda: FourNetworkTopo())}
'''

    # Write topology file to container
    cmd = f'podman exec ukm_mininet bash -c "cat > /tmp/fournet_topo.py << \'EOF\'\n{topo_script}\nEOF"'
    success, stdout, stderr = run_command(cmd)
    if not success:
        print("❌ Failed to create topology file")
        return False
    print("   ✅ Topology file created")

    # Stop existing Ryu controller and start L3 router
    print("4. Starting L3 Router controller...")
    cmd = 'podman exec ukm_ryu pkill -f ryu-manager'
    run_command(cmd)  # Kill existing controller
    time.sleep(2)

    # Try to start the sophisticated L3 router app with REST API
    target_l3_file = "/opt/ukmsdn/examples/ryu/ryu_l3_router_app.py"
    cmd = f'podman exec -d ukm_ryu bash -c "cd /opt/ukmsdn && ryu-manager {target_l3_file} --verbose"'
    success, stdout, stderr = run_command(cmd)
    if success:
        print("   ✅ L3 Router controller started with REST API")
        time.sleep(4)  # Give controller time to start

        # Verify it's actually running
        verify_cmd = f'podman exec ukm_ryu pgrep -f "ryu_l3_router_app.py"'
        verify_success, _, _ = run_command(verify_cmd)
        if not verify_success:
            print("   ⚠️  L3 controller process not found, falling back to simple_switch_13.py")
            target_simple_file = "/opt/ukmsdn/examples/ryu/simple_switch_13.py"
            fallback_cmd = f'podman exec -d ukm_ryu bash -c "cd /opt/ukmsdn && ryu-manager {target_simple_file} --verbose"'
            fallback_success, _, fallback_stderr = run_command(fallback_cmd)
            if not fallback_success:
                print(f"   ❌ Fallback controller failed: {fallback_stderr}")
                return False
            print("   ✅ Fallback to simple_switch_13.py successful")
        else:
            # Check if REST API is responding
            print("   🔍 Checking REST API availability...")

            # First check if curl is available
            curl_check_cmd = 'podman exec ukm_ryu which curl'
            curl_available, _, _ = run_command(curl_check_cmd)

            if curl_available:
                api_check_cmd = f'podman exec ukm_ryu curl -s -f http://localhost:8080/hello'
                api_success, api_stdout, api_stderr = run_command(api_check_cmd, timeout=10)

                if api_success and "Hello from Ryu L3 Router Controller" in api_stdout:
                    print("   ✅ REST API is responding correctly")
                    print("   🌐 REST API available at: http://<controller-ip>:8080/")
                    print("     Endpoints: /hello, /flows, /activity, /subnets, /routing_table, /stats")
                else:
                    print("   ⚠️  REST API not responding, controller may still work for basic routing")
                    print(f"   API check result: {api_stderr if api_stderr else 'No response'}")
            else:
                print("   ⚠️  curl not available in container, cannot check REST API")
                print("   🌐 REST API should be available at: http://<controller-ip>:8080/")
                print("     Endpoints: /hello, /flows, /activity, /subnets, /routing_table, /stats")
                # Don't fallback just for missing curl - L3 routing should still work
    else:
        print("   ❌ Failed to start L3 controller, trying fallback...")
        target_simple_file = "/opt/ukmsdn/examples/ryu/simple_switch_13.py"
        fallback_cmd = f'podman exec -d ukm_ryu bash -c "cd /opt/ukmsdn && ryu-manager {target_simple_file} --verbose"'
        fallback_success, _, fallback_stderr = run_command(fallback_cmd)
        if not fallback_success:
            print(f"   ❌ Fallback controller failed: {fallback_stderr}")
            return False
        print("   ✅ Using simple_switch_13.py as fallback controller")

    # Run Mininet with custom topology and L3 routing
    print("\n🚀 Starting Mininet with 4-Internetwork topology...")
    cmd = f'podman exec -it ukm_mininet mn --custom /tmp/fournet_topo.py --topo fournet --controller=remote,ip={controller_ip},port=6633 --switch ovs,datapath=user'

    print(f"Running: {cmd}")
    print("\n💡 In Mininet CLI, try:")
    print("   mininet> pingall           # Should work with advanced L3 routing!")
    print("   mininet> h1 ping h6        # Cross-subnet: 10.0.0.1 -> 192.168.0.6")
    print("   mininet> h2 ping h5        # Same subnet: 172.16.0.2 -> 172.16.0.5")
    print("   mininet> h1 ping 10.0.0.254    # Ping gateway")
    print("   mininet> dump")
    print("   mininet> exit")
    print("\n🔧 Controller monitoring (if REST API is running):")
    print("   • View activity: curl http://<controller-ip>:8080/activity")
    print("   • Check flows: curl http://<controller-ip>:8080/flows")
    print("   • Subnet info: curl http://<controller-ip>:8080/subnets")
    print("   • Statistics: curl http://<controller-ip>:8080/stats")

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