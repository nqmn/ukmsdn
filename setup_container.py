#!/usr/bin/env python3

import subprocess
import sys
import os
import tempfile
import shutil
import time

def run_command(cmd, shell=True, check=True, capture_output=False):
    """Run a command and handle errors"""
    try:
        if capture_output:
            result = subprocess.run(cmd, shell=shell, check=check, capture_output=True, text=True)
            return result.stdout.strip()
        else:
            result = subprocess.run(cmd, shell=shell, check=check)
            return result.returncode == 0
    except subprocess.CalledProcessError as e:
        if not check:
            return False
        print(f"Command failed: {cmd}")
        print(f"Error: {e}")
        return False

def check_podman():
    """Check if Podman is installed"""
    print("📋 Checking Podman installation...")
    if not shutil.which('podman'):
        print("❌ Podman is not installed. Installing Podman...")
        run_command("sudo apt update")
        run_command("sudo apt install -y podman")

def build_base_image(base_image_name):
    """Build the custom base image"""
    print(f"Building custom base image ({base_image_name})...")

    dockerfile_content = '''FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \\
    PYTHONDONTWRITEBYTECODE=1 \\
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get upgrade -y && \\
    apt-get install -y \\
        git \\
        mininet \\
        python3-pip \\
        python3-dev \\
        python3-setuptools \\
        python3-venv \\
        build-essential \\
        curl \\
        wget \\
        tshark \\
        slowhttptest \\
        iproute2 \\
        iputils-ping \\
        net-tools \\
        sudo \\
        vim \\
        nano \\
        tcpdump \\
        openvswitch-switch \\
        openvswitch-common \\
        iperf3 \\
        hping3 && \\
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN pip3 install --break-system-packages \\
        'scapy>=2.4.5' \\
        'pandas>=0.24' \\
        'numpy>=1.3.0' \\
        'requests>=2.26.0' \\
        'psutil>=1.8.9' \\
        'webob>=1.8.9' \\
        'pytest>=4.6.11' \\
        'pytest-cov>=2.12.1' \\
        'flake8>=3.9.2' \\
        'black>=22.8.0' \\
        'isort>=4.3.21' \\
        'pycryptodome>=3.21.0' \\
        'cryptography>=2.5,<38.0.0' \\
        'pyOpenSSL<23.0.0' \\
        'eventlet>=0.33.0' \\
        'Routes>=2.5.1' \\
        'greenlet>=2.0.2' \\
        'msgpack>=1.0.7' \\
        'netaddr>=0.8.0' \\
        'oslo.config>=9.2.0' \\
        'oslo.i18n>=6.1.0' \\
        'oslo.utils>=6.0.1' \\
        'rfc3986>=1.5.0' \\
        'repoze.lru>=0.7' \\
        'stevedore>=5.1.0' \\
        'tinyrpc>=1.1.1'

RUN useradd -m -s /bin/bash mininet && \\
    echo 'mininet ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers && \\
    useradd -m -s /bin/bash ryu && \\
    mkdir -p /opt/ukmsdn/scripts /opt/ukmsdn/data /opt/ukmsdn/logs /opt/ukmsdn/apps

RUN git clone https://github.com/nqmn/cicflowmeter.git /opt/ukmsdn/cicflowmeter && \\
    pip3 install --break-system-packages /opt/ukmsdn/cicflowmeter

RUN git clone https://github.com/nqmn/ryu.git /opt/ukmsdn/ryu && \\
    pip3 install --break-system-packages --no-deps -e /opt/ukmsdn/ryu && \\
    echo 'export PATH="/opt/ukmsdn/ryu/bin:$PATH"' >> /etc/profile.d/ryu.sh

RUN touch /opt/ukmsdn/.base_image_ready
'''

    with tempfile.TemporaryDirectory() as workdir:
        dockerfile_path = os.path.join(workdir, 'Dockerfile')
        with open(dockerfile_path, 'w') as f:
            f.write(dockerfile_content)

        if not run_command(f'podman build -t "{base_image_name}" "{workdir}"', check=False):
            print("Failed to build base image.")
            sys.exit(1)

def check_image_exists(image_name):
    """Check if a Podman image exists"""
    return run_command(f'podman image exists "{image_name}"', check=False)

def cleanup_containers():
    """Clean up existing containers"""
    print("🧹 Cleaning up existing containers...")
    run_command("podman stop ukm_mininet ukm_ryu", check=False)
    run_command("podman rm ukm_mininet ukm_ryu", check=False)

def create_network():
    """Create custom network"""
    print("")
    print("🌐 Creating UKMSDN Network")
    print("==========================")
    run_command("podman network create ukmsdn-network", check=False)

def create_containers(base_image_name):
    """Create containers on custom network"""
    print("")
    print("📦 Creating Containers on Custom Network")
    print("========================================")

    print("Creating Mininet container (ukm_mininet)...")
    run_command(f'podman run -d --name ukm_mininet --privileged --network ukmsdn-network {base_image_name} sleep infinity')

    print("Creating Ryu controller container (ukm_ryu)...")
    run_command(f'podman run -d --name ukm_ryu --privileged --network ukmsdn-network {base_image_name} sleep infinity')

def get_container_ip(container_name):
    """Get container IP address"""
    return run_command(f'podman inspect {container_name} | grep \'"IPAddress"\' | tail -1 | cut -d\'"\' -f4', capture_output=True)

def create_start_ovs_script():
    """Create the start_ovs.sh script using Python and copy to container"""
    start_ovs_content = """#!/bin/bash

echo 'Starting container-optimized OpenVSwitch services...'

cleanup_processes() {
    echo 'Cleaning up existing OVS processes...'
    pkill -TERM -f ovsdb-server 2>/dev/null || true
    pkill -TERM -f ovs-vswitchd 2>/dev/null || true
    sleep 2
    pkill -KILL -f ovsdb-server 2>/dev/null || true
    pkill -KILL -f ovs-vswitchd 2>/dev/null || true
    sleep 1

    rm -rf /var/run/openvswitch/*
    rm -f /var/log/openvswitch/*.log
}

start_ovs_services() {
    mkdir -p /var/run/openvswitch /var/log/openvswitch /etc/openvswitch

    if [ ! -f /etc/openvswitch/conf.db ]; then
        echo 'Creating OVS database...'
        ovsdb-tool create /etc/openvswitch/conf.db /usr/share/openvswitch/vswitch.ovsschema
    fi

    echo 'Starting ovsdb-server...'
    ovsdb-server /etc/openvswitch/conf.db \\
        --remote=punix:/var/run/openvswitch/db.sock \\
        --remote=db:Open_vSwitch,Open_vSwitch,manager_options \\
        --pidfile=/var/run/openvswitch/ovsdb-server.pid \\
        --detach \\
        --log-file=/var/log/openvswitch/ovsdb-server.log \\
        --unixctl=/var/run/openvswitch/ovsdb-server.ctl

    local timeout=30
    local count=0
    while [ ! -S /var/run/openvswitch/db.sock ] && [ $count -lt $timeout ]; do
        sleep 1
        count=$((count + 1))
    done

    if [ ! -S /var/run/openvswitch/db.sock ]; then
        echo 'ERROR: OVS database socket not created within timeout'
        return 1
    fi

    echo 'Initializing OVS database...'
    ovs-vsctl --no-wait init

    echo 'Starting ovs-vswitchd with userspace datapath...'
    ovs-vswitchd --pidfile=/var/run/openvswitch/ovs-vswitchd.pid \\
        --detach \\
        --log-file=/var/log/openvswitch/ovs-vswitchd.log \\
        --unixctl=/var/run/openvswitch/ovs-vswitchd.ctl

    sleep 5

    if ovs-vsctl show >/dev/null 2>&1; then
        echo 'OpenVSwitch started successfully in userspace mode'
        echo 'USERSPACE' > /opt/ukmsdn/scripts/.ovs_mode
        return 0
    else
        echo 'ERROR: OVS connection test failed'
        return 1
    fi
}

cleanup_processes

if start_ovs_services; then
    echo 'OpenVSwitch is ready for use'
    ovs-vsctl show
    exit 0
else
    echo 'ERROR: Failed to start OpenVSwitch'
    exit 1
fi
"""

    # Create temporary file with the script content
    with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as tmp_file:
        tmp_file.write(start_ovs_content)
        tmp_file_path = tmp_file.name

    try:
        # Copy the script to the container
        run_command(f'podman cp "{tmp_file_path}" ukm_mininet:/opt/ukmsdn/scripts/start_ovs.sh')
        # Make it executable and run it
        run_command('podman exec ukm_mininet chmod +x /opt/ukmsdn/scripts/start_ovs.sh')
        run_command('podman exec ukm_mininet /opt/ukmsdn/scripts/start_ovs.sh')
    finally:
        # Clean up temporary file
        try:
            os.unlink(tmp_file_path)
        except:
            pass

def install_mininet_container():
    """Install Mininet container"""
    print("")
    print("🔧 Installing Mininet Container (ukm_mininet - Container 1)")
    print("===========================================================")

    mininet_script = '''set -e
export DEBIAN_FRONTEND=noninteractive
BASE_IMAGE_READY_FLAG="/opt/ukmsdn/.base_image_ready"

if [ ! -f "$BASE_IMAGE_READY_FLAG" ]; then
  echo "Updating package manager..."
  apt-get update && apt-get upgrade -y
  echo "Installing system dependencies..."
  apt-get install -y     git mininet python3-pip python3-dev python3-setuptools python3-venv     build-essential curl wget tshark slowhttptest iproute2 iputils-ping     net-tools sudo vim nano tcpdump openvswitch-switch openvswitch-common     iperf3 hping3
  echo "Installing Python packages..."
  pip3 install --break-system-packages     'scapy>=2.4.5' 'pandas>=0.24' 'numpy>=1.3.0' 'requests>=2.26.0'     'psutil>=1.8.9' 'webob>=1.8.9' 'pytest>=4.6.11' 'pytest-cov>=2.12.1'     'flake8>=3.9.2' 'black>=22.8.0' 'isort>=4.3.21' 'pycryptodome>=3.21.0'     'cryptography>=2.5,<38.0.0' 'pyOpenSSL<23.0.0'     'eventlet>=0.33.0' 'Routes>=2.5.1' 'greenlet>=2.0.2' 'msgpack>=1.0.7'     'netaddr>=0.8.0' 'oslo.config>=9.2.0' 'oslo.i18n>=6.1.0' 'oslo.utils>=6.0.1'     'rfc3986>=1.5.0' 'repoze.lru>=0.7' 'stevedore>=5.1.0' 'tinyrpc>=1.1.1'
else
  echo "Base image detected - skipping package installation for Mininet."
fi

echo "Setting up OpenVSwitch (OVS)..."
mkdir -p /var/run/openvswitch /var/log/openvswitch /etc/openvswitch
pkill -f ovsdb-server || true
pkill -f ovs-vswitchd || true
rm -f /var/run/openvswitch/db.sock /var/run/openvswitch/*.pid
[ -f /etc/openvswitch/conf.db ] ||   ovsdb-tool create /etc/openvswitch/conf.db /usr/share/openvswitch/vswitch.ovsschema
ovsdb-server --remote=punix:/var/run/openvswitch/db.sock   --remote=db:Open_vSwitch,Open_vSwitch,manager_options   --pidfile --detach --log-file
sleep 2
ovs-vsctl --no-wait init || true
ovs-vswitchd --pidfile --detach --log-file
sleep 3
ovs-vsctl show || true

useradd -m -s /bin/bash mininet || true
echo 'mininet ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers || true
usermod -aG sudo mininet || true

mkdir -p /opt/ukmsdn/data /opt/ukmsdn/logs /opt/ukmsdn/scripts

if [ ! -d /opt/ukmsdn/cicflowmeter ]; then
  echo "Cloning and installing CICFlowMeter..."
  cd /opt/ukmsdn
  git clone https://github.com/nqmn/cicflowmeter.git
  cd cicflowmeter
  pip3 install --break-system-packages .
else
  echo "CICFlowMeter already present; skipping clone."
fi
'''

    process = subprocess.Popen(['podman', 'exec', '-i', 'ukm_mininet', 'bash'],
                              stdin=subprocess.PIPE, text=True)
    process.communicate(input=mininet_script)

    # Create the start_ovs.sh script using Python
    create_start_ovs_script()

def install_ryu_container():
    """Install Ryu controller container"""
    print("")
    print("🎛️ Installing Ryu Controller Container (ukm_ryu - Container 2)")
    print("==============================================================")

    ryu_script = '''set -e
export DEBIAN_FRONTEND=noninteractive
BASE_IMAGE_READY_FLAG="/opt/ukmsdn/.base_image_ready"

if [ ! -f "$BASE_IMAGE_READY_FLAG" ]; then
  echo "Updating package manager..."
  apt-get update && apt-get upgrade -y
  echo "Installing system dependencies..."
  apt-get install -y git python3-pip python3-dev python3-setuptools python3-venv     build-essential curl wget tshark sudo vim nano
  echo "Installing Python packages..."
  pip3 install --break-system-packages     'scapy>=2.4.5' 'pandas>=0.24' 'numpy>=1.3.0' 'requests>=2.26.0'     'psutil>=1.8.9' 'webob>=1.8.9' 'pytest>=4.6.11' 'pytest-cov>=2.12.1'     'flake8>=3.9.2' 'black>=22.8.0' 'isort>=4.3.21' 'pycryptodome>=3.21.0'     'cryptography>=2.5,<38.0.0' 'pyOpenSSL<23.0.0'     'eventlet>=0.33.0' 'Routes>=2.5.1' 'greenlet>=2.0.2' 'msgpack>=1.0.7'     'netaddr>=0.8.0' 'oslo.config>=9.2.0' 'oslo.i18n>=6.1.0' 'oslo.utils>=6.0.1'     'rfc3986>=1.5.0' 'repoze.lru>=0.7' 'stevedore>=5.1.0' 'tinyrpc>=1.1.1'
else
  echo "Base image detected - skipping package installation for Ryu controller."
fi

echo "Setting up working directory..."
mkdir -p /opt/ukmsdn
cd /opt/ukmsdn

if [ ! -d /opt/ukmsdn/ryu ]; then
  echo "Cloning and installing Ryu from GitHub..."
  git clone https://github.com/nqmn/ryu.git
  cd /opt/ukmsdn/ryu
  pip3 install --break-system-packages --no-deps -e .
else
  echo "Ryu repository already present; pulling latest changes."
  cd /opt/ukmsdn/ryu
  git pull --ff-only || true
  pip3 install --break-system-packages --no-deps -e .
fi

echo 'export PATH="/opt/ukmsdn/ryu/bin:$PATH"' > /etc/profile.d/ryu.sh
useradd -m -s /bin/bash ryu || true
chown -R ryu:ryu /opt/ukmsdn
mkdir -p /opt/ukmsdn/data /opt/ukmsdn/logs /opt/ukmsdn/apps
chown -R ryu:ryu /opt/ukmsdn
'''

    process = subprocess.Popen(['podman', 'exec', '-i', 'ukm_ryu', 'bash'],
                              stdin=subprocess.PIPE, text=True)
    process.communicate(input=ryu_script)

def get_ovs_mode():
    """Get OVS mode from container"""
    try:
        return run_command('podman exec ukm_mininet bash -lc "cat /opt/ukmsdn/scripts/.ovs_mode"', capture_output=True)
    except:
        return "UNKNOWN"

def show_final_status():
    """Show final status and instructions"""
    print("")
    print("🎉 Installation Complete!")
    print("========================")

    print("")
    print("📋 Container Status:")
    run_command('podman ps --format "table {{.Names}}\\t{{.Image}}\\t{{.Status}}\\t{{.Ports}}"')

    print("")
    print("📍 Final IP Addresses:")
    mininet_ip = get_container_ip('ukm_mininet')
    ryu_ip = get_container_ip('ukm_ryu')
    print(f"   Mininet Container: {mininet_ip}")
    print(f"   Ryu Controller: {ryu_ip}")

    ovs_mode = get_ovs_mode()

    if ovs_mode == "USERSPACE":
        mininet_test_cmd = f"podman exec -it ukm_mininet mn --controller=remote,ip={ryu_ip},port=6633 --topo=single,3 --switch ovs,datapath=user"
    else:
        mininet_test_cmd = f"podman exec -it ukm_mininet mn --controller=remote,ip={ryu_ip},port=6633 --topo=single,3"

    print("")
    print(f"Detected OVS datapath mode: {ovs_mode}")
    if ovs_mode == "USERSPACE":
        print("   Userspace datapath detected - Mininet commands include '--switch ovs,datapath=user'.")
    print("")

    print("🚀 Usage Instructions:")
    print("=====================")

    print("")
    print("📡 Access Mininet Container:")
    print("   podman exec -it ukm_mininet /bin/bash")

    print("")
    print("🎛️ Access Ryu Controller Container:")
    print("   podman exec -it ukm_ryu /bin/bash")

    print("")
    print("✅ Your UKMSDN containerized environment is ready!")
    print("🌐 Containers are on custom network with DNS enabled for better SDN functionality")

    print("")
    print("🧪 Running Integration Tests")
    print("============================")
    if os.path.exists("test_ukmsdn.py"):
        print("Starting automated testing...")
        run_command("python3 test_ukmsdn.py", check=False)
    elif os.path.exists("test_ukmsdn.sh"):
        print("Starting automated testing...")
        run_command("bash test_ukmsdn.sh", check=False)
    else:
        print("⚠️  Test script not found. Running quick validation test...")
        print("Testing basic connectivity...")

        # Quick validation test
        ryu_start_cmd = f"podman exec -d ukm_ryu bash -c 'cd /opt/ukmsdn/ryu && ryu-manager ryu/app/simple_switch_13.py --verbose'"
        run_command(ryu_start_cmd, check=False)
        time.sleep(3)

        validation_cmd = f"podman exec ukm_mininet timeout 30 mn --controller=remote,ip={ryu_ip},port=6633 --topo=single,2 --switch ovs,datapath=user --test pingall"
        if run_command(validation_cmd, check=False):
            print("✅ Quick validation: PASSED - SDN environment is working!")
        else:
            print("⚠️  Quick validation: Check manually using commands above")

def main():
    """Main function"""
    print("🚀 UKMSDN Complete Setup - Creating Containers and Installing Components")
    print("=========================================================================")

    base_image_name = "ukm-ubuntu:24.04-updated"

    # Step 1: Check Podman
    check_podman()

    # Step 2: Prepare custom base image
    print(f"Checking custom base image ({base_image_name})...")
    if not check_image_exists(base_image_name):
        print("Custom base image not found. Building...")
        build_base_image(base_image_name)
    else:
        print("Custom base image already exists locally")

    # Step 3: Clean up existing containers
    cleanup_containers()

    # Step 4: Create custom network
    create_network()

    # Step 5: Create containers
    create_containers(base_image_name)

    # Step 6: Get container IPs
    print("")
    print("📍 Container IP Addresses:")
    mininet_ip = get_container_ip('ukm_mininet')
    ryu_ip = get_container_ip('ukm_ryu')
    print(f"   Mininet (ukm_mininet): {mininet_ip}")
    print(f"   Ryu Controller (ukm_ryu): {ryu_ip}")

    # Step 7: Install Mininet container
    install_mininet_container()

    # Step 8: Install Ryu container
    install_ryu_container()

    # Step 9: Show final status
    show_final_status()

if __name__ == "__main__":
    main()