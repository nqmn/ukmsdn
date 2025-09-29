#!/usr/bin/env python3
"""
Ryu Controller Health Check Script
Checks if ryu-manager is running and functioning properly
"""

import subprocess
import sys
import time
import socket
import json
import requests
from datetime import datetime

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

def check_container_status():
    """Check if Ryu container is running"""
    print("🔍 Checking Container Status")
    print("===========================")

    cmd = "podman ps --filter name=ukm_ryu --format '{{.Names}}\t{{.Status}}\t{{.Image}}'"
    success, stdout, stderr = run_command(cmd)

    if success and stdout.strip():
        lines = stdout.strip().split('\n')
        for line in lines:
            if 'ukm_ryu' in line:
                parts = line.split('\t')
                name = parts[0] if len(parts) > 0 else "Unknown"
                status = parts[1] if len(parts) > 1 else "Unknown"
                image = parts[2] if len(parts) > 2 else "Unknown"

                print(f"   📦 Container: {name}")
                print(f"   ✅ Status: {status}")
                print(f"   🐳 Image: {image}")
                return True

    print("   ❌ Ryu container not running")
    return False

def check_ryu_process():
    """Check if ryu-manager process is running"""
    print("\n🔍 Checking Ryu-Manager Process")
    print("===============================")

    cmd = "podman exec ukm_ryu ps aux | grep ryu-manager | grep -v grep"
    success, stdout, stderr = run_command(cmd)

    if success and stdout.strip():
        lines = stdout.strip().split('\n')
        for line in lines:
            if 'ryu-manager' in line:
                parts = line.split()
                pid = parts[1] if len(parts) > 1 else "Unknown"
                cpu = parts[2] if len(parts) > 2 else "Unknown"
                mem = parts[3] if len(parts) > 3 else "Unknown"
                cmd_line = ' '.join(parts[10:]) if len(parts) > 10 else "Unknown"

                print(f"   ✅ Process running")
                print(f"   📊 PID: {pid}")
                print(f"   💾 CPU: {cpu}%")
                print(f"   🧠 Memory: {mem}%")
                print(f"   📝 Command: {cmd_line}")
                return True, cmd_line

    print("   ❌ ryu-manager process not found")
    return False, None

def check_controller_port():
    """Check if controller is listening on OpenFlow port 6633"""
    print("\n🔍 Checking OpenFlow Port (6633)")
    print("=================================")

    controller_ip = get_controller_ip()
    if not controller_ip:
        print("   ❌ Could not get controller IP")
        return False

    print(f"   📍 Controller IP: {controller_ip}")

    # Check if port 6633 is listening
    cmd = "podman exec ukm_ryu netstat -tlnp | grep 6633"
    success, stdout, stderr = run_command(cmd)

    if success and "6633" in stdout:
        print("   ✅ Port 6633 is listening")
        print(f"   📝 Details: {stdout.strip()}")

        # Test TCP connection
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((controller_ip, 6633))
            sock.close()

            if result == 0:
                print("   ✅ TCP connection successful")
                return True
            else:
                print(f"   ⚠️  TCP connection failed (error {result})")
                return False
        except Exception as e:
            print(f"   ⚠️  TCP connection test failed: {e}")
            return False
    else:
        print("   ❌ Port 6633 not listening")
        return False

def check_controller_logs():
    """Check recent controller logs for errors"""
    print("\n🔍 Checking Controller Logs")
    print("===========================")

    cmd = "podman logs ukm_ryu | tail -20"
    success, stdout, stderr = run_command(cmd)

    if success:
        if stdout.strip():
            print("   📝 Recent logs:")
            for line in stdout.strip().split('\n')[-10:]:  # Show last 10 lines
                if line.strip():
                    timestamp = datetime.now().strftime('%H:%M:%S')
                    if any(keyword in line.lower() for keyword in ['error', 'exception', 'failed', 'traceback']):
                        print(f"   ❌ {line}")
                    elif any(keyword in line.lower() for keyword in ['info', 'connected', 'started', 'success']):
                        print(f"   ✅ {line}")
                    else:
                        print(f"   📄 {line}")
            return True
        else:
            print("   ⚠️  No recent logs found")
            return False
    else:
        print("   ❌ Could not retrieve logs")
        return False

def check_rest_api():
    """Check if Ryu REST API is available (if controller supports it)"""
    print("\n🔍 Checking REST API (Optional)")
    print("===============================")

    controller_ip = get_controller_ip()
    if not controller_ip:
        print("   ❌ Could not get controller IP")
        return False

    # Common Ryu REST API ports
    api_ports = [8080, 8181, 8000]

    for port in api_ports:
        try:
            response = requests.get(f"http://{controller_ip}:{port}/stats/switches", timeout=5)
            if response.status_code == 200:
                print(f"   ✅ REST API available on port {port}")
                try:
                    data = response.json()
                    print(f"   📊 Connected switches: {len(data)}")
                    return True
                except:
                    print(f"   ✅ REST API responding on port {port}")
                    return True
        except:
            continue

    print("   ⚠️  REST API not available (normal for some controllers)")
    return False

def test_simple_connectivity():
    """Test basic controller connectivity with a simple topology"""
    print("\n🔍 Testing Basic Connectivity")
    print("=============================")

    controller_ip = get_controller_ip()
    if not controller_ip:
        print("   ❌ Could not get controller IP")
        return False

    print("   🧪 Running quick connectivity test...")

    # Create a minimal topology test
    test_cmd = f'podman exec ukm_mininet timeout 15 mn --controller=remote,ip={controller_ip},port=6633 --topo=single,1 --switch ovs,datapath=user --test pingall'
    success, stdout, stderr = run_command(test_cmd, timeout=20)

    output = stdout + stderr
    if "completed" in output and any(keyword in output for keyword in ["0% dropped", "received"]):
        print("   ✅ Basic connectivity test passed")
        return True
    elif "timeout" in output.lower():
        print("   ⚠️  Connectivity test timed out")
        return False
    else:
        print("   ❌ Basic connectivity test failed")
        if stderr:
            print(f"   📝 Error: {stderr[-200:]}")
        return False

def diagnose_issues():
    """Provide diagnostic suggestions based on test results"""
    print("\n🔧 Diagnostic Summary")
    print("====================")

    # Re-run key checks for summary
    container_ok = check_container_status()
    process_ok, cmd_line = check_ryu_process()
    port_ok = check_controller_port()

    if container_ok and process_ok and port_ok:
        print("   ✅ Controller appears to be healthy")
        print("   💡 If you're having connectivity issues:")
        print("      - Check switch connections")
        print("      - Verify OpenFlow version compatibility")
        print("      - Check firewall settings")
    else:
        print("   ⚠️  Issues detected:")

        if not container_ok:
            print("      🔴 Container not running - run: podman start ukm_ryu")

        if not process_ok:
            print("      🔴 ryu-manager not running - start controller:")
            print("         podman exec -d ukm_ryu ryu-manager <app>.py")

        if not port_ok:
            print("      🔴 OpenFlow port not accessible")
            print("         - Check if controller started properly")
            print("         - Verify network configuration")

    if process_ok and cmd_line:
        if "simple_switch" in cmd_line:
            print("   📊 Controller type: Basic L2 Switch")
        elif "l3_router" in cmd_line:
            print("   📊 Controller type: L3 Router")
        else:
            print(f"   📊 Controller type: Custom ({cmd_line.split('/')[-1]})")

def main():
    """Main function"""
    print("🌐 Ryu Controller Health Check")
    print("==============================")
    print(f"📅 Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Run all checks
    checks = [
        check_container_status,
        check_ryu_process,
        check_controller_port,
        check_controller_logs,
        check_rest_api,
        test_simple_connectivity
    ]

    results = []
    for check in checks:
        try:
            result = check()
            results.append(result)
        except Exception as e:
            print(f"   ❌ Check failed with error: {e}")
            results.append(False)

    # Provide diagnosis
    diagnose_issues()

    # Final summary
    passed = sum(1 for r in results if r)
    total = len(results)

    print(f"\n📊 Overall Health: {passed}/{total} checks passed")

    if passed >= total - 1:  # Allow 1 optional check to fail
        print("🎉 Controller is healthy!")
        return True
    else:
        print("⚠️  Controller has issues that need attention")
        return False

if __name__ == "__main__":
    healthy = main()
    sys.exit(0 if healthy else 1)