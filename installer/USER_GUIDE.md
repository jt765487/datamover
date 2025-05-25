## Application Suite Deployment and Management Guide - Version 2.1

**Document Version:** 2.1
**Application Suite Orchestrator Version:** v2.4.3
*(Individual component script versions: Base Installer v1.3.0, Instance Configurator v4.1.0, Service Manager v1.3.0)*

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
    3.  Shared Authentication (`common.auth.conf`) (If used)
    4.  `bitmover` Service Configuration (`config.ini`)
    5.  Restarting Services After Configuration Changes
6.  Updating Application Components
    1.  Bundle Update Workflow (Using a New Package)
    2.  Surgical Update Workflow (Applying Specific Files)
    3.  Understanding Orchestrator Actions During `--update`
7.  Managing Services (Everyday Activities)
    1.  Using `exportcli-manage` (or `manage_services.sh`)
    2.  Common Commands
8.  Troubleshooting
9.  Appendix A: Key Configuration and Template File Details
    1.  A.1 `install-app.conf` (Primary Input Configuration)
    2.  A.2 `run_exportcliv2_instance.sh.template` (Wrapper Script)
    3.  A.3 `common.auth.conf` (Shared Authentication)
    4.  A.4 `config.ini.template` (Bitmover Configuration)
    5.  A.5 Systemd Unit Templates Overview
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
    *   `python3` and `python3-venv` (The `install_base_exportcliv2.sh` script uses `python3 -m venv` to create a virtual environment for the `bitmover` service; `python3-venv` or its equivalent for your Python 3 installation must be present).
    *   Standard utilities: `flock`, `date`, `chmod`, `dirname`, `basename`, `readlink`, `realpath`, `mktemp`, `cp`, `sed`, `touch`, `getent`, `groupadd`, `useradd`, `install`, `systemctl`, `find`, `id`, `chown`, `ln`, `pushd`, `popd`, `mkdir`, `printf`. These are generally present on a standard server installation. The Orchestrator script performs a check for its core dependencies.
*   **Application Artifacts:** You must have the `exportcliv2-suite-vX.Y.Z.tar.gz` deployment package.

---

### 3. Deployment Package Structure

The deployment process starts with the `exportcliv2-suite-vX.Y.Z.tar.gz` package. After extraction, it creates a top-level directory named `exportcliv2-suite-vX.Y.Z/`.

**All operations involving `deploy_orchestrator.sh` should be initiated from within this extracted `exportcliv2-suite-vX.Y.Z/` directory.**

The structure of the extracted package is as follows:

```
exportcliv2-suite-vX.Y.Z/
├── deploy_orchestrator.sh                # Main script to drive installation or updates
├── QUICK_START_GUIDE.md                  # This quick start guide
├── USER_GUIDE.md                         # This comprehensive user guide
│
└── exportcliv2-deploy/                   # Deployment subdirectory
    ├── install_base_exportcliv2.sh       # Core installer for base system
    ├── configure_instance.sh             # Script to set up individual exportcliv2 instances
    ├── manage_services.sh                # Script for everyday service management
    │
    ├── install-app.conf                  # Primary configuration for the installer scripts
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
        ├── exportcliv2@.service.template
        ├── exportcliv2-restart@.path.template
        └── exportcliv2-restart@.service.template
```

---

### 4. Initial Environment Setup (Fresh Install)

This procedure installs the entire application suite from scratch.

1.  **Extract the Package:**
    ```bash
    tar -xzvf exportcliv2-suite-vX.Y.Z.tar.gz
    cd exportcliv2-suite-vX.Y.Z/
    ```

#### 4.1 Step 1: Prepare `install-app.conf`

Before running the Orchestrator, configure `exportcliv2-deploy/install-app.conf`. This file dictates crucial settings for the installation.

Open `exportcliv2-deploy/install-app.conf` in a text editor.
**Verify and/or Set the following MANDATORY variables:**

*   `VERSIONED_APP_BINARY_FILENAME`: The exact filename of your `exportcliv2` binary (e.g., `"exportcliv2-v0.4.0-B1771-24.11.15"`). This file must be present in the `exportcliv2-deploy/` directory. *(This is usually pre-filled by the packaging process, but verification is good practice).*
*   `VERSIONED_DATAMOVER_WHEEL_FILENAME`: The exact filename of your `bitmover` Python wheel (e.g., `"datamover-0.1.0-py3-none-any.whl"`). This file must be present in the `exportcliv2-deploy/` directory. *(This is usually pre-filled by the packaging process, but verification is good practice).*
*   `REMOTE_HOST_URL_CONFIG`: The full URL where `bitmover` will upload files (e.g., `"http://data-ingest.example.com:8989/pcap"`).
*   `EXPORT_TIMEOUT_CONFIG`: The default timeout in seconds for `exportcliv2` instances (e.g., `"15"`). This value is stored in `/etc/default/exportcliv2_base_vars` for `configure_instance.sh` to use.

Additionally, review and optionally modify other settings in `install-app.conf` such as:
*   `USER_CONFIG` (default: "exportcliv2_user")
*   `GROUP_CONFIG` (default: "exportcliv2_group")
*   `BASE_DIR_CONFIG` (default: "/opt/exportcliv2")
Detailed comments within the file explain each option (See Appendix A.1).

#### 4.2 Step 2: Run the Orchestrator Script for Installation

From the `exportcliv2-suite-vX.Y.Z/` directory:

1.  Execute the `deploy_orchestrator.sh` script with the `--install` flag. You will need `sudo` privileges.

    *   **To install and configure default instances** (e.g., `AAA`, `BBB`, `CCC` as defined in the Orchestrator script):
        ```bash
        sudo ./deploy_orchestrator.sh --install
        ```
    *   **To install and configure specific instances** (e.g., `site1`, `lab_test`):
        ```bash
        sudo ./deploy_orchestrator.sh --install -i "site1,lab_test"
        ```
    *   **To perform a dry run** (see what commands would be executed without making changes):
        ```bash
        sudo ./deploy_orchestrator.sh --install -i "site1,lab_test" -n
        ```
    *   **To force reconfiguration of instances** if their configuration files already exist, or to auto-confirm in non-interactive environments:
        ```bash
        sudo ./deploy_orchestrator.sh --install -i site1 --force
        ```
        The `--force` flag with `--install` will overwrite existing instance configurations. For all modes, if running in a non-interactive (non-TTY) environment, `--force` assumes 'yes' to the main confirmation prompt.

2.  The script will perform dependency checks, acquire an execution lock, and then (if in an interactive TTY) ask for confirmation:
    ```
    Proceed with install for instances: (AAA,BBB,CCC) using source '/root/exportcliv2-suite-vX.Y.Z'? [y/N]
    ```
    Type `y` and press Enter to continue (unless in dry-run or non-TTY with `--force`).

#### 4.3 Understanding Orchestrator Actions During `--install`

When run with `--install`, the `deploy_orchestrator.sh` script (from the root of the extracted bundle) performs:

1.  **Initial Checks & Argument Parsing:** Verifies dependencies, parses arguments, and acquires a lock.
2.  **Directory Navigation:** Sets its working directory to the source directory (which is the current directory `.` by default, i.e., `exportcliv2-suite-vX.Y.Z/`).
3.  **File Verification:** Ensures sub-scripts and `install-app.conf` are present within the `exportcliv2-deploy/` subdirectory.
4.  **Script Permissions:** Makes sub-scripts in `exportcliv2-deploy/` executable.
5.  **Run Base Installer (`./exportcliv2-deploy/install_base_exportcliv2.sh`):**
    *   Reads settings from `exportcliv2-deploy/install-app.conf`.
    *   Creates the application user/group (e.g., `exportcliv2_user`, `datapipeline_group` if customized).
    *   Creates directory structures (e.g., under `/opt/exportcliv2/`, `/etc/exportcliv2/`).
    *   Copies the versioned `exportcliv2` binary and `bitmover` wheel from `exportcliv2-deploy/` to their respective installation locations.
    *   Creates a symlink (e.g., `/opt/exportcliv2/bin/exportcliv2`) to the versioned binary.
    *   Sets up a Python virtual environment and installs the `bitmover` wheel.
    *   Deploys the `run_exportcliv2_instance.sh` wrapper script from template.
    *   Deploys processed systemd unit files from `exportcliv2-deploy/systemd_units/` templates to `/etc/systemd/system/` and reloads the systemd daemon.
    *   Deploys common configuration files (e.g., `config.ini` for `bitmover` from template, `common.auth.conf` if present) from `exportcliv2-deploy/config_files/`.
    *   Creates `/etc/default/exportcliv2_base_vars`.
    *   Installs `manage_services.sh` to the installation's `bin` directory and creates the `/usr/local/bin/exportcli-manage` symlink.
6.  **Configure Instances (`./exportcliv2-deploy/configure_instance.sh`):**
    *   For each instance name (from `-i` flag or defaults like "AAA", "BBB", "CCC"):
        *   Runs `configure_instance.sh -i <INSTANCE_NAME> [--force if orchestrator had it]`.
        *   Creates `/etc/exportcliv2/<INSTANCE_NAME>.conf` and `/etc/exportcliv2/<INSTANCE_NAME>_app.conf`.
7.  **Manage Services (`./exportcliv2-deploy/manage_services.sh`):**
    *   **Enables and Starts the main `bitmover.service`**.
    *   If instances are specified/defaulted (e.g., "AAA", "BBB", "CCC"):
        *   For each such instance: Enables (`--enable`) and then starts (`--start`) its services (e.g., `exportcliv2@<INSTANCE_NAME>.service` and related path units).
    *   If no instances are specified via `-i` and no defaults are defined in the Orchestrator, only the main `bitmover.service` enable/start actions are performed.
8.  **Completion:** Releases the lock and prints a final summary.

---

### 5. Post-Installation Configuration

After a successful fresh installation, review and adjust instance configurations.

#### 5.1 Critical: `exportcliv2` Instance Configuration (`<INSTANCE_NAME>.conf`)

For each `exportcliv2` instance (e.g., `AAA`), edit its environment configuration file:
*   File location: `/etc/exportcliv2/<INSTANCE_NAME>.conf` (e.g., `/etc/exportcliv2/AAA.conf`).
*   This file provides environment variables to the `run_exportcliv2_instance.sh` wrapper. `configure_instance.sh` generates it with defaults:
    ```ini
    # Generated by configure_instance.sh ...
    EXPORT_TIMEOUT="15" # From EXPORT_TIMEOUT_CONFIG in install-app.conf
    EXPORT_SOURCE="AAA" # Defaults to instance name
    EXPORT_STARTTIME_OFFSET_SPEC="3 minutes ago" # Default
    EXPORT_ENDTIME="-1" # Default
    EXPORT_IP="10.0.0.1" # Default, **MUST EDIT for your target IP**
    EXPORT_PORTID="1"    # Default, **MUST EDIT for your target port/interface**
    EXPORT_APP_CONFIG_FILE_PATH="/etc/exportcliv2/AAA_app.conf" # Default path
    ```
*   **Key variables to set for your environment:** `EXPORT_IP` and `EXPORT_PORTID`. You might also adjust `EXPORT_SOURCE`.

#### 5.2 Application-Specific Configuration (`<INSTANCE_NAME>_app.conf`)

*   File location: `/etc/exportcliv2/<INSTANCE_NAME>_app.conf` (e.g., `/etc/exportcliv2/AAA_app.conf`).
*   Default content from `configure_instance.sh`: `mining_delta_sec=120`.
*   Edit if needed for this specific instance.

#### 5.3 Shared Authentication (`common.auth.conf`) (If used)

*   File location: `/etc/exportcliv2/common.auth.conf`.
*   If this file was present in `exportcliv2-deploy/config_files/` in your deployment package, it's copied during installation.
*   Can contain shared `EXPORT_AUTH_TOKEN_U` and `EXPORT_AUTH_TOKEN_P`.

#### 5.4 `bitmover` Service Configuration (`config.ini`)

*   File location: `/etc/exportcliv2/config.ini`.
*   Generated from `exportcliv2-deploy/config_files/config.ini.template`.
*   `remote_host_url` is set from `REMOTE_HOST_URL_CONFIG` in `install-app.conf`.
*   Review `verify_ssl` and other settings.

#### 5.5 Restarting Services After Configuration Changes

If you modify any of the above configuration files *after* the initial installation, **restart the affected services**:
Use `exportcli-manage` (symlinked to `/usr/local/bin/exportcli-manage`):
*   For `/etc/exportcliv2/config.ini` (bitmover):
    ```bash
    sudo exportcli-manage --restart
    ```
*   For instance configs (`<INSTANCE_NAME>.conf`, `<INSTANCE_NAME>_app.conf`, or `common.auth.conf` affecting an instance):
    ```bash
    sudo exportcli-manage -i <INSTANCE_NAME> --restart
    ```

---

### 6. Updating Application Components

This section describes how to update the `exportcliv2` binary or the `bitmover` Python wheel.

#### 6.1 Bundle Update Workflow (Using a New Package)

This is for when you have a new `exportcliv2-suite-vX.Y.Z.tar.gz` package.

1.  **Obtain and Extract New Package:**
    ```bash
    tar -xzvf exportcliv2-suite-vNEW_VERSION.tar.gz
    cd exportcliv2-suite-vNEW_VERSION/
    ```
2.  **Prepare `install-app.conf`:** In the new package's `exportcliv2-deploy/` directory, edit `exportcliv2-deploy/install-app.conf`:
    *   Ensure `VERSIONED_APP_BINARY_FILENAME` points to the new binary filename within `exportcliv2-deploy/`.
    *   Ensure `VERSIONED_DATAMOVER_WHEEL_FILENAME` points to the new wheel filename within `exportcliv2-deploy/`.
    *   Other settings like `REMOTE_HOST_URL_CONFIG` or `BASE_DIR_CONFIG` should typically match your existing deployment unless intentionally changing them.
3.  **Run Orchestrator in Update Mode:**
    *   From the root of the **new `exportcliv2-suite-vNEW_VERSION/` directory**:
        ```bash
        sudo ./deploy_orchestrator.sh --update
        ```
    *   **To automatically restart relevant services:**
        ```bash
        sudo ./deploy_orchestrator.sh --update -r  # or --restart-services
        ```
        If `-i INSTANCE_LIST` is used with `-r`, only those specified instances' services (and potentially `bitmover` if it's considered a general dependency) are restarted. If `-i` is omitted, the main `bitmover` service(s) are targeted by the restart action.

#### 6.2 Surgical Update Workflow (Applying Specific Files)

This is for applying a specific hotfix binary or wheel file without a full new package.

1.  **Obtain New Artifact(s):** Download the specific new `exportcliv2` binary and/or `bitmover` wheel. Note their **absolute paths** on your system.
2.  **Run Orchestrator in Update Mode:**
    *   Navigate to your existing `exportcliv2-suite-vX.Y.Z/` directory (or any directory from which you can run `deploy_orchestrator.sh` and correctly point to your installation's source files if needed).
    *   Execute `deploy_orchestrator.sh` with `--update` and point to the new files using absolute paths:
        ```bash
        # Example: Update only the binary, restart services
        sudo ./deploy_orchestrator.sh --update --new-binary /path/to/downloaded/new_exportcliv2.bin -r

        # Example: Update only the wheel, no auto-restart
        sudo ./deploy_orchestrator.sh --update --new-wheel /path/to/downloaded/new_datamover.whl

        # Example: Update both
        sudo ./deploy_orchestrator.sh --update --new-binary /path/to/new.bin --new-wheel /path/to/new.whl
        ```
    *   The `--source-dir` option for `deploy_orchestrator.sh` points to the root of the bundle structure containing the `exportcliv2-deploy` subdirectory which holds the current `install-app.conf`. This `install-app.conf` is used as a base for the temporary configuration during surgical updates. By default, `--source-dir` is `.`.

#### 6.3 Understanding Orchestrator Actions During `--update`

When run with `--update`, `deploy_orchestrator.sh`:
1.  Performs initial checks, argument parsing, and acquires a lock.
2.  **For Surgical Updates (`--new-binary` or `--new-wheel`):**
    *   Copies the provided new binary/wheel into the `SOURCE_DIR/exportcliv2-deploy/` directory (where `SOURCE_DIR` is the effective source directory for the orchestrator).
    *   Creates a temporary copy of the base configuration file (`SOURCE_DIR/exportcliv2-deploy/install-app.conf`).
    *   Modifies this temporary config to reference the newly staged binary/wheel filenames. This temporary config is then passed to the base installer.
3.  **Runs Base Installer (`./exportcliv2-deploy/install_base_exportcliv2.sh`):**
    *   Uses the effective configuration (original `install-app.conf` from the current bundle for a bundle update, or the temporary modified one for a surgical update).
    *   Copies the new versioned binary to the installation's `bin` directory.
    *   Updates the main symlink (e.g., `/opt/exportcliv2/bin/exportcliv2`) to point to this new binary.
    *   Upgrades the `bitmover` Python package in its virtual environment using the new wheel.
    *   Re-processes and re-installs systemd unit files and the wrapper script. This ensures supporting files are aligned with the potentially new binary/wheel behavior.
    *   Existing instance configurations (`<INSTANCE_NAME>.conf`, `<INSTANCE_NAME>_app.conf`) are **not** modified by this process.
4.  **Cleanup (for Surgical Updates):** Removes the staged binary/wheel and the temporary configuration file from the `SOURCE_DIR/exportcliv2-deploy/` directory.
5.  If `-r` (or `--restart-services`) was specified, it calls `manage_services.sh` to restart affected services. Otherwise, it reminds the user to restart services manually.

---

### 7. Managing Services (Everyday Activities)

The `exportcli-manage` command (a symlink to `manage_services.sh`) is your primary tool for controlling and monitoring services.

#### 7.1 Using `exportcli-manage` (or `manage_services.sh`)

*   **Location:** The `install_base_exportcliv2.sh` script creates a symlink at `/usr/local/bin/exportcli-manage`.
*   **Permissions:** Most actions require `sudo`.
*   **Invocation:**
    ```bash
    sudo exportcli-manage [OPTIONS] ACTION_FLAG
    ```
    If the symlink is not available, or you prefer to run directly from the bundle:
    ```bash
    cd /path/to/your/exportcliv2-suite-vX.Y.Z/
    sudo ./exportcliv2-deploy/manage_services.sh [OPTIONS] ACTION_FLAG
    ```

#### 7.2 Common Commands

Replace `<INSTANCE_NAME>` with your instance name (e.g., `AAA`).
If `-i <INSTANCE_NAME>` is omitted, commands apply to the global `bitmover.service`.

*   **Check Status:**
    *   Global `bitmover.service`:
        ```bash
        sudo exportcli-manage --status
        ```
        *(Output shows status for `bitmover.service`)*
    *   Specific Instance (e.g., `AAA`):
        ```bash
        sudo exportcli-manage -i AAA --status
        ```
        *(Output shows status for `exportcliv2@AAA.service`, `exportcliv2-restart@AAA.path`, and `exportcliv2-restart@AAA.service`)*

*   **Start Services:**
    *   `sudo exportcli-manage --start`
    *   `sudo exportcli-manage -i <INSTANCE_NAME> --start`

*   **Stop Services:**
    *   `sudo exportcli-manage --stop`
    *   `sudo exportcli-manage -i <INSTANCE_NAME> --stop`

*   **Restart Services:**
    *   `sudo exportcli-manage --restart`
    *   `sudo exportcli-manage -i <INSTANCE_NAME> --restart`

*   **View Recent Logs:** (Use `--since "time"` for specific timeframes, e.g., `--since "1 hour ago"`)
    *   `sudo exportcli-manage --logs`
    *   `sudo exportcli-manage -i <INSTANCE_NAME> --logs`

*   **Follow Logs (Live Tail):**
    *   `sudo exportcli-manage --logs-follow`
    *   `sudo exportcli-manage -i <INSTANCE_NAME> --logs-follow`
        *(For instances, follows logs for multiple related units).*

*   **Enable Services (Start at Boot):**
    *   `sudo exportcli-manage --enable`
    *   `sudo exportcli-manage -i <INSTANCE_NAME> --enable`

*   **Disable Services (Prevent Start at Boot):**
    *   `sudo exportcli-manage --disable`
    *   `sudo exportcli-manage -i <INSTANCE_NAME> --disable`

*   **Reset Failed State:** (If a service is stuck in a "failed" state)
    *   `sudo exportcli-manage --reset-failed`
    *   `sudo exportcli-manage -i <INSTANCE_NAME> --reset-failed`

Run `sudo exportcli-manage --help` for a full list of options and actions.

---

### 8. Troubleshooting

*   **Script Output:** Pay close attention to `[INFO]`, `[WARN]`, and `[ERROR]` messages.
*   **Dry Run:** Use the `-n` or `--dry-run` flag with `deploy_orchestrator.sh` and `exportcli-manage` (or `manage_services.sh`) to see what commands *would* be executed.
*   **Systemd Journal:** The primary source for service runtime issues.
    *   `sudo journalctl -u bitmover.service`
    *   `sudo journalctl -u exportcliv2@<INSTANCE_NAME>.service`
    *   `sudo journalctl -u exportcliv2-restart@<INSTANCE_NAME>.path`
    *   `sudo journalctl -u exportcliv2-restart@<INSTANCE_NAME>.service`
    *   Use `-f` to follow, `-n <lines>` for recent lines, `--since "time"` for time-based filtering.
*   **Configuration Files:** Verify paths, permissions, and values in:
    *   `/etc/default/exportcliv2_base_vars` (key paths, default instance timeout set by base installer)
    *   `/etc/exportcliv2/common.auth.conf` (if used for shared credentials)
    *   `/etc/exportcliv2/config.ini` (bitmover settings)
    *   `/etc/exportcliv2/<INSTANCE_NAME>.conf` (instance environment variables)
    *   `/etc/exportcliv2/<INSTANCE_NAME>_app.conf` (instance app-specific settings)
*   **File Permissions:** Ensure the application user (e.g., `exportcliv2_user`) has correct read/write access to its data directories (e.g., in `/opt/exportcliv2/source/`, `/opt/exportcliv2/csv/`, as defined by `BASE_DIR_CONFIG`) and log directories.
*   **`systemctl status <unit_name>`:** Provides detailed status, including recent log snippets.
*   **Lockfile:** If `deploy_orchestrator.sh` exits abnormally, the lockfile (`/tmp/deploy_orchestrator.lock`) might remain. Delete it manually if you are sure no other instance is running.
*   **Restart Trigger Files:** For `exportcliv2` instances, the auto-restart mechanism (if configured via `.path` units) typically monitors for a trigger file like `{{CSV_DATA_DIR}}/%i.restart` (where `CSV_DATA_DIR` is defined in `/etc/default/exportcliv2_base_vars`).

---

### 9. Appendix A: Key Configuration and Template File Details

This appendix provides insight into the content and structure of key configuration and template files.

#### A.1 `install-app.conf` (Primary Input Configuration)

*(Located in `exportcliv2-suite-vX.Y.Z/exportcliv2-deploy/`. Drives `install_base_exportcliv2.sh`)*

```ini
# install-app.conf - Example
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
# GROUP_CONFIG="datapipeline_group"

# BASE_DIR_CONFIG: Base installation directory. Default: "/opt/exportcliv2"
# BASE_DIR_CONFIG="/var/tmp/testme"
# ... other optional path overrides for PYTHON_VENV_DIR_NAME, etc.
```
*   **Key takeaway:** `VERSIONED_*_FILENAME` variables must match files in `exportcliv2-deploy/`. `REMOTE_HOST_URL_CONFIG` and `EXPORT_TIMEOUT_CONFIG` are crucial functional settings.

#### A.2 `run_exportcliv2_instance.sh.template` (Wrapper Script)

*(Located in `exportcliv2-suite-vX.Y.Z/exportcliv2-deploy/config_files/`. Processed by `install_base_exportcliv2.sh` and installed, e.g., to `/opt/exportcliv2/bin/run_exportcliv2_instance.sh`. Executed by `exportcliv2@INSTANCE.service`)*

The template contains placeholders like `{{APP_NAME}}`, `{{APP_USER}}`, `{{ETC_DIR}}`, `{{SYMLINK_EXECUTABLE_PATH}}`, `{{SOURCE_DATA_DIR}}`, `{{CSV_DATA_DIR}}`.
*   **Key Function:** This script is executed by the `exportcliv2@INSTANCE.service`. It sources instance-specific environment variables from `/etc/exportcliv2/INSTANCE.conf` (and potentially `/etc/exportcliv2/common.auth.conf`). It then calculates dynamic arguments (like start time from `EXPORT_STARTTIME_OFFSET_SPEC`) and assembles the full command line to execute the main `exportcliv2` binary (`{{SYMLINK_EXECUTABLE_PATH}}`). The `EXPORT_APP_CONFIG_FILE_PATH` variable from `INSTANCE.conf` points to the instance's application-specific config (e.g., `/etc/exportcliv2/INSTANCE_app.conf`), which is passed to the binary via its `-c` argument.

#### A.3 `common.auth.conf` (Shared Authentication)

*(Optional. If present in `exportcliv2-suite-vX.Y.Z/exportcliv2-deploy/config_files/`, it's copied by `install_base_exportcliv2.sh` to `/etc/exportcliv2/common.auth.conf`)*
```ini
# Common authentication tokens
EXPORT_AUTH_TOKEN_U="shared_user"
EXPORT_AUTH_TOKEN_P="shared_password"
```
*   **Key Function:** Provides default/shared authentication credentials, sourced by `exportcliv2@INSTANCE.service`.

#### A.4 `config.ini.template` (Bitmover Configuration)

*(Located in `exportcliv2-suite-vX.Y.Z/exportcliv2-deploy/config_files/`. Processed by `install_base_exportcliv2.sh` and saved as `/etc/exportcliv2/config.ini`)*
Contains placeholders like `{{BASE_DIR}}`, `{{BITMOVER_LOG_DIR}}`, `{{REMOTE_HOST_URL}}` which are filled based on `install-app.conf` values.
*   **Key Function:** Main configuration for the `bitmover` Python service.

#### A.5 Systemd Unit Templates Overview

*(Located in `exportcliv2-suite-vX.Y.Z/exportcliv2-deploy/systemd_units/`. Processed by `install_base_exportcliv2.sh` and installed into `/etc/systemd/system/`)*

*   **`bitmover.service.template`:** Defines the `bitmover` service. Runs as `{{APP_USER}}`, executes `{{PYTHON_VENV_PATH}}/bin/bitmover --config {{BITMOVER_CONFIG_FILE}}`.
*   **`exportcliv2@.service.template`:** Defines a templated service for `exportcliv2` instances. Runs as `{{APP_USER}}`. Sources `EnvironmentFile={{ETC_DIR}}/common.auth.conf` and `EnvironmentFile={{ETC_DIR}}/%i.conf`. Executes `ExecStart={{INSTALLED_WRAPPER_SCRIPT_PATH}} %i`.
*   **`exportcliv2-restart@.path.template`:** Path unit monitoring `PathExists={{CSV_DATA_DIR}}/%i.restart` to trigger the `.service` below.
*   **`exportcliv2-restart@.service.template`:** One-shot service, triggered by the `.path` unit, that executes `systemctl restart {{APP_NAME}}@%i.service` and removes the trigger file.

---

### 10. Appendix B: System Architecture Diagram (Conceptual)

*(Placeholder for your system diagram image/description)*
