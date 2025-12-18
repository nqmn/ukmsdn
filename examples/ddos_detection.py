#!/usr/bin/env python3
"""
UKMSDN DDoS Detection Example - Packet Rate-Based Rule Detection with Mitigation
=================================================================================

OVERVIEW:
This script creates a Software-Defined Network with DDoS detection capabilities.
It demonstrates how the Ryu DDoS Detection Controller monitors traffic patterns and
blocks suspected attackers based on configurable JSON rules.

NETWORK TOPOLOGY:
  ┌─────────────────────────────────────────┐
  │     Ryu DDoS Detection Controller        │
  │     (REST API: 8080, OpenFlow: 6633)    │
  └─────────────────────────────────────────┘
                        │
         ┌──────────────┼──────────────┐
         │              │              │
      [h1]           [h2]           [h3]
   (Normal)       (Normal)      (Attacker)
         │              │              │
         └──────────────┼──────────────┘
                        │
                      [sw1]
            (OpenVSwitch with OF 1.3)

DDoS DETECTION FEATURES:
1. Packet Rate Monitoring (PPS)
   - Tracks packets per second from each source IP
   - Detects volumetric attacks with high packet rates

2. Bandwidth Monitoring (BPS)
   - Tracks bytes per second from each source IP
   - Detects large-payload attacks

3. Multi-Feature Rule Logic
   - AND logic: Block only if ALL thresholds exceeded
   - OR logic: Block if ANY threshold exceeded
   - Per-rule configuration for flexibility

4. Blocking Types
   - Temporary: Auto-expiring blocks (configurable duration)
   - Permanent: Manual unblock required via REST API

5. Whitelist Support
   - Trusted IPs that are never blocked
   - Configured in JSON rules

REST API ENDPOINTS (8080):
  GET  /hello              - Health check
  GET  /config             - View current thresholds
  POST /config             - Update thresholds in real-time
  GET  /stats              - View traffic statistics per IP
  GET  /blocked            - List currently blocked IPs
  POST /unblock/<ip>       - Manually unblock an IP
  GET  /activity           - View recent detection events
  GET  /whitelist          - View whitelist IPs
  POST /whitelist          - Add IP to whitelist
  POST /reset              - Clear all stats and blocks

EXAMPLE USAGE:
1. Start topology:
   python3 examples/ddos_detection.py

2. In Mininet CLI, generate normal traffic:
   mininet> h1 ping h2

3. Simulate DDoS attack from h3:
   mininet> h3 cmd hping3 --flood --faster h1

4. Monitor detection (in another terminal):
   curl http://<controller-ip>:8080/stats
   curl http://<controller-ip>:8080/blocked

5. View activity log:
   curl http://<controller-ip>:8080/activity

6. Update thresholds (lower to trigger faster):
   curl -X POST http://<controller-ip>:8080/config \\
     -H "Content-Type: application/json" \\
     -d @new_config.json

7. Manually unblock an IP:
   curl -X POST http://<controller-ip>:8080/unblock/<ip>

8. Exit Mininet:
   mininet> exit

ATTACK SIMULATION EXAMPLES:
  # High packet rate flood (triggers PPS threshold)
  h3 cmd hping3 --flood --faster h1

  # Large payload flood (triggers BPS threshold)
  h3 iperf -c h1 -i 1 -t 10 -R

  # Sustained attack (triggers AND logic rules)
  h3 ping -c 10000 h1

TESTING PHASES:
Phase 1: Normal Traffic
  - Verify h1, h2, h3 can communicate normally
  - Check REST API responds with stats
  - Confirm no blocking of normal traffic

Phase 2: Attack Detection
  - Generate high-rate traffic from h3
  - Monitor /stats endpoint for high PPS/BPS
  - Verify h3 IP appears in /blocked list
  - Confirm h3 traffic is dropped

Phase 3: Configuration Update
  - Lower PPS/BPS thresholds via REST API
  - Generate lower-rate traffic
  - Verify detection at new thresholds

Phase 4: Blocking Management
  - Test temporary block auto-expiration
  - Test permanent block manual unblock
  - Test whitelist immunity

DEFAULT THRESHOLDS (from ddos_config.json):
Rule 1 - Volumetric Flood (OR logic):
  - Trigger: PPS > 1000 OR BPS > 10 MB/s
  - Action: Temporary block for 300 seconds

Rule 2 - Sustained Attack (AND logic):
  - Trigger: PPS > 500 AND BPS > 5 MB/s
  - Action: Permanent block until manual unblock

PERFORMANCE NOTES:
- Packet history stored efficiently with deque (max 10,000 packets)
- Rate calculation: 10-second sliding window (configurable)
- Detection check: Every 5 seconds (configurable)
- Statistics update: Every 1 second

REQUIREMENTS:
- Podman containers: ukm_mininet, ukm_ryu
- Ryu DDoS Detection app: examples/ryu/ryu_ddos_detection_app.py
- Config file: examples/ddos_config.json
- Network tools: hping3, iperf3 (optional for attacks)
- curl (for REST API testing)

TROUBLESHOOTING:
- No blocking: Check thresholds are appropriate for your traffic
- Config errors: Validate JSON structure against ddos_config.json
- REST API 404: Ensure controller is running (check podman logs ukm_ryu)
- High CPU: Reduce monitoring_window or increase check_interval in config
"""

import subprocess
import sys
import time
import os


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
    print("🧹 Preparing Environment for DDoS Detection")
    print("=" * 50)

    # Step 1: Clean up any existing Mininet processes
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
    if success and ("OpenVSwitch is ready" in output or "OpenVSwitch started" in output):
        print("   ✅ OpenVSwitch service restarted successfully")
    else:
        print("   ❌ OpenVSwitch restart failed")
        print("   Error:", stderr[-300:] if stderr else "Unknown error")
        return False

    # Step 3: Setup Ryu DDoS detection files
    print("3. Setting up Ryu DDoS Detection Controller...")

    # Create directory structure
    mkdir_cmd = 'podman exec ukm_ryu mkdir -p /opt/ukmsdn/examples/ryu'
    success, stdout, stderr = run_command(mkdir_cmd)
    if not success:
        print(f"   ❌ Failed to create directory: {stderr}")
        return False

    # Copy DDoS detection app
    check_app_cmd = 'podman exec ukm_ryu test -f /opt/ukmsdn/examples/ryu/ryu_ddos_detection_app.py'
    app_exists, _, _ = run_command(check_app_cmd)

    if not app_exists:
        print("   📂 Copying DDoS Detection app...")
        copy_app_cmd = 'podman cp examples/ryu/ryu_ddos_detection_app.py ukm_ryu:/opt/ukmsdn/examples/ryu/ryu_ddos_detection_app.py'
        success, stdout, stderr = run_command(copy_app_cmd)
        if not success:
            print(f"   ❌ Failed to copy DDoS detection app: {stderr}")
            return False
        print("   ✅ DDoS Detection app copied successfully")
    else:
        print("   ✅ DDoS Detection app already in container")

    # Copy configuration file
    check_config_cmd = 'podman exec ukm_ryu test -f /opt/ukmsdn/examples/ddos_config.json'
    config_exists, _, _ = run_command(check_config_cmd)

    if not config_exists:
        print("   📂 Copying DDoS configuration...")
        copy_config_cmd = 'podman cp examples/ddos_config.json ukm_ryu:/opt/ukmsdn/examples/ddos_config.json'
        success, stdout, stderr = run_command(copy_config_cmd)
        if not success:
            print(f"   ❌ Failed to copy config: {stderr}")
            return False
        print("   ✅ DDoS configuration copied successfully")
    else:
        print("   ✅ DDoS configuration already in container")

    return True


def start_ddos_controller():
    """Start the DDoS detection controller"""
    print("\n4. Starting DDoS Detection Controller...")

    # Stop existing Ryu controller
    stop_cmd = 'podman exec ukm_ryu pkill -f ryu-manager'
    run_command(stop_cmd)
    time.sleep(2)

    # Start DDoS detection controller
    target_app = "/opt/ukmsdn/examples/ryu/ryu_ddos_detection_app.py"
    start_cmd = f'podman exec -d ukm_ryu bash -c "cd /opt/ukmsdn && ryu-manager {target_app} --verbose"'
    success, stdout, stderr = run_command(start_cmd)

    if not success:
        print("   ❌ Failed to start DDoS detection controller")
        print(f"   Error: {stderr}")
        return False

    time.sleep(4)  # Give controller time to start

    # Verify controller is running
    verify_cmd = 'podman exec ukm_ryu pgrep -f ryu_ddos_detection_app.py'
    verify_success, _, _ = run_command(verify_cmd)

    if not verify_success:
        print("   ❌ DDoS detection controller process not found")
        return False

    print("   ✅ DDoS Detection Controller started")

    # Check REST API
    print("   🔍 Checking REST API availability...")

    api_check_cmd = 'podman exec ukm_ryu curl -s -f http://localhost:8080/hello'
    api_success, api_stdout, _ = run_command(api_check_cmd, timeout=10)

    if api_success and "DDoS Detection" in api_stdout:
        print("   ✅ REST API is responding correctly")
        print("   🌐 REST API available at: http://<controller-ip>:8080/")
        print("      Endpoints: /config, /stats, /blocked, /activity, /unblock/<ip>, /whitelist")
    else:
        print("   ⚠️  REST API not responding immediately (controller may need more time)")

    return True


def create_test_topology(controller_ip):
    """Create DDoS detection test topology"""
    print("\n5. Creating DDoS Detection Test Topology...")

    if not controller_ip:
        print("❌ Failed to get controller IP address")
        return False

    print(f"📍 Using controller IP: {controller_ip}")

    # Create simple topology file
    topo_script = '''
from mininet.topo import Topo

class DDoSTestTopo(Topo):
    def build(self):
        # Add one switch
        s1 = self.addSwitch('s1')

        # Add three hosts
        h1 = self.addHost('h1', ip='10.0.0.1/24')      # Normal host
        h2 = self.addHost('h2', ip='10.0.0.2/24')      # Normal host
        h3 = self.addHost('h3', ip='10.0.0.3/24')      # Potential attacker

        # Connect hosts to switch
        self.addLink(h1, s1)
        self.addLink(h2, s1)
        self.addLink(h3, s1)

topos = {'ddostest': (lambda: DDoSTestTopo())}
'''

    # Write topology file to container
    cmd = "podman exec ukm_mininet bash -c \"cat > /tmp/ddos_topo.py << 'EOF'\n" + topo_script + "\nEOF\""
    success, stdout, stderr = run_command(cmd)
    if not success:
        print("❌ Failed to create topology file")
        return False
    print("✅ Topology file created")

    # Create Mininet command
    mn_cmd = f'podman exec -it ukm_mininet mn --custom /tmp/ddos_topo.py --topo ddostest --controller=remote,ip={controller_ip},port=6633 --switch ovs,datapath=user'

    print("\n🎯 DDoS Detection Test Topology")
    print("=" * 50)
    print("Network: Single switch (s1) with 3 hosts")
    print("  • h1 (10.0.0.1) - Normal traffic generator")
    print("  • h2 (10.0.0.2) - Normal traffic generator")
    print("  • h3 (10.0.0.3) - Potential attacker/flooder")
    print()

    print("💡 TESTING INSTRUCTIONS:")
    print("-" * 50)
    print()
    print("1️⃣  NORMAL TRAFFIC TEST (no blocking expected):")
    print("   mininet> h1 ping h2")
    print("   mininet> h1 ping h3")
    print()
    print("2️⃣  SIMULATE DDoS ATTACK (should trigger blocking):")
    print("   mininet> h3 cmd hping3 --flood --faster h1")
    print("   (or in another terminal:)")
    print(f"   curl http://{controller_ip}:8080/stats       # View traffic stats")
    print(f"   curl http://{controller_ip}:8080/blocked     # View blocked IPs")
    print()
    print("3️⃣  ALTERNATIVE ATTACK METHODS:")
    print("   mininet> h3 iperf -c h1 -i 1 -t 10 -R")
    print("   mininet> h3 ping -c 100000 h1")
    print()
    print("4️⃣  MONITOR CONTROLLER:")
    print(f"   curl http://{controller_ip}:8080/config         # Current thresholds")
    print(f"   curl http://{controller_ip}:8080/activity       # Detection events")
    print(f"   curl http://{controller_ip}:8080/whitelist      # Whitelisted IPs")
    print()
    print("5️⃣  UNBLOCK MANUALLY (if permanent block):")
    print(f"   curl -X POST http://{controller_ip}:8080/unblock/10.0.0.3")
    print()
    print("6️⃣  UPDATE THRESHOLDS (lower to test faster):")
    print(f"   curl -X POST http://{controller_ip}:8080/config \\")
    print("     -H 'Content-Type: application/json' \\")
    print("     -d '{\"detection_rules\":[{\"name\":\"test\",\"enabled\":true,\"logic\":\"OR\",\"thresholds\":{\"pps\":100},\"action\":{\"type\":\"temporary\",\"duration\":60}}],\"whitelist\":[],\"monitoring_window\":10,\"check_interval\":5}'")
    print()
    print("7️⃣  EXIT MININET:")
    print("   mininet> exit")
    print()

    # Launch Mininet
    print("🚀 Launching interactive Mininet session...")
    print("=" * 50)
    result = os.system(mn_cmd)
    return result == 0


def main():
    """Main function"""
    print()
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║     UKMSDN DDoS Detection Example - Packet Rate Monitoring     ║")
    print("║          with Rule-Based Detection and IP Mitigation          ║")
    print("╚════════════════════════════════════════════════════════════════╝")
    print()

    # Setup environment
    if not setup_environment():
        print("\n❌ Environment setup failed. Exiting.")
        return

    # Get controller IP
    controller_ip = get_controller_ip()
    if not controller_ip:
        print("\n❌ Could not determine controller IP. Exiting.")
        return

    # Start DDoS controller
    if not start_ddos_controller():
        print("\n❌ Failed to start DDoS detection controller. Exiting.")
        return

    # Create and run topology
    success = create_test_topology(controller_ip)

    print("\n" + "=" * 50)
    if success:
        print("✅ DDoS Detection topology session completed successfully!")
    else:
        print("⚠️  Topology session ended")
    print("=" * 50)
    print()


if __name__ == "__main__":
    main()
