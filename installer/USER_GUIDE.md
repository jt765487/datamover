## Application Suite Deployment and Management Guide

**Document Version:** 2.3 (reflecting updates to align with script changes)
**Application Suite Orchestrator Version:** v2.4.8
**Patch Script Version:** v1.0.0
**(Individual component script versions: Base Installer v1.3.2, Instance Configurator v4.1.0, Service Manager v1.3.2)**

This guide provides comprehensive instructions for deploying, configuring, updating, and managing the "exportcliv2" application suite. This suite includes the main `exportcliv2` data export client and the Bitmover service (a Python-based service responsible for PCAP uploads).

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
    *   A.4 `/etc/exportcliv2/config.ini` (Bitmover Service Configuration)
    *   A.5 Systemd Unit Templates Overview
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

The `exportcliv2` application suite is designed for robust data processing and management. It consists of:

*   **`exportcliv2` client:** A high-performance data processing application, typically run as multiple instances, each configured for a specific data source or task.
*   **Bitmover service:** A Python-based service responsible for managing and uploading PCAP files generated or processed by the system.

This guide details the use of a set of deployment and management scripts to install, configure, update, and operate this suite on an Oracle Linux 9 system (or compatible).

---

## 2. Deployment Package Structure
*(Know what's in the bundle you receive.)*

The deployment process starts with the `exportcliv2-suite-vX.Y.Z.tar.gz` package. After extraction, it creates a top-level directory, for example, `exportcliv2-suite-v0.1.2/`.

> **Important:** All operations involving `deploy_orchestrator.sh` and `install_patch.sh` must be initiated from within this extracted bundle directory.

The structure of the extracted package is typically as follows:

```
exportcliv2-suite-vX.Y.Z/
├── deploy_orchestrator.sh       # Main script for installation or updates (e.g., v2.4.8)
├── install_patch.sh             # Script to prepare this bundle with patches (e.g., v1.0.0)
├── QUICK_START_GUIDE.md         # This quick start guide
├── USER_GUIDE.md                # (If present) This more comprehensive user guide
│
└── exportcliv2-deploy/          # Deployment subdirectory
    ├── install_base_exportcliv2.sh # Core installer for base system components
    ├── configure_instance.sh    # Script to set up individual exportcliv2 instances
    ├── manage_services.sh       # Core script for service management (used by exportcli-manage)
    │
    ├── install-app.conf         # Primary configuration for the installer scripts in this bundle
    │
    ├── exportcliv2-vA.B.C       # The versioned exportcliv2 binary itself
    ├── datamover-vX.Y.Z-...whl  # The versioned Python wheel for the Bitmover service
    │
    ├── config_files/            # Directory for config file templates used during installation
    │   ├── common.auth.conf     # Template/default for shared authentication tokens
    │   ├── config.ini.template  # Template for Bitmover's INI configuration
    │   └── run_exportcliv2_instance.sh.template # Template for the instance wrapper script
    │
    ├── systemd_units/           # Directory for systemd unit file templates
    │   ├── bitmover.service.template
    │   ├── exportcliv2@.service.template
    │   ├── exportcliv2-restart@.path.template
    │   └── exportcliv2-restart@.service.template
    │
    └── wheelhouse/              # (Optional) Offline Python dependency wheels
        └── ...
```

---

## 3. Step 0: Prerequisites and System Preparation
*(Ensure system compatibility and required tools are ready.)*

1.  **System Compatibility:**
    *   This suite is designed for Oracle Linux 9 or compatible RHEL 9 derivatives (e.g., AlmaLinux 9, Rocky Linux 9).

2.  **System Updates & Repository Access:**
    *   Ensure your system is registered with appropriate subscriptions (if applicable, e.g., for RHEL) and can access package repositories.
    *   It's recommended to have an up-to-date system:
        ```bash
        dnf update -y
        ```

3.  **Installation Package:**
    *   Ensure you have the application suite package: `exportcliv2-suite-vX.Y.Z.tar.gz`.
        *(Replace `vX.Y.Z` with the actual version you are installing, e.g., `v0.1.2`)*.

4.  **Python 3 Environment:**
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

1.  Copy `exportcliv2-suite-vX.Y.Z.tar.gz` to your server (e.g., into `/root/`).
2.  Log in as `root` (if not already) and navigate to where you placed the package.
3.  Extract the archive:
    ```bash
    tar vxf exportcliv2-suite-vX.Y.Z.tar.gz
    ```
    This creates a directory like `exportcliv2-suite-vX.Y.Z/`.
4.  Navigate into the extracted directory:
    ```bash
    cd exportcliv2-suite-vX.Y.Z/
    ```

---

## 5. Step 2: Review Bundle Installer Configuration (`install-app.conf`)
*(Check the bundle's default settings before installation.)*

The main configuration file *for the installer scripts within this specific bundle* is located at `exportcliv2-deploy/install-app.conf`.

1.  **View the Bundle's Installer Configuration:**
    ```bash
    cat exportcliv2-deploy/install-app.conf
    ```
    ### Key settings you might see (example values):
    ```ini
    # exportcliv2-deploy/install-app.conf (in your bundle)
    DEFAULT_INSTANCES_CONFIG="AAA" # Default exportcliv2 instance(s) to set up
    VERSIONED_APP_BINARY_FILENAME="exportcliv2-0.4.0-B1771-24.11.15" # Initial binary
    VERSIONED_DATAMOVER_WHEEL_FILENAME="datamover-0.1.2-py3-none-any.whl"
    REMOTE_HOST_URL_CONFIG="http://192.168.0.180:8989/pcap"
    EXPORT_TIMEOUT_CONFIG="15"
    USER_CONFIG="exportcliv2_user"
    GROUP_CONFIG="datapipeline_group"
    BASE_DIR_CONFIG="/var/tmp/testme" # For testing; consider /opt/exportcliv2 for production
    WHEELHOUSE_SUBDIR="wheelhouse"
    LOG_DIR_CONFIG="/var/log/exportcliv2/" # Base for application logs
    # These might be used by install_base_exportcliv2.sh to populate /etc/default/exportcliv2_base_vars
    # DEFAULT_INSTANCE_STARTTIME_OFFSET="3 minutes ago"
    # DEFAULT_INSTANCE_ENDTIME_VALUE="-1"
    # DEFAULT_INSTANCE_APP_CONFIG_CONTENT="mining_delta_sec=120"
    ```
    > **Note on Quotes:** In `.ini` style files, quotes around values are generally optional unless the value contains spaces (e.g., `DEFAULT_INSTANCES_CONFIG="AAA BBB"` would require quotes) or special characters.

    > **Note on Production Paths:** For production deployments, consider changing `BASE_DIR_CONFIG` in this bundle file to a path like `/opt/exportcliv2` *before* running the first installation.

2.  **Edit (Optional, Before First Install):**
    If you need to change settings like `DEFAULT_INSTANCES_CONFIG` or `BASE_DIR_CONFIG` *before the very first installation*, edit the file:
    ```bash
    vi exportcliv2-deploy/install-app.conf
    ```

---

## 6. Step 3: Run the Initial Installation (`deploy_orchestrator.sh --install`)
*(Execute the main deployment script to install base components and default instances.)*

1.  From within the `exportcliv2-suite-vX.Y.Z/` directory, execute:
    ```bash
    ./deploy_orchestrator.sh --install
    ```
2.  The script will list the instances to be configured (from `DEFAULT_INSTANCES_CONFIG`) and ask for confirmation. Type `y` and press Enter.
3.  Upon successful completion, you will see a message like:
    ```
    # ... (detailed installation log output) ...
    YYYY-MM-DDTHH:MM:SSZ [INFO] ▶ Orchestrator finished successfully.
    ```

---

## 7. Step 4: Post-Installation Instance Configuration (Live System)
*(Configure the live system's settings for each `exportcliv2` instance, e.g., "AAA".)*

After the base installation, you **must** edit the system configuration file for each `exportcliv2` instance to define its specific data source target. These files are located on the live system in `/etc/exportcliv2/`.

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
    EXPORT_ENDTIME="-1"
    # ---- EDIT THESE TWO LINES FOR YOUR ENVIRONMENT ----
    EXPORT_IP="<YOUR_DATA_SOURCE_IP>" # e.g., "10.0.0.1"
    EXPORT_PORTID="<YOUR_PORT_ID>"    # e.g., "1"
    # -------------------------------------------------
    EXPORT_APP_CONFIG_FILE_PATH="/etc/exportcliv2/AAA_app.conf"
    ```
3.  Save the changes and exit the editor.
4.  **Review Application-Specific Configuration (Optional):**
    Review and edit `/etc/exportcliv2/AAA_app.conf` if needed. By default, it may contain:
    ```ini
    mining_delta_sec=120
    ```

---

## 8. Step 5: Restart `exportcliv2` Instance After Configuration
*(Apply the instance configuration changes.)*

For the changes in `/etc/exportcliv2/AAA.conf` to take effect, restart the instance:
```bash
exportcli-manage -i AAA --restart
```
> **Note:** `exportcli-manage` is a user-friendly wrapper script installed by the suite, typically at `/usr/local/bin/exportcli-manage`. It uses `systemctl` to manage the `bitmover.service` and `exportcliv2@<INSTANCE_NAME>.service` units.

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

---

## 10. Step 7: Understanding Key System Directories and Files
*(Learn where important application files and data are located on the system.)*

Key paths for the installed application are determined during installation and recorded in `/etc/default/exportcliv2_base_vars`.
*   **Base Application Directory:** (e.g., `/var/tmp/testme/`). Check `BASE_DIR` in `/etc/default/exportcliv2_base_vars`.
    *   `bin/`: Contains executables (e.g., `exportcliv2-0.4.0-...`), the `exportcliv2` symlink pointing to the active binary, helper scripts like `run_exportcliv2_instance.sh` and `manage_services.sh`.
    *   `csv/`: For CSV metadata files (e.g., `AAA.csv`) and `.restart` trigger files.
    *   `datamover_venv/`: Python virtual environment for the Bitmover service.
    *   `source/`, `worker/`, `uploaded/`, `dead_letter/`: Working directories for the Bitmover service.
*   **System Configuration Directory:** `/etc/exportcliv2/` (Check `ETC_DIR` in `/etc/default/exportcliv2_base_vars`).
    *   Instance configurations: e.g., `AAA.conf`, `AAA_app.conf`.
    *   Common configurations: `common.auth.conf`, `config.ini` (for the Bitmover service).
*   **Base Log Directory:** `/var/log/exportcliv2/` (Check `BITMOVER_LOG_DIR`'s parent or instance log parent in `/etc/default/exportcliv2_base_vars`).
    *   `bitmover/`: Contains `app.log.jsonl` (main Bitmover log) and `audit.log.jsonl` (upload audit log).
    *   `AAA/` (or other instance names): Contains instance-specific file logs (e.g., `exportcliv2_<DATE>.log`). `exportcliv2` instances also log to the system journal.

---

## 11. Step 8: Checking Logs
*(View logs for troubleshooting or monitoring.)*

Use `exportcli-manage` or view files directly.
*   **Follow Bitmover service main logs:**
    ```bash
    exportcli-manage --logs-follow
    ```
*   **Follow `exportcliv2` instance "AAA" journald logs:**
    ```bash
    exportcli-manage -i AAA --logs-follow
    ```
*   **Example of viewing a file-based log directly:**
    ```bash
    tail -f /var/log/exportcliv2/bitmover/audit.log.jsonl
    ```

---

## 12. Step 9: Preparing the Installation Bundle with a Patch (`install_patch.sh`)
*(Update your local installation bundle with a new binary or wheel before deploying it to the system.)*

1.  **Navigate to your Installation Package Directory:**
    This is the directory you extracted in Step 1 (e.g., `/root/exportcliv2-suite-vX.Y.Z/`), which contains `install_patch.sh`.
    ```bash
    cd /root/exportcliv2-suite-vX.Y.Z/ # Adjust to your actual path
    ```

2.  **Run `install_patch.sh` with an *absolute path* to the new component:**
    *   **To prepare the bundle to use a different binary already present *within this bundle's staging area*** (e.g., an emulator like `exportcliv8` located in `./exportcliv2-deploy/`):
        Ensure the desired binary (e.g., `exportcliv8`) exists in `./exportcliv2-deploy/`.
        ```bash
        # Example: In /root/exportcliv2-suite-vX.Y.Z/
        ./install_patch.sh --new-binary "$(pwd)/exportcliv2-deploy/exportcliv8"
        ```
        This updates the bundle's `install-app.conf` to reference `exportcliv8`.

    *   **To prepare the bundle with an *externally provided* new binary** (a patch file not originally in this bundle):
        Suppose the new binary patch is located at `/tmp/exportcliv2-patch-vNEW`.
        ```bash
        # Example: In /root/exportcliv2-suite-vX.Y.Z/
        ./install_patch.sh --new-binary /tmp/exportcliv2-patch-vNEW
        ```
        This copies `exportcliv2-patch-vNEW` into this bundle's `./exportcliv2-deploy/` directory and updates the `install-app.conf`.

    *   **To prepare the bundle with an *externally provided* new DataMover wheel:**
        Suppose the new wheel is at `/tmp/datamover-patch-vNEW.whl`.
        ```bash
        # Example: In /root/exportcliv2-suite-vX.Y.Z/
        ./install_patch.sh --new-wheel /tmp/datamover-patch-vNEW.whl
        ```
    After `install_patch.sh` completes successfully, it will confirm the bundle is prepared.

---

## 13. Step 10: Deploying a Prepared/Patched Bundle (`deploy_orchestrator.sh --update`)
*(Apply the changes from your updated local bundle to the live system.)*

1.  **Ensure you are still in your Installation Package Directory** (e.g., `/root/exportcliv2-suite-vX.Y.Z/`).

2.  **Run the Orchestrator in Update Mode:**
    ```bash
    ./deploy_orchestrator.sh --update
    ```
    Confirm when prompted. This command applies the components specified in the (now patched) bundle's `install-app.conf` to your system.

3.  **Restart Affected Services:**
    The `deploy_orchestrator.sh --update` script will provide guidance.
    *   **If `exportcliv2` binary changed:** Restart all affected `exportcliv2` instances (e.g., `exportcli-manage -i AAA --restart`).
    *   **If DataMover wheel changed:** Restart the Bitmover service (`exportcli-manage --restart`).

4.  **Verify Operation:**
    Check status and logs. Verify the active binary symlink (replace `/var/tmp/testme` with your `BASE_DIR` from `base_vars`):
    ```bash
    ls -l /var/tmp/testme/bin/exportcliv2
    ```

> **Note on SELinux/AppArmor:** If using non-standard paths for `BASE_DIR_CONFIG` during installation, security contexts might need adjustment (e.g., `semanage fcontext`, `restorecon`). Default paths are generally chosen to work with standard system policies.

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
    *   Check application file logs in `/var/log/exportcliv2/`.
3.  **Verify Configuration:**
    *   System-wide defaults: `/etc/default/exportcliv2_base_vars`.
    *   Bitmover config: `/etc/exportcliv2/config.ini`.
    *   Instance environment: `/etc/exportcliv2/<INSTANCE_NAME>.conf`.
    *   Instance application config: `/etc/exportcliv2/<INSTANCE_NAME>_app.conf`.
    *   Shared authentication: `/etc/exportcliv2/common.auth.conf`.
4.  **Permissions:** Ensure file and directory permissions and ownerships are correct, especially in `/etc/exportcliv2/`, `/var/log/exportcliv2/`, and your base application directory (e.g. `/var/tmp/testme/`).
5.  **Path Issues:** Ensure `exportcli-manage` is in the system `PATH` (`ls -l /usr/local/bin/exportcli-manage`).

---

## 16. Appendix A: Key Configuration and Template File Details
*(Details about important configuration files and templates used by the suite.)*

The installation process uses several configuration files and templates. The `install_base_exportcliv2.sh` script processes templates by replacing placeholders (like `{{APP_NAME}}`, `{{APP_USER}}`, `{{ETC_DIR}}`, etc.) with actual values derived during installation (many from `/etc/default/exportcliv2_base_vars` or `install-app.conf`).

### A.1 `install-app.conf` (Bundle's Primary Input Configuration)
*(Located in `exportcliv2-suite-vX.Y.Z/exportcliv2-deploy/`. This file drives the `deploy_orchestrator.sh` and subsequently the `install_base_exportcliv2.sh` scripts for initial setup or updates.)*

```ini
# install-app.conf (Example from your testing)

# Space-separated list of instance names.
# MANDATORY for default installs via 'deploy_orchestrator.sh --install'.
DEFAULT_INSTANCES_CONFIG="AAA"

# The filename of the VERSIONED main application binary within this bundle.
# MANDATORY. Must exist in ./exportcliv2-deploy/
VERSIONED_APP_BINARY_FILENAME="exportcliv2-v0.4.0-B1771-24.11.15"

# The filename of the VERSIONED DataMover Python wheel within this bundle.
# MANDATORY. Must exist in ./exportcliv2-deploy/
VERSIONED_DATAMOVER_WHEEL_FILENAME="datamover-0.1.2-py3-none-any.whl"

# The remote URL for the Bitmover component to upload data to.
# MANDATORY. Must start with http:// or https://
REMOTE_HOST_URL_CONFIG="http://192.168.0.180:8989/pcap"

# Timeout (-t) in seconds for exportcliv2 instances.
# MANDATORY. This value is stored in /etc/default/exportcliv2_base_vars
# for configure_instance.sh to use as a default.
EXPORT_TIMEOUT_CONFIG="15"

# --- Optional Overrides for System Setup ---
# The user name for the service. Default used by installer if not set: "exportcliv2_user"
USER_CONFIG="exportcliv2_user"

# The group name for the service. Default used by installer if not set: "exportcliv2_group"
GROUP_CONFIG="datapipeline_group"

# BASE_DIR_CONFIG: Overrides the default base installation directory.
# Installer default: "/opt/exportcliv2"
BASE_DIR_CONFIG="/var/tmp/testme"

# WHEELHOUSE_SUBDIR: Subdirectory within the bundle containing dependency wheels
# for offline Python package installation. Default: "wheelhouse"
WHEELHOUSE_SUBDIR="wheelhouse"

# LOG_DIR_CONFIG: Base directory for application logs.
# Installer default: "/var/log/exportcliv2/"
LOG_DIR_CONFIG="/var/log/exportcliv2/"

```
**Key Points:**
*   `DEFAULT_INSTANCES_CONFIG` drives which instances are set up by `deploy_orchestrator.sh --install` if not overridden.
*   `VERSIONED_APP_BINARY_FILENAME` and `VERSIONED_DATAMOVER_WHEEL_FILENAME` must match files present in the `exportcliv2-deploy/` directory of the bundle.
*   `REMOTE_HOST_URL_CONFIG` and `EXPORT_TIMEOUT_CONFIG` are critical operational settings.
*   Other `*_CONFIG` variables provide system-level defaults for the installation.

---

### A.2 `run_exportcliv2_instance.sh.template` (Instance Wrapper Script)
*(Template located in `exportcliv2-deploy/config_files/`. `install_base_exportcliv2.sh` processes this template and installs it as `run_exportcliv2_instance.sh` in the application's `bin` directory, e.g., `/var/tmp/testme/bin/run_exportcliv2_instance.sh`.)*

This script is executed by the `exportcliv2@.service` systemd unit for each instance.
```bash
#!/bin/bash
# Shellcheck directives from your template included
set -euo pipefail

# Wrapper script for {{APP_NAME}} instance: $1 (passed by systemd as %i)
# Executed as {{APP_USER}}

# --- Instance Name from Argument ---
if [[ -z "$1" ]]; then
  echo "Error: Instance name argument (%i) not provided to wrapper script." >&2
  exit 78 # EX_CONFIG
fi
INSTANCE_NAME="$1"

# --- Log script start (optional but helpful) ---
echo "Wrapper script for {{APP_NAME}}@${INSTANCE_NAME} starting..."

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
  # "EXPORT_ENDTIME" is also used but typically defaults to -1 if not explicitly set
)
for var_name in "${required_vars[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then # Indirect expansion
    echo "Error: {{APP_NAME}}@${INSTANCE_NAME}: Required environment variable '${var_name}' is not set. Check {{ETC_DIR}}/common.auth.conf and {{ETC_DIR}}/${INSTANCE_NAME}.conf." >&2
    exit 78 # EX_CONFIG
  fi
done

# --- Calculate dynamic start time ---
# Uses EXPORT_STARTTIME_OFFSET_SPEC from the environment
calculated_start_time=$(date +%s%3N --date="${EXPORT_STARTTIME_OFFSET_SPEC}" 2>/dev/null)

if [[ -z "$calculated_start_time" ]]; then
  echo "Error: {{APP_NAME}}@${INSTANCE_NAME}: Could not calculate start_time using EXPORT_STARTTIME_OFFSET_SPEC ('${EXPORT_STARTTIME_OFFSET_SPEC}'). Check this variable in {{ETC_DIR}}/${INSTANCE_NAME}.conf and ensure 'date' command works." >&2
  exit 78 # EX_CONFIG
fi

# --- Check if the app-specific config file actually exists ---
if [[ ! -f "${EXPORT_APP_CONFIG_FILE_PATH}" ]]; then
    echo "Error: {{APP_NAME}}@${INSTANCE_NAME}: Application specific config file specified by EXPORT_APP_CONFIG_FILE_PATH ('${EXPORT_APP_CONFIG_FILE_PATH}') does not exist." >&2
    exit 78 # EX_CONFIG
fi

# --- Construct paths for arguments ---
# {{CSV_DATA_DIR}} and {{SOURCE_DATA_DIR}} are replaced with actual paths during template processing.
CSV_INSTANCE_DIR="{{CSV_DATA_DIR}}"
SOURCE_INSTANCE_PATH="{{SOURCE_DATA_DIR}}/${EXPORT_SOURCE}" # EXPORT_SOURCE usually matches INSTANCE_NAME

# --- Log execution details (optional, can be verbose) ---
# This section is commented out in the actual template for brevity in logs,
# but shown here for understanding.
# printf "Executing for %s: %s \\\n" "${INSTANCE_NAME}" "{{SYMLINK_EXECUTABLE_PATH}}"
# printf "  -c %s \\\n" "${EXPORT_APP_CONFIG_FILE_PATH}"
# ... and so on for other arguments, masking credentials ...

# --- Execute the main application binary ---
# {{SYMLINK_EXECUTABLE_PATH}} is replaced with the actual path to the active binary symlink.
# EXPORT_ENDTIME is used directly if set in the environment, otherwise defaults to -1.
exec "{{SYMLINK_EXECUTABLE_PATH}}" \
  -c "${EXPORT_APP_CONFIG_FILE_PATH}" \
  -u "${EXPORT_AUTH_TOKEN_U}" \
  -p "${EXPORT_AUTH_TOKEN_P}" \
  -C \
  -t "${EXPORT_TIMEOUT}" \
  -H "${CSV_INSTANCE_DIR}" \
  -o "${SOURCE_INSTANCE_PATH}" \
  "${EXPORT_IP}" \
  "${EXPORT_PORTID}" \
  "${calculated_start_time}" \
  "${EXPORT_ENDTIME:--1}" # Use EXPORT_ENDTIME if set, otherwise default to -1

exit $? # Should not be reached if exec succeeds
```
**Key Points:**
*   Receives instance name (`%i`) from systemd.
*   Sources instance-specific environment variables from `/etc/exportcliv2/<INSTANCE_NAME>.conf` and shared credentials from `/etc/exportcliv2/common.auth.conf` (via `EnvironmentFile` in the systemd unit).
*   Dynamically calculates `start_time` based on `EXPORT_STARTTIME_OFFSET_SPEC`.
*   Constructs and `exec`s the command to run the actual `exportcliv2` binary.
*   Placeholders like `{{APP_NAME}}`, `{{ETC_DIR}}`, `{{CSV_DATA_DIR}}`, `{{SOURCE_DATA_DIR}}`, `{{SYMLINK_EXECUTABLE_PATH}}` are replaced by `install_base_exportcliv2.sh` during deployment.

---

### A.3 `/etc/exportcliv2/common.auth.conf` (Shared Authentication)
*(This file is deployed by `install_base_exportcliv2.sh` from the `config_files/common.auth.conf` template in the bundle. It is located on the live system at `/etc/exportcliv2/common.auth.conf` by default.)*

Used to store shared credentials sourced by `run_exportcliv2_instance.sh` for each instance.
```ini
# Common authentication tokens
# These values will be used by all exportcliv2 instances.
# Ensure this file has restricted permissions (e.g., 0640, root:your_app_group).
EXPORT_AUTH_TOKEN_U="<DEFAULT_SHARED_USER>"
EXPORT_AUTH_TOKEN_P="<DEFAULT_SHARED_PASSWORD_OR_TOKEN>"
```
**Key Points:**
*   Edit this file on the system to set actual credentials.
*   Permissions should be restrictive (e.g., `0640`, owner `root`, group `datapipeline_group`).

---

### A.4 `/etc/exportcliv2/config.ini` (Bitmover Service Configuration)
*(This file is deployed by `install_base_exportcliv2.sh` from the `config_files/config.ini.template` in the bundle. It is located on the live system at `/etc/exportcliv2/config.ini` by default.)*

This INI file configures the Bitmover service.
```ini
# Example content generated from config.ini.template
[main]
# Directories are typically populated by install_base_exportcliv2.sh
# based on BASE_DIR_CONFIG from install-app.conf
source_dir = {{SOURCE_DATA_DIR}}
csv_dir = {{CSV_DATA_DIR}}
worker_dir = {{WORKER_DATA_DIR}}
uploaded_dir = {{UPLOADED_DATA_DIR}}
dead_letter_dir = {{DEAD_LETTER_DATA_DIR}}
log_file_path = {{BITMOVER_LOG_DIR}}/app.log.jsonl
audit_log_path = {{BITMOVER_LOG_DIR}}/audit.log.jsonl

[uploader]
remote_host_url = {{REMOTE_HOST_URL}} # Populated from REMOTE_HOST_URL_CONFIG
# ... other uploader specific settings ...

[scanner]
# ... scanner specific settings ...
```
**Key Points:**
*   Placeholders like `{{SOURCE_DATA_DIR}}`, `{{REMOTE_HOST_URL}}`, `{{BITMOVER_LOG_DIR}}` are replaced by `install_base_exportcliv2.sh` with actual paths and values from `install-app.conf` and derived settings.

---

### A.5 Systemd Unit Templates Overview
*(Templates are located in `exportcliv2-deploy/systemd_units/`. `install_base_exportcliv2.sh` processes them and installs the resulting unit files into `/etc/systemd/system/`.)*

Placeholders like `{{APP_NAME}}`, `{{APP_USER}}`, `{{APP_GROUP}}`, `{{PYTHON_VENV_PATH}}`, `{{BITMOVER_CONFIG_FILE}}`, `{{ETC_DIR}}`, `{{CSV_DATA_DIR}}`, `{{INSTALLED_WRAPPER_SCRIPT_PATH}}` are replaced with actual values during template processing.

1.  **`bitmover.service.template`:**
    *   Manages the main Bitmover upload service.
    *   Runs as `{{APP_USER}}`:`{{APP_GROUP}}`.
    *   Executes `{{PYTHON_VENV_PATH}}/bin/bitmover --config {{BITMOVER_CONFIG_FILE}}`.
    *   Includes `ExecStartPre` checks for directory existence and writability.
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
    # ... other ExecStartPre checks from your template ...
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
    *   Uses `LogsDirectory={{APP_NAME}}/%i` (e.g., `/var/log/exportcliv2/AAA`) for systemd to manage a per-instance log/working directory.
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
    WorkingDirectory=/var/log/{{APP_NAME}}/%i
    ExecStartPre=-/usr/bin/rm -f {{CSV_DATA_DIR}}/%i.restart
    ExecStartPre=/usr/bin/test -d {{SOURCE_DATA_DIR}} -a -w {{SOURCE_DATA_DIR}}
    ExecStartPre=/usr/bin/test -d {{CSV_DATA_DIR}} -a -w {{CSV_DATA_DIR}}
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
    *   A path unit that monitors for the existence of a trigger file (e.g., `/var/tmp/testme/csv/AAA.restart`).
    *   If the file appears, it activates `exportcliv2-restart@%i.service`.
    ```systemd
    [Unit]
    Description=Path watcher to trigger restart for {{APP_NAME}} instance %I

    [Path]
    PathExists={{CSV_DATA_DIR}}/%i.restart
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
    ExecStartPost=-/usr/bin/rm -f {{CSV_DATA_DIR}}/%i.restart
    StandardOutput=journal
    StandardError=journal
    SyslogIdentifier={{APP_NAME}}-restart@%i
    ```
