#!/usr/bin/env python3

import subprocess
import sys
import shutil

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
    print("Checking Podman installation...")
    if not shutil.which('podman'):
        print("ERROR: Podman is not installed. Cannot proceed with removal.")
        sys.exit(1)
    print("Podman found.")

def check_resource_exists(resource_type, resource_name):
    """Check if a Podman resource exists"""
    # Check if Podman is still installed
    if not shutil.which('podman'):
        return False

    if resource_type == "container":
        return run_command(f'podman container exists {resource_name}', check=False)
    elif resource_type == "network":
        # Check if network exists by listing networks
        networks = run_command('podman network ls --format "{{.Name}}"', capture_output=True)
        if isinstance(networks, str):
            return resource_name in networks.split('\n')
        return False
    elif resource_type == "image":
        return run_command(f'podman image exists {resource_name}', check=False)
    return False

def stop_container(container_name):
    """Stop a running container"""
    if not check_resource_exists("container", container_name):
        print(f"   Container '{container_name}' does not exist - skipping stop")
        return True

    # Check if container is running
    is_running = run_command(f'podman ps -q -f name={container_name}', capture_output=True)
    if not is_running:
        print(f"   Container '{container_name}' is not running - skipping stop")
        return True

    print(f"   Stopping container '{container_name}'...")
    result = run_command(f'podman stop {container_name}', check=False)
    if result:
        print(f"   Successfully stopped '{container_name}'")
    else:
        print(f"   Warning: Failed to stop '{container_name}' (may already be stopped)")
    return result

def remove_container(container_name):
    """Remove a container"""
    if not check_resource_exists("container", container_name):
        print(f"   Container '{container_name}' does not exist - skipping removal")
        return True

    print(f"   Removing container '{container_name}'...")
    result = run_command(f'podman rm -f {container_name}', check=False)
    if result:
        print(f"   Successfully removed '{container_name}'")
    else:
        print(f"   Warning: Failed to remove '{container_name}'")
    return result

def remove_network(network_name):
    """Remove a custom network"""
    if not check_resource_exists("network", network_name):
        print(f"   Network '{network_name}' does not exist - skipping removal")
        return True

    print(f"   Removing network '{network_name}'...")
    result = run_command(f'podman network rm {network_name}', check=False)
    if result:
        print(f"   Successfully removed network '{network_name}'")
    else:
        print(f"   Warning: Failed to remove network '{network_name}'")
        print(f"   (Network may still have containers attached)")
    return result

def remove_image(image_name):
    """Remove an image"""
    if not check_resource_exists("image", image_name):
        print(f"   Image '{image_name}' does not exist - skipping removal")
        return True

    print(f"   Removing image '{image_name}'...")
    result = run_command(f'podman rmi {image_name}', check=False)
    if result:
        print(f"   Successfully removed image '{image_name}'")
    else:
        print(f"   Warning: Failed to remove image '{image_name}'")
        print(f"   (Image may be in use by other containers)")
    return result

def get_user_confirmation(prompt):
    """Get yes/no confirmation from user"""
    while True:
        response = input(f"{prompt} (y/n): ").lower().strip()
        if response in ['y', 'yes']:
            return True
        elif response in ['n', 'no']:
            return False
        else:
            print("Please enter 'y' or 'n'")

def show_resources_status():
    """Show current status of UKMSDN resources"""
    print("")
    print("Current UKMSDN Resources:")
    print("=========================")

    # Check containers
    print("")
    print("Containers:")
    for container in ['ukm_mininet', 'ukm_ryu']:
        exists = check_resource_exists("container", container)
        if exists:
            status = run_command(f'podman ps -a -f name={container} --format "{{{{.Status}}}}"', capture_output=True)
            print(f"   - {container}: EXISTS ({status})")
        else:
            print(f"   - {container}: NOT FOUND")

    # Check network
    print("")
    print("Networks:")
    network = 'ukmsdn-network'
    exists = check_resource_exists("network", network)
    if exists:
        print(f"   - {network}: EXISTS")
    else:
        print(f"   - {network}: NOT FOUND")

    # Check image
    print("")
    print("Images:")
    image = 'ukm-ubuntu:24.04-updated'
    exists = check_resource_exists("image", image)
    if exists:
        size = run_command(f'podman images {image} --format "{{{{.Size}}}}"', capture_output=True)
        print(f"   - {image}: EXISTS ({size})")
    else:
        print(f"   - {image}: NOT FOUND")
    print("")

def remove_containers():
    """Remove both UKMSDN containers"""
    print("")
    print("Removing UKMSDN Containers")
    print("==========================")

    containers = ['ukm_mininet', 'ukm_ryu']

    # First stop all containers
    print("")
    print("Step 1: Stopping containers...")
    for container in containers:
        stop_container(container)

    # Then remove all containers
    print("")
    print("Step 2: Removing containers...")
    for container in containers:
        remove_container(container)

def remove_ukmsdn_network():
    """Remove UKMSDN network"""
    print("")
    print("Removing UKMSDN Network")
    print("=======================")
    remove_network('ukmsdn-network')

def remove_base_image_with_confirmation():
    """Remove base image with user confirmation"""
    print("")
    print("Removing Base Image")
    print("===================")

    image_name = 'ukm-ubuntu:24.04-updated'

    if not check_resource_exists("image", image_name):
        print(f"   Base image '{image_name}' does not exist - nothing to remove")
        return

    print("")
    print("WARNING: The base image contains all pre-installed packages and dependencies.")
    print("         Removing it will require rebuilding the image (~10-15 minutes) if you")
    print("         run setup_container.py again.")
    print("")

    if get_user_confirmation(f"Do you want to remove the base image '{image_name}'?"):
        remove_image(image_name)
    else:
        print(f"   Skipping removal of base image '{image_name}'")
        print(f"   (You can manually remove it later with: podman rmi {image_name})")

def remove_podman():
    """Remove Podman package with user confirmation"""
    print("")
    print("Removing Podman")
    print("===============")

    print("")
    print("WARNING: This will uninstall Podman from your system.")
    print("         If you use Podman for other projects, DO NOT proceed.")
    print("")
    print("This will remove:")
    print("   - podman package and all subpackages")
    print("   - Container images, networks, and volumes created by Podman")
    print("   - Configuration files (/etc/containers/)")
    print("")

    if not get_user_confirmation("Do you want to uninstall Podman?"):
        print("   Skipping Podman uninstall")
        print("   (You can manually uninstall with: sudo apt remove -y podman)")
        return

    print("   Removing Podman package...")
    result = run_command('sudo apt remove -y podman', check=False)
    if result:
        print("   ✅ Podman package removed")
    else:
        print("   ⚠️  Failed to remove Podman package")
        print("   Try manually: sudo apt remove -y podman")

    # Optional: Clean up Podman configuration
    if get_user_confirmation("Also remove Podman configuration files and storage?"):
        print("   Removing Podman configuration and storage...")

        # Remove system configs
        result1 = run_command('sudo rm -rf /etc/containers', check=False)
        if result1:
            print("   ✅ System configuration (/etc/containers/) removed")
        else:
            print("   ⚠️  Could not remove /etc/containers/ (try: sudo rm -rf /etc/containers)")

        # Remove user storage
        result2 = run_command('rm -rf ~/.local/share/containers', check=False)
        if result2:
            print("   ✅ User storage (~/.local/share/containers/) removed")
        else:
            print("   ⚠️  Could not remove ~/.local/share/containers/")

        if result1 and result2:
            print("   ✅ Podman configuration cleaned up")

def show_final_status():
    """Show final status after removal"""
    print("")
    print("Cleanup Complete!")
    print("=================")

    podman_installed = shutil.which('podman')

    if podman_installed:
        # Check if any resources remain
        containers_exist = any(check_resource_exists("container", c) for c in ['ukm_mininet', 'ukm_ryu'])
        network_exists = check_resource_exists("network", 'ukmsdn-network')
        image_exists = check_resource_exists("image", 'ukm-ubuntu:24.04-updated')

        print("")
        print("Remaining UKMSDN Resources:")
        if not containers_exist and not network_exists and not image_exists:
            print("   None - All UKMSDN resources have been removed")
        else:
            if containers_exist:
                print("   - Containers: Some containers may still exist")
            if network_exists:
                print("   - Network: ukmsdn-network still exists")
            if image_exists:
                print("   - Image: ukm-ubuntu:24.04-updated still exists (preserved by user choice)")

        print("")
        print("Verification:")
        print("   Run 'podman ps -a' to check for remaining containers")
        print("   Run 'podman network ls' to check for remaining networks")
        print("   Run 'podman images' to check for remaining images")
    else:
        print("")
        print("Status:")
        print("   ✅ Podman has been successfully uninstalled")
        print("   ✅ All UKMSDN resources have been removed")
        print("")
        print("Verification:")
        print("   Run 'which podman' to confirm Podman removal")

    print("")

def main():
    """Main function"""
    print("UKMSDN Complete Removal")
    print("=======================")
    print("")
    print("This script will remove all resources created by setup_container.py:")
    print("   - Containers: ukm_mininet, ukm_ryu")
    print("   - Network: ukmsdn-network")
    print("   - Image: ukm-ubuntu:24.04-updated (optional)")
    print("   - Podman package (optional, only if not used for other projects)")
    print("")

    # Step 1: Check Podman
    check_podman()

    # Step 2: Show current resources
    show_resources_status()

    # Step 3: Get confirmation to proceed
    print("")
    if not get_user_confirmation("Do you want to proceed with removing UKMSDN resources?"):
        print("")
        print("Removal cancelled by user")
        sys.exit(0)

    # Step 4: Remove containers
    remove_containers()

    # Step 5: Remove network
    remove_ukmsdn_network()

    # Step 6: Optionally remove base image
    remove_base_image_with_confirmation()

    # Step 7: Optionally remove Podman
    remove_podman()

    # Step 8: Show final status
    show_final_status()

if __name__ == "__main__":
    main()
