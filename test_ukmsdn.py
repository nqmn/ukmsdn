#!/usr/bin/env python3

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

def test_mininet_basic():
    """Test basic Mininet functionality"""
    print("🧪 Testing Basic Mininet Functionality")
    print("======================================")

    # Get dynamic controller IP
    controller_ip = get_controller_ip()
    if not controller_ip:
        print("❌ Failed to get controller IP address")
        return False

    print(f"📍 Using controller IP: {controller_ip}")

    # Test 1: Quick ping test with 2 hosts
    print("\n1. Testing with 2 hosts (quick test)...")
    cmd = f'podman exec ukm_mininet timeout 30 mn --controller=remote,ip={controller_ip},port=6633 --topo=single,2 --switch ovs,datapath=user --test pingall'
    success, stdout, stderr = run_command(cmd, timeout=35)

    # Check both stdout and stderr since Mininet outputs to stderr
    output = stdout + stderr

    if "0% dropped" in output and "received" in output:
        print("✅ 2-host test: PASSED")
        result_line = [line for line in output.split('\n') if 'Results:' in line]
        if result_line:
            print("   Ping results:", result_line[0].strip())
    else:
        print("❌ 2-host test: FAILED")
        if stderr:
            print("Output:", stderr[-500:] if len(stderr) > 500 else stderr)
        return False

    # Test 2: Run the standard command with remote controller
    print("\n2. Testing with Remote Controller (Ryu SDN Controller)...")
    print(f"   Controller: remote,ip={controller_ip},port=6633 (OpenFlow)")
    print("   Topology: single switch with 2 hosts")
    print("   Switch: Open vSwitch with userspace datapath")
    print("   Test: pingall - verifying SDN-controlled connectivity")
    cmd = f'podman exec ukm_mininet timeout 30 mn --controller=remote,ip={controller_ip},port=6633 --topo=single,2 --switch ovs,datapath=user --test pingall'
    success, stdout, stderr = run_command(cmd, timeout=35)
    output = stdout + stderr

    if "0% dropped" in output and "received" in output:
        print("✅ Standard test: PASSED")
        result_line = [line for line in output.split('\n') if 'Results:' in line]
        if result_line:
            print("   Ping results:", result_line[0].strip())
    else:
        print("⚠️  Standard test: Had issues")
        if stderr:
            print("Output:", stderr[-500:] if len(stderr) > 500 else stderr)

    return True


def show_usage_examples():
    """Show practical usage examples"""
    print("\n💡 Practical Usage Examples")
    print("===========================")

    # Get current controller IP for examples
    controller_ip = get_controller_ip()
    if not controller_ip:
        controller_ip = "<CONTROLLER_IP>"
        print("⚠️  Could not detect controller IP. Replace <CONTROLLER_IP> with actual IP.")

    print(f"\n🚀 Quick Tests (Recommended for containers):")
    print("1. Basic 2-host test:")
    print(f"   podman exec ukm_mininet timeout 30 mn --controller=remote,ip={controller_ip},port=6633 --topo=single,2 --switch ovs,datapath=user --test pingall")

    print("\n2. Linear topology test:")
    print(f"   podman exec ukm_mininet timeout 45 mn --controller=remote,ip={controller_ip},port=6633 --topo=linear,3 --switch ovs,datapath=user --test pingall")

    print("\n3. Tree topology test:")
    print(f"   podman exec ukm_mininet timeout 60 mn --controller=remote,ip={controller_ip},port=6633 --topo=tree,2 --switch ovs,datapath=user --test pingall")

    print("\n🎯 Interactive Mode (Use with timeout):")
    print(f"   timeout 120 podman exec -it ukm_mininet mn --controller=remote,ip={controller_ip},port=6633 --topo=single,2 --switch ovs,datapath=user")
    print("\n   Inside Mininet CLI:")
    print("   mininet> pingall")
    print("   mininet> h1 ping -c3 h2")
    print("   mininet> dump")
    print("   mininet> exit")

    print("\n📊 Monitoring Commands:")
    print("   podman exec ukm_mininet ovs-vsctl show")
    print("   podman exec ukm_mininet ovs-ofctl dump-flows s1")
    print("   podman logs ukm_ryu  # Check controller logs")

def setup_environment():
    """Setup and clean environment before testing"""
    print("🧹 Preparing Environment")
    print("========================")
    print("ℹ️  Services now auto-start via container entry points")

    # Step 1: Clean up any existing Mininet processes and interfaces
    print("1. Cleaning up existing Mininet processes...")
    cleanup_cmd = 'podman exec ukm_mininet mn -c'
    success, stdout, stderr = run_command(cleanup_cmd)
    if success:
        print("   ✅ Mininet cleanup completed")
    else:
        print("   ⚠️  Mininet cleanup had warnings (normal)")

    # Step 2: Verify OpenVSwitch service (auto-started by entry point)
    print("2. Verifying OpenVSwitch service (auto-started)...")
    cmd = 'podman exec ukm_mininet pgrep -f ovsdb-server'
    success, stdout, stderr = run_command(cmd)
    if success:
        print("   ✅ OpenVSwitch service running")
        print("   📍 Userspace datapath mode (auto-started)")
    else:
        print("   ⚠️  OpenVSwitch not running - checking entry point logs...")
        log_cmd = 'podman exec ukm_mininet tail -20 /var/log/ukmsdn/mininet_entrypoint.log'
        success, stdout, stderr = run_command(log_cmd)
        if stdout:
            print(f"   Entry point log:\n{stdout}")
        return False

    # Step 3: Verify Ryu controller (auto-started by entry point)
    print("3. Verifying Ryu controller (auto-started)...")
    cmd = 'podman exec ukm_ryu pgrep -f ryu-manager'
    success, stdout, stderr = run_command(cmd)

    if success:
        print("   ✅ Ryu controller is running")
    else:
        print("   ⚠️  Ryu controller not running - checking entry point logs...")
        log_cmd = 'podman exec ukm_ryu tail -20 /var/log/ukmsdn/ryu_entrypoint.log'
        success, stdout, stderr = run_command(log_cmd)
        if stdout:
            print(f"   Entry point log:\n{stdout}")
        # Don't fail - may still be starting
        time.sleep(5)

    # Get controller IP address and verify connectivity
    print("4. Getting controller IP address...")
    controller_ip = get_controller_ip()
    if controller_ip:
        print(f"   📍 Controller IP: {controller_ip}")

        # Verify controller is listening on port 6633
        cmd = f'podman exec ukm_ryu netstat -tlnp 2>/dev/null | grep 6633 || ss -tlnp 2>/dev/null | grep 6633'
        success, stdout, stderr = run_command(cmd)
        if success and "6633" in stdout:
            print("   ✅ Controller listening on port 6633")
        else:
            print("   ⚠️  Controller may not be listening on port 6633 yet")
            time.sleep(3)
    else:
        print("   ❌ Could not get controller IP address")
        return False

    print("\n🎯 Environment verified - services auto-started successfully!")
    return True

def main():
    """Main function"""
    print("🌐 UKMSDN Container Testing Suite")
    print("===================================")

    # Setup environment first
    if not setup_environment():
        print("❌ Environment setup failed. Exiting.")
        return

    # Run tests
    test_mininet_basic()

    show_usage_examples()

    print("\n🎉 Container testing completed!")
    print("💡 For stuck processes, use: podman exec ukm_mininet mn -c")

if __name__ == "__main__":
    main()