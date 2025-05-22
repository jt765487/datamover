## Application Suite Deployment and Management Guide - Version 2.0

**Document Version:** 2.0
**Application Suite Version (Orchestrator):** v2.2.3 (as per last script version)

This guide provides comprehensive instructions for deploying, configuring, updating, and managing the "exportcliv2" application suite. This suite includes the main `exportcliv2` data processing application and the `bitmover` Python-based PCAP upload service.

**Table of Contents:**

1.  Introduction
2.  Prerequisites
3.  Deployment Package Structure
4.  Initial Environment Setup (Fresh Install)
    1.  Step 1: Prepare `install-app.conf`
    2.  Step 2: Run the Orchestrator Script for Installation
    3.  Understanding Orchestrator Actions During `--install`
5.  Post-Installation Configuration
    1.  Critical: `exportcliv2` Instance Configuration (`<INSTANCE_NAME>.conf`)
    2.  Application-Specific Configuration (`<INSTANCE_NAME>_app.conf`)
    3.  Shared Authentication (`common.auth.conf`)
    4.  `bitmover` Service Configuration (`config.ini`)
    5.  Restarting Services After Configuration Changes
6.  Updating Application Components
    1.  General Update Workflow
    2.  Understanding Orchestrator Actions During `--update`
7.  Managing Services (Everyday Activities)
    1.  Using `manage_services.sh`
    2.  Common Commands
8.  Troubleshooting
9.  Appendix A: Key Configuration and Template File Details
    1.  A.1 `install-app.conf` (Primary Input Configuration)
    2.  A.2 `run_exportcliv2_instance.sh.template` (Wrapper Script)
    3.  A.3 `common.auth.conf` (Shared Authentication)
    4.  A.4 `config.ini.template` (Bitmover Configuration)
    5.  A.5 Systemd Unit Templates Overview
        *   `bitmover.service.template`
        *   `exportcliv2@.service.template`
        *   `exportcliv2-restart@.path.template`
        *   `exportcliv2-restart@.service.template`
10. Appendix B: System Architecture Diagram (Conceptual)

---

### 1. Introduction

The `exportcliv2` application suite is designed for robust data processing and management. It consists of:
*   **`exportcliv2`**: A high-performance data processing application, typically run as multiple instances, each configured for a specific data source or task.
*   **`bitmover`**: A Python service responsible for uploading PCAP files generated or processed by the system.

This guide details the use of a set of deployment and management scripts to install, configure, update, and operate this suite on an Oracle Linux 9 system.

---

### 2. Prerequisites

*   **Operating System:** Oracle Linux 9 (or a compatible RHEL 9 derivative).
*   **User Privileges:** `sudo` or root access is required for all installation, update, and service management tasks.
*   **Required System Packages:**
    *   `python3` and `python3-venv` (for the `bitmover` service).
    *   Standard utilities: `date`, `chmod`, `dirname`, `basename`, `readlink`, `realpath`, `flock`, `getent`, `groupadd`, `useradd`, `install`, `sed`, `systemctl`, `find`, `id`, `chown`, `ln`, `pushd`, `popd`, `mkdir`, `printf`. These are generally present on a standard server installation. The orchestrator script performs a check for its core dependencies.
*   **Application Artifacts:** You must have the deployment package containing the versioned `exportcliv2` binary, the versioned `bitmover` Python wheel, the suite of scripts, and configuration templates.

---

### 3. Deployment Package Structure

The deployment process assumes an unpacked package directory with the following structure. The `deploy_orchestrator.sh` script (the main driver script) **must be run from the root of this directory.**

```
deployment_package_root/
├── deploy_orchestrator.sh                # Main script to drive installation or updates
├── install_base_exportcliv2.sh           # Core installer for base system
├── configure_instance.sh                 # Script to set up individual exportcliv2 instances
├── manage_services.sh                    # Script for everyday service management
|
├── install-app.conf                      # Primary configuration for the installer scripts
|
├── exportcliv2-vA.B.C                    # The versioned exportcliv2 binary itself
├── datamover-vX.Y.Z-py3-none-any.whl     # The versioned Python wheel for bitmover
|
├── config_files/                         # Directory for config file templates
│   ├── common.auth.conf                  # For shared authentication tokens (copied as-is)
│   ├── config.ini.template               # Template for bitmover's INI configuration
│   └── run_exportcliv2_instance.sh.template # Wrapper script template for exportcliv2
|
└── systemd_units/                        # Directory for systemd unit file templates
    ├── bitmover.service.template
    ├── exportcliv2@.service.template
    ├── exportcliv2-restart@.path.template
    └── exportcliv2-restart@.service.template
```

---

### 4. Initial Environment Setup (Fresh Install)

This procedure installs the entire application suite from scratch.

#### 4.1 Step 1: Prepare `install-app.conf`

Before running any scripts, you **must** configure `install-app.conf` located in the root of your deployment package. This file dictates crucial settings for the installation.

Open `install-app.conf` in a text editor and set the following **MANDATORY** variables:

*   `VERSIONED_APP_BINARY_FILENAME`: The exact filename of your `exportcliv2` binary (e.g., `"exportcliv2-v1.0.0"`). This file must be present in the deployment package root.
*   `VERSIONED_DATAMOVER_WHEEL_FILENAME`: The exact filename of your `bitmover` Python wheel (e.g., `"datamover-0.2.1-py3-none-any.whl"`). This file must be present in the deployment package root.
*   `REMOTE_HOST_URL_CONFIG`: The full URL where `bitmover` will upload PCAP files (e.g., `"http://data-ingest.example.com:8080/upload"`).
*   `EXPORT_TIMEOUT_CONFIG`: The default timeout in seconds that will be configured for new `exportcliv2` instances (e.g., `"15"`).

Additionally, review and optionally modify other settings in `install-app.conf` such as `USER_CONFIG` (application username), `GROUP_CONFIG` (application group name), and `BASE_DIR_CONFIG` (base installation directory). Detailed comments within the file explain each option. (See Appendix A.1 for an example).

#### 4.2 Step 2: Run the Orchestrator Script for Installation

Once `install-app.conf` is prepared:

1.  Navigate to the root of your deployment package directory in your terminal.
2.  Execute the `deploy_orchestrator.sh` script with the `--install` flag. You will need `sudo` privileges.

    *   **To install and configure default instances** (e.g., `AAA`, `BBB`, `CCC` as defined in the orchestrator script):
        ```bash
        sudo ./deploy_orchestrator.sh --install
        ```
    *   **To install and configure specific instances** (e.g., `site1`, `lab_test`):
        ```bash
        sudo ./deploy_orchestrator.sh --install -i site1,lab_test
        ```
    *   **To perform a dry run** (see what commands would be executed without making changes):
        ```bash
        sudo ./deploy_orchestrator.sh --install -i site1,lab_test -n
        ```
    *   **To force reconfiguration of instances** if their configuration files already exist (use with caution):
        ```bash
        sudo ./deploy_orchestrator.sh --install -i site1 --force-reconfigure
        ```

3.  The script will perform dependency checks, acquire an execution lock, and then ask for confirmation before proceeding (unless in dry-run mode). Type `y` and press Enter to continue.

#### 4.3 Understanding Orchestrator Actions During `--install`

When run with `--install`, the `deploy_orchestrator.sh` script performs the following sequence:

1.  **Initial Checks:** Verifies dependencies and acquires a lock to prevent concurrent runs.
2.  **Directory Navigation:** Changes its working directory to the specified source directory (`-s`, default is current).
3.  **File Verification:** Ensures all required sub-scripts (`install_base_exportcliv2.sh`, `configure_instance.sh`, `manage_services.sh`) and the base configuration file (`install-app.conf`) are present.
4.  **Script Permissions:** Makes the sub-scripts executable (`chmod +x`).
5.  **Run Base Installer (`install_base_exportcliv2.sh`):**
    *   Reads settings from the `install-app.conf` you prepared.
    *   Creates the dedicated application user and group (e.g., `exportcliv2_user`, `datapipeline_group`).
    *   Creates essential directory structures (e.g., under `/opt/exportcliv2/`, `/etc/exportcliv2/`, `/var/log/exportcliv2/`).
    *   Copies the versioned `exportcliv2` binary (specified by `VERSIONED_APP_BINARY_FILENAME`) into the installation's `bin` directory and creates a generic symlink (e.g., `/opt/exportcliv2/bin/exportcliv2`) pointing to it.
    *   Sets up a Python virtual environment for the `bitmover` service.
    *   Installs the `bitmover` Python wheel (specified by `VERSIONED_DATAMOVER_WHEEL_FILENAME`) into this virtual environment.
    *   Deploys the `run_exportcliv2_instance.sh` wrapper script (from template) into the installation's `bin` directory.
    *   Processes all systemd unit file templates (from `systemd_units/`) by replacing placeholders (like `{{APP_USER}}`, `{{BASE_DIR}}`) with actual values, and installs the resulting unit files into `/etc/systemd/system/`.
    *   Reloads the systemd daemon (`systemctl daemon-reload`).
    *   Deploys common configuration files:
        *   `/etc/exportcliv2/common.auth.conf` (copied from `config_files/`).
        *   `/etc/exportcliv2/config.ini` (generated from `config_files/config.ini.template` for `bitmover`).
    *   Creates the `/etc/default/exportcliv2_base_vars` file, storing key paths and the default `EXPORT_TIMEOUT_CONFIG` for use by other scripts.
6.  **Configure Instances (`configure_instance.sh`):**
    *   For each instance name provided via the `-i` flag (or defaults):
        *   Runs `configure_instance.sh -i <INSTANCE_NAME> [other_options]`.
        *   This creates two files in `/etc/exportcliv2/`:
            *   `<INSTANCE_NAME>.conf`: Contains environment variables specific to this instance (e.g., `EXPORT_IP`, `EXPORT_SOURCE`, `EXPORT_STARTTIME_OFFSET_SPEC`). These are used by the wrapper script.
            *   `<INSTANCE_NAME>_app.conf`: Contains application-specific settings (e.g., `mining_delta_sec=120`) used by the `exportcliv2` binary via its `-c` argument.
7.  **Manage Services (`manage_services.sh`):**
    *   Enables `bitmover.service` to start on boot.
    *   Starts `bitmover.service`.
    *   Checks and displays the status of `bitmover.service`.
    *   For each configured `exportcliv2` instance:
        *   Enables `exportcliv2@<INSTANCE_NAME>.service` and its associated `exportcliv2-restart@<INSTANCE_NAME>.path` unit.
        *   Starts `exportcliv2@<INSTANCE_NAME>.service` (and its path unit).
        *   Checks and displays the status of these instance-specific services.
8.  **Completion:** Releases the lock and prints a final summary.

---

### 5. Post-Installation Configuration

After a successful fresh installation, some manual configuration is usually required for the `exportcliv2` instances to function correctly with your specific data sources.

#### 5.1 Critical: `exportcliv2` Instance Configuration (`<INSTANCE_NAME>.conf`)

For each `exportcliv2` instance you configured (e.g., `site1`), you **must edit its environment configuration file**:
*   File location: `/etc/exportcliv2/<INSTANCE_NAME>.conf` (e.g., `/etc/exportcliv2/site1.conf`).
*   This file provides environment variables to the `run_exportcliv2_instance.sh` wrapper script.
*   **Key variables to set:**
    *   `EXPORT_IP="<target_ip_address>"`: The IP address this instance should focus on.
    *   `EXPORT_PORTID="<port_identifier>"`: The specific port or interface ID.
    *   `EXPORT_SOURCE="<data_source_tag>"`: A unique tag or sub-path for this instance's data source. This is used by the wrapper to form the output path for the `exportcliv2` binary (e.g., if `EXPORT_SOURCE="feedA"`, the output path might become `/opt/exportcliv2/source/feedA`).
*   **Review other default values:**
    *   `EXPORT_TIMEOUT`: Defaults to the value of `EXPORT_TIMEOUT_CONFIG` from `install-app.conf`. Adjust if this instance needs a different timeout.
    *   `EXPORT_STARTTIME_OFFSET_SPEC`: Defaults to "3 minutes ago". Change this if the instance needs to start processing data from a different relative time (e.g., "1 hour ago", "1 day ago 00:00:00").
    *   `EXPORT_ENDTIME`: Defaults to "-1", which is passed to the `exportcliv2` binary.
    *   `EXPORT_APP_CONFIG_FILE_PATH`: This should correctly point to `<ETC_DIR>/<INSTANCE_NAME>_app.conf`. Usually no change is needed here.

#### 5.2 Application-Specific Configuration (`<INSTANCE_NAME>_app.conf`)

For each instance, a small application-specific configuration file is also created:
*   File location: `/etc/exportcliv2/<INSTANCE_NAME>_app.conf` (e.g., `/etc/exportcliv2/site1_app.conf`).
*   Default content: `mining_delta_sec=120`
*   This file is passed to the `exportcliv2` binary via its `-c` command-line argument.
*   Edit this file only if the `mining_delta_sec` (or other future parameters added here) needs to be different from the default for this specific instance.

#### 5.3 Shared Authentication (`common.auth.conf`)

*   File location: `/etc/exportcliv2/common.auth.conf`.
*   This file is copied from `config_files/common.auth.conf` in your deployment package during installation.
*   It contains shared `EXPORT_AUTH_TOKEN_U` and `EXPORT_AUTH_TOKEN_P` variables.
*   Edit this file if your `exportcliv2` application uses these tokens for authentication.

#### 5.4 `bitmover` Service Configuration (`config.ini`)

*   File location: `/etc/exportcliv2/config.ini`.
*   This is the main configuration file for the `bitmover` Python service, generated from `config_files/config.ini.template`.
*   The `remote_host_url` is set from `REMOTE_HOST_URL_CONFIG` in `install-app.conf`.
*   **Important:** Review the `verify_ssl` setting. If `remote_host_url` uses `https://` and the server has a valid SSL certificate, set `verify_ssl = true`. The default is `false` for easier initial setup, but `true` is recommended for production.
*   Adjust other `bitmover` settings (poll intervals, timeouts, etc.) as needed.

#### 5.5 Restarting Services After Configuration Changes

If you modify any of the above configuration files *after* the initial installation and service startup by the orchestrator, you **must restart the affected services** for the changes to take effect.

Use the `manage_services.sh` script (located in your deployment package, or via a symlink if set up):
*   For changes to `/etc/exportcliv2/config.ini`:
    ```bash
    sudo ./manage_services.sh --restart
    ```
*   For changes to `/etc/exportcliv2/<INSTANCE_NAME>.conf`, `/etc/exportcliv2/<INSTANCE_NAME>_app.conf`, or `/etc/exportcliv2/common.auth.conf` affecting instance `<INSTANCE_NAME>`:
    ```bash
    sudo ./manage_services.sh -i <INSTANCE_NAME> --restart
    ```

---

### 6. Updating Application Components

This section describes how to update the `exportcliv2` binary or the `bitmover` Python wheel to newer versions.

#### 6.1 General Update Workflow

1.  **Obtain New Artifacts:** Download or acquire the new versioned binary file (e.g., `exportcliv2-v1.1.0`) and/or the new versioned Python wheel file (e.g., `datamover-0.3.0-py3-none-any.whl`).
2.  **Prepare Update Package:**
    *   It's recommended to have a dedicated deployment package directory for each release. Copy the new artifacts into this directory.
    *   Ensure the `deploy_orchestrator.sh`, `install_base_exportcliv2.sh`, and other scripts are also present in this directory (usually they come with the new artifacts).
3.  **Update `install-app.conf`:**
    *   In the **new** deployment package directory, edit `install-app.conf`.
    *   Set `VERSIONED_APP_BINARY_FILENAME` to the exact filename of the new `exportcliv2` binary.
    *   Set `VERSIONED_DATAMOVER_WHEEL_FILENAME` to the exact filename of the new `bitmover` wheel.
    *   Other settings in `install-app.conf` (like `BASE_DIR_CONFIG`) should generally match your existing deployed environment unless you are intentionally changing them (which is a more complex migration).
4.  **Run Orchestrator in Update Mode:**
    *   Navigate your terminal to the **root of the new deployment package directory** (containing the new artifacts and updated `install-app.conf`).
    *   Execute `deploy_orchestrator.sh` with the `--update` flag:
        ```bash
        sudo ./deploy_orchestrator.sh --update
        ```
    *   **To automatically restart relevant services after the update:**
        ```bash
        sudo ./deploy_orchestrator.sh --update --restart-services
        ```
        If you provide `-i INSTANCE_LIST` with `--update --restart-services`, only the specified instances (and `bitmover`) will be targeted for restart. If `-i` is omitted, only `bitmover` is targeted for restart by this flag.
    *   The script will ask for confirmation before proceeding.

#### 6.2 Understanding Orchestrator Actions During `--update`

When run with `--update`, `deploy_orchestrator.sh`:
1.  Performs initial checks (dependencies, lockfile).
2.  Runs `install_base_exportcliv2.sh -c install-app.conf` (using the `install-app.conf` from the current package directory). This script is idempotent and will:
    *   Copy the new versioned binary (from `VERSIONED_APP_BINARY_FILENAME`) to the existing installation's `bin` directory.
    *   Update the symbolic link (e.g., `/opt/exportcliv2/bin/exportcliv2`) to point to this new binary.
    *   Upgrade the `bitmover` Python package in its virtual environment using the new wheel (from `VERSIONED_DATAMOVER_WHEEL_FILENAME`).
    *   Re-process and re-install systemd unit files and the wrapper script. This is generally safe and ensures they are up-to-date, though often not strictly necessary for minor binary/wheel updates.
    *   It does **not** typically re-run `configure_instance.sh` or modify existing instance-specific `.conf` files.
3.  If `--restart-services` was specified, it calls `manage_services.sh` to restart `bitmover.service` and any `exportcliv2` instances specified via `-i`.
4.  If services are not automatically restarted, it provides guidance on how to restart them manually using `manage_services.sh`.

---

### 7. Managing Services (Everyday Activities)

The `manage_services.sh` script is your primary tool for controlling and monitoring the `bitmover` service and individual `exportcliv2` instances.

#### 7.1 Using `manage_services.sh`

*   **Location:** This script is part of your deployment package. After the initial installation, it's recommended to:
    *   Either always run it from a consistent location (e.g., if you copy the deployment package scripts to `/opt/exportcliv2/deployment_scripts/`).
    *   Or (recommended for ease of use), create a symbolic link to it from a directory in your system's `PATH`, e.g.:
        ```bash
        sudo ln -s /opt/exportcliv2/deployment_scripts/manage_services.sh /usr/local/bin/manage-appsuite
        # Then you can run: sudo manage-appsuite [options] <action>
        ```
*   **Permissions:** Most actions require `sudo`.

#### 7.2 Common Commands

Replace `<INSTANCE_NAME>` with the actual name of your `exportcliv2` instance (e.g., `site1`).
If `-i <INSTANCE_NAME>` is omitted, commands apply to the `bitmover.service`.

*   **Check Status:**
    *   `sudo ./manage_services.sh --status`
    *   `sudo ./manage_services.sh -i <INSTANCE_NAME> --status`
        *(Shows status for the main service, its restart path, and its restart service).*

*   **Start Services:**
    *   `sudo ./manage_services.sh --start`
    *   `sudo ./manage_services.sh -i <INSTANCE_NAME> --start`

*   **Stop Services:**
    *   `sudo ./manage_services.sh --stop`
    *   `sudo ./manage_services.sh -i <INSTANCE_NAME> --stop`

*   **Restart Services:** (Restarts the main service component)
    *   `sudo ./manage_services.sh --restart`
    *   `sudo ./manage_services.sh -i <INSTANCE_NAME> --restart`

*   **View Recent Logs:**
    *   `sudo ./manage_services.sh --logs`
    *   `sudo ./manage_services.sh -i <INSTANCE_NAME> --logs`
    *   With time filter: `sudo ./manage_services.sh -i <INSTANCE_NAME> --logs --since "2 hours ago"`

*   **Follow Logs (Live Tail):**
    *   `sudo ./manage_services.sh --logs-follow`
    *   `sudo ./manage_services.sh -i <INSTANCE_NAME> --logs-follow`
        *(For instances, follows logs for the main service, its restart path, and its restart service).*

*   **Enable Services (Start at Boot):**
    *   `sudo ./manage_services.sh --enable`
    *   `sudo ./manage_services.sh -i <INSTANCE_NAME> --enable`

*   **Disable Services (Prevent Start at Boot):**
    *   `sudo ./manage_services.sh --disable`
    *   `sudo ./manage_services.sh -i <INSTANCE_NAME> --disable`

*   **Reset Failed State:** (If a service is stuck in a "failed" state)
    *   `sudo ./manage_services.sh --reset-failed`
    *   `sudo ./manage_services.sh -i <INSTANCE_NAME> --reset-failed`

Run `sudo ./manage_services.sh --help` for a full list of options and actions.

---

### 8. Troubleshooting

*   **Script Output:** Pay close attention to the `[INFO]`, `[WARN]`, and `[ERROR]` messages produced by the orchestrator and management scripts.
*   **Dry Run:** Use the `-n` or `--dry-run` flag with `deploy_orchestrator.sh` and `manage_services.sh` to see what commands *would* be executed.
*   **Systemd Journal:** The ultimate source of truth for service runtime issues.
    *   `sudo journalctl -u bitmover.service`
    *   `sudo journalctl -u exportcliv2@<INSTANCE_NAME>.service`
    *   `sudo journalctl -u exportcliv2-restart@<INSTANCE_NAME>.path`
    *   `sudo journalctl -u exportcliv2-restart@<INSTANCE_NAME>.service`
    *   Use `-f` to follow, `-n <lines>` for recent lines, `--since "time"` for time-based filtering.
*   **Configuration Files:** Verify paths, permissions, and values in:
    *   `/etc/default/exportcliv2_base_vars` (key paths set by base installer)
    *   `/etc/exportcliv2/common.auth.conf` (shared credentials)
    *   `/etc/exportcliv2/config.ini` (bitmover settings)
    *   `/etc/exportcliv2/<INSTANCE_NAME>.conf` (instance environment variables)
    *   `/etc/exportcliv2/<INSTANCE_NAME>_app.conf` (instance app-specific settings)
*   **File Permissions:** Ensure the application user (e.g., `exportcliv2_user`) has correct read/write access to its data directories (e.g., in `/opt/exportcliv2/source/`, `/opt/exportcliv2/csv/`) and log directories.
*   **`systemctl status <unit_name>`:** Provides detailed status, including recent log snippets.
*   **Lockfile:** If `deploy_orchestrator.sh` exits abnormally, the lockfile (typically `/tmp/deploy_orchestrator.lock`) might remain. Delete it manually if you are sure no other instance is running.
*   **Restart Trigger Files:** For `exportcliv2` instances, the restart is triggered by the creation of `/opt/exportcliv2/csv/<INSTANCE_NAME>.restart` (adjust path if `BASE_DIR` was changed).

---

### 9. Appendix A: Key Configuration and Template File Details

This appendix provides insight into the content and structure of key configuration and template files used by the deployment system.

#### A.1 `install-app.conf` (Primary Input Configuration)

*(Located in your deployment package root. Drives `install_base_exportcliv2.sh`)*

```ini
# install-app.conf - Example

# --- Core Application Setup ---
# The APP_NAME is fixed internally by install_base_exportcliv2.sh to "exportcliv2".

VERSIONED_APP_BINARY_FILENAME="exportcliv2-v1.0.0"
VERSIONED_DATAMOVER_WHEEL_FILENAME="datamover-0.2.1-py3-none-any.whl"
REMOTE_HOST_URL_CONFIG="http://your-remote-server:8080/upload"
EXPORT_TIMEOUT_CONFIG="15"

# --- Optional Overrides ---
# USER_CONFIG="exportcliv2_user"
# GROUP_CONFIG="exportcliv2_group"
# BASE_DIR_CONFIG="/opt/exportcliv2"
# PYTHON_VENV_DIR_NAME="datamover_venv"
# BITMOVER_LOG_DIR_CONFIG="/var/log/exportcliv2/bitmover"
# SYSTEMD_TEMPLATES_SUBDIR="systemd_units"
# COMMON_CONFIGS_SUBDIR="config_files"
```
*   **Key takeaway:** `VERSIONED_*_FILENAME` variables must match the files in your package. `EXPORT_TIMEOUT_CONFIG` sets the default for new instances. Other variables allow customization of install paths and names.

#### A.2 `run_exportcliv2_instance.sh.template` (Wrapper Script)

*(Located in `config_files/`. Processed by `install_base_exportcliv2.sh` and installed, e.g., to `/opt/exportcliv2/bin/run_exportcliv2_instance.sh`. Executed by `exportcliv2@INSTANCE.service`)*

```bash
#!/bin/bash
set -euo pipefail

# Wrapper script for {{APP_NAME}} instance: $1 (passed by systemd as %i)
# Executed as {{APP_USER}}

# --- Instance Name from Argument ---
if [[ -z "$1" ]]; then
  echo "Error: Instance name argument (%i) not provided to wrapper script." >&2
  exit 78 # EX_CONFIG (standard exit code for configuration error)
fi
INSTANCE_NAME="$1"

echo "Wrapper script for {{APP_NAME}}@${INSTANCE_NAME} starting..."

# --- Sanity check required environment variables ---
# These are sourced by systemd from:
#   {{ETC_DIR}}/common.auth.conf
#   {{ETC_DIR}}/${INSTANCE_NAME}.conf
required_vars=(
  "EXPORT_AUTH_TOKEN_U" "EXPORT_AUTH_TOKEN_P" "EXPORT_TIMEOUT"
  "EXPORT_SOURCE" "EXPORT_IP" "EXPORT_PORTID"
  "EXPORT_APP_CONFIG_FILE_PATH" "EXPORT_STARTTIME_OFFSET_SPEC"
  # EXPORT_ENDTIME is also used but hardcoded to -1 in exec call below
)
for var_name in "${required_vars[@]}"; do
  if [[ -z "${!var_name:-}" ]]; then # Indirect expansion
    echo "Error: {{APP_NAME}}@${INSTANCE_NAME}: Required environment variable '${var_name}' is not set. Check {{ETC_DIR}}/common.auth.conf and {{ETC_DIR}}/${INSTANCE_NAME}.conf." >&2
    exit 78 # EX_CONFIG
  fi
done

# --- Calculate dynamic start time ---
# Uses EXPORT_STARTTIME_OFFSET_SPEC from the instance's .conf file
calculated_start_time=$(date +%s%3N --date="${EXPORT_STARTTIME_OFFSET_SPEC}" 2>/dev/null)
if [[ -z "$calculated_start_time" ]]; then
  echo "Error: {{APP_NAME}}@${INSTANCE_NAME}: Could not calculate start_time using EXPORT_STARTTIME_OFFSET_SPEC ('${EXPORT_STARTTIME_OFFSET_SPEC}'). Check this variable in {{ETC_DIR}}/${INSTANCE_NAME}.conf and ensure 'date' command works." >&2
  exit 78 # EX_CONFIG
fi

# --- Check if the app-specific config file actually exists ---
# Path provided by EXPORT_APP_CONFIG_FILE_PATH from instance's .conf file
if [[ ! -f "${EXPORT_APP_CONFIG_FILE_PATH}" ]]; then
    echo "Error: {{APP_NAME}}@${INSTANCE_NAME}: Application specific config file specified by EXPORT_APP_CONFIG_FILE_PATH ('${EXPORT_APP_CONFIG_FILE_PATH}') does not exist." >&2
    exit 78 # EX_CONFIG
fi

# --- Construct paths for arguments to the binary ---
CSV_INSTANCE_DIR="{{CSV_DATA_DIR}}/${INSTANCE_NAME}"
SOURCE_INSTANCE_PATH="{{SOURCE_DATA_DIR}}/${EXPORT_SOURCE}" # EXPORT_SOURCE is from instance's .conf

# --- Log execution details (optional, often commented out in production) ---
# printf "Executing for %s: %s \\\n" "${INSTANCE_NAME}" "{{SYMLINK_EXECUTABLE_PATH}}"
# printf "  -c %s \\\n" "${EXPORT_APP_CONFIG_FILE_PATH}"
# printf "  -u %s \\\n" "***" # Mask auth token
# printf "  -p %s \\\n" "***" # Mask auth token
# printf "  -C \\\n"
# printf "  -t %s \\\n" "${EXPORT_TIMEOUT}"
# printf "  -H %s \\\n" "${CSV_INSTANCE_DIR}"
# printf "  -o %s \\\n" "${SOURCE_INSTANCE_PATH}"
# printf "  %s \\\n" "${EXPORT_IP}"
# printf "  %s \\\n" "${EXPORT_PORTID}"
# printf "  %s \\\n" "${calculated_start_time}"
# printf "  %s\n" "-1" # Hardcoded end time for the binary

# --- Execute the main application binary ---
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
  -1 # Hardcoded end time argument

exit $? # Should not be reached if exec succeeds
```
*   **Placeholders filled by `install_base_exportcliv2.sh`:** `{{APP_NAME}}`, `{{APP_USER}}`, `{{ETC_DIR}}`, `{{CSV_DATA_DIR}}`, `{{SOURCE_DATA_DIR}}`, `{{SYMLINK_EXECUTABLE_PATH}}`.
*   **Key Function:** Dynamically calculates start time, assembles arguments from environment variables (set by `INSTANCE.conf` and `common.auth.conf`), and `exec`s the main `exportcliv2` binary.

#### A.3 `common.auth.conf` (Shared Authentication)

*(Located in `config_files/`. Copied by `install_base_exportcliv2.sh` to `/etc/exportcliv2/common.auth.conf`)*

```ini
# Common authentication tokens
# These are sourced by exportcliv2@INSTANCE.service and made available to the wrapper script.
EXPORT_AUTH_TOKEN_U="shared_user"
EXPORT_AUTH_TOKEN_P="shared_password"
```
*   **Key Function:** Provides default/shared authentication credentials. Can be overridden per-instance if these variables are also set in an `<INSTANCE_NAME>.conf` file (due to `EnvironmentFile` load order in the service unit).

#### A.4 `config.ini.template` (Bitmover Configuration)

*(Located in `config_files/`. Processed by `install_base_exportcliv2.sh` and saved as `/etc/exportcliv2/config.ini`)*
(Content as you provided, showing `base_dir = {{BASE_DIR}}`, `logger_dir = {{BITMOVER_LOG_DIR}}`, `remote_host_url = {{REMOTE_HOST_URL}}`, etc.)
*   **Placeholders:** `{{BASE_DIR}}`, `{{BITMOVER_LOG_DIR}}`, `{{REMOTE_HOST_URL}}`.
*   **Key Function:** Main configuration for the `bitmover` Python service.

#### A.5 Systemd Unit Templates Overview

*(Located in `systemd_units/`. Processed by `install_base_exportcliv2.sh` and installed into `/etc/systemd/system/`)*

*   **`bitmover.service.template`:**
    *   Defines the `bitmover` service.
    *   Runs as `{{APP_USER}}`.
    *   Executes `{{PYTHON_VENV_PATH}}/bin/bitmover --config {{BITMOVER_CONFIG_FILE}}`.
    *   Includes `ExecStartPre` directives to check for necessary directories like `{{SOURCE_DATA_DIR}}`, `{{CSV_DATA_DIR}}`, `{{BITMOVER_LOG_DIR}}`, etc.
    *   Sets `PYTHONUNBUFFERED=1`.
    *   Configured for auto-restart on failure.

*   **`exportcliv2@.service.template`:**
    *   Defines a templated service for `exportcliv2` instances (e.g., `exportcliv2@site1.service`).
    *   Runs as `{{APP_USER}}` (or user specified in `install-app.conf`).
    *   `WorkingDirectory={{BASE_DIR}}`.
    *   `EnvironmentFile={{ETC_DIR}}/common.auth.conf`
    *   `EnvironmentFile={{ETC_DIR}}/%i.conf` (loads instance-specific variables)
    *   `ExecStart={{INSTALLED_WRAPPER_SCRIPT_PATH}} %i` (runs the wrapper script, passing instance name).
    *   Includes `ExecStartPre` for directory checks and cleaning up `{{CSV_DATA_DIR}}/%i.restart`.

*   **`exportcliv2-restart@.path.template`:**
    *   Defines a path unit that monitors for the existence of a trigger file: `PathExists={{CSV_DATA_DIR}}/%i.restart`.
    *   When the file appears, it activates `{{APP_NAME}}-restart@%i.service`.

*   **`exportcliv2-restart@.service.template`:**
    *   A one-shot service that runs as `root`.
    *   Triggered by the corresponding `.path` unit.
    *   Executes `systemctl restart {{APP_NAME}}@%i.service`.
    *   Deletes the trigger file (`{{CSV_DATA_DIR}}/%i.restart`) after issuing the restart.

---

### 10. Appendix B: System Architecture Diagram (Conceptual)

![Conceptual Information Flow (path/to/your/image.png "Optional Title Text")

---
