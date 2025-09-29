#!/usr/bin/env python3
"""
Quick Ryu-Manager Check Script
Focuses on checking if ryu-manager is working properly in ukm_ryu container
"""

import subprocess
import time

def run_command(cmd, timeout=15):
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

def check_ryu_status():
    """Quick check of ryu-manager status"""
    print("🔍 Quick Ryu-Manager Status Check")
    print("=================================")

    # 1. Check if ryu-manager process is running
    print("1. Checking ryu-manager process...")
    cmd = "podman exec ukm_ryu pgrep -f ryu-manager"
    success, stdout, stderr = run_command(cmd)

    if success and stdout.strip():
        pid = stdout.strip()
        print(f"   ✅ ryu-manager running (PID: {pid})")

        # Get more details about the process
        cmd = f"podman exec ukm_ryu ps -p {pid} -o pid,ppid,cmd --no-headers"
        success, stdout, stderr = run_command(cmd)
        if success:
            print(f"   📝 Process: {stdout.strip()}")
    else:
        print("   ❌ ryu-manager not running")
        return False

    # 2. Check if OpenFlow port is listening
    print("\n2. Checking OpenFlow port (6633)...")
    controller_ip = get_controller_ip()
    if controller_ip:
        print(f"   📍 Controller IP: {controller_ip}")

        cmd = "podman exec ukm_ryu netstat -tlnp | grep 6633"
        success, stdout, stderr = run_command(cmd)

        if success and "6633" in stdout:
            print("   ✅ Port 6633 listening")
        else:
            print("   ❌ Port 6633 not listening")
            return False
    else:
        print("   ❌ Could not get controller IP")
        return False

    # 3. Quick connectivity test
    print("\n3. Testing basic connectivity...")
    test_cmd = f'podman exec ukm_mininet timeout 10 mn --controller=remote,ip={controller_ip},port=6633 --topo=single,1 --switch ovs,datapath=user --test pingall'
    success, stdout, stderr = run_command(test_cmd, timeout=15)

    output = stdout + stderr
    if "0% dropped" in output or "received" in output:
        print("   ✅ Basic connectivity works")
        return True
    else:
        print("   ❌ Connectivity test failed")
        print(f"   📝 Output: {output[-100:]}")  # Last 100 chars
        return False

def restart_ryu_controller():
    """Restart ryu-manager with simple_switch_13"""
    print("\n🔄 Restarting Ryu Controller")
    print("============================")

    # Kill existing ryu-manager
    print("1. Stopping existing ryu-manager...")
    cmd = "podman exec ukm_ryu pkill -f ryu-manager"
    run_command(cmd)
    time.sleep(2)

    # Start simple_switch_13
    print("2. Starting simple_switch_13...")
    cmd = 'podman exec -d ukm_ryu bash -c "cd /opt/ukmsdn/ryu && ryu-manager ryu/app/simple_switch_13.py --verbose"'
    success, stdout, stderr = run_command(cmd)

    if success:
        print("   ✅ Controller started")
        time.sleep(3)
        return True
    else:
        print(f"   ❌ Failed to start: {stderr}")
        return False

def main():
    """Main function"""
    print("🌐 Quick Ryu Controller Check")
    print("=============================")

    # First check current status
    if check_ryu_status():
        print("\n🎉 Ryu controller is working properly!")
        return True
    else:
        print("\n⚠️  Ryu controller has issues")

        # Ask if user wants to restart
        try:
            response = input("\n🔄 Try restarting the controller? (y/n): ").lower()
            if response in ['y', 'yes']:
                if restart_ryu_controller():
                    print("\n🔍 Re-checking after restart...")
                    if check_ryu_status():
                        print("\n🎉 Controller is now working!")
                        return True
                    else:
                        print("\n❌ Still having issues after restart")
                        return False
                else:
                    print("\n❌ Failed to restart controller")
                    return False
            else:
                print("\nℹ️  To manually restart:")
                print("   podman exec ukm_ryu pkill -f ryu-manager")
                print("   podman exec -d ukm_ryu bash -c \"cd /opt/ukmsdn/ryu && ryu-manager ryu/app/simple_switch_13.py --verbose\"")
                return False
        except KeyboardInterrupt:
            print("\n\n👋 Cancelled by user")
            return False

if __name__ == "__main__":
    main()