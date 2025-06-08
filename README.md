## README: exportcliv2 Application Suite (v1.0.0)

This guide walks you through installing the `exportcliv2` application suite, which includes the `exportcliv2` data
export client and the Bitmover service (responsible for PCAP uploads and disk space management).

**Quick Steps Overview:**

* **Step 0: Prerequisites & Preparation:** Ensure system compatibility, tools, and dedicated ext4 filesystem.
* **Step 1: Unpack Bundle:** Extract the installation package.
* **Step 2: Review Bundle Config:** Check `install-app.conf` in the bundle.
* **Step 3: Run Installation:** Execute `deploy_orchestrator.sh --install`.
* **Step 4: Configure Instance:** Edit the live system's instance config (e.g., `AAA.conf`).
* **Step 5: Restart Instance:** Apply instance config changes.
* **Step 6: Verify Services:** Check `bitmover` and `exportcliv2` instance status.
* **Step 7: Understand Paths:** Learn key directory locations.
* **Step 8: Check Logs:** View service and application logs.
* **Step 9: Prepare Bundle Patch:** Use `install_patch.sh` to update the bundle.
* **Step 10: Deploy Patched Bundle:** Use `deploy_orchestrator.sh --update`.
* **Step 11: Update Credentials:** Modify `common.auth.conf` if needed.

---

**Required Privileges & User:**
All installation, patching, and service management commands in this guide **must be executed as the `root` user.**

* Log in directly as `root`, or from a non-root user with sudo privileges, switch to a root shell:
  ```bash
  sudo su -
  ```
* Once you are `root`, you can run the script commands directly (e.g., `./deploy_orchestrator.sh --install`).

---

**Step 0: Prerequisites and System Preparation**
*(Ensure system compatibility and required tools are ready.)*

1. **System Compatibility:**
    * This suite is designed for Oracle Linux 9 or compatible RHEL 9 derivatives (e.g., AlmaLinux 9, Rocky Linux 9).

2. **System Updates & Repository Access:**
    * Ensure your system is registered with appropriate subscriptions (if applicable, e.g., for RHEL) and can access
      package repositories.
    * It's recommended to have an up-to-date system:
      ```bash
      dnf update -y
      ```

3. **Installation Package:**
    * Ensure you have the application suite package: `exportcliv2-suite-v1.0.0.tar.gz`.

4. **Prepare Dedicated ext4 Filesystem (Crucial Prerequisite):**
    * It is **essential** to create a dedicated **ext4** filesystem for the application's data. This filesystem **must
      be formatted as ext4 (not ext3 or other types)** and **must be mounted** at the `BASE_DIR_CONFIG` path (default:
      `/opt/bitmover`) **before you run the main installation script (Step 3)**. This step is crucial for performance
      and reliable disk space management. Refer to the full `USER_GUIDE.md` for detailed commands on how to prepare and
      mount this filesystem.

5. **Python 3 Environment:**
    * The Bitmover service's DataMover component requires Python 3 (typically Python 3.9.x on Oracle Linux 9) and its
      standard `venv` module.
    * As `root`, verify Python 3 and `venv` module availability:
      ```bash
      python3 --version
      python3 -m venv --help
      ```
    * If Python 3 is missing or `venv` is unavailable, install it as `root`:
      ```bash
      dnf install python3 -y
      ```

---

**Step 1: Prepare the Installation Package**
*(Unpack the suite to access installer scripts.)*

1. Copy `exportcliv2-suite-v1.0.0.tar.gz` to your server (e.g., into `/root/`).
2. Log in as `root` (if not already) and navigate to where you placed the package.
3. Extract the archive:
   ```bash
   tar vxf exportcliv2-suite-v1.0.0.tar.gz
   ```
   This creates a directory like `exportcliv2-suite-v1.0.0/`.
4. Navigate into the extracted directory:
   ```bash
   cd exportcliv2-suite-v1.0.0/
   ```
   > **Important:** All subsequent `deploy_orchestrator.sh` and `install_patch.sh` commands in this guide must be run
   from within this extracted bundle directory.

---

**Step 2: Review Installer Configuration (`install-app.conf`)**
*(Check the bundle's default settings before installation.)*

The main configuration file *for the installer scripts within the bundle* is located at
`exportcliv2-deploy/install-app.conf`. This file contains defaults that will be used during the installation process. *
*Ensure the `BASE_DIR_CONFIG` value matches the mount point of your prepared ext4 filesystem.**

1. **View the Bundle's Installer Configuration:**
   ```bash
   cat exportcliv2-deploy/install-app.conf
   ```
   ### Key settings you will see (values are defaults for v1.0.0):
   ```ini
   # install-app.conf (This file is in your bundle, NOT on the live system yet)
   DEFAULT_INSTANCES_CONFIG="AAA"
   VERSIONED_APP_BINARY_FILENAME="exportcliv2-.4.0-B1771-24.11.15" # Actual binary filename in bundle
   VERSIONED_DATAMOVER_WHEEL_FILENAME="datamover-1.0.0-py3-none-any.whl" # Actual wheel filename in bundle
   REMOTE_HOST_URL_CONFIG="http://192.168.0.180:8989/pcap" # Default production endpoint
   EXPORT_TIMEOUT_CONFIG="15"
   USER_CONFIG="exportcliv2_user"
   GROUP_CONFIG="exportcliv2_group" # Default service group
   BASE_DIR_CONFIG="/opt/bitmover"   # Default base installation directory - MUST be your ext4 mount point
   WHEELHOUSE_SUBDIR="wheelhouse"
   LOG_DIR_CONFIG="/var/log/exportcliv2/"
   ```
   > **Note on Default Settings:** The `BASE_DIR_CONFIG` and `REMOTE_HOST_URL_CONFIG` are key defaults. If you need to
   use different values for a specific installation *before the very first install*, you can edit this
   `exportcliv2-deploy/install-app.conf` file within the extracted bundle prior to running
   `deploy_orchestrator.sh --install`.

   > **Note on Quotes:** In `.ini` style files, quotes around values are generally optional unless the value contains
   spaces or special characters.

2. **Edit (Optional, Before First Install):**
   If you need to change settings like `BASE_DIR_CONFIG` *before the very first installation*, edit the file within the
   extracted bundle:
   ```bash
   vi exportcliv2-deploy/install-app.conf
   ```

---

**Step 3: Run the Installation**
*(Execute the main deployment script to install base components and default instances.)*

**Prerequisite Check:** Before running this step, **double-check that your dedicated ext4 filesystem is prepared and
mounted at the `BASE_DIR_CONFIG` path** (default: `/opt/bitmover`).

1. From within the `exportcliv2-suite-v1.0.0/` directory, execute:
   ```bash
   ./deploy_orchestrator.sh --install
   ```
2. The script will list the instances to be configured and ask for confirmation. Type `y` and press Enter.
3. Upon successful completion, you will see:
   ```
   # ... (detailed installation log output) ...
   YYYY-MM-DDTHH:MM:SSZ [INFO] ▶ Orchestrator finished successfully.
   ```

---

**Step 4: Post-Installation Configuration (Instance Specific)**
*(Configure the live system's settings for each `exportcliv2` instance, e.g., "AAA".)*

You **must** edit the system configuration file for each `exportcliv2` instance to define its data source target. These
files are located in `/etc/exportcliv2/`.

1. **Edit the Instance Environment Configuration File:**
   For instance "AAA", edit:
   ```bash
   vi /etc/exportcliv2/AAA.conf
   ```
2. **Update Instance-Specific Settings:**
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
3. Save the changes and exit the editor.
4. **Review Application-Specific Configuration (Optional):**
   Review and edit `/etc/exportcliv2/AAA_app.conf` if needed. By default, it may contain:
   ```ini
   mining_delta_sec=120
   ```

---

**Step 5: Restart the `exportcliv2` Instance "AAA"**
*(Apply the instance configuration changes.)*

For the changes in `/etc/exportcliv2/AAA.conf` to take effect, restart the instance:

```bash
exportcli-manage -i AAA --restart
```

> **Note:** `exportcli-manage` is a user-friendly wrapper script installed by the suite, typically at
`/usr/local/bin/exportcli-manage`. It uses `systemctl` to manage the `bitmover.service` and
`exportcliv2@<INSTANCE_NAME>.service` units.

---

**Step 6: Verify Services are Running**
*(Check that both the Bitmover service and your `exportcliv2` instance are active.)*

1. **Check the Bitmover service status:**
   ```bash
   exportcli-manage --status
   ```
   Look for `Active: active (running)` for `bitmover.service`.

2. **Check the `exportcliv2` instance "AAA" status:**
   ```bash
   exportcli-manage -i AAA --status
   ```
   Look for `Active: active (running)` for `exportcliv2@AAA.service`.

---

**Step 7: Understanding Key Directories and Files**
*(Learn where important application files and data are located on the system.)*

Key paths are recorded in `/etc/default/exportcliv2_base_vars`. The default base application directory is
`/opt/bitmover/`, which **must be your dedicated ext4 mount point**.

* **Base Application Directory:** (e.g., `/opt/bitmover/`). Check `BASE_DIR` in `/etc/default/exportcliv2_base_vars`.
    * `bin/`: Executables (e.g., `exportcliv2-.4.0-B1771-24.11.15`), the `exportcliv2` symlink, helper scripts.
    * `csv/`: Metadata (`AAA.csv`), restart triggers.
    * `datamover_venv/`: Python environment for Bitmover.
    * `source/`, `worker/`, `uploaded/`, `dead_letter/`: Bitmover working directories.
* **System Configuration Directory:** `/etc/exportcliv2/` (Check `ETC_DIR` in `/etc/default/exportcliv2_base_vars`).
    * Instance configs: `AAA.conf`, `AAA_app.conf`.
    * Common configs: `common.auth.conf`, `config.ini`.
* **Base Log Directory:** `/var/log/exportcliv2/` (Check `BITMOVER_LOG_DIR`'s parent in
  `/etc/default/exportcliv2_base_vars`).
    * `bitmover/`: `app.log.jsonl`, `audit.log.jsonl`.
    * `AAA/`: Instance file logs (e.g., `exportcliv2_<DATE>.log`). `exportcliv2` instances also log to the system
      journal.

---

**Step 8: Checking Logs**
*(View logs for troubleshooting or monitoring.)*

Use `exportcli-manage` or view files directly.

* **Follow Bitmover service main logs:**
  ```bash
  exportcli-manage --logs-follow
  ```
* **Follow `exportcliv2` instance "AAA" journald logs:**
  ```bash
  exportcli-manage -i AAA --logs-follow
  ```
* **Example of viewing a file-based log directly:**
  ```bash
  tail -f /var/log/exportcliv2/bitmover/audit.log.jsonl
  ```

---

**Step 9: Preparing the Installation Bundle with a Patch**
*(Update your local installation bundle with a new binary or wheel before deploying it.)*

1. **Navigate to your Installation Package Directory:**
   This is the directory you extracted in Step 1 (e.g., `/root/exportcliv2-suite-v1.0.0/`), which contains
   `install_patch.sh`.
   ```bash
   cd /root/exportcliv2-suite-v1.0.0/ # Adjust to your actual path
   ```

2. **Run `install_patch.sh` with an *absolute path* to the new component:**
    * **To use a different binary already present *within this bundle's `exportcliv2-deploy/` directory* (e.g., an
      included emulator like `exportcliv8`):**
      ```bash
      # Example: In /root/exportcliv2-suite-v1.0.0/
      ./install_patch.sh --new-binary "$(pwd)/exportcliv2-deploy/exportcliv8"
      ```

    * **To apply an *externally provided* new binary (a patch file not in this bundle):**
      Suppose the new binary patch is located at `/tmp/exportcliv2-patch-vNEW`.
      ```bash
      # Example: In /root/exportcliv2-suite-v1.0.0/
      ./install_patch.sh --new-binary /tmp/exportcliv2-patch-vNEW
      ```

    * **To apply an *externally provided* new DataMover wheel:**
      Suppose the new wheel is at `/tmp/datamover-patch-vNEW.whl`.
      ```bash
      # Example: In /root/exportcliv2-suite-v1.0.0/
      ./install_patch.sh --new-wheel /tmp/datamover-patch-vNEW.whl
      ```
   The `install_patch.sh` script ensures the specified component is present in this bundle's `./exportcliv2-deploy/`
   directory (copying it from the provided path if it's different or external) and updates the
   `VERSIONED_APP_BINARY_FILENAME` or `VERSIONED_DATAMOVER_WHEEL_FILENAME` in `./exportcliv2-deploy/install-app.conf`.

---

**Step 10: Deploying a Prepared/Patched Bundle**
*(Apply the changes from your updated local bundle to the live system.)*

1. **Ensure you are still in your Installation Package Directory** (e.g., `/root/exportcliv2-suite-v1.0.0/`).

2. **Run the Orchestrator in Update Mode:**
   ```bash
   ./deploy_orchestrator.sh --update
   ```
   Confirm when prompted. This command applies the components specified in the (now patched) bundle's `install-app.conf`
   to your system.

3. **Restart Affected Services:**
   The `deploy_orchestrator.sh --update` script will provide guidance.
    * **If `exportcliv2` binary changed:** Restart all `exportcliv2` instances (e.g.,
      `exportcli-manage -i AAA --restart`).
    * **If DataMover wheel changed:** Restart the Bitmover service (`exportcli-manage --restart`).

4. **Verify Operation:**
   Check status and logs. Verify the active binary symlink (replace `/opt/bitmover` with your `BASE_DIR` from
   `/etc/default/exportcliv2_base_vars` if it was changed post-install):
   ```bash
   ls -l /opt/bitmover/bin/exportcliv2
   ```

> **Note on SELinux/AppArmor:** If using non-standard paths for `BASE_DIR_CONFIG` (i.e., other than the default
`/opt/bitmover/` used during the initial installation), security contexts might need adjustment (e.g.,
`semanage fcontext`, `restorecon`). The default path is generally chosen to work with standard system policies.

---

**Step 11: Updating Authentication Credentials**
*(Modify credentials if required for `exportcliv2` instances.)*

1. Edit the common authentication file: `/etc/exportcliv2/common.auth.conf`:
   ```bash
   vi /etc/exportcliv2/common.auth.conf
   ```
2. Update `EXPORT_AUTH_TOKEN_U` (username) and `EXPORT_AUTH_TOKEN_P` (password).
3. Save and exit.
4. **Restart all `exportcliv2` instances:**
   ```bash
   exportcli-manage -i AAA --restart # And for any other instances.
   ```

---

**Further Information**

For more detailed information, refer to the full `USER_GUIDE.md` document included in this bundle or examine the scripts
and configuration templates within the `exportcliv2-deploy` directory.
