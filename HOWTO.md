# Simple How-To: Install and Configure exportcliv2 Suite

This guide provides the essential steps to get the `exportcliv2` suite running.
**All commands must be run as `root` unless specified otherwise.**

## 1. System Preparation

### 1.1. Update System

Ensure your Oracle Linux 9 (or compatible) system is up-to-date:

```shell
dnf update -y
```

### 1.2. Prepare Dedicated `ext4` Filesystem (Crucial)

The application **requires** a dedicated **`ext4`** filesystem, typically mounted at `/opt/bitmover`.

1. **Identify target disk** (e.g., `/dev/xvdb` if it's a new, unformatted 1TB disk):
   ```shell
   lsblk
   ```
   *(Example output showing `xvdb` as a candidate):*
   ```
   NAME    MAJ:MIN RM SIZE RO TYPE MOUNTPOINTS
   xvda    202:0    0  15G  0 disk
   ├─xvda1 202:1    0   1G  0 part /boot
   └─xvda2 202:2    0  14G  0 part /
   xvdb    202:16   0   1T  0 disk
   ```

2. **Format as `ext4`** (Replace `/dev/xvdb` with your actual disk):
   ```shell
   mkfs.ext4 /dev/xvdb
   ```

3. **Create Mount Point:**
   ```shell
   mkdir -p /opt/bitmover
   ```

4. **Get UUID for `fstab`** (Replace `/dev/xvdb`):
   ```shell
   blkid /dev/xvdb
   ```
   *(Note the `UUID="<YOUR_UUID_HERE>"` from the output, e.g., `b48cc093-059c-4c11-9f5d-26b465182c28`)*

5. **Update `/etc/fstab`** to make the mount permanent. Add a line similar to this, using **your UUID**:
   ```shell
   # Example line to add to /etc/fstab:
   # UUID=<YOUR_UUID_HERE> /opt/bitmover           ext4    defaults        0 0
   
   # Using the example UUID:
   # UUID=b48cc093-059c-4c11-9f5d-26b465182c28 /opt/bitmover           ext4    defaults        0 0
   ```
   Use `vi /etc/fstab` or your preferred editor.

6. **Reload `systemd` and Mount:**
   ```shell
   systemctl daemon-reload
   mount -a
   ```

7. **Verify Mount:**
   ```shell
   df -hT /opt/bitmover
   ```
   *(Ensure it shows `/dev/xvdb` (or your disk) mounted at `/opt/bitmover` with `Type ext4`)*

## 2. Application Installation

### 2.1. Prepare Bundle

1. Copy the release tarball (e.g., `exportcliv2-suite-v1.0.5.tar.gz`) to the server, for example, into `/root/`.
2. Navigate to where you placed the package: `cd /root/`
3. Extract the archive (adjust filename if version differs):
   ```shell
   tar -xzf exportcliv2-suite-v1.0.5.tar.gz
   ```
4. Navigate into the extracted directory:
   ```shell
   cd exportcliv2-suite-v1.0.5/
   ```
   **All subsequent `./deploy_orchestrator.sh` commands must be run from this directory.**

### 2.2. Configure Installer (Before First Install)

Edit `exportcliv2-deploy/install-app.conf` within the extracted bundle to set essential parameters.

```shell
vi exportcliv2-deploy/install-app.conf
```

**Key lines to check/change:**

* `DEFAULT_INSTANCES_CONFIG="AZ61"` (Set your desired default instance name(s), space-separated)
* `REMOTE_HOST_URL_CONFIG="http://192.168.0.180:8989/pcap"` (Set the NiFi endpoint URL)
* `BASE_DIR_CONFIG="/opt/bitmover"` (Ensure this matches your `ext4` mount point from Step 1.2)

### 2.3. Run Installation

From within the extracted bundle directory (e.g., `/root/exportcliv2-suite-v1.0.5/`):

```shell
./deploy_orchestrator.sh --install
```

When prompted `Proceed with install for instances: (AZ61)... [y/N]`, type `y` and press Enter.

## 3. Post-Installation Configuration

### 3.1. Configure `exportcliv2` Instance

For each instance (e.g., "AZ61"), you **must** edit its live configuration file.

1. Edit the instance config (replace `AZ61` if your instance name is different):
   ```shell
   vi /etc/exportcliv2/AZ61.conf
   ```
2. Set `EXPORT_IP` and `EXPORT_PORTID` for your data source:
   ```ini
   # /etc/exportcliv2/AZ61.conf
   # ... (other settings) ...
   EXPORT_IP="<YOUR_DATA_SOURCE_IP>" # e.g., "10.0.0.1"
   EXPORT_PORTID="<YOUR_PORT_ID>"    # e.g., "1"
   # ... (other settings) ...
   ```
   Save the file.

### 3.2. Restart Instance

Apply the configuration changes by restarting the instance (replace `AZ61` if needed):

```shell
exportcli-manage -i AZ61 --restart
```

*(The `exportcli-manage` tool should be in your PATH, typically `/usr/local/bin/exportcli-manage`)*

## 4. Verification and Operation

### 4.1. Check Service Status

* **Bitmover service (handles uploads & disk cleaning):**
  ```shell
  exportcli-manage --status
  ```
* **`exportcliv2` instance (e.g., AZ61):**
  ```shell
  exportcli-manage -i AZ61 --status
  ```
  Look for `Active: active (running)` for both.

### 4.2. Monitor Logs

* **Bitmover service logs (includes uploader & purger activity):**
  ```shell
  exportcli-manage --logs-follow
  # OR direct file: tail -f /var/log/exportcliv2/bitmover/app.log.jsonl
  ```
* **`exportcliv2` instance logs (e.g., AZ61):**
  ```shell
  exportcli-manage -i AZ61 --logs-follow
  # Systemd journal logs are primary; file logs might be in /var/log/exportcliv2/AZ61/
  ```

### 4.3. Key Data Directories (Defaults under `/opt/bitmover/`)

* `/opt/bitmover/csv/`: Metadata files (`<INSTANCE_NAME>.csv`).
* `/opt/bitmover/source/`: Incoming PCAP files.
* `/opt/bitmover/worker/`: PCAPs being processed/uploaded.
* `/opt/bitmover/uploaded/`: Successfully uploaded PCAPs (before purging).
* The Purger (part of Bitmover) will automatically manage disk space on `/opt/bitmover/` to keep it around 75% free by
  deleting older files from `worker/` and `uploaded/`.

---

This covers the basic installation and startup. Refer to `README.md` and `USER_GUIDE.md` in the bundle for more details
on patching, advanced configuration, and troubleshooting.

```