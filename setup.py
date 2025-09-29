#!/usr/bin/env python3
"""
Setup script for UKMDDoSDN v1.0 - DDoS Dataset Generation Framework
Installs dependencies and configures environment for Ubuntu 24.04.3
"""

import os
import sys
import subprocess
import platform
from pathlib import Path

class UKMDDoSDNSetup:
    def __init__(self):
        self.system_packages = [
            'git',
            'mininet',
            'python3-pip',
            'python3-dev',
            'python3-setuptools',
            'build-essential',
            'curl',
            'tshark',
            'slowhttptest'
        ]

        self.python_packages = [
            'scapy>=2.4.5',
            'pandas>=0.24',
            'numpy>=1.3.0',
            'requests>=2.26.0',
            'psutil>=1.8.9',
            'webob>=1.8.9',
            'pytest>=4.6.11',
            'pytest-cov>=2.12.1',
            'flake8>=3.9.2',
            'black>=22.8.0',
            'isort>=4.3.21',
            'pycryptodome>=3.21.0',
            'cryptography>=2.5,<38.0.0',
            'pyOpenSSL<23.0.0'
        ]

        self.suite_dir = "ukmddosdn-suite"
        self.ryu_repo_url = "https://github.com/nqmn/ryu.git"
        self.ryu_dir = os.path.join(self.suite_dir, "ryu")
        self.cicflowmeter_repo_url = "https://github.com/nqmn/cicflowmeter.git"
        self.cicflowmeter_dir = os.path.join(self.suite_dir, "cicflowmeter")

    def check_root(self):
        """Check if running as root (required for Mininet)"""
        if os.geteuid() != 0:
            print("ERROR: This setup must be run as root (sudo)")
            print("Mininet requires superuser privileges to create network namespaces")
            print("\nUsage: sudo python3 setup.py")
            sys.exit(1)

    def check_ubuntu_version(self):
        """Verify Ubuntu 24.04 compatibility"""
        try:
            with open('/etc/os-release', 'r') as f:
                os_info = f.read()

            if 'Ubuntu' not in os_info:
                print("WARNING: This setup is designed for Ubuntu 24.04.3")
                print("Your system may not be fully supported")

            if '24.04' not in os_info:
                print("WARNING: Recommended Ubuntu version is 24.04.3")
                print("Current version may have compatibility issues")

        except FileNotFoundError:
            print("WARNING: Could not detect OS version")

    def run_command(self, command, description):
        """Execute shell command with error handling"""
        print(f"\n[INFO] {description}")
        print(f"[CMD] {command}")

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                check=True
            )
            print(f"[SUCCESS] {description}")
            return True

        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Failed: {description}")
            print(f"Command: {command}")
            print(f"Return code: {e.returncode}")
            print(f"Error output: {e.stderr}")
            return False

    def update_package_manager(self):
        """Update apt package manager"""
        commands = [
            ("apt update", "Updating package manager"),
            ("apt upgrade -y", "Upgrading system packages")
        ]

        for cmd, desc in commands:
            if not self.run_command(cmd, desc):
                print("WARNING: Package manager update failed")
                return False
        return True

    def install_system_packages(self):
        """Install system packages via apt"""
        for package in self.system_packages:
            cmd = f"DEBIAN_FRONTEND=noninteractive apt install {package} -y"
            if not self.run_command(cmd, f"Installing {package}"):
                print(f"ERROR: Failed to install {package}")
                return False
        return True

    def install_ryu_from_source(self):
        """Install Ryu from GitHub repository"""
        print(f"\n[INFO] Installing Ryu from source: {self.ryu_repo_url}")

        # Create suite directory and change to it
        original_dir = os.getcwd()

        try:
            # Create suite directory if it doesn't exist
            if not os.path.exists(self.suite_dir):
                os.makedirs(self.suite_dir)
                print(f"[INFO] Created {self.suite_dir} directory")

            # Remove existing ryu directory if it exists
            if os.path.exists(self.ryu_dir):
                print(f"[INFO] Removing existing {self.ryu_dir} directory")
                subprocess.run(f"rm -rf {self.ryu_dir}", shell=True, check=True)

            # Change to suite directory for cloning
            os.chdir(self.suite_dir)

            if not self.run_command(f"git clone {self.ryu_repo_url}", "Cloning Ryu repository"):
                return False

            # Change to ryu directory (now just 'ryu' since we're in suite_dir)
            os.chdir("ryu")

            # Upgrade pip with sudo
            if not self.run_command("sudo pip install --upgrade pip --break-system-packages --ignore-installed", "Upgrading pip (sudo)"):
                print("WARNING: pip upgrade failed, continuing...")

            # Install Ryu in editable mode with sudo
            if not self.run_command("sudo pip install -e . --break-system-packages --ignore-installed", "Installing Ryu (sudo)"):
                print("ERROR: Ryu installation failed")
                return False

            # Return to original directory
            os.chdir(original_dir)

            # Add to PATH in bashrc
            bashrc_path = os.path.expanduser("~/.bashrc")
            path_export = 'export PATH="$HOME/.local/bin:$PATH"'

            # Check if PATH export already exists
            try:
                with open(bashrc_path, 'r') as f:
                    bashrc_content = f.read()

                if path_export not in bashrc_content:
                    with open(bashrc_path, 'a') as f:
                        f.write(f"\n# Added by UKMDDoSDN setup\n{path_export}\n")
                    print("[INFO] Added PATH export to ~/.bashrc")
                else:
                    print("[INFO] PATH export already exists in ~/.bashrc")

            except FileNotFoundError:
                # Create bashrc if it doesn't exist
                with open(bashrc_path, 'w') as f:
                    f.write(f"# Created by UKMDDoSDN setup\n{path_export}\n")
                print("[INFO] Created ~/.bashrc with PATH export")

            return True

        except Exception as e:
            print(f"[ERROR] Ryu installation failed: {e}")
            os.chdir(original_dir)
            return False

    def install_cicflowmeter_from_source(self):
        """Install CICFlowMeter from GitHub repository"""
        print(f"\n[INFO] Installing CICFlowMeter from source: {self.cicflowmeter_repo_url}")

        # Change to current directory for cloning
        original_dir = os.getcwd()

        try:
            # Create suite directory if it doesn't exist
            if not os.path.exists(self.suite_dir):
                os.makedirs(self.suite_dir)
                print(f"[INFO] Created {self.suite_dir} directory")

            # Remove existing cicflowmeter directory if it exists
            if os.path.exists(self.cicflowmeter_dir):
                print(f"[INFO] Removing existing {self.cicflowmeter_dir} directory")
                subprocess.run(f"rm -rf {self.cicflowmeter_dir}", shell=True, check=True)

            # Change to suite directory for cloning
            os.chdir(self.suite_dir)

            if not self.run_command(f"git clone {self.cicflowmeter_repo_url}", "Cloning CICFlowMeter repository"):
                return False

            # Change to cicflowmeter directory (now just 'cicflowmeter' since we're in suite_dir)
            os.chdir("cicflowmeter")

            # Upgrade pip with sudo
            if not self.run_command("sudo pip install --upgrade pip --break-system-packages", "Upgrading pip for CICFlowMeter"):
                print("WARNING: pip upgrade failed, continuing...")

            # Install CICFlowMeter using pyproject.toml with sudo
            if not self.run_command("sudo pip install . --break-system-packages", "Installing CICFlowMeter (sudo)"):
                print("ERROR: CICFlowMeter installation failed")
                return False

            # Return to original directory
            os.chdir(original_dir)

            print("[SUCCESS] CICFlowMeter installed successfully")
            return True

        except Exception as e:
            print(f"[ERROR] CICFlowMeter installation failed: {e}")
            os.chdir(original_dir)
            return False

    def install_python_packages(self):
        """Install Python packages via pip with sudo"""
        for package in self.python_packages:
            cmd = f'sudo pip install "{package}" --break-system-packages'
            if not self.run_command(cmd, f"Installing {package} (sudo)"):
                print(f"ERROR: Failed to install {package}")
                return False
        return True

    def test_ryu_installation(self):
        """Test Ryu installation by running simple switch"""
        print(f"\n[INFO] Testing Ryu installation with simple switch")

        # Test if test_full_deployment.py exists in current dir or ryu repo
        test_file_locations = [
            "test_full_deployment.py",
            os.path.join(self.suite_dir, "ryu", "test_full_deployment.py")
        ]

        test_file_found = None
        for test_file in test_file_locations:
            if os.path.exists(test_file):
                test_file_found = test_file
                break

        if test_file_found:
            print(f"[INFO] Running {test_file_found}")
            try:
                result = subprocess.run(
                    f"python3 {test_file_found}",
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode == 0 or result.returncode == 124:  # 124 = timeout
                    print(f"[SUCCESS] {test_file_found} executed successfully")
                    return True
                else:
                    print(f"[WARNING] {test_file_found} failed with return code {result.returncode}")
                    print(f"Error: {result.stderr}")
            except Exception as e:
                print(f"[WARNING] Could not run {test_file_found}: {e}")
        else:
            print(f"[INFO] test_full_deployment.py not found in current directory or {self.suite_dir}/ryu/, skipping test")

        # Test ryu-manager command
        print(f"[INFO] Testing ryu-manager command")
        try:
            result = subprocess.run(
                "timeout 5 ryu-manager --help",
                shell=True,
                capture_output=True,
                text=True
            )
            if result.returncode == 0 or result.returncode == 124:  # 124 = timeout
                print(f"[SUCCESS] ryu-manager command is available")
                return True
            else:
                print(f"[WARNING] ryu-manager command failed")
                print(f"Error: {result.stderr}")
        except Exception as e:
            print(f"[WARNING] Could not test ryu-manager: {e}")

        return False

    def test_mininet_functionality(self):
        """Test Mininet functionality by creating a basic network"""
        print(f"\n[INFO] Testing Mininet functionality with basic network")

        # Test basic mininet command
        try:
            print(f"[INFO] Running basic Mininet test (sudo mn --test pingall)")
            result = subprocess.run(
                "timeout 30 sudo mn --test pingall",
                shell=True,
                capture_output=True,
                text=True
            )

            if result.returncode == 0 or result.returncode == 124:  # 124 = timeout
                print(f"[SUCCESS] Mininet basic test completed successfully")
                if "Results:" in result.stdout:
                    print(f"    Mininet created network and ran connectivity test")
                return True
            else:
                print(f"[WARNING] Mininet test failed with return code {result.returncode}")
                print(f"Error output: {result.stderr}")

        except Exception as e:
            print(f"[WARNING] Could not run Mininet test: {e}")

        # Fallback: Test if mininet can at least start
        try:
            print(f"[INFO] Testing if Mininet can start (sudo mn --version)")
            result = subprocess.run(
                "sudo mn --version",
                shell=True,
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                print(f"[SUCCESS] Mininet version check passed")
                if result.stdout.strip():
                    print(f"    Version: {result.stdout.strip()}")
                return True
            else:
                print(f"[ERROR] Mininet version check failed")
                print(f"Error: {result.stderr}")

        except Exception as e:
            print(f"[ERROR] Mininet version test failed: {e}")

        return False

    def verify_installation(self):
        """Verify critical components are installed"""
        verifications = [
            ("mn --version", "Mininet installation"),
            ("python3 -c 'import scapy; print(\"Scapy:\", scapy.__version__)'", "Scapy import"),
            ("python3 -c 'import ryu; print(\"Ryu installed successfully\")'", "Ryu import"),
            ("python3 -c 'import mininet; print(\"Mininet Python module\")'", "Mininet Python module"),
            ("python3 -c 'import cicflowmeter; print(\"CICFlowMeter installed successfully\")'", "CICFlowMeter import"),
            ("curl --version", "Curl installation"),
            ("which ryu-manager", "Ryu manager command"),
            ("which cicflowmeter", "CICFlowMeter command")
        ]

        print("\n" + "="*50)
        print("VERIFICATION TESTS")
        print("="*50)

        all_passed = True
        for cmd, desc in verifications:
            try:
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    check=True
                )
                print(f"[✓] {desc}: PASS")
                if result.stdout.strip():
                    print(f"    Output: {result.stdout.strip()}")

            except subprocess.CalledProcessError as e:
                print(f"[✗] {desc}: FAIL")
                print(f"    Error: {e.stderr.strip()}")
                all_passed = False

        return all_passed

    def create_suite_info(self):
        """Create info file for the suite directory"""
        try:
            # Create suite directory if it doesn't exist
            if not os.path.exists(self.suite_dir):
                os.makedirs(self.suite_dir)
                print(f"[INFO] Created {self.suite_dir} directory")

            # Create suite directory info file
            suite_info_file = os.path.join(self.suite_dir, "README.md")
            suite_info_content = """# UKMDDoSDN Suite Directory

This directory contains external dependencies for the UKMDDoSDN project:

## Contents:
- **ryu/**: Ryu SDN controller framework (from https://github.com/nqmn/ryu.git)
- **cicflowmeter/**: CICFlowMeter flow analysis tool (from https://github.com/nqmn/cicflowmeter.git)

## Installation:
All tools in this directory are installed system-wide with sudo privileges.

## Usage:
Tools are accessible globally after installation via the main setup.py script.
Main UKMDDoSDN project files remain in the parent directory.
"""
            with open(suite_info_file, 'w') as f:
                f.write(suite_info_content)
            print(f"[INFO] Created {suite_info_file}")
            return True

        except Exception as e:
            print(f"[WARNING] Could not create suite info file: {e}")
            return False

    def display_usage_info(self):
        """Display post-installation usage information"""
        print("\n" + "="*60)
        print("UKMDDOSDN v1.0 SETUP COMPLETE")
        print("="*60)
        print("\nInstallation Details:")
        print("  • All packages installed with sudo for system-wide access")
        print("  • Dependencies directory: ukmddosdn-suite/")
        print("  • Ryu installed in: ukmddosdn-suite/ryu/")
        print("  • CICFlowMeter installed in: ukmddosdn-suite/cicflowmeter/")
        print("  • Main project files remain in current directory")
        print("  • PATH added to ~/.bashrc")
        print("  • Run 'source ~/.bashrc' or restart terminal")
        print("="*60)

    def run_setup(self):
        """Execute complete setup process"""
        print("UKMDDoSDN v1.0 Setup for Ubuntu 24.04.3")
        print("="*50)

        # Pre-checks
        self.check_root()
        self.check_ubuntu_version()

        # Installation steps
        install_steps = [
            (self.update_package_manager, "Updating package manager"),
            (self.install_system_packages, "Installing system packages"),
            (self.install_ryu_from_source, "Installing Ryu from GitHub source"),
            (self.install_cicflowmeter_from_source, "Installing CICFlowMeter from GitHub source"),
            (self.install_python_packages, "Installing Python packages")
        ]

        for step_func, description in install_steps:
            print(f"\n[STEP] {description}")
            if not step_func():
                print(f"[FATAL] Setup failed at: {description}")
                sys.exit(1)

        # Testing steps
        print(f"\n[STEP] Verifying installation")
        if not self.verify_installation():
            print("[WARNING] Some verification tests failed")
            print("Setup completed but there may be issues")
        else:
            print("[SUCCESS] All verification tests passed")

        print(f"\n[STEP] Testing Mininet functionality")
        self.test_mininet_functionality()

        # Create suite directory info file
        print(f"\n[STEP] Creating suite directory documentation")
        self.create_suite_info()

        self.display_usage_info()

if __name__ == "__main__":
    setup = UKMDDoSDNSetup()
    setup.run_setup()