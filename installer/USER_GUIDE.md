# Application Suite Deployment and Management Guide - Version 2.2

**Document Version:** 2.2
**Application Suite Orchestrator Version:** v2.4.6
**(Individual component script versions: Base Installer v1.3.2, Instance Configurator v4.1.0 (with updated output), Service Manager v1.3.2)**

This guide provides comprehensive instructions for deploying, configuring, updating, and managing the "exportcliv2" application suite. This suite includes the main exportcliv2 data processing application and the bitmover Python-based PCAP upload service.

## Table of Contents:

1.  Introduction
2.  Prerequisites
3.  Deployment Package Structure
4.  Initial Environment Setup (Fresh Install)
    *   Step 1: Prepare install-app.conf
    *   Step 2: Run the Orchestrator Script for Installation
    *   Understanding Orchestrator Actions During --install
5.  Post-Installation Configuration
    *   Critical: exportcliv2 Instance Configuration (<INSTANCE_NAME>.conf)
    *   Application-Specific Configuration (<INSTANCE_NAME>_app.conf)
    *   Shared Authentication (common.auth.conf) (If used)
    *   bitmover Service Configuration (config.ini)
    *   Restarting Services After Configuration Changes
6.  Updating Application Components
    *   Bundle Update Workflow (Using a New Package)
    *   Surgical Update Workflow (Applying Specific Files)
    *   Understanding Orchestrator Actions During --update
    *   Post-Update: Manual Service Restarts
7.  Managing Services (Everyday Activities)
    *   Using exportcli-manage (or manage_services.sh)
    *   Common Commands
8.  Troubleshooting
9.  Appendix A: Key Configuration and Template File Details
    *   A.1 install-app.conf (Primary Input Configuration)
    *   A.2 run_exportcliv2_instance.sh.template (Wrapper Script)
    *   A.3 common.auth.conf (Shared Authentication)
    *   A.4 config.ini.template (Bitmover Configuration)
    *   A.5 Systemd Unit Templates Overview
10. Appendix B: System Architecture Diagram (Conceptual)

---

## 1. Introduction

The exportcliv2 application suite is designed for robust data processing and management. It consists of:

*   **exportcliv2**: A high-performance data processing application, typically run as multiple instances, each configured for a specific data source or task.
*   **bitmover**: A Python service responsible for uploading PCAP files generated or processed by the system.

This guide details the use of a set of deployment and management scripts to install, configure, update, and operate this suite on an Oracle Linux 9 system.

---

## 2. Prerequisites

*   **Operating System**: Oracle Linux 9 (or a compatible RHEL 9 derivative).
*   **User Privileges**: `sudo` or `root` access is required for all installation, update, and service management tasks.
*   **Required System Packages**:
    *   `python3` and `python3-venv` (The `install_base_exportcliv2.sh` script uses `python3 -m venv` to create a virtual environment for the bitmover service; `python3-venv` or its equivalent for your Python 3 installation must be present).
    *   Standard utilities: `flock`, `date`, `chmod`, `dirname`, `basename`, `readlink`, `realpath`, `mktemp`, `cp`, `sed`, `touch`, `getent`, `groupadd`, `useradd`, `install`, `systemctl`, `find`, `id`, `chown`, `ln`, `pushd`, `popd`, `mkdir`, `printf`. These are generally present on a standard server installation. The Orchestrator script performs a check for its core dependencies.
*   **Application Artifacts**: You must have the `exportcliv2-suite-vX.Y.Z.tar.gz` deployment package.

---

## 3. Deployment Package Structure

The deployment process starts with the `exportcliv2-suite-vX.Y.Z.tar.gz` package. After extraction, it creates a top-level directory named `exportcliv2-suite-vX.Y.Z/`.

**All operations involving `deploy_orchestrator.sh` should be initiated from within this extracted `exportcliv2-suite-vX.Y.Z/` directory.**

The structure of the extracted package is as follows:

```
exportcliv2-suite-vX.Y.Z/
├── deploy_orchestrator.sh                # Main script to drive installation or updates (v2.4.6)
├── QUICK_START_GUIDE.md                  # Quick start guide
├── USER_GUIDE.md                         # This comprehensive user guide
│
└── exportcliv2-deploy/                   # Deployment subdirectory
    ├── install_base_exportcliv2.sh       # Core installer for base system (v1.3.2)
    ├── configure_instance.sh             # Script to set up individual exportcliv2 instances
    ├── manage_services.sh                # Script for everyday service management (v1.3.2)
    │
    ├── install-app.conf                  # Primary configuration for the installer scripts, including settings for core paths and an optional override for Bitmover's log directory.
    │
    ├── exportcliv2-vA.B.C                # The versioned exportcliv2 binary itself
    ├── datamover-vX.Y.Z-py3-none-any.whl # The versioned Python wheel for bitmover
    │
    ├── config_files/                     # Directory for config file templates
    │   ├── common.auth.conf              # (Optional) For shared authentication tokens
    │   ├── config.ini.template           # Template for bitmover's INI configuration
    │   └── run_exportcliv2_instance.sh.template # Wrapper script template for exportcliv2
    │
    └── systemd_units/                    # Directory for systemd unit file templates
        ├── bitmover.service.template
        ├── exportcliv2@.service.template   # Utilizes systemd features for instance-specific log directory management.
        ├── exportcliv2-restart@.path.template
        └── exportcliv2-restart@.service.template
```

---

## 4. Initial Environment Setup (Fresh Install)

This procedure installs the entire application suite from scratch.

1.  **Extract the Package:**
    ```bash
    tar -xzvf exportcliv2-suite-vX.Y.Z.tar.gz
    cd exportcliv2-suite-vX.Y.Z/
    ```

### 4.1 Step 1: Prepare `install-app.conf`

Before running the Orchestrator, configure `exportcliv2-deploy/install-app.conf`. This file dictates crucial settings for the installation.

1.  Open `exportcliv2-deploy/install-app.conf` in a text editor.
2.  Verify and/or Set the following **MANDATORY** variables:
    *   `DEFAULT_INSTANCES_CONFIG`: A space-separated list of instance names (e.g., `"ABC DEF GHI"`). This list **must be defined and non-empty** if you intend to run `deploy_orchestrator.sh --install` without the `-i` flag to specify instances directly. These will be the default instances configured.
    *   `VERSIONED_APP_BINARY_FILENAME`: The exact filename of your `exportcliv2` binary (e.g., `"exportcliv2-v0.4.0-B1771-24.11.15"`). This file must be present in the `exportcliv2-deploy/` directory. (This is usually pre-filled by the packaging process, but verification is good practice).
    *   `VERSIONED_DATAMOVER_WHEEL_FILENAME`: The exact filename of your bitmover Python wheel (e.g., `"datamover-0.1.0-py3-none-any.whl"`). This file must be present in the `exportcliv2-deploy/` directory. (This is usually pre-filled by the packaging process, but verification is good practice).
    *   `REMOTE_HOST_URL_CONFIG`: The full URL where bitmover will upload files (e.g., `"http://data-ingest.example.com:8989/pcap"`).
    *   `EXPORT_TIMEOUT_CONFIG`: The default timeout in seconds for `exportcliv2` instances (e.g., `"15"`). This value is stored in `/etc/default/exportcliv2_base_vars` for `configure_instance.sh` to use.

3.  Additionally, review and optionally modify other settings in `install-app.conf` such as:
    *   `USER_CONFIG` (default: `"exportcliv2_user"`)
    *   `GROUP_CONFIG` (default: `"exportcliv2_group"`, your example uses `"datapipeline_group"`)
    *   `BASE_DIR_CONFIG` (default: `"/opt/exportcliv2"`)
    *   `BITMOVER_LOG_DIR_CONFIG` (default: `"/var/log/exportcliv2/bitmover"`)
    Detailed comments within the file explain each option (See Appendix A.1).

### 4.2 Step 2: Run the Orchestrator Script for Installation

From the `exportcliv2-suite-vX.Y.Z/` directory:

1.  Execute the `deploy_orchestrator.sh` script with the `--install` flag. You will need `sudo` privileges.
    *   To install and configure default instances (as defined by `DEFAULT_INSTANCES_CONFIG` in `install-app.conf`):
        ```bash
        sudo ./deploy_orchestrator.sh --install
        ```
    *   To install and configure specific instances (e.g., `site1`, `lab_test`), overriding the defaults from `install-app.conf`:
        ```bash
        sudo ./deploy_orchestrator.sh --install -i "site1,lab_test"
        ```
    *   To perform a dry run (see what commands would be executed without making changes):
        ```bash
        sudo ./deploy_orchestrator.sh --install -n
        ```
        (You can combine `-n` with `-i "site1,lab_test"` if desired).
    *   To force reconfiguration of instances if their configuration files already exist, or to auto-confirm in non-interactive environments:
        ```bash
        sudo ./deploy_orchestrator.sh --install --force 
        # (This will use default instances from install-app.conf)
        # OR
        sudo ./deploy_orchestrator.sh --install -i site1 --force
        ```
        The `--force` flag with `--install` will overwrite existing instance configurations. For all modes, if running in a non-interactive (non-TTY) environment, `--force` assumes 'yes' to the main confirmation prompt.

2.  The script will perform dependency checks, acquire an execution lock, determine the configuration file, source it, and then (if in an interactive TTY) ask for confirmation:
    ```
    Proceed with install for instances: (ABC,DEF,GHI) using source '/root/exportcliv2-suite-vX.Y.Z'? [y/N]
    ```
    (The instance list `(ABC,DEF,GHI)` will reflect `DEFAULT_INSTANCES_CONFIG` if `-i` was not used).
3.  Type `y` and press Enter to continue (unless in dry-run or non-TTY with `--force`).

### 4.3 Understanding Orchestrator Actions During `--install`

When run with `--install`, the `deploy_orchestrator.sh` script performs:

*   **Initial Checks & Argument Parsing**: Verifies dependencies, parses arguments (including `-s` and `-c` to locate the correct `install-app.conf`), and acquires a lock.
*   **Configuration Sourcing**: Sources the effective `install-app.conf` to read variables like `DEFAULT_INSTANCES_CONFIG`. If `-i` is not used, it validates that `DEFAULT_INSTANCES_CONFIG` is set and non-empty.
*   **Directory Navigation**: Sets its working directory to the resolved source directory.
*   **File Verification**: Ensures sub-scripts and the effective `install-app.conf` (or its temporary copy for surgical updates) are present within the `exportcliv2-deploy/` subdirectory.
*   **Script Permissions**: Makes sub-scripts in `exportcliv2-deploy/` executable.
*   **Run Base Installer (`./exportcliv2-deploy/install_base_exportcliv2.sh`)**:
    *   The orchestrator passes the `--operation-type install` flag to this sub-script.
    *   The sub-script logs "Starting installation..."
    *   Reads settings from `exportcliv2-deploy/install-app.conf`.
    *   Creates the application user/group (e.g., `exportcliv2_user`, `datapipeline_group`).
    *   Creates core application directory structures, including the base log directory `/var/log/exportcliv2/` (by default) and the specific Bitmover log directory (default: `/var/log/exportcliv2/bitmover/`).
    *   Copies binaries and wheel to installation locations, creates symlinks.
    *   Sets up Python virtual environment for bitmover and installs the wheel.
    *   Deploys wrapper scripts and systemd unit files from templates.
    *   Deploys common configuration files.
    *   Creates `/etc/default/exportcliv2_base_vars`.
    *   Installs `manage_services.sh` and creates `/usr/local/bin/exportcli-manage` symlink.
    *   Suppresses its generic restart advice because it was called with `--operation-type install`.
*   **Configure Instances (`./exportcliv2-deploy/configure_instance.sh`)**:
    *   For each instance name (from `-i` flag, or from `DEFAULT_INSTANCES_CONFIG` in `install-app.conf` if `-i` was not used):
        *   Runs `configure_instance.sh -i <INSTANCE_NAME> [--force if orchestrator had it]`.
        *   Creates `/etc/exportcliv2/<INSTANCE_NAME>.conf` and `/etc/exportcliv2/<INSTANCE_NAME>_app.conf`.
        *   The "Next Steps" output from this script will correctly point to `exportcli-manage`.
*   **Manage Services (`./exportcliv2-deploy/manage_services.sh`)**:
    *   Enables and Starts the main `bitmover.service`.
    *   If instances are being processed (from `-i` or `DEFAULT_INSTANCES_CONFIG`):
        *   For each such instance: Enables (`--enable`) and then starts (`--start`) its services (e.g., `exportcliv2@<INSTANCE_NAME>.service` and related path units).
*   **Completion**: Releases the lock and prints a final summary.

---

## 5. Post-Installation Configuration

After a successful fresh installation, review and adjust instance configurations.

### 5.1 Critical: `exportcliv2` Instance Configuration (`<INSTANCE_NAME>.conf`)

For each `exportcliv2` instance (e.g., `ABC`), edit its environment configuration file:

*   **File location**: `/etc/exportcliv2/<INSTANCE_NAME>.conf` (e.g., `/etc/exportcliv2/ABC.conf`).
*   This file provides environment variables to the `run_exportcliv2_instance.sh` wrapper. `configure_instance.sh` generates it with defaults:
    ```ini
    # Generated by configure_instance.sh ...
    EXPORT_TIMEOUT="15" # From EXPORT_TIMEOUT_CONFIG in install-app.conf
    EXPORT_SOURCE="ABC" # Defaults to instance name
    EXPORT_STARTTIME_OFFSET_SPEC="3 minutes ago" # Default
    EXPORT_ENDTIME="-1" # Default
    EXPORT_IP="10.0.0.1" # Default, **MUST EDIT for your target IP**
    EXPORT_PORTID="1"    # Default, **MUST EDIT for your target port/interface**
    EXPORT_APP_CONFIG_FILE_PATH="/etc/exportcliv2/ABC_app.conf" # Default path
    ```
*   **Key variables to set for your environment**: `EXPORT_IP` and `EXPORT_PORTID`. You might also adjust `EXPORT_SOURCE`.

### 5.2 Application-Specific Configuration (`<INSTANCE_NAME>_app.conf`)

(Content as before - this section typically contains application-level JSON or similar structured data for `exportcliv2` itself.)

### 5.3 Shared Authentication (`common.auth.conf`) (If used)

(Content as before - this file typically contains shared API keys or tokens used by `exportcliv2` instances.)

### 5.4 bitmover Service Configuration (`config.ini`)

This file, located at `/etc/exportcliv2/config.ini` (by default), configures the bitmover service, including the `remote_host_url` and its specific logging path (populated during installation from `install-app.conf`).

### 5.5 Restarting Services After Configuration Changes

If you modify any of the above configuration files after the initial installation, restart the affected services:
Use `exportcli-manage` (symlinked to `/usr/local/bin/exportcli-manage`):

*   For `/etc/exportcliv2/config.ini` (bitmover):
    ```bash
    sudo exportcli-manage --restart
    ```
    *(Note: This command will display a warning that the operation may take some time if the service is slow to respond.)*

*   For instance configs (`<INSTANCE_NAME>.conf`, `<INSTANCE_NAME>_app.conf`, or `common.auth.conf` affecting an instance):
    ```bash
    sudo exportcli-manage -i <INSTANCE_NAME> --restart
    ```
    *(Note: This command will display a warning that the operation may take some time if the service is slow to respond.)*

---

## 6. Updating Application Components

This section describes how to update the `exportcliv2` binary or the bitmover Python wheel. **The `-r` / `--restart-services` option has been removed from `deploy_orchestrator.sh`. Services must be restarted manually after an update.**

### 6.1 Bundle Update Workflow (Using a New Package)

1.  **Obtain and Extract New Package**: (Same as fresh install)
2.  **Prepare `install-app.conf`**: (Same as fresh install - ensure `VERSIONED_...` filenames are correct for the new bundle).
3.  **Run Orchestrator in Update Mode**:
    *   From the root of the new `exportcliv2-suite-vNEW_VERSION/` directory:
        ```bash
        sudo ./deploy_orchestrator.sh --update
        ```
4.  **Post-Update: Manual Service Restart**: After the orchestrator completes the update, you must manually restart the relevant services using `exportcli-manage`. See Section 6.4.

### 6.2 Surgical Update Workflow (Applying Specific Files)

1.  **Obtain New Artifact(s)**: (e.g., download a new binary or wheel)
2.  **Run Orchestrator in Update Mode**:
    (Same as before, e.g.)
    ```bash
    # Example: Update only the binary
    sudo ./deploy_orchestrator.sh --update --new-binary /path/to/downloaded/new_exportcliv2.bin

    # Example: Update only the wheel
    sudo ./deploy_orchestrator.sh --update --new-wheel /path/to/downloaded/new_datamover.whl
    ```
3.  **Post-Update: Manual Service Restart**: After the orchestrator completes the update, you must manually restart the relevant services using `exportcli-manage`. See Section 6.4.

### 6.3 Understanding Orchestrator Actions During `--update`

When run with `--update`, `deploy_orchestrator.sh`:

*   Performs initial checks, argument parsing, sources `install-app.conf`, and acquires a lock.
*   **For Surgical Updates (`--new-binary` or `--new-wheel`)**: (Same as before - staging files into a temporary `exportcliv2-deploy` structure, creating a temporary `install-app.conf` with updated filenames).
*   **Runs Base Installer (`./exportcliv2-deploy/install_base_exportcliv2.sh`)**:
    *   The orchestrator passes the `--operation-type update` flag to this sub-script.
    *   The sub-script logs "Starting update..."
    *   (Rest of the actions like copying binary, updating symlink, upgrading wheel, re-processing systemd units are the same as install, but target existing locations).
    *   Existing instance configurations (`<INSTANCE_NAME>.conf`, `<INSTANCE_NAME>_app.conf`) are **not** modified.
    *   The sub-script will display its generic restart advice because it was called with `--operation-type update`.
*   **Cleanup (for Surgical Updates)**: (Same as before - removes temporary staging directory).
*   **Final Message**: The orchestrator will display a prominent message instructing the user to manually restart services and provide examples.

### 6.4 Post-Update: Manual Service Restarts (NEW SECTION)

After any `--update` operation using `deploy_orchestrator.sh`, services are **not** automatically restarted. You must do this manually using `exportcli-manage`.

The orchestrator will provide specific advice based on what was updated (e.g., if `--new-binary` or `--new-wheel` was used). Generally:

*   If the Datamover wheel was updated (or if it was a general bundle update where the wheel might have changed): Restart the main bitmover service:
    ```bash
    sudo exportcli-manage --restart
    ```
*   If the `exportcliv2` binary was updated (or if it was a general bundle update where the binary might have changed): Restart all affected `exportcliv2` instances:
    ```bash
    sudo exportcli-manage -i <INSTANCE_NAME_1> --restart
    sudo exportcli-manage -i <INSTANCE_NAME_2> --restart
    # Repeat for all active instances that use the updated binary.
    ```
    For example, if instances `ABC`, `DEF`, `GHI` were installed:
    ```bash
    sudo exportcli-manage -i ABC --restart
    sudo exportcli-manage -i DEF --restart
    sudo exportcli-manage -i GHI --restart
    ```
*   For a general bundle update (where `deploy_orchestrator.sh --update` was run without `--new-binary` or `--new-wheel`), it's safest to assume both the bitmover service and all `exportcliv2` instances might need restarting.
*   **Always check the output of the `deploy_orchestrator.sh --update` command for specific restart recommendations.**
*   *(Note: The `exportcli-manage --restart` command will display a warning that the operation may take some time if a service is slow to stop.)*

---

## 7. Managing Services (Everyday Activities)

The `exportcli-manage` command (a symlink to `manage_services.sh`, script version `v1.3.2`) is your primary tool for controlling and checking the status of the `bitmover` and `exportcliv2` services.

### 7.1 Using `exportcli-manage` (or `manage_services.sh`)

(Content largely the same - usage examples, help output overview)
*   Run `exportcli-manage --help` for a full list of commands and options.
*   It can manage the main `bitmover` service or specific `exportcliv2` instances using the `-i <INSTANCE_NAME>` flag.

### 7.2 Common Commands

(Content largely the same, ensure all commands reflect what `exportcli-manage --help` shows)
Examples:
*   **Check Status:**
    ```bash
    sudo exportcli-manage --status
    sudo exportcli-manage -i <INSTANCE_NAME> --status
    ```
*   **Start Services:**
    ```bash
    sudo exportcli-manage --start
    sudo exportcli-manage -i <INSTANCE_NAME> --start
    ```
*   **Stop Services:**
    ```bash
    sudo exportcli-manage --stop
    sudo exportcli-manage -i <INSTANCE_NAME> --stop
    ```
*   **Restart Services:**
    ```bash
    sudo exportcli-manage --restart
    sudo exportcli-manage -i <INSTANCE_NAME> --restart 
    ```
    *(Note: This command will display a warning that the operation may take some time if the service is slow to respond to stop signals.)*
*   **Enable Services (to start on boot):**
    ```bash
    sudo exportcli-manage --enable
    sudo exportcli-manage -i <INSTANCE_NAME> --enable
    ```
*   **Disable Services (to prevent start on boot):**
    ```bash
    sudo exportcli-manage --disable
    sudo exportcli-manage -i <INSTANCE_NAME> --disable
    ```

---

## 8. Troubleshooting

*   Check service status: `sudo exportcli-manage --status` or `sudo exportcli-manage -i <INSTANCE_NAME> --status`.
*   View logs captured by systemd: `journalctl -u bitmover.service`, `journalctl -u exportcliv2@<INSTANCE_NAME>.service`.
*   Verify configuration files in `/etc/exportcliv2/`.

For more detailed troubleshooting, or if applications write their own log/status files not captured by `journalctl`:

*   **Bitmover Logs:** Check the directory specified during installation (default: `/var/log/exportcliv2/bitmover/`, or as set by `BITMOVER_LOG_DIR_CONFIG` in `install-app.conf`). The `config.ini` for Bitmover (at `/etc/exportcliv2/config.ini`) will also reference its configured log path.
*   **exportcliv2 Instance Files:** The `exportcliv2@<INSTANCE_NAME>.service` instances use `/var/log/exportcliv2/<INSTANCE_NAME>/` as their working directory and for logs managed by systemd's `LogsDirectory=` feature. This directory is automatically created by systemd. Any files generated directly by an instance (e.g., temporary files, specific status files, or direct log files not sent to standard output/error which would be captured by journald) would be found here.

---

## 9. Appendix A: Key Configuration and Template File Details

### A.1 `install-app.conf` (Primary Input Configuration)

(Located in `exportcliv2-suite-vX.Y.Z/exportcliv2-deploy/`. Sourced by `deploy_orchestrator.sh` and drives `install_base_exportcliv2.sh`)

```ini
# install-app.conf - Example v2

# MANDATORY for default installs: Space-separated list of instance names.
# Used by 'deploy_orchestrator.sh --install' if the -i flag is not provided.
DEFAULT_INSTANCES_CONFIG="ABC DEF GHI"

# MANDATORY: Filename of the main application binary.
VERSIONED_APP_BINARY_FILENAME="exportcliv2-v0.4.0-B1771-24.11.15"

# MANDATORY: Filename of the DataMover Python wheel.
VERSIONED_DATAMOVER_WHEEL_FILENAME="datamover-0.1.0-py3-none-any.whl"

# MANDATORY: Remote URL for Bitmover uploads.
REMOTE_HOST_URL_CONFIG="http://192.168.0.180:8989/pcap"

# MANDATORY: Default timeout for exportcliv2 instances.
EXPORT_TIMEOUT_CONFIG="15"

# --- Optional Overrides ---
# USER_CONFIG: Service user name. Default: "exportcliv2_user"
# USER_CONFIG="exportcliv2_user"

# GROUP_CONFIG: Service group name. Default: "exportcliv2_group"
# GROUP_CONFIG="datapipeline_group" # Example from your tests

# BASE_DIR_CONFIG: Base installation directory. Default: "/opt/exportcliv2"
# BASE_DIR_CONFIG="/var/tmp/testme" # Example from your tests

# PYTHON_VENV_DIR_NAME: Name of the Python virtual environment directory for Bitmover.
# Default: "datamover_venv" (created under DATAMOVER_INSTALL_DIR_CONFIG, which is derived from BASE_DIR_CONFIG)
# PYTHON_VENV_DIR_NAME="my_bitmover_env"

# BITMOVER_LOG_DIR_CONFIG: Overrides the default log directory for Bitmover.
# The base log directory /var/log/exportcliv2/ is created by the installer.
# This variable defines a subdirectory within /var/log/exportcliv2/ for Bitmover's specific logs,
# or an entirely custom path if an absolute path is provided.
# Default: "/var/log/exportcliv2/bitmover"
# Example: BITMOVER_LOG_DIR_CONFIG="/var/log/my_app/custom_bitmover_logs"
# Example (relative to /var/log/exportcliv2/): BITMOVER_LOG_DIR_CONFIG="bitmover_custom_logs"

# --- Advanced Optional Overrides (rarely changed) ---
# SYSTEMD_TEMPLATES_SUBDIR: Subdirectory within the deployment package containing systemd unit templates.
# Default: "systemd_units"
# SYSTEMD_TEMPLATES_SUBDIR="my_custom_systemd_units"

# COMMON_CONFIGS_SUBDIR: Subdirectory within the deployment package containing common config file templates.
# Default: "config_files"
# COMMON_CONFIGS_SUBDIR="my_common_configs"

# Note: Other path configurations (like where binaries are installed, or the main application config directory /etc/exportcliv2)
# are derived from BASE_DIR_CONFIG or are hardcoded conventions in the installer (e.g., /etc/exportcliv2).
# The main application log directory /var/log/exportcliv2 is also a fixed convention of the installer.
```

**Key takeaway**: `DEFAULT_INSTANCES_CONFIG` is now a key orchestrator input. `VERSIONED_*_FILENAME` variables must match files in `exportcliv2-deploy/`. `REMOTE_HOST_URL_CONFIG` and `EXPORT_TIMEOUT_CONFIG` are crucial functional settings that get propagated during initial setup. `BITMOVER_LOG_DIR_CONFIG` allows customization of Bitmover's log location.

### A.2 `run_exportcliv2_instance.sh.template`

(Content largely the same - explains the wrapper script that sources `<INSTANCE_NAME>.conf` and launches `exportcliv2`.)

### A.3 `common.auth.conf`

(Content largely the same - explains the optional shared authentication file.)

### A.4 `config.ini.template` (Bitmover Configuration)

(Template for `/etc/exportcliv2/config.ini` (by default). `REMOTE_HOST_URL_CONFIG` from `install-app.conf` and the configured Bitmover log path (from `BITMOVER_LOG_DIR_CONFIG` in `install-app.conf`) populate this template during installation.)

### A.5 Systemd Unit Templates Overview

Describes `bitmover.service.template`, `exportcliv2@.service.template`, and the restart path/service templates.

*   **`exportcliv2@.service.template` specific notes:**
    *   This template uses the systemd directive `LogsDirectory=exportcliv2/%i`. This instructs systemd to automatically create a unique directory for each instance (e.g., `/var/log/exportcliv2/ABC/`) before the service starts.
    *   This directory is owned by the service user (`{{APP_USER}}`) and group (`{{APP_GROUP}}`) with permissions suitable for logging (e.g., 0750).
    *   The `WorkingDirectory` for each `exportcliv2` instance is also set to this systemd-managed path (e.g., `/var/log/exportcliv2/ABC/`). This means any relative file paths used by the `exportcliv2` application instance will resolve within its dedicated log/working directory.


