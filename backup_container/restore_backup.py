#!/usr/bin/env python3
import subprocess
import json
from pathlib import Path
from datetime import datetime

# === CONFIGURATION ===
BACKUP_DIR = Path("podman_backups")
IMAGE_PREFIX = "ukm-ubuntu"      # Base name for saved image
IMAGE_TAG = "24.04-updated"      # Your updated image tag
CONTAINERS = ["ukm_mininet", "ukm_ryu"]
NETWORKS = ["ukmsdn-network"]

# === HELPER FUNCTIONS ===
def run_command(cmd, capture_output=False):
    """Run shell command safely."""
    print(f"[INFO] Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, check=True, text=True,
                                capture_output=capture_output)
        return result.stdout if capture_output else None
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Command failed: {' '.join(cmd)}")
        print(e.stderr)
        raise

def find_latest_backup(prefix):
    """Find the latest backup tar file for given image prefix."""
    backups = sorted(BACKUP_DIR.glob(f"{prefix}_*.tar"))
    return backups[-1] if backups else None

# === RESTORE FUNCTIONS ===
def restore_image():
    """Restore the latest saved image from TAR."""
    print("\n[STEP] Restoring image...")
    image_file = find_latest_backup(IMAGE_PREFIX)
    if not image_file:
        print(f"[ERROR] No image backup found in {BACKUP_DIR}")
        return False

    print(f"[INFO] Loading image from {image_file}")
    run_command(["podman", "load", "-i", str(image_file)])
    return True

def restore_networks():
    """Restore Podman networks from JSON backup safely."""
    print("\n[STEP] Restoring networks...")

    # Get existing networks
    try:
        result = run_command(["podman", "network", "ls", "--format", "json"], capture_output=True)
        existing_nets = json.loads(result) if result else []
    except subprocess.CalledProcessError:
        existing_nets = []

    # Extract existing network names
    existing_net_names = {net.get("Name") or net.get("name") for net in existing_nets if isinstance(net, dict)}

    for net_name in NETWORKS:
        net_file = BACKUP_DIR / f"{net_name}_network.json"
        if not net_file.exists():
            print(f"[WARNING] Network backup file '{net_file}' not found. Skipping.")
            continue

        print(f"[INFO] Restoring network '{net_name}' from {net_file}")

        # Load network config
        with open(net_file, "r") as f:
            try:
                network_config = json.load(f)
            except json.JSONDecodeError:
                print(f"[ERROR] Failed to read network backup file {net_file}")
                continue

        # network_config is a list, take the first dict
        if isinstance(network_config, list) and len(network_config) > 0:
            network_config = network_config[0]

        # Extract subnet and gateway from 'subnets' field
        subnet = None
        gateway = None
        subnets = network_config.get("subnets", [])
        if subnets and isinstance(subnets, list) and len(subnets) > 0:
            subnet = subnets[0].get("subnet")
            gateway = subnets[0].get("gateway")

        # Remove existing network if exists
        if net_name in existing_net_names:
            print(f"[INFO] Removing existing network '{net_name}'")
            run_command(["podman", "network", "rm", net_name])

        # Build create command
        cmd = ["podman", "network", "create", net_name]
        if subnet:
            cmd += ["--subnet", subnet]
        if gateway:
            cmd += ["--gateway", gateway]

        run_command(cmd)
        print(f"[SUCCESS] Network '{net_name}' restored.")

def restore_containers():
    """Recreate containers from metadata."""
    print("\n[STEP] Restoring containers...")
    for cname in CONTAINERS:
        meta_file = BACKUP_DIR / f"{cname}_metadata.json"
        if not meta_file.exists():
            print(f"[WARNING] Metadata for {cname} not found, skipping.")
            continue

        # Stop and remove container if it exists
        existing = run_command(["podman", "ps", "-a", "--format", "json"], capture_output=True)
        existing = json.loads(existing)

        if any(c["Names"][0] == cname for c in existing):
            print(f"[INFO] Removing existing container '{cname}'")
            run_command(["podman", "rm", "-f", cname])

        # Load metadata
        with open(meta_file, "r") as f:
            metadata = json.load(f)

        # Extract key info
        image = metadata[0]["ImageName"]
        cmd = metadata[0]["Config"]["Cmd"] or ["/opt/ukmsdn/scripts/start_ovs.sh"]

        # Recreate container
        print(f"[INFO] Recreating container '{cname}' with image '{image}'")
        run_command(["podman", "run", "-d", "--name", cname, "--network", NETWORKS[0], image] + cmd)

        print(f"[SUCCESS] Container '{cname}' restored and running.")

# === MAIN ===
def main():
    print("=== Podman Restore Script ===")
    BACKUP_DIR.mkdir(exist_ok=True)

    if not restore_image():
        print("[ERROR] Failed to restore image. Aborting.")
        return

    restore_networks()
    restore_containers()

    print("\n[SUCCESS] Restore completed successfully!")
    print("[INFO] Verify with: podman ps")

if __name__ == "__main__":
    main()

