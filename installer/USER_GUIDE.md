## Application Suite Deployment and Management Guide (v1.0.7)

This guide provides comprehensive instructions for deploying, configuring, updating, and managing the "exportcliv2"
application suite (v1.0.0). This suite includes the main `exportcliv2` data export client and the Bitmover service (a
Python-based service responsible for PCAP uploads and disk space management).
Additionally, the suite includes an automatic health-monitoring system for `exportcliv2` instances to ensure high
availability by detecting and restarting unresponsive processes.

## Table of Contents:

1.  Introduction
2.  Deployment Package Structure
3.  Step 0: Prerequisites and System Preparation
4.  Step 1: Prepare the Installation Package (Unpack)
5.  Step 2: Review Bundle Installer Configuration (`install-app.conf`)
6.  Step 3: Run the Initial Installation (`deploy_orchestrator.sh --install`)
7.  Step 4: Post-Installation Instance Configuration (Live System)
8.  Step 5: Restart `exportcliv2` Instance After Configuration
9.  Step 6: Verify Service Operation
10. Step 7: Understanding Key System Directories and Files
11. Step 8: Checking Logs
12. Step 9: Preparing the Installation Bundle with a Patch (`install_patch.sh`)
13. Step 10: Deploying a Prepared/Patched Bundle (`deploy_orchestrator.sh --update`)
14. Step 11: Updating Authentication Credentials
15. Troubleshooting
16. Appendix A: Key Configuration and Template File Details
    *   A.1 `install-app.conf` (Bundle's Primary Input Configuration)
    *   A.2 `run_exportcliv2_instance.sh.template` (Instance Wrapper Script)
    *   A.3 `/etc/exportcliv2/common.auth.conf` (Shared Authentication)
    *   A.4 `app.conf.template` (Instance's Application Configuration Template)
    *   A.5 `/etc/exportcliv2/config.ini` (Bitmover Service Configuration)
    *   A.6 Systemd Unit Templates Overview
17. Further Information

---

**Required Privileges & User (Applies to all relevant steps):**
All installation, patching, and service management commands in this guide **must be executed as the `root` user.**

*   Log in directly as `root`, or from a non-root user with sudo privileges, switch to a root shell:
    ```bash
    sudo su -
    ```
*   Once you are `root`, you can run the script commands directly (e.g., `./deploy_orchestrator.sh --install`).

---

## 1. Introduction

*(Understand the components of the suite.)*

The `exportcliv2` application suite (v1.0.0) is designed for robust data processing and management. It consists of:

*   **`exportcliv2` client:** A high-performance data processing application (e.g., binary version
    `exportcliv2-v0.4.0-B1771-24.11.15`). This core binary is provided by an external supplier and has its own versioning
    scheme. The overall application suite, including supporting scripts and the Bitmover service, is versioned
    independently (e.g., `v1.0.0`). The `exportcliv2` client is typically run as multiple instances, each configured for a
    specific data source or task.
*   **Bitmover service:** A Python-based service (featuring the `datamover` component, e.g., `v1.0.0`) responsible for
    managing and uploading PCAP files generated or processed by the system, and for automatic disk space management (
    purging).

This guide details the use of a set of deployment and management scripts to install, configure, update, and operate this
suite on an Oracle Linux 9 system (or compatible).

---

## 2. Deployment Package Structure

*(Know what's in the bundle you receive.)*

The deployment process starts with the `exportcliv2-suite-v1.0.0.tar.gz` package. After extraction, it creates a
top-level directory: `exportcliv2-suite-v1.0.0/`.

> **Important:** All operations involving `deploy_orchestrator.sh` and `install_patch.sh` must be initiated from within
> this extracted bundle directory.

The structure of the extracted package is typically as follows:

```
exportcliv2-suite-v1.0.0/
├── deploy_orchestrator.sh       # Main script for installation or updates
├── install_patch.sh             # Script to prepare this bundle with patches
├── README.md                    # Quick start and overview
├── USER_GUIDE.md                # This comprehensive user guide
│
└── exportcliv2-deploy/          # Deployment subdirectory
    ├── install_base_exportcliv2.sh # Core installer for base system components
    ├── configure_instance.sh    # Script to set up individual exportcliv2 instances
    ├── manage_services.sh       # Core script for service management (used by exportcli-manage)
    │
    ├── install-app.conf         # Primary configuration for the installer scripts in this bundle
    │
    ├── exportcliv2-v0.4.0-B1771-24.11.15 # Example: The versioned exportcliv2 binary
    ├── datamover-1.0.0-py3-none-any.whl  # Example: The versioned Python wheel for Bitmover
    │   # (Other binaries like an emulator 'exportcliv8' might also be present if included during bundling)
    │
    ├── config_files/            # Directory for config file templates used during installation
    │   ├── app.conf.template    # Template for the instance's application-specific config
    │   ├── common.auth.conf     # Template/default for shared authentication tokens
    │   ├── config.ini.template  # Template for Bitmover's INI configuration (includes Purger settings)
    │   └── run_exportcliv2_instance.sh.template # Template for the instance wrapper script
    │
    ├── systemd_units/           # Directory for systemd unit file templates
    │   ├── bitmover.service.template
    │   ├── exportcliv2@.service.template
    │   ├── exportcliv2-restart@.path.template
    │   ├── exportcliv2-restart@.service.template
    │   ├── exportcliv2-healthcheck@.service.template
    │   └── exportcliv2-healthcheck@.timer.template
    │
    └── wheelhouse/              # Offline Python dependency wheels
        └── ...
```

---

## 3. Step 0: Prerequisites and System Preparation

*(Ensure system compatibility and required tools are ready.)*

1.  **System Compatibility:**
    *   This suite is designed for Oracle Linux 9 or compatible RHEL 9 derivatives (e.g., AlmaLinux 9, Rocky Linux 9).

2.  **System Updates & Repository Access:**
    *   Ensure your system is registered with appropriate subscriptions (if applicable, e.g., for RHEL) and can access
        package repositories.
    *   It's recommended to have an up-to-date system:
        ```bash
        dnf update -y
        ```

3.  **Installation Package:**
    *   Ensure you have the application suite package: `exportcliv2-suite-v1.0.0.tar.gz`.

4.  **Dedicated ext4 Filesystem for Application Data (Crucial Prerequisite):**
    For optimal performance, reliable disk space management by the Purger component, and easier capacity planning, it is
    **essential** to prepare a dedicated **ext4** filesystem for the application's base data directory. **Do not use ext3
    or other filesystem types for this purpose.**

    *   **Requirement:** This **ext4** filesystem **must be created and correctly mounted** at the path defined by
        `BASE_DIR_CONFIG` in the bundle's `exportcliv2-deploy/install-app.conf` file (default: `/opt/bitmover`) **before
        you proceed to run the application installation (Step 3: `deploy_orchestrator.sh --install`)**. If you intend to
        change `BASE_DIR_CONFIG` from its default, ensure your dedicated ext4 filesystem is prepared and mounted at that
        custom path *prior* to installation.
    *   **Filesystem Type:** **ext4 (strictly)**.
    *   **Preparation Steps (as `root` user):**
        1.  **Identify Disk:** Use `lsblk` or `sudo fdisk -l` to identify the unpartitioned disk or partition you intend
            to use (e.g., `/dev/sdb`).
        2.  **Format Disk as ext4:** Format the chosen disk/partition specifically as **ext4**.
            ```bash
            sudo mkfs.ext4 /dev/sdX  # Replace /dev/sdX with your actual disk/partition
            ```
        3.  **Create Mount Point:** Create the directory that will serve as the mount point (if it doesn't already
            exist). This must match `BASE_DIR_CONFIG`.
            ```bash
            sudo mkdir -p /opt/bitmover # Or your custom BASE_DIR_CONFIG path
            ```
        4.  **Mount Temporarily (Optional Test):**
            ```bash
            sudo mount /dev/sdX /opt/bitmover # Replace /dev/sdX and /opt/bitmover accordingly
            ```
        5.  **Make Mount Permanent (Update `/etc/fstab`):**
            *   Get the UUID of your formatted disk/partition:
                ```bash
                sudo blkid /dev/sdX # Note the UUID="<YOUR_UUID_HERE>"
                ```
            *   Edit `/etc/fstab` (e.g., `sudo vi /etc/fstab`) and add a line like the following, replacing
                `<YOUR_UUID_HERE>` and `/opt/bitmover` as needed:
                ```fstab
                UUID=<YOUR_UUID_HERE>  /opt/bitmover   ext4    defaults        0       2
                ```
            *   Save the file.
        6.  **Test `fstab` and Mount:** If you temporarily mounted in step 4, unmount it first (
            `sudo umount /opt/bitmover`). Then, mount all filesystems defined in `/etc/fstab`:
            ```bash
            sudo mount -a
            ```
            If no errors appear, the configuration is likely correct.
        7.  **Verify Mount:** Ensure the **ext4** filesystem is correctly mounted at the target path (e.g.,
            `/opt/bitmover`) and is indeed ext4:
            ```bash
            df -hT /opt/bitmover
            # In the output, ensure the 'Type' column shows 'ext4' and it's mounted on the correct device.
            ```

    > **Important:** Performing disk formatting and `fstab` modifications carries risks if done incorrectly. Ensure you
    are targeting the correct disk device. If unsure, consult your system administration team. The application
    installation process **will proceed assuming this ext4 filesystem is correctly prepared and mounted at
    the `BASE_DIR_CONFIG` location.** The application services (Bitmover, exportcliv2 instances) expect their data
    directories under this mount point to be writable by the service user (`exportcliv2_user` by default).

5.  **Python 3 Environment:**
    *   The Bitmover service requires Python 3 (typically Python 3.9.x on Oracle Linux 9) and its standard `venv` module.
    *   As `root`, verify Python 3 and `venv` module availability:
        ```bash
        python3 --version
        python3 -m venv --help
        ```
    *   If Python 3 is missing or `venv` is unavailable, install it as `root`:
        ```bash
        dnf install python3 -y
        ```

---

## 4. Step 1: Prepare the Installation Package (Unpack)

*(Unpack the suite to access installer scripts.)*

1.  Copy `exportcliv2-suite-v1.0.0.tar.gz` to your server (e.g., into `/root/`).
2.  Log in as `root` (if not already) and navigate to where you placed the package.
3.  Extract the archive:
    ```bash
    tar vxf exportcliv2-suite-v1.0.0.tar.gz
    ```
    This creates a directory: `exportcliv2-suite-v1.0.0/`.
4.  Navigate into the extracted directory:
    ```bash
    cd exportcliv2-suite-v1.0.0/
    ```

---

## 5. Step 2: Review Bundle Installer Configuration (`install-app.conf`)

*(Check the bundle's default settings before installation.)*

The main configuration file *for the installer scripts within this specific bundle* is located at
`exportcliv2-deploy/install-app.conf`. This file contains defaults used during the installation.

1.  **View the Bundle's Installer Configuration:**
    ```bash
    cat exportcliv2-deploy/install-app.conf
    ```
    *(For detailed content of `install-app.conf`, see Appendix A.1.)*

    > **Note on Default Settings:** The `BASE_DIR_CONFIG` and `REMOTE_HOST_URL_CONFIG` are key defaults. If you need to
    use different values for a specific installation *before the very first install*, you can edit this
    `exportcliv2-deploy/install-app.conf` file within the extracted bundle prior to running
    `deploy_orchestrator.sh --install`. **Ensure that the `BASE_DIR_CONFIG` matches the mount point of your prepared ext4
    filesystem (see Step 0.4).**

2.  **Edit (Optional, Before First Install):**
    If you need to change settings *before the very first installation*, edit the file:
    ```bash
    vi exportcliv2-deploy/install-app.conf
    ```

---

## 6. Step 3: Run the Initial Installation (`deploy_orchestrator.sh --install`)

*(Execute the main deployment script to install base components and default instances.)*

**Prerequisite Check:** Ensure you have completed all items in "Step 0: Prerequisites and System Preparation",
especially the creation and mounting of the dedicated ext4 filesystem at the path specified by `BASE_DIR_CONFIG`.

1.  From within the `exportcliv2-suite-v1.0.0/` directory, execute:
    ```bash
    ./deploy_orchestrator.sh --install
    ```
2.  The script will list the instances to be configured (from `DEFAULT_INSTANCES_CONFIG`) and ask for confirmation. Type
    `y` and press Enter.
3.  Upon successful completion, you will see a message like:
    ```
    # ... (detailed installation log output) ...
    YYYY-MM-DDTHH:MM:SSZ [INFO] ▶ Orchestrator finished successfully.
    ```
    This step also deploys the default `/etc/exportcliv2/config.ini` which includes initial settings for the Bitmover
    service's Purger component.

This process also installs and enables a periodic health check for each `exportcliv2` instance. The health check
automatically monitors the instance and triggers a restart if it becomes unresponsive (i.e., stops logging).

---

## 7. Step 4: Post-Installation Instance Configuration (Live System)

*(Configure the live system's settings for each `exportcliv2` instance, e.g., "AAA".)*

After the base installation, you **must** edit the system configuration file for each `exportcliv2` instance to define
its specific data source target. These files are located on the live system in `/etc/exportcliv2/`.

1.  **Edit the Instance Environment Configuration File:**
    For instance "AAA", edit:
    ```bash
    vi /etc/exportcliv2/AAA.conf
    ```
2.  **Update Instance-Specific Settings:**
    Locate and update `EXPORT_IP` and `EXPORT_PORTID` according to your environment. The file content will be similar to:
    ```ini
    # /etc/exportcliv2/AAA.conf (on the live system)
    # Generated by configure_instance.sh on YYYY-MM-DDTHH:MM:SSZ
    EXPORT_TIMEOUT="15"
    EXPORT_SOURCE="AAA"
    EXPORT_STARTTIME_OFFSET_SPEC="3 minutes ago"
    EXPORT_ENDTIME="-1" # Note: This line is written by the configuration script for informational
                        # purposes. However, the actual export end time is fixed to -1 (indefinite)
                        # by the run_exportcliv2_instance.sh wrapper script in this version and
                        # changing this value here will have no effect.
    # ---- EDIT THESE TWO LINES FOR YOUR ENVIRONMENT ----
    EXPORT_IP="<YOUR_DATA_SOURCE_IP>" # e.g., "10.0.0.1"
    EXPORT_PORTID="<YOUR_PORT_ID>"    # e.g., "1"
    # -------------------------------------------------
    EXPORT_APP_CONFIG_FILE_PATH="/etc/exportcliv2/AAA_app.conf"
    ```
3.  Save the changes and exit the editor.
4.  **Review Application-Specific Configuration (Recommended):**
    The installer creates `/etc/exportcliv2/AAA_app.conf` by copying a template from the installation bundle (see Appendix A.4). This file contains application-level settings passed to the `exportcliv2` binary.

    Review and, if necessary, edit `/etc/exportcliv2/AAA_app.conf`. The default template provides settings like:
    ```ini
    # /etc/exportcliv2/AAA_app.conf (on the live system)
    # Copied from the bundle's app.conf.template
    mining_delta_sec=120
    ```
    You should adjust these values if the requirements for this specific instance (e.g., "AAA") differ from the template's defaults.

5.  **Review Bitmover (including Purger) Configuration (Recommended):**
    Review `/etc/exportcliv2/config.ini` and adjust settings for the Bitmover service, particularly the `[Scanner]` and
    `[Purger]` sections, to suit your environment's PCAP generation rate and disk capacity. See Appendix A.5 for details.

---

## 8. Step 5: Restart `exportcliv2` Instance After Configuration

*(Apply the instance configuration changes.)*

For the changes in `/etc/exportcliv2/AAA.conf` (and potentially `/etc/exportcliv2/config.ini` if changed) to take
effect:

*   Restart the specific `exportcliv2` instance:
    ```bash
    exportcli-manage -i AAA --restart
    ```
*   If `/etc/exportcliv2/config.ini` was changed for the Bitmover service, restart it:
    ```bash
    exportcli-manage --restart
    ```

> **Note:** `exportcli-manage` is a user-friendly wrapper script installed by the suite, typically at
`/usr/local/bin/exportcli-manage`. It uses `systemctl` to manage the `bitmover.service` and
`exportcliv2@<INSTANCE_NAME>.service` units.

---

## 9. Step 6: Verify Service Operation

*(Check that both the Bitmover service and your `exportcliv2` instance are active.)*

1.  **Check the Bitmover service status:**
    ```bash
    exportcli-manage --status
    ```
    Look for `Active: active (running)` for `bitmover.service`.

2.  **Check the `exportcliv2` instance "AAA" status:**
    ```bash
    exportcli-manage -i AAA --status
    ```
    Look for `Active: active (running)` for `exportcliv2@AAA.service`.

3.  **Check the Health Check Timer status (Optional):**
    To verify that the automatic health monitoring is scheduled, you can list the active timers for the application:
    ```bash
    systemctl list-timers 'exportcliv2-healthcheck@*.timer'
    ```
    You should see an entry for each instance (e.g., `exportcliv2-healthcheck@AAA.timer`), indicating when it will next
    run.

---

## 10. Step 7: Understanding Key System Directories and Files

*(Learn where important application files and data are located on the system.)*

Key paths for the installed application are determined during installation (based on `BASE_DIR_CONFIG` from
`install-app.conf`, defaulting to `/opt/bitmover/`) and recorded in `/etc/default/exportcliv2_base_vars`. The `BASE_DIR`
path should correspond to your dedicated ext4 filesystem mount point.

*   **Base Application Directory:** (Default: `/opt/bitmover/`). Check `BASE_DIR` in `/etc/default/exportcliv2_base_vars`.
    This **must** be on your dedicated ext4 filesystem.
    *   `bin/`: Contains executables (e.g., `exportcliv2-v0.4.0-B1771-24.11.15`), the `exportcliv2` symlink pointing to
        the active binary, helper scripts like `run_exportcliv2_instance.sh` and `manage_services.sh`.
    *   `csv/`: For CSV metadata files (e.g., `AAA.csv`) and `.restart` trigger files.
    *   `datamover_venv/`: Python virtual environment for the Bitmover service.
    *   `source/`, `worker/`, `uploaded/`, `dead_letter/`: Working directories for the Bitmover service (these are
        subdirectories of `BASE_DIR`). The Purger component acts on files in `worker/` and `uploaded/`.
*   **System Configuration Directory:** `/etc/exportcliv2/` (Check `ETC_DIR` in `/etc/default/exportcliv2_base_vars`).
    *   Instance configurations: e.g., `AAA.conf`, `AAA_app.conf`.
    *   Common configurations: `common.auth.conf`, `config.ini` (for the Bitmover service, including its Purger component
        settings – see Appendix A.5).
*   **Base Log Directory:** `/var/log/exportcliv2/` (Check `BITMOVER_LOG_DIR`'s parent or instance log parent in
    `/etc/default/exportcliv2_base_vars`).
    *   `bitmover/`: Contains `app.log.jsonl` (main Bitmover log, including Purger activity) and `audit.log.jsonl` (upload
        audit log). This specific path is configured via `logger_dir` in `/etc/exportcliv2/config.ini`.
    *   `AAA/` (or other instance names): Contains instance-specific file logs (e.g., `exportcliv2_<DATE>.log`) if the
        application writes them to its working directory. This directory (`/var/log/exportcliv2/AAA`) is also managed by
        systemd as `LogsDirectory` for the instance. `exportcliv2` instances also log to the system journal.

---

## 11. Step 8: Checking Logs

*(View logs for troubleshooting or monitoring.)*

Use `exportcli-manage` or view files directly.

*   **Follow Bitmover service main logs (includes Purger activity):**
    ```bash
    exportcli-manage --logs-follow
    ```
*   **Follow `exportcliv2` instance "AAA" journald logs:**
    ```bash
    exportcli-manage -i AAA --logs-follow
    ```
*   **Example of viewing a file-based log directly (Bitmover audit log):**
    ```bash
    tail -f /var/log/exportcliv2/bitmover/audit.log.jsonl
    ```

---

## 12. Step 9: Preparing the Installation Bundle with a Patch (`install_patch.sh`)

*(Update your local installation bundle with a new binary or wheel before deploying it to the system.)*

1.  **Navigate to your Installation Package Directory:**
    This is the directory you extracted in Step 1 (e.g., `/root/exportcliv2-suite-v1.0.0/`), which contains
    `install_patch.sh`.
    ```bash
    cd /root/exportcliv2-suite-v1.0.0/ # Adjust to your actual path
    ```

2.  **Run `install_patch.sh` with an *absolute path* to the new component:**
    *   **To prepare the bundle to use a different binary already
        present *within this bundle's `exportcliv2-deploy/` directory*** (e.g., an included emulator like `exportcliv8`):
        ```bash
        # Example: In /root/exportcliv2-suite-v1.0.0/
        ./install_patch.sh --new-binary "$(pwd)/exportcliv2-deploy/exportcliv8"
        ```
        This updates the bundle's `install-app.conf` to reference `exportcliv8` as `VERSIONED_APP_BINARY_FILENAME`.

    *   **To prepare the bundle with an *externally provided* new binary** (a patch file not originally in this bundle):
        Suppose the new binary patch is located at `/tmp/exportcliv2-patch-vNEW`.
        ```bash
        # Example: In /root/exportcliv2-suite-v1.0.0/
        ./install_patch.sh --new-binary /tmp/exportcliv2-patch-vNEW
        ```
        This copies `exportcliv2-patch-vNEW` into this bundle's `./exportcliv2-deploy/` directory and updates
        `VERSIONED_APP_BINARY_FILENAME` in `install-app.conf`.

    *   **To prepare the bundle with an *externally provided* new DataMover wheel:**
        Suppose the new wheel is at `/tmp/datamover-patch-vNEW.whl`. This wheel might include updates to the Purger or
        changes to the `config.ini.template` (which would then be deployed during an update).
        ```bash
        # Example: In /root/exportcliv2-suite-v1.0.0/
        ./install_patch.sh --new-wheel /tmp/datamover-patch-vNEW.whl
        ```
    After `install_patch.sh` completes successfully, it will confirm the bundle is prepared.

---

## 13. Step 10: Deploying a Prepared/Patched Bundle (`deploy_orchestrator.sh --update`)

*(Apply the changes from your updated local bundle to the live system.)*

1.  **Ensure you are still in your Installation Package Directory** (e.g., `/root/exportcliv2-suite-v1.0.0/`).

2.  **Run the Orchestrator in Update Mode:**
    ```bash
    ./deploy_orchestrator.sh --update
    ```
    Confirm when prompted. This command applies the components specified in the (now patched) bundle's `install-app.conf`
    to your system. This includes deploying the `config.ini.template` from the bundle as `/etc/exportcliv2/config.ini`,
    which would update any default Purger settings if the template changed.

3.  **Restart Affected Services:**
    The `deploy_orchestrator.sh --update` script will provide guidance.
    *   **If `exportcliv2` binary changed:** Restart all affected `exportcliv2` instances (e.g.,
        `exportcli-manage -i AAA --restart`).
    *   **If DataMover wheel or `config.ini.template` changed:** Restart the Bitmover service (
        `exportcli-manage --restart`) to pick up new code or default configurations (including for the Purger).

4.  **Verify Operation:**
    Check status and logs. Verify the active binary symlink (replace `/opt/bitmover` with your `BASE_DIR` from
    `/etc/default/exportcliv2_base_vars` if it was changed post-install):
    ```bash
    ls -l /opt/bitmover/bin/exportcliv2
    ```

> **Note on SELinux/AppArmor:** If using non-standard paths for `BASE_DIR_CONFIG` during installation (i.e., not
`/opt/bitmover/`), security contexts might need adjustment (e.g., `semanage fcontext`, `restorecon`). The default path
> is generally chosen to work with standard system policies.

---

## 14. Step 11: Updating Authentication Credentials

*(Modify credentials if required for `exportcliv2` instances.)*

1.  Edit the common authentication file: `/etc/exportcliv2/common.auth.conf`:
    ```bash
    vi /etc/exportcliv2/common.auth.conf
    ```
2.  Update `EXPORT_AUTH_TOKEN_U` (username) and `EXPORT_AUTH_TOKEN_P` (password).
3.  Save and exit.
4.  **Restart all `exportcliv2` instances:**
    ```bash
    exportcli-manage -i AAA --restart # And for any other instances.
    ```

---

## 15. Troubleshooting

*(Basic steps to diagnose issues.)*

1.  **Check Service Status:**
    *   Bitmover service: `exportcli-manage --status`
    *   `exportcliv2` instance: `exportcli-manage -i <INSTANCE_NAME> --status`
2.  **Review Logs:**
    *   Use `exportcli-manage --logs [-follow]` or `exportcli-manage -i <INSTANCE_NAME> --logs [-follow]`.
    *   Check system journal: `journalctl -u bitmover.service` or `journalctl -u exportcliv2@<INSTANCE_NAME>.service`.
    *   Check application file logs in `/var/log/exportcliv2/` (Bitmover logs in `bitmover/` subdirectory, including
        Purger activity; instance-specific logs potentially in `INSTANCE_NAME/` subdirectory if configured and
        `WorkingDirectory` is used).
3.  **Verify Configuration:**
    *   System-wide defaults: `/etc/default/exportcliv2_base_vars`.
    *   Bitmover config (including Purger): `/etc/exportcliv2/config.ini` (See Appendix A.5).
    *   Instance environment: `/etc/exportcliv2/<INSTANCE_NAME>.conf`.
    *   Instance application config: `/etc/exportcliv2/<INSTANCE_NAME>_app.conf`.
    *   Shared authentication: `/etc/exportcliv2/common.auth.conf`.
4.  **Permissions:** Ensure file and directory permissions and ownerships are correct, especially in `/etc/exportcliv2/`,
    `/var/log/exportcliv2/`, and your base application directory (e.g. `/opt/bitmover/`). Expected ownership for
    service-writable areas is often `exportcliv2_user:exportcliv2_group` (or your configured user/group).
5.  **Path Issues:** Ensure `exportcli-manage` is in the system `PATH` (`command -v exportcli-manage` or
    `ls -l /usr/local/bin/exportcli-manage`).
6.  **Disk Space / Purger Issues:**
    *   **Verify Filesystem Setup:** Confirm that the `base_dir` specified in `/etc/exportcliv2/config.ini` (typically
        `/opt/bitmover/`) is correctly mounted on a dedicated **ext4** filesystem as outlined in "Step 0: Prerequisites
        and System Preparation". Issues with the underlying filesystem (wrong type, not mounted, insufficient space,
        incorrect permissions) are common causes of Purger or general operational problems.
    *   If files are being deleted unexpectedly, or not being deleted when disk space is low, check the Bitmover
        `app.log.jsonl` (in `/var/log/exportcliv2/bitmover/`) for messages from the "PurgerThread".
    *   Verify the `[Purger]` section in `/etc/exportcliv2/config.ini`, especially `target_disk_usage_percent` and
        `total_disk_capacity_bytes`.
    *   If `total_disk_capacity_bytes` is set to `0` (auto-detect), ensure the Bitmover service (`exportcliv2_user`) has
        permissions to query disk usage for the filesystem containing the `base_dir` specified in `config.ini` (this
        `base_dir` is where `uploaded_dir` resides, which is used for detection). Errors during auto-detection will be
        logged at service startup in `app.log.jsonl` and may prevent the service from starting correctly.
7.  **Instance Health Check and Auto-Restart Issues:**
    The system includes an automatic health check that restarts an `exportcliv2` instance if it detects it has become
    unresponsive.
    *   **How it works:** A systemd timer (`exportcliv2-healthcheck@.timer`) periodically runs a service (
        `exportcliv2-healthcheck@.service`). This service executes `exportcli-manage --run-health-check`, which checks if
        the main instance service has logged anything recently. If not, it triggers a restart.
    *   **Check health check logs:** To see the health check's own activity (e.g., "PASSED" or "FAILED" messages), run:
        ```bash
        journalctl -u exportcliv2-healthcheck@<INSTANCE_NAME>.service
        ```
    *   **Check timer and service status:** To see when the timer will next run or when the check last ran, use:
        ```bash
        systemctl status exportcliv2-healthcheck@<INSTANCE_NAME>.timer
        systemctl status exportcliv2-healthcheck@<INSTANCE_NAME>.service
        ```
    *   **Configure or Disable:** The health check is controlled by the `HEALTH_CHECK_INTERVAL_MINS` variable in
        `/etc/default/exportcliv2_base_vars`. To change the check frequency, edit this value. **To disable the health
        check, set this value to `0`.**
    *   **Frequent Restarts:** If you see in the logs that an instance is being restarted frequently by the health check,
        it indicates an underlying problem with the `exportcliv2` application itself. The health check is functioning
        correctly by detecting the problem; you should investigate the main application logs (
        `exportcli-manage -i <INSTANCE_NAME> --logs`) for errors that might be causing it to freeze or crash.

---

## 16. Appendix A: Key Configuration and Template File Details

*(Details about important configuration files and templates used by the suite.)*

The installation process uses several configuration files and templates. The `install_base_exportcliv2.sh` script
processes templates by replacing placeholders (like `{{APP_NAME}}`, `{{APP_USER}}`, `{{ETC_DIR}}`, etc.) with actual
values derived during installation (many from `/etc/default/exportcliv2_base_vars` or the bundle's `install-app.conf`).

### A.1 `install-app.conf` (Bundle's Primary Input Configuration)

*(Located in `exportcliv2-suite-v1.0.0/exportcliv2-deploy/`. This file drives the `deploy_orchestrator.sh` and
subsequently the `install_base_exportcliv2.sh` scripts for initial setup or updates.)*

```ini
# install-app.conf

# Space-separated list of instance names.
DEFAULT_INSTANCES_CONFIG = "AAA"

# The filename of the VERSIONED main application binary.
VERSIONED_APP_BINARY_FILENAME = "exportcliv2-v0.4.0-B1771-24.11.15"

# The filename of the VERSIONED DataMover Python wheel.
VERSIONED_DATAMOVER_WHEEL_FILENAME = "datamover-1.0.0-py3-none-any.whl"

# The remote URL for the Bitmover component to upload data to.
# Must start with http:// or https://
REMOTE_HOST_URL_CONFIG = "http://192.168.0.180:8989/pcap"

# Timeout (-t) in seconds for exportcliv2 instances.
EXPORT_TIMEOUT_CONFIG = "15"

# Health Check: Interval in minutes to check if an instance of the exportcliv2 is alive.
# If an instance has not logged anything to the journal in this time,
# it is considered locked and will be automatically restarted.
# Set to 0 to disable this feature.
HEALTH_CHECK_INTERVAL_MINS_CONFIG = "5"

# The user name for the service.
USER_CONFIG = "exportcliv2_user"

# The group name for the service.
GROUP_CONFIG = "exportcliv2_group"

# BASE_DIR_CONFIG: Overrides the default base installation directory.
BASE_DIR_CONFIG = "/opt/bitmover"

# WHEELHOUSE_SUBDIR: Subdirectory containing dependency wheels for offline Python package installation.
WHEELHOUSE_SUBDIR = "wheelhouse"

# LOG_DIR_CONFIG: Base directory for application suite logs.
LOG_DIR_CONFIG = "/var/log/exportcliv2/"
```

**Key Points:**

*   `DEFAULT_INSTANCES_CONFIG` drives which instances are set up by `deploy_orchestrator.sh --install` if not overridden.
*   `HEALTH_CHECK_INTERVAL_MINS_CONFIG` configures the automatic health monitoring for instances. This value is written by
    the installer to `/etc/default/exportcliv2_base_vars` as `HEALTH_CHECK_INTERVAL_MINS`.
*   `VERSIONED_APP_BINARY_FILENAME`, `VERSIONED_DATAMOVER_WHEEL_FILENAME`, and `WHEELHOUSE_SUBDIR` are set by the
    `create_bundle.sh` script to match the files included in the `exportcliv2-deploy/` directory of the bundle.
*   `REMOTE_HOST_URL_CONFIG`, `EXPORT_TIMEOUT_CONFIG`, `USER_CONFIG`, `GROUP_CONFIG`, `BASE_DIR_CONFIG`, and
    `LOG_DIR_CONFIG` are critical operational settings and system defaults used by the installer.
*   **`BASE_DIR_CONFIG` must point to the mount point of your prepared dedicated ext4 filesystem.**
*   `LOG_DIR_CONFIG` defines the base path under which service-specific log directories are created (e.g., the Bitmover
    service log directory will be `LOG_DIR_CONFIG`/bitmover/).

---

### A.2 `run_exportcliv2_instance.sh.template` (Instance Wrapper Script)

*(Template located in `exportcliv2-deploy/config_files/`. `install_base_exportcliv2.sh` processes this template and
installs it as `run_exportcliv2_instance.sh` in the application's `bin` directory,
e.g., `/opt/bitmover/bin/run_exportcliv2_instance.sh`.)*

This script is executed by the `exportcliv2@.service` systemd unit for each instance.

```bash
#!/bin/bash
set -euo pipefail

# Wrapper script for {{APP_NAME}} instance: $1 (passed by systemd as %i)
# Executed as {{APP_USER}}

# --- Instance Name from Argument ---
if [[ -z "$1" ]]; then
  # Log to stderr (for immediate journalctl context) and syslog (for alerting/filtering)
  echo "Error: Instance name argument (%i) not provided to wrapper script." >&2
  logger -t "{{APP_NAME}}" -p daemon.error "Instance name argument (%i) not provided to wrapper script."
  exit 78 # EX_CONFIG
fi
INSTANCE_NAME="$1"
LOGGER_TAG="{{APP_NAME}}@${INSTANCE_NAME}"

# --- Log script start (optional but helpful) ---
echo "Wrapper script for ${LOGGER_TAG} starting..."

# --- Constants ---
# A value of -1 indicates the application should run indefinitely with no end time.
readonly INDEFINITE_RUN_ARG="-1"

# --- Sanity check required environment variables ---
# These are expected to be set by systemd via EnvironmentFile directives
# (e.g., from {{ETC_DIR}}/common.auth.conf and {{ETC_DIR}}/${INSTANCE_NAME}.conf)
required_vars=(
  "EXPORT_AUTH_TOKEN_U"
  "EXPORT_AUTH_TOKEN_P"
  "EXPORT_TIMEOUT"
  "EXPORT_SOURCE" # Used to build -o path
  "EXPORT_IP"
  "EXPORT_PORTID"
  "EXPORT_APP_CONFIG_FILE_PATH"
  "EXPORT_STARTTIME_OFFSET_SPEC"
)
for var_name in "${required_vars[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then # Indirect expansion
    error_msg="Required environment variable '${var_name}' is not set. Check {{ETC_DIR}}/common.auth.conf and {{ETC_DIR}}/${INSTANCE_NAME}.conf."
    echo "Error: ${LOGGER_TAG}: ${error_msg}" >&2
    logger -t "${LOGGER_TAG}" -p daemon.error "${error_msg}"
    exit 78 # EX_CONFIG
  fi
done

# --- Calculate dynamic start time ---
# Uses EXPORT_STARTTIME_OFFSET_SPEC from the environment.
# The 'if !' construct is safer than checking for empty output.
if ! calculated_start_time=$(date +%s%3N --date="${EXPORT_STARTTIME_OFFSET_SPEC}"); then
  error_msg="Could not calculate start_time using EXPORT_STARTTIME_OFFSET_SPEC ('${EXPORT_STARTTIME_OFFSET_SPEC}')."
  echo "Error: ${LOGGER_TAG}: ${error_msg}" >&2
  logger -t "${LOGGER_TAG}" -p daemon.error "${error_msg}"
  exit 78 # EX_CONFIG
fi

# --- Check if the app-specific config file actually exists ---
if [[ ! -f "${EXPORT_APP_CONFIG_FILE_PATH}" ]]; then
    error_msg="Application specific config file specified by EXPORT_APP_CONFIG_FILE_PATH ('${EXPORT_APP_CONFIG_FILE_PATH}') does not exist."
    echo "Error: ${LOGGER_TAG}: ${error_msg}" >&2
    logger -t "${LOGGER_TAG}" -p daemon.error "${error_msg}"
    exit 78 # EX_CONFIG
fi

# --- Construct paths and arguments ---
CSV_INSTANCE_DIR="{{CSV_DATA_DIR}}"
SOURCE_INSTANCE_PATH="{{SOURCE_DATA_DIR}}/${EXPORT_SOURCE}"

# Build the argument list in an array for robustness and clarity.
# This array contains the REAL credentials and will be used for execution.
args=(
  "-c" "${EXPORT_APP_CONFIG_FILE_PATH}"
  "-u" "${EXPORT_AUTH_TOKEN_U}"
  "-p" "${EXPORT_AUTH_TOKEN_P}"
  "-C"
  -t "${EXPORT_TIMEOUT}"
  -H "${CSV_INSTANCE_DIR}"
  -o "${SOURCE_INSTANCE_PATH}"
  "${EXPORT_IP}"
  "${EXPORT_PORTID}"
  "${calculated_start_time}"
  "${INDEFINITE_RUN_ARG}"
)

# --- Create a sanitized version of the command for logging ---
# This iterates through the real arguments and replaces sensitive values.
log_args_safe=()
skip_next=false
for arg in "${args[@]}"; do
  if [[ "$skip_next" == true ]]; then
    skip_next=false
    continue
  fi

  case "$arg" in
    -u|-p)
      log_args_safe+=("$arg" "'***'") # Add the flag and the mask
      skip_next=true # Tell the loop to ignore the next item (the real token)
      ;;
    *)
      # Use printf %q to quote the argument exactly as the shell would need it.
      # This handles spaces and special characters safely.
      log_args_safe+=("$(printf '%q' "$arg")")
      ;;
  esac
done

# --- Log the final, sanitized command string ---
printf "Executing for %s:\n  %q %s\n" \
  "${INSTANCE_NAME}" \
  "{{SYMLINK_EXECUTABLE_PATH}}" \
  "${log_args_safe[*]}"

# --- Execute the main application binary ---
# The shell expands "${args[@]}" into separate, quoted arguments.
exec "{{SYMLINK_EXECUTABLE_PATH}}" "${args[@]}"

# If exec fails, this script will exit.
# If exec succeeds, this part is never reached.
exit $?
```

**Key Points:**

*   Receives instance name (`%i`) from systemd.
*   Sources instance-specific environment variables from `/etc/exportcliv2/<INSTANCE_NAME>.conf` and shared credentials
    from `/etc/exportcliv2/common.auth.conf`.
*   Performs robust checks for required environment variables.
*   Dynamically calculates `start_time` based on `EXPORT_STARTTIME_OFFSET_SPEC` using a safe `date` command invocation.
*   Verifies the existence of the application-specific configuration file.
*   **The `EXPORT_ENDTIME` parameter for the application is fixed to `-1` (signifying now/indefinite) via
    the `INDEFINITE_RUN_ARG` variable. It is not configurable via instance environment files.**
*   Constructs command arguments in a bash array for robustness.
*   Logs a sanitized version of the command, masking sensitive credentials (`-u` and `-p` arguments).
*   Uses `exec` to run the actual `exportcliv2` binary, a process that replaces the wrapper script.
*   Placeholders like `{{APP_NAME}}`, `{{ETC_DIR}}`, `{{CSV_DATA_DIR}}`, `{{SOURCE_DATA_DIR}}`,
    `{{SYMLINK_EXECUTABLE_PATH}}` are replaced by `install_base_exportcliv2.sh` during deployment.

---

### A.3 `/etc/exportcliv2/common.auth.conf` (Shared Authentication)

*(This file is deployed by `install_base_exportcliv2.sh` from the `config_files/common.auth.conf` template in the
bundle. It is located on the live system at `/etc/exportcliv2/common.auth.conf` by default.)*

Used to store shared credentials sourced by `run_exportcliv2_instance.sh` for each instance.

```ini
# Common authentication tokens
# These values will be used by all exportcliv2 instances.
# Ensure this file has restricted permissions (e.g., 0640, root:{{APP_GROUP}}).
EXPORT_AUTH_TOKEN_U = "<DEFAULT_SHARED_USER>" # Example: shared_user
EXPORT_AUTH_TOKEN_P = "<DEFAULT_SHARED_PASSWORD_OR_TOKEN>" # Example: shared_password
```

**Key Points:**

*   The deployed file will contain the default values from the template (e.g., `shared_user`, `shared_password`). Edit
    this file on the live system to set actual credentials.
*   Permissions should be restrictive (e.g., `0640`, owner `root`, group `exportcliv2_group` (or your configured group)).
    The placeholder `{{APP_GROUP}}` will be replaced by the installer with the value from `GROUP_CONFIG` in
    `install-app.conf`.

---

### A.4 `app.conf.template` (Instance's Application Configuration Template)

*(This template is located in `exportcliv2-deploy/config_files/`. During installation, `configure_instance.sh` copies it to `/etc/exportcliv2/<INSTANCE_NAME>_app.conf` for each new instance.)*

This file serves as the base configuration for the application-specific settings that are passed to the `exportcliv2` binary via the `-c` command-line argument.

**Example Content:**

```ini
# /etc/exportcliv2/<INSTANCE_NAME>_app.conf
# This file is copied from the app.conf.template in the installation bundle.
# Edit this file on the live system to configure instance-specific application parameters.

mining_delta_sec=120
```

**Key Points:**

*   Unlike other templates, this file is copied **as-is** without placeholder replacement.
*   It allows you to define a standard set of default application parameters in the bundle.
*   After installation, you can edit the resulting `/etc/exportcliv2/<INSTANCE_NAME>_app.conf` file for each instance to override the templated defaults as needed.

---

### A.5 `/etc/exportcliv2/config.ini` (Bitmover Service Configuration)

*(This file is deployed by `install_base_exportcliv2.sh` from the `config_files/config.ini.template` in the bundle. It
is located on the live system at `/etc/exportcliv2/config.ini` by default.)*

This INI file configures the Bitmover service, which handles PCAP file processing, uploading, and disk space management.
The installer (`install_base_exportcliv2.sh`) populates placeholders like `{{BASE_DIR}}` and `{{REMOTE_HOST_URL}}`
based on values from the bundle's `install-app.conf`. The `{{BITMOVER_LOG_DIR}}` placeholder in the template (which
becomes `logger_dir`) is derived by appending "bitmover" to the `LOG_DIR_CONFIG` value from `install-app.conf`.
The `base_dir` configured here **must** reside on the dedicated ext4 filesystem prepared in Step 0.

**Example Structure and Key Settings (after template processing):**

```ini
# /etc/exportcliv2/config.ini (on the live system)
# Configuration File for the PCAP Uploader Service (bitmover)
# Templated by base installer

[Directories]
# All directories must be on the same file system.
# Base directory for Bitmover's operational subdirectories (source, worker, etc.).
# Populated from BASE_DIR_CONFIG in install-app.conf (e.g., /opt/bitmover), via {{BASE_DIR}} placeholder.
# This path MUST be on your dedicated ext4 filesystem.
# The Bitmover application will create source, csv, worker, uploaded, dead_letter subdirectories within this base_dir.
base_dir = /opt/bitmover # Example value

# Directory to put Bitmover's own log files in (app.log.jsonl, audit.log.jsonl).
# This directory must exist.
# The installer derives this path (represented by the {{BITMOVER_LOG_DIR}} placeholder
# in the template) by appending "bitmover" to the LOG_DIR_CONFIG value from install-app.conf.
# For example, if LOG_DIR_CONFIG is "/var/log/exportcliv2/", this becomes "/var/log/exportcliv2/bitmover/".
logger_dir = /var/log/exportcliv2/bitmover # Example value after template processing

[Files]
# The file extension (without the dot) to look for for pcap files when scanning the source directory.
pcap_extension_no_dot = pcap

# The file extension (without the dot) to look for when scanning the source directory for CSV files.
csv_extension_no_dot = csv

[Mover]
# How often (in seconds) to check the queue for files to move from the source directory to the worker directory.
# Leave at the default of 0.5 seconds.
move_poll_interval_seconds = 0.5

[Scanner]
# The stuck_active_file_timeout_seconds must be greater than the lost_timeout_seconds.

# How often (in seconds) to scan the source directory for lost / broken files.
# Match this to the pcap file generation rate.
scanner_check_seconds = 15.0

# How long (in seconds) to wait for a file to be considered "lost" and moved to the worker directory.
# This should be long enough to let the hash be generated too fast and it will be marked lost while it is still being worked on.
lost_timeout_seconds = 301.0

# How long (in seconds) to wait for a file to be considered "broken" (e.g., if it is still being written to).
# This should be greater than the pcap file generation rate - at least one cycle longer than lost_timeout_seconds.
stuck_active_file_timeout_seconds = 361.0

[Tailer]
# How often (in seconds) to check the exit - leave at the default of 0.5 seconds.
event_queue_poll_timeout_seconds = 0.5

[Purger]
# This section configures the automatic disk space management (purging) feature.
# The Purger periodically checks disk usage and deletes older files from the
# 'uploaded' and 'worker' directories if disk usage exceeds the target.
# This relies on 'base_dir' being on a correctly configured ext4 filesystem.

# How often (in seconds) the Purger checks disk usage.
# Default value from template: 600 (10 minutes).
purger_poll_interval_seconds = 600

# Target maximum disk usage percentage (e.g., 0.75 means system aims to not let disk usage exceed 75%).
# If actual disk usage (as a percentage of total_disk_capacity_bytes) exceeds this value,
# the Purger will attempt to delete older files from 'uploaded' and then 'worker' directories to free up space.
# Value must be between 0.0 (exclusive) and 1.0 (inclusive).
# Default value from template: 0.75
target_disk_usage_percent = 0.75

# Total capacity of the disk being monitored, in bytes. This refers to the capacity of the
# ext4 filesystem where 'base_dir' resides.
# - Set to a positive integer value to define a fixed capacity (e.g., 107374182400 for 100 GiB).
# - Set to 0 (zero) to enable auto-detection of the disk capacity. The capacity will be detected
#   from the filesystem where the 'uploaded_dir' (a subdirectory of 'base_dir') resides.
# Auto-detection (0) is generally recommended for production unless specific override is needed.
# If auto-detection fails (e.g., due to permissions or filesystem issues), the Bitmover
# service may fail to start; check application logs in 'logger_dir'.
# Default value from template: 0 (auto-detect)
total_disk_capacity_bytes = 0

[Uploader]
# How often (in seconds) to check the queue for files to upload from the worker directory.
uploader_poll_interval_seconds = 0.5

# How often to report progress - leave at the default of 60 seconds.
heartbeat_target_interval_s = 60.0

# Full URL of the remote endpoint for uploading PCAP files
# Populated from REMOTE_HOST_URL_CONFIG in install-app.conf, via {{REMOTE_HOST_URL}} placeholder.
remote_host_url = http://192.168.0.180:8989/pcap # Example value (production endpoint)

# How long (in seconds) to wait for the server to respond during upload
request_timeout = 30.0

# IMPORTANT: Set this to 'true' if using HTTPS (https://...) AND the server has a valid SSL certificate.
# Setting to 'false' disables certificate checking (less secure, use only for testing or specific internal networks).
# The current default endpoint is HTTP, so 'false' is appropriate. If changing to HTTPS, review this.
verify_ssl = false

# Initial delay (in seconds) before retrying a failed network connection/upload
initial_backoff = 1.0

# Maximum delay (in seconds) between network retries (prevents excessively long waits)
max_backoff = 60.0
```

**Key Points:**

*   The configuration is structured into sections like `[Directories]`, `[Files]`, `[Scanner]`, `[Purger]`, `[Uploader]`.
*   `base_dir`: The Bitmover application internally uses this to locate its working subdirectories (e.g., `source/`,
    `worker/`, etc. will be under this path, which defaults to `/opt/bitmover/`). **This path must reside on your
    dedicated ext4 filesystem.**
*   `logger_dir`: The Bitmover application writes its logs (e.g., `app.log.jsonl`, `audit.log.jsonl`) into this
    directory (e.g., `/var/log/exportcliv2/bitmover/`).
*   `remote_host_url` is populated from `install-app.conf`.
*   `verify_ssl` is set to `false` by default. The current production endpoint is HTTP. **If the endpoint changes to HTTPS
    in the future, this setting MUST be reviewed and updated to `true` on the live system for secure operation, assuming a
    valid server certificate.**
*   Scanner timings (`scanner_check_seconds`, `lost_timeout_seconds`, `stuck_active_file_timeout_seconds`) are crucial for
    reliable operation and may need tuning based on the environment's PCAP file generation characteristics.
*   **Purger Settings (`[Purger]` section):**
    *   `purger_poll_interval_seconds`: Controls frequency of disk checks.
    *   `target_disk_usage_percent`: Defines the threshold for when purging should begin.
    *   `total_disk_capacity_bytes`: Allows manual override or auto-detection (`0`) of disk size for the filesystem
        hosting `base_dir`. Auto-detection is recommended.

---

### A.6 Systemd Unit Templates Overview

*(Templates are located in `exportcliv2-deploy/systemd_units/`. `install_base_exportcliv2.sh` processes them and
installs the resulting unit files into `/etc/systemd/system/`.)*

Placeholders like `{{APP_NAME}}`, `{{APP_USER}}`, `{{APP_GROUP}}`, `{{PYTHON_VENV_PATH}}`, `{{BITMOVER_CONFIG_FILE}}`,
`{{ETC_DIR}}`, `{{CSV_DATA_DIR}}`, `{{INSTALLED_WRAPPER_SCRIPT_PATH}}` are replaced with actual values during template
processing. The value for `{{BITMOVER_LOG_DIR}}` is derived by appending "bitmover" to `LOG_DIR_CONFIG` (from
`install-app.conf`). The value for `LogsDirectory={{APP_NAME}}/%i` in `exportcliv2@.service.template` will use the
`LOG_DIR_CONFIG` value as its base (e.g., `/var/log/exportcliv2/AAA`).
The paths `{{SOURCE_DATA_DIR}}`, `{{CSV_DATA_DIR}}`, etc., within the service units will point to locations under the
`BASE_DIR` (which must be on the dedicated ext4 filesystem).

1.  **`bitmover.service.template`:**
    *   Manages the main Bitmover upload service.
    *   Runs as `{{APP_USER}}`:`{{APP_GROUP}}` (e.g., `exportcliv2_user:exportcliv2_group`).
    *   Executes `{{PYTHON_VENV_PATH}}/bin/bitmover --config {{BITMOVER_CONFIG_FILE}}`.
    *   Includes `ExecStartPre` checks for directory existence and writability. These directories (e.g.,
        `{{SOURCE_DATA_DIR}}`, `{{CSV_DATA_DIR}}`) are subdirectories of the `base_dir` defined in
        `/etc/exportcliv2/config.ini` (e.g., `/opt/bitmover/source`, `/opt/bitmover/csv`). `{{BITMOVER_LOG_DIR}}`
        corresponds to `logger_dir` in `config.ini` (e.g., `/var/log/exportcliv2/bitmover`).
    *   Configured for auto-restart on failure (excluding config/usage errors).
    ```systemd
    [Unit]
    Description=Bitmover - PCAP Upload Service for {{APP_NAME}}
    After=network-online.target
    Wants=network-online.target
    StartLimitIntervalSec=300
    StartLimitBurst=5

    [Service]
    Type=simple
    User={{APP_USER}}
    Group={{APP_GROUP}}
    UMask=0027
    ExecStart={{PYTHON_VENV_PATH}}/bin/bitmover --config {{BITMOVER_CONFIG_FILE}}
    ExecStartPre=/usr/bin/test -d {{SOURCE_DATA_DIR}} -a -w {{SOURCE_DATA_DIR}}
    ExecStartPre=/usr/bin/test -d {{CSV_DATA_DIR}} -a -w {{CSV_DATA_DIR}}
    ExecStartPre=/usr/bin/test -d {{WORKER_DATA_DIR}} -a -w {{WORKER_DATA_DIR}}
    ExecStartPre=/usr/bin/test -d {{UPLOADED_DATA_DIR}} -a -w {{UPLOADED_DATA_DIR}}
    ExecStartPre=/usr/bin/test -d {{DEAD_LETTER_DATA_DIR}} -a -w {{DEAD_LETTER_DATA_DIR}}
    ExecStartPre=/usr/bin/test -d {{BITMOVER_LOG_DIR}} -a -w {{BITMOVER_LOG_DIR}}
    Environment="PYTHONUNBUFFERED=1"
    Restart=on-failure
    RestartSec=10s
    RestartPreventExitStatus=64 78 # EX_USAGE, EX_CONFIG
    StandardOutput=journal
    StandardError=journal
    SyslogIdentifier=bitmover

    [Install]
    WantedBy=multi-user.target
    ```

2.  **`exportcliv2@.service.template`:**
    *   A systemd template unit for running individual `exportcliv2` instances (e.g., `exportcliv2@AAA.service`).
    *   Runs as `{{APP_USER}}`:`{{APP_GROUP}}`.
    *   Uses `EnvironmentFile` to load `/etc/exportcliv2/common.auth.conf` and `/etc/exportcliv2/%i.conf`.
    *   Executes `{{INSTALLED_WRAPPER_SCRIPT_PATH}} %i` (which is the processed `run_exportcliv2_instance.sh`).
    *   Uses `LogsDirectory={{APP_NAME}}/%i` (e.g., `/var/log/exportcliv2/AAA`, where `/var/log/exportcliv2` is from
        `LOG_DIR_CONFIG`) for systemd to manage a per-instance log/working directory.
    *   `WorkingDirectory` is set to this `LogsDirectory`.
    ```systemd
    [Unit]
    Description={{APP_NAME}} instance %I
    After=network-online.target
    Wants=network-online.target
    StartLimitIntervalSec=300
    StartLimitBurst=5

    [Service]
    User={{APP_USER}}
    Group={{APP_GROUP}}
    UMask=0027
    LogsDirectory={{APP_NAME}}/%i
    LogsDirectoryMode=0750
    WorkingDirectory=/var/log/{{APP_NAME}}/%i # Example: /var/log/exportcliv2/AAA
    ExecStartPre=-/usr/bin/rm -f {{CSV_DATA_DIR}}/%i.restart # CSV_DATA_DIR e.g. /opt/bitmover/csv
    ExecStartPre=/usr/bin/test -d {{SOURCE_DATA_DIR}} -a -w {{SOURCE_DATA_DIR}} # e.g. /opt/bitmover/source
    ExecStartPre=/usr/bin/test -d {{CSV_DATA_DIR}} -a -w {{CSV_DATA_DIR}} # e.g. /opt/bitmover/csv
    EnvironmentFile={{ETC_DIR}}/common.auth.conf
    EnvironmentFile={{ETC_DIR}}/%i.conf
    ExecStart={{INSTALLED_WRAPPER_SCRIPT_PATH}} %i
    StandardOutput=journal
    StandardError=journal
    SyslogIdentifier={{APP_NAME}}@%i
    Restart=on-failure
    RestartSec=5s

    [Install]
    WantedBy=multi-user.target
    ```

3.  **`exportcliv2-restart@.path.template`:**
    *   A path unit that monitors for the existence of a trigger file (e.g., `/opt/bitmover/csv/AAA.restart`).
    *   If the file appears, it activates `exportcliv2-restart@%i.service`.
    ```systemd
    [Unit]
    Description=Path watcher to trigger restart for {{APP_NAME}} instance %I

    [Path]
    PathExists={{CSV_DATA_DIR}}/%i.restart # CSV_DATA_DIR e.g. /opt/bitmover/csv
    Unit={{APP_NAME}}-restart@%i.service

    [Install]
    WantedBy=multi-user.target
    ```

4.  **`exportcliv2-restart@.service.template`:**
    *   A one-shot service triggered by the `.path` unit.
    *   Restarts the corresponding `exportcliv2@%i.service`.
    *   Deletes the trigger file after attempting the restart.
    ```systemd
    [Unit]
    Description=Oneshot service to restart {{APP_NAME}} instance %I
    Wants={{APP_NAME}}@%i.service
    After={{APP_NAME}}@%i.service

    [Service]
    Type=oneshot
    RemainAfterExit=no
    User=root # Needs root to restart another systemd service
    ExecStartPre=/bin/echo "Restart triggered for {{APP_NAME}}@%i.service by presence of {{CSV_DATA_DIR}}/%i.restart"
    ExecStart=/usr/bin/systemctl restart {{APP_NAME}}@%i.service
    ExecStartPost=-/usr/bin/rm -f {{CSV_DATA_DIR}}/%i.restart # CSV_DATA_DIR e.g. /opt/bitmover/csv
    StandardOutput=journal
    StandardError=journal
    SyslogIdentifier={{APP_NAME}}-restart@%i
    ```

5.  **`exportcliv2-healthcheck@.service.template`:**
    *   A one-shot service that runs the `manage_services.sh` script with the `--run-health-check` action.
    *   It is triggered by the corresponding timer unit.
    *   Its purpose is to evaluate the health of a running `exportcliv2` instance.
    ```systemd
    [Unit]
    Description=Health check for {{APP_NAME}} instance %i
    After={{APP_NAME}}@%i.service

    [Service]
    Type=oneshot
    User={{APP_USER}}
    Group={{APP_GROUP}}
    ExecStart={{INSTALLED_MANAGER_SCRIPT_PATH}} -i %i --run-health-check
    StandardOutput=journal
    StandardError=journal
    SyslogIdentifier={{APP_NAME}}-healthcheck@%i
    ```

6.  **`exportcliv2-healthcheck@.timer.template`:**
    *   A timer unit that periodically triggers the health check service.
    *   By default, it starts 2 minutes after boot and then runs every minute. This ensures the main service has time to
        start up before the first check.
    *   The frequency of subsequent checks (`OnUnitActiveSec`) is frequent, but the actual logic is controlled by
        `HEALTH_CHECK_INTERVAL_MINS` inside the script.
    ```systemd
    [Unit]
    Description=Run health check for {{APP_NAME}} instance %i every minute

    [Timer]
    # Run 2 minutes after boot, and every 1 minute thereafter.
    # The delay on boot gives the main service time to start.
    OnBootSec=2min
    OnUnitActiveSec=1min
    Unit={{APP_NAME}}-healthcheck@%i.service

    [Install]
    WantedBy=timers.target
    ```