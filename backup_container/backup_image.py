#!/usr/bin/env python3
import subprocess
from datetime import datetime
from pathlib import Path

BACKUP_DIR = Path("podman_backups")
CONTAINERS = ["ukm_mininet", "ukm_ryu"]
IMAGE = "localhost/ukm-ubuntu:24.04-updated"
NETWORKS = ["ukmsdn-network"]

def run_command(cmd):
    print(f"[INFO] Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

def backup_image():
    """Backup updated image only."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    image_file = BACKUP_DIR / f"ukm-ubuntu_{timestamp}.tar"
    print(f"[INFO] Saving image to {image_file}")
    run_command(["podman", "save", "-o", str(image_file), IMAGE])

def backup_containers():
    """Backup container metadata only."""
    for cname in CONTAINERS:
        meta_file = BACKUP_DIR / f"{cname}_metadata.json"
        print(f"[INFO] Saving metadata for {cname}")
        run_command(["podman", "inspect", cname, "-f", "json"])
        with open(meta_file, "w") as f:
            subprocess.run(["podman", "inspect", cname], stdout=f, check=True)

def backup_networks():
    """Backup networks."""
    for net in NETWORKS:
        net_file = BACKUP_DIR / f"{net}_network.json"
        print(f"[INFO] Saving network {net}")
        with open(net_file, "w") as f:
            subprocess.run(["podman", "network", "inspect", net], stdout=f, check=True)

def main():
    BACKUP_DIR.mkdir(exist_ok=True)
    backup_image()
    backup_containers()
    backup_networks()
    print("[SUCCESS] Backup completed successfully!")

if __name__ == "__main__":
    main()

