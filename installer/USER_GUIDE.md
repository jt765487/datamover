## Application Suite Deployment and Management Guide

This guide provides instructions for deploying, configuring, updating, and managing the "exportcliv2" application suite, which includes the main `exportcliv2` data processing application and the `bitmover` Python service.

**Table of Contents:**

1.  Prerequisites
2.  Deployment Package Structure
3.  Initial Environment Setup (Fresh Install)
4.  Post-Installation Configuration Checks
5.  Updating Application Components
    *   Updating the `exportcliv2` Binary
    *   Updating the `bitmover` Python Wheel
    *   Using the Orchestrator for Updates
6.  Managing Services (Everyday Activities)
7.  Troubleshooting

---

### 1. Prerequisites

*   **Operating System:** Oracle Linux 9 (or a compatible RHEL 9 derivative).
*   **User Privileges:** `sudo` or root access is required for installation and service management.
*   **Required System Packages:**
    *   `python3` and `python3-venv` (for the `bitmover` service).
    *   Standard utilities: `date`, `chmod`, `dirname`, `basename`, `readlink`, `realpath`, `flock` (for the orchestrator script), `getent`, `groupadd`, `useradd`, `install`, `sed`, `systemctl`, `find`, `id`, `ln`, `pushd`, `popd`, `mkdir`, `printf` (used across the various scripts). These are typically present on a standard Linux installation. The orchestrator script will perform a basic dependency check for `flock`, `date`, and `chmod`. The base installer checks for its own set.
*   **Application Artifacts:** You must have the deployment package containing:
    *   The versioned `exportcliv2` binary (e.g., `exportcliv2-vX.Y.Z`).
    *   The versioned `bitmover` Python wheel (e.g., `datamover-vA.B.C.whl`).
    *   The suite of installation and management scripts.
    *   Configuration templates.

---

### 2. Deployment Package Structure

It is expected that you have an unpacked deployment package with the following structure. The `deploy_orchestrator.sh` script should be run from the root of this directory.

```
deployment_package_root/
├── deploy_orchestrator.sh                # Main script to drive installation or updates
├── install_base_exportcliv2.sh           # Core installer for base system and shared components
├── configure_instance.sh                 # Script to set up individual exportcliv2 instances
├── manage_services.sh                    # Script for everyday service management (start, stop, status, logs)
|
├── install-app.conf                      # Main configuration for the installer scripts
|
├── exportcliv2-vA.B.C                    # The versioned exportcliv2 binary
├── datamover-vX.Y.Z-py3-none-any.whl     # The versioned Python wheel for bitmover
|
├── config_files/                         # Directory for configuration file templates
│   ├── common.auth.conf                  # Template for shared authentication tokens
│   ├── config.ini.template               # Template for bitmover's INI configuration
│   └── run_exportcliv2_instance.sh.template # Wrapper script template for exportcliv2 instances
|
└── systemd_units/                        # Directory for systemd unit file templates
    ├── bitmover.service.template
    ├── exportcliv2@.service.template
    ├── exportcliv2-restart@.path.template
    └── exportcliv2-restart@.service.template
```

---

### 3. Initial Environment Setup (Fresh Install)

This process sets up the entire application suite, including users, directories, base configurations, and services for specified instances.

**Steps:**

1.  **Prepare `install-app.conf`:**
    *   Navigate to your unpacked deployment package directory.
    *   Open the `install-app.conf` file in a text editor.
    *   **Crucially, update the following MANDATORY variables:**
        *   `VERSIONED_APP_BINARY_FILENAME`: Set this to the exact filename of your `exportcliv2` binary (e.g., `VERSIONED_APP_BINARY_FILENAME="exportcliv2-vA.B.C"`).
        *   `VERSIONED_DATAMOVER_WHEEL_FILENAME`: Set this to the exact filename of your `datamover` Python wheel (e.g., `VERSIONED_DATAMOVER_WHEEL_FILENAME="datamover-vX.Y.Z-py3-none-any.whl"`).
        *   `REMOTE_HOST_URL_CONFIG`: Set the target URL for the `bitmover` service (e.g., `REMOTE_HOST_URL_CONFIG="http://your-remote-server:8989/pcap"`).
        *   `EXPORT_TIMEOUT_CONFIG`: Set the default timeout in seconds for new `exportcliv2` instances (e.g., `EXPORT_TIMEOUT_CONFIG="15"`).
    *   **Optionally, review and modify other parameters** like `USER_CONFIG`, `GROUP_CONFIG`, `BASE_DIR_CONFIG` if the defaults are not suitable for your environment. Refer to the comments within `install-app.conf` for details.

2.  **Run the Orchestrator Script:**
    *   From the root of your deployment package directory, execute the orchestrator script with the `--install` flag.
    *   You can specify which `exportcliv2` instances to create using the `-i` flag with a comma-separated list. If `-i` is omitted, default instances (e.g., `AAA,BBB,CCC` as defined in the orchestrator) will be configured.
    *   Example for a fresh install configuring instances `prod1` and `prod2`:
        ```bash
        sudo ./deploy_orchestrator.sh --install -i prod1,prod2
        ```
    *   To install with default instances (e.g., AAA, BBB, CCC):
        ```bash
        sudo ./deploy_orchestrator.sh --install
        ```
    *   To perform a dry run (see what commands would be executed without making changes):
        ```bash
        sudo ./deploy_orchestrator.sh --install -i prod1,prod2 -n
        ```
    *   The script will ask for confirmation before proceeding (unless in dry-run mode).

3.  **Orchestrator Actions during `--install`:**
    *   Acquires an execution lock.
    *   Checks for dependencies.
    *   Changes to the specified source directory (default is current directory).
    *   Verifies required scripts and the `install-app.conf` file are present.
    *   Makes sub-scripts executable.
    *   Runs `install_base_exportcliv2.sh -c install-app.conf`:
        *   Creates the application user and group (e.g., `exportcliv2_user`, `exportcliv2_group`).
        *   Creates base directories (e.g., `/opt/exportcliv2/`, `/etc/exportcliv2/`, `/var/log/exportcliv2/`).
        *   Installs the versioned `exportcliv2` binary and creates a symlink (e.g., `/opt/exportcliv2/bin/exportcliv2`).
        *   Sets up the Python virtual environment for `bitmover` and installs the wheel.
        *   Deploys the `run_exportcliv2_instance.sh` wrapper script.
        *   Processes systemd template files and installs them into `/etc/systemd/system/`.
        *   Deploys common configuration files (e.g., `common.auth.conf`, `config.ini` for bitmover).
        *   Creates `/etc/default/exportcliv2_base_vars` with key paths and defaults.
    *   For each specified instance (e.g., `prod1`):
        *   Runs `configure_instance.sh -i prod1` (and `--force` if `--force-reconfigure` was given to orchestrator):
            *   Creates `/etc/exportcliv2/prod1.conf` (environment variables for the instance wrapper).
            *   Creates `/etc/exportcliv2/prod1_app.conf` (config for `exportcliv2 -c` argument).
    *   Runs `manage_services.sh` to:
        *   Enable and start `bitmover.service`.
        *   Enable and start `exportcliv2@prod1.service` and `exportcliv2-restart@prod1.path`.
        *   (Repeats for other instances).
        *   Shows the status of these services.
    *   Releases the lock and exits.

---

### 4. Post-Installation Configuration Checks

After the orchestrator completes an `--install` operation:

1.  **Review Instance Configuration Files:**
    *   The most critical step is to **edit the instance-specific environment files** created by `configure_instance.sh`. These are located in `/etc/exportcliv2/` (or your custom `ETC_DIR`).
    *   For each instance (e.g., `prod1`), open `/etc/exportcliv2/prod1.conf`.
    *   **You MUST update at least:**
        *   `EXPORT_IP`: The specific IP address this instance should monitor/process.
        *   `EXPORT_PORTID`: The port ID or interface identifier.
        *   `EXPORT_SOURCE`: The specific source identifier or sub-path for this instance's data (e.g., `customerX/feedY`).
    *   Review and adjust other generated defaults if necessary:
        *   `EXPORT_TIMEOUT`: (Default taken from `install-app.conf`'s `EXPORT_TIMEOUT_CONFIG`).
        *   `EXPORT_STARTTIME_OFFSET_SPEC`: How far back data processing should start (e.g., "3 minutes ago", "1 hour ago").
        *   `EXPORT_ENDTIME`: (Default is "-1", meaning continuous for the `exportcliv2` binary).
    *   The `/etc/exportcliv2/prod1_app.conf` file (containing `mining_delta_sec=120`) usually does not need editing unless this specific parameter for the `exportcliv2` binary needs to change per instance.

2.  **Shared Authentication (`common.auth.conf`):**
    *   If your `exportcliv2` application requires authentication tokens (`EXPORT_AUTH_TOKEN_U`, `EXPORT_AUTH_TOKEN_P`), ensure they are correctly set in `/etc/exportcliv2/common.auth.conf`. The base installer copies this file from `config_files/common.auth.conf`.

3.  **Bitmover Configuration (`config.ini`):**
    *   Review `/etc/exportcliv2/config.ini` (for `bitmover`). The `remote_host_url` should have been set from `install-app.conf`. Check other settings like `verify_ssl` if you are using HTTPS.

4.  **Restart Services if Configurations Were Changed:**
    *   If you edited any of the `.conf` files or `config.ini` after the initial start by the orchestrator, you need to restart the affected services for changes to take effect.
    *   Use the `manage_services.sh` script:
        ```bash
        sudo ./manage_services.sh --restart                     # For bitmover
        sudo ./manage_services.sh -i prod1 --restart            # For exportcliv2 instance prod1
        ```
        (Run `manage_services.sh` from the deployment package directory, or use a symlink if created).

---

### 5. Updating Application Components

Updates typically involve providing new versions of the `exportcliv2` binary and/or the `bitmover` Python wheel.

**General Update Workflow:**

1.  **Obtain New Artifacts:** Get the new versioned binary (e.g., `exportcliv2-vNEW`) and/or wheel (e.g., `datamover-vNEW.whl`).
2.  **Update Deployment Package:**
    *   Place these new files into your deployment package directory (the same directory where `deploy_orchestrator.sh` and `install-app.conf` reside).
    *   Remove or archive the old versioned files from this directory to avoid confusion.
3.  **Update `install-app.conf`:**
    *   Edit `install-app.conf` in your deployment package directory.
    *   Modify `VERSIONED_APP_BINARY_FILENAME` to the exact filename of the new binary.
    *   Modify `VERSIONED_DATAMOVER_WHEEL_FILENAME` to the exact filename of the new wheel.
4.  **Run Orchestrator in Update Mode:**
    *   Navigate to your deployment package directory.
    *   Execute the orchestrator with the `--update` flag:
        ```bash
        sudo ./deploy_orchestrator.sh --update
        ```
    *   To also automatically restart services after the update:
        ```bash
        sudo ./deploy_orchestrator.sh --update --restart-services
        ```
        If you use `--restart-services` with `-i INSTANCE_LIST`, only those specified instances (and bitmover) will be restarted. Without `-i`, only bitmover is targeted for restart by this flag after an update.

**What the Orchestrator Does During `--update`:**

*   It re-runs `install_base_exportcliv2.sh -c install-app.conf`.
*   The `install_base_exportcliv2.sh` script will:
    *   Copy the new versioned binary specified in `install-app.conf` to the installation directory (e.g., `/opt/exportcliv2/bin/`).
    *   Update the symbolic link (e.g., `/opt/exportcliv2/bin/exportcliv2`) to point to the new binary.
    *   Upgrade the `bitmover` package in its Python virtual environment using the new wheel specified in `install-app.conf`.
    *   It generally does *not* reconfigure instances (i.e., does not run `configure_instance.sh`).
*   If `--restart-services` was used, the orchestrator then calls `manage_services.sh` to restart `bitmover` and any specified `exportcliv2` instances. Otherwise, it advises manual restarts.

---

### 6. Managing Services (Everyday Activities)

Use the `manage_services.sh` script for routine operations. It's recommended to run this script from the deployment package directory or set up a symlink to it in your system `PATH` (e.g., `/usr/local/bin/manage-appsuite`).

**Common Commands:**

*   **Check Status:**
    *   Bitmover: `sudo ./manage_services.sh --status`
    *   Instance `prod1`: `sudo ./manage_services.sh -i prod1 --status`
        *(This shows status for `exportcliv2@prod1.service`, `exportcliv2-restart@prod1.path`, and `exportcliv2-restart@prod1.service`)*

*   **Start Services:**
    *   Bitmover: `sudo ./manage_services.sh --start`
    *   Instance `prod1`: `sudo ./manage_services.sh -i prod1 --start`

*   **Stop Services:**
    *   Bitmover: `sudo ./manage_services.sh --stop`
    *   Instance `prod1`: `sudo ./manage_services.sh -i prod1 --stop`

*   **Restart Services:**
    *   Bitmover: `sudo ./manage_services.sh --restart`
    *   Instance `prod1` (main service only): `sudo ./manage_services.sh -i prod1 --restart`

*   **View Logs:**
    *   Bitmover (last 50 lines): `sudo ./manage_services.sh --logs`
    *   Instance `prod1` (last 50 lines for main service, 20 for restart service): `sudo ./manage_services.sh -i prod1 --logs`
    *   With time filter: `sudo ./manage_services.sh -i prod1 --logs --since "1 hour ago"`

*   **Follow Logs (Live Tail):**
    *   Bitmover: `sudo ./manage_services.sh --logs-follow`
    *   Instance `prod1` (follows main, path, and restart service): `sudo ./manage_services.sh -i prod1 --logs-follow`

*   **Enable Services (Start at Boot):**
    *   Bitmover: `sudo ./manage_services.sh --enable`
    *   Instance `prod1`: `sudo ./manage_services.sh -i prod1 --enable`

*   **Disable Services (Prevent Start at Boot):**
    *   Bitmover: `sudo ./manage_services.sh --disable`
    *   Instance `prod1`: `sudo ./manage_services.sh -i prod1 --disable`

*   **Reset Failed State:**
    *   If a service enters a "failed" state and systemd stops trying to restart it:
    *   Bitmover: `sudo ./manage_services.sh --reset-failed`
    *   Instance `prod1`: `sudo ./manage_services.sh -i prod1 --reset-failed`
        *(This applies `systemctl reset-failed` to both the main service and its path unit).*

Refer to `sudo ./manage_services.sh --help` for all available options.

---

### 7. Troubleshooting

*   **Check Script Logs:** All three scripts (`deploy_orchestrator.sh`, `install_base_exportcliv2.sh`, `configure_instance.sh`) print detailed informational and error messages to standard error. The `manage_services.sh` script also uses this.
*   **Systemd Journal:** The primary source for runtime service issues.
    *   Use `sudo journalctl -u unit_name` (e.g., `sudo journalctl -u bitmover.service` or `sudo journalctl -u exportcliv2@prod1.service`).
    *   The `manage_services.sh --logs` and `--logs-follow` commands are convenient wrappers.
*   **Configuration Files:** Double-check paths and values in:
    *   `/etc/default/exportcliv2_base_vars` (created by base installer)
    *   `/etc/exportcliv2/common.auth.conf`
    *   `/etc/exportcliv2/config.ini` (for bitmover)
    *   `/etc/exportcliv2/<INSTANCE_NAME>.conf`
    *   `/etc/exportcliv2/<INSTANCE_NAME>_app.conf`
*   **File Permissions:** Ensure the application user (e.g., `exportcliv2_user`) has appropriate read/write permissions on data directories (e.g., `/opt/exportcliv2/source`, `/opt/exportcliv2/csv`) and log directories. The installer scripts aim to set these correctly.
*   **`systemctl status unit_name`:** Provides a detailed overview of a service's state. The `manage_services.sh --status` command uses this.
*   **Lockfile Issues:** If the orchestrator script (`deploy_orchestrator.sh`) exits unexpectedly and fails to remove its lockfile (`/tmp/deploy_orchestrator.sh.lock`), you may need to remove it manually before re-running.

---
