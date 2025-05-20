# Application Suite Deployment Guide: `exportcliv2` & `bitmover`

This guide explains how to deploy the **`exportcliv2` application suite**, which includes the core `exportcliv2` service and its associated `bitmover` (Python data mover) service. The deployment involves script-driven stages for base installation and `exportcliv2` instance configuration, followed by service management.

The internal application name used for creating users, directories, and service structures is fixed as **`exportcliv2`** by the installation scripts.

---

## Prerequisites

Before you begin, ensure the target Linux system has:

1.  **Root or Sudo Access**: Installation and management scripts require `sudo` privileges.
2.  **Bash Shell**: The scripts are written for Bash.
3.  **Essential System Commands**:
    *   `bash`, `date`, `id`, `getent`, `groupadd`, `useradd`, `install` (from coreutils), `sed`, `find`
    *   `systemctl`, `journalctl` (from systemd)
    *   `basename` (from coreutils)
4.  **Python 3 Environment**:
    * `python3` (e.g., version 3.9 or newer is needed).
    * The Python `venv` module: Essential for creating isolated Python environments. This is often part of the core Python installation or available via a package like `python3-venv` (on Debian/Ubuntu systems) or `python3.x-venv` (on RHEL/CentOS derivatives, where `x` is the Python minor version). The base install script uses `python3 -m venv`.

---

## Files Required for Installation

Place the following files and directories in a single deployment directory (e.g., `app_deploy/`) on the target server. The scripts expect to find assets like the binary, wheel, and template subdirectories relative to their own location.

```
app_deploy/
├── install_base_exportcliv2.sh     # Main base installation script
├── configure_instance.sh           # Script to configure exportcliv2 instances
├── manage_services.sh              # Unified script to manage all services
│
├── install-app.conf                # MANDATORY: Configuration for install_base_exportcliv2.sh
│
├── exportcliv2-v1.2.3              # MANDATORY: Your compiled exportcliv2 binary
│                                   # (Filename MUST be specified in install-app.conf)
│
├── datamover-0.1.0-py3-none-any.whl # MANDATORY: Python wheel for bitmover
│                                   # (Filename can be overridden in install-app.conf)
│
├── systemd_units/                  # MANDATORY: Directory with systemd service templates
│   │                               # (Subdir name can be overridden in install-app.conf)
│   ├── exportcliv2@.service.template
│   ├── exportcliv2-restart@.path.template
│   ├── exportcliv2-restart@.service.template
│   └── bitmover.service.template
│
└── config_files/                   # MANDATORY: Directory for config templates and common files
    │                               # (Subdir name can be overridden in install-app.conf)
    ├── config.ini.template         # Template for bitmover's configuration
    └── common.auth.conf            # Optional: Common auth file for exportcliv2 instances
```

**Important:**

*   Ensure the shell scripts are executable:
    ```bash
    chmod +x install_base_exportcliv2.sh configure_instance.sh manage_services.sh
    ```
*   The `exportcliv2-vX.Y.Z` is an example filename for your main application binary. You **must** provide your actual compiled binary and specify its exact filename in `install-app.conf` via the `APPLICATION_BINARY_FILENAME` variable.
*   The `datamover-0.1.0-py3-none-any.whl` is the default expected filename for the Python wheel. If your wheel file has a different name, set `DATAMOVER_WHEEL_NAME` in `install-app.conf`.

---

## Step 1: Prepare Base Installation Configuration (`install-app.conf`)

The `install_base_exportcliv2.sh` script **requires** the `install-app.conf` file (or a file specified with the `-c` option). This file provides critical information to the installer.

**Create `install-app.conf` in your deployment directory (`app_deploy/`).**

**Example `install-app.conf`:**
```bash
# install-app.conf
# Configuration for the 'exportcliv2' base installation.
# The base application name is fixed to "exportcliv2" by the installer script.

# MANDATORY: The actual filename of the main application binary (e.g., exportcliv2)
# This file must exist in the same directory as the install_base_exportcliv2.sh script.
APPLICATION_BINARY_FILENAME="exportcliv2-v1.2.3" # Replace with your binary's exact filename

# MANDATORY: The remote URL for the Bitmover component to upload data to.
REMOTE_HOST_URL_CONFIG="http://192.168.0.180:8989/pcap" # Replace with your actual server URL

# --- Optional Overrides ---
# If these variables are not defined in this file, the installer script will use
# its internal defaults, which are often based on the fixed APP_NAME "exportcliv2"
# or other sensible values.

# Service user for 'exportcliv2' and 'bitmover' services
# Script default: "exportcliv2_user"
# USER_CONFIG="custom_exportcliv2_user"

# Service group for 'exportcliv2' and 'bitmover' services
# Script default: "exportcliv2_group" (Note: your example uses "datapipeline_group")
# GROUP_CONFIG="custom_datapipeline_group"

# Base installation directory for application data, binary, and Python venv
# Script default: "/opt/exportcliv2"
# BASE_DIR_CONFIG="/var/custom_app/exportcliv2"

# Optional: Overrides the default filename for the DataMover wheel.
# Default is "datamover-0.1.0-py3-none-any.whl". This file is expected in the same directory as the install script.
DATAMOVER_WHEEL_NAME="datamover-0.1.0-py3-none-any.whl"

# Directory name for the Python virtual environment (created under BASE_DIR)
# Script default: "datamover_venv"
# PYTHON_VENV_DIR_NAME="app_python_env"

# Log directory for the 'bitmover' service
# Script default: "/var/log/exportcliv2/bitmover"
# BITMOVER_LOG_DIR_CONFIG="/var/log/custom_app/bitmover_logs"

# Subdirectory (relative to script) containing systemd service template files
# Script default: "systemd_units"
# SYSTEMD_TEMPLATES_SUBDIR="custom_systemd_templates"

# Subdirectory (relative to script) for common config files and config.ini.template
# Script default: "config_files"
# COMMON_CONFIGS_SUBDIR="shared_configs"
```

**Key actions for `install-app.conf`:**
1.  **Create this file.** It is not optional.
2.  **You MUST define `APPLICATION_BINARY_FILENAME`** and ensure this file exists in your deployment directory.
3.  **You MUST define `REMOTE_HOST_URL_CONFIG`** for the `bitmover` service.
4.  Review and set any optional override variables (like `USER_CONFIG`, `GROUP_CONFIG`, `BASE_DIR_CONFIG`, `DATAMOVER_WHEEL_NAME`, etc.) if your setup requires values different from the script's internal defaults. The script uses "exportcliv2" as the base for many defaults (e.g., default user is `exportcliv2_user`).

---

## Step 2: Run the Base Installation Script

This script sets up the environment, users, directories, installs the `exportcliv2` binary, creates a Python venv for `bitmover`, installs the `datamover` wheel, and deploys systemd unit files and configurations.

1.  Navigate to your deployment directory (e.g., `app_deploy/`):
    ```bash
    cd /path/to/your/app_deploy/
    ```
2.  Run the installer with `sudo`:
    ```bash
    sudo ./install_base_exportcliv2.sh -c install-app.conf
    ```
    *   Replace `install-app.conf` if you used a different configuration filename.
    *   Use the `-n` option for a dry-run to preview commands without making system changes.

### What the `install_base_exportcliv2.sh` script does:

*   Loads configuration from `install-app.conf`.
*   Creates the service user (e.g., `exportcliv2_user`) and group (e.g., `datapipeline_group` if configured, otherwise `exportcliv2_group`).
*   Creates directories like `${BASE_DIR}` (e.g., `/opt/exportcliv2`), `${ETC_DIR}` (e.g., `/etc/exportcliv2`), `${BITMOVER_LOG_DIR}` (e.g., `/var/log/exportcliv2/bitmover`), and various subdirectories under `${BASE_DIR}` for binaries, data, and Python venv.
*   Installs the application binary (specified by `APPLICATION_BINARY_FILENAME`) to `${BASE_DIR}/bin/exportcliv2`.
*   Creates a Python virtual environment in `${PYTHON_VENV_PATH}`.
*   Installs the `datamover` wheel (specified by `DATAMOVER_WHEEL_NAME`) into this venv.
*   Deploys templated systemd unit files from the `systemd_units/` subdirectory to `/etc/systemd/system/`. (See Appendix A for placeholders).
*   Deploys configuration templates from the `config_files/` subdirectory, including processing `config.ini.template` for `bitmover` and placing it in `${ETC_DIR}/config.ini`. (See Appendix A for placeholders).
*   Reloads the systemd daemon.
*   Saves essential environment variables (derived paths, user/group names) to `/etc/default/exportcliv2_base_vars` for use by other scripts.

After running, carefully review the script's output for any `[WARN]` or `[ERROR]` messages. The script will also print a summary of key installed paths and remind you to review the `bitmover` configuration.

---

## Step 3: Configure `exportcliv2` Instances

The `exportcliv2` application runs as instanced systemd services (e.g., `exportcliv2@instance_name.service`). Each instance requires its own configuration file located in `/etc/exportcliv2/`.

The `configure_instance.sh` script helps create these instance configurations. It reads settings from `/etc/default/exportcliv2_base_vars` to know where to place files.

### To generate a new default instance configuration:
For an instance named `prod_main`:
```bash
sudo ./configure_instance.sh -i prod_main
```
This creates `/etc/exportcliv2/prod_main.conf` with default values.

### To use a custom pre-existing configuration file for an instance:
If you have a file `/tmp/my_dev_instance.conf` for an instance named `dev_test`:
```bash
sudo ./configure_instance.sh -i dev_test --config-source-file /tmp/my_dev_instance.conf
```

### To overwrite an existing instance configuration:
If `/etc/exportcliv2/prod_main.conf` already exists and you want to replace it (e.g., with a new default or a new source file):
```bash
sudo ./configure_instance.sh -i prod_main --force
# or
sudo ./configure_instance.sh -i prod_main --config-source-file /tmp/new_prod_main.conf --force
```

After creating an instance configuration (especially if generated with defaults), **edit the file** (e.g., `sudo nano /etc/exportcliv2/prod_main.conf`) to set instance-specific parameters like `EXPORT_IP`, `EXPORT_PORTID`, authentication tokens (`EXPORT_AUTH_TOKEN_U`, `EXPORT_AUTH_TOKEN_P`), etc.

The `configure_instance.sh` script will output the exact `systemctl` commands needed to enable and start the services for the configured instance.

---

## Step 4: Manage Services

The `manage_services.sh` script provides a unified interface for controlling both the `bitmover` service and specific `exportcliv2` instances. Ensure it's executable (`chmod +x manage_services.sh`).

### Using `manage_services.sh`

**Syntax:**
```bash
sudo ./manage_services.sh [OPTIONS] ACTION_FLAG
```
*   To manage `bitmover.service`: Omit the `-i` option.
*   To manage an `exportcliv2` instance (e.g., `prod_main`): Use `-i prod_main`. This will also manage the associated `exportcliv2-restart@prod_main.path` unit where applicable.

**Common `ACTION_FLAG`s:**
`--start`, `--stop`, `--restart`, `--status` (or `--check`), `--logs`, `--logs-follow`, `--enable`, `--disable`

**Other `OPTIONS`:**
`--since <time>`, `--dry-run` (or `-n`), `--version`, `-h` (or `--help`)

**Examples:**
```bash
# Manage bitmover service
sudo ./manage_services.sh --start
sudo ./manage_services.sh --status
sudo ./manage_services.sh --logs-follow --since "1 hour ago"

# Manage exportcliv2 instance "site_alpha"
sudo ./manage_services.sh -i site_alpha --enable
sudo ./manage_services.sh -i site_alpha --start --dry-run
sudo ./manage_services.sh -i site_alpha --logs --since "yesterday"
```

### Using `systemctl` directly

You can also use `systemctl` directly. Remember that `exportcliv2` uses "exportcliv2" as its fixed application name.

**Bitmover (`bitmover.service`):**
```bash
sudo systemctl enable bitmover.service
sudo systemctl start bitmover.service
sudo systemctl status bitmover.service
sudo journalctl -u bitmover.service -f
```

**`exportcliv2` instance `prod_main` (example):**
```bash
# Enable services
sudo systemctl enable exportcliv2@prod_main.service
sudo systemctl enable exportcliv2-restart@prod_main.path

# Start services
sudo systemctl start exportcliv2@prod_main.service
# The .path unit typically starts when its associated service is active or can be started:
# sudo systemctl start exportcliv2-restart@prod_main.path

# Check status
sudo systemctl status exportcliv2@prod_main.service
sudo systemctl status exportcliv2-restart@prod_main.path

# View logs
sudo journalctl -u exportcliv2@prod_main.service -f

# To manually trigger a restart for 'prod_main' (if path unit is active):
# The path depends on your BASE_DIR, e.g., if BASE_DIR=/opt/exportcliv2:
# sudo touch /opt/exportcliv2/csv/prod_main.restart
# Consult /etc/default/exportcliv2_base_vars for the exact CSV_DATA_DIR if BASE_DIR was customized.
```

## 5. Dry-Run Behavior

**Dry-run caveat:** The dry-run mode shows the installer’s `install`, `useradd`, `sed`, etc. commands but does **not** simulate the creation of directories or files. It’s purely a preview—you still need to run without `-n` to actually provision.

---

## Troubleshooting

*   **Script Errors**: Check for `[ERROR]` messages in the console output from the installer scripts.
*   **`install-app.conf` Issues**:
    *   Ensure the file exists and is specified correctly with `-c`.
    *   Verify mandatory `APPLICATION_BINARY_FILENAME` and `REMOTE_HOST_URL_CONFIG` are set.
    *   Ensure filenames specified (like `APPLICATION_BINARY_FILENAME`, `DATAMOVER_WHEEL_NAME`) match actual files in your deployment directory.
*   **Missing Files**: Double-check that the `exportcliv2` binary, `datamover` wheel, and the `systemd_units/` and `config_files/` directories (with their contents) are present in your deployment directory.
*   **Permissions**:
    *   Binary (`${BASE_DIR}/bin/exportcliv2`): Should be `root:exportcliv2_group` (or your custom group), mode `0750`.
    *   Data Dirs (`${BASE_DIR}/source`, `${BASE_DIR}/csv`, etc.): Should be `exportcliv2_user:exportcliv2_group` (or custom user/group), mode `0770`.
    *   Log Dirs (`${BITMOVER_LOG_DIR}`): Should be `exportcliv2_user:exportcliv2_group`, mode `0770` or `0775`.
*   **Python/Venv Errors**:
    *   Confirm `python3` and the `python3-venv` (or equivalent) package are installed on the system.
    *   Check `install_base_exportcliv2.sh` output for errors during `setup_python_venv`.
*   **Service Failures (`systemctl status <service>` shows failed state)**:
    *   Use `sudo journalctl -u <service_name>.service -xe --no-pager` for detailed error messages.
    *   For `bitmover.service`, ensure `remote_host_url` in `/etc/exportcliv2/config.ini` is correct and reachable.
    *   For `exportcliv2@instance.service`, ensure `/etc/exportcliv2/instance.conf` exists, is populated correctly, and readable by the service user/group.
*   **Templates Not Processed**: If files in `/etc/systemd/system/` or `/etc/exportcliv2/config.ini` still contain `{{PLACEHOLDERS}}`, the `sed` substitution in `install_base_exportcliv2.sh` likely failed or missed a placeholder. Verify placeholders in your `.template` files against the `sed_replacements` arrays in the script (see Appendix A).

---

## Re-running Scripts

*   **`install_base_exportcliv2.sh`**: This script is designed to be idempotent. Re-running it will:
    *   Skip creating users/groups if they already exist.
    *   Ensure directories have the correct ownership and permissions.
    *   Overwrite the installed binary, Python packages within the venv, systemd unit files, and the `bitmover` `config.ini`. This is useful for deploying updates to these components.
*   **`configure_instance.sh`**: This script will exit if an instance configuration file already exists, unless the `--force` option is used. With `--force`, it will overwrite the existing configuration.

---
## Appendix A: Key Template Placeholders

The `install_base_exportcliv2.sh` script replaces the following placeholders in your `.template` files:

**Commonly used in `systemd_units/*.template` files:**
*   `{{APP_NAME}}`: Replaced with "exportcliv2" (the fixed application name).
*   `{{APP_USER}}`: The derived service user (e.g., `exportcliv2_user`).
*   `{{APP_GROUP}}`: The derived service group (e.g., `datapipeline_group`).
*   `{{BASE_DIR}}`: The main application installation and data directory (e.g., `/opt/exportcliv2`).
*   `{{ETC_DIR}}`: The base configuration directory in `/etc` (e.g., `/etc/exportcliv2`).
*   `{{TARGET_BINARY_PATH}}`: Full path to the installed `exportcliv2` binary (e.g., `/opt/exportcliv2/bin/exportcliv2`).
*   `{{SOURCE_DATA_DIR}}`: Path to the source data directory for `exportcliv2`.
*   `{{CSV_DATA_DIR}}`: Path to the CSV data directory for `exportcliv2`.
*   `{{PYTHON_VENV_PATH}}`: Full path to the Python virtual environment for `bitmover`.
*   `{{BITMOVER_CONFIG_FILE}}`: Full path to `bitmover`'s `config.ini` (e.g., `/etc/exportcliv2/config.ini`).

**Used in `config_files/config.ini.template` for `bitmover`:**
*   `{{BASE_DIR}}`
*   `{{BITMOVER_LOG_DIR}}`: Path to `bitmover`'s log directory.
*   `{{REMOTE_HOST_URL}}`: The upload endpoint URL (from `REMOTE_HOST_URL_CONFIG`).

*(Note: `pcap_extension_no_dot` and `csv_extension_no_dot` are hardcoded in `config.ini.template` and are not placeholders if you've followed that decision).*

Ensure your template files use these exact placeholder strings for successful substitution.

## Appendix B: Using `common.auth.conf`

If you place a `common.auth.conf` file in your `config_files/` directory (or the directory specified by `COMMON_CONFIGS_SUBDIR` in `install-app.conf`), the `install_base_exportcliv2.sh` script will deploy it to `${ETC_DIR}/common.auth.conf` (e.g. `/etc/exportcliv2/common.auth.conf`).

The example `exportcliv2@.service.template` includes:
```ini
EnvironmentFile={{ETC_DIR}}/%i.conf
EnvironmentFile={{ETC_DIR}}/common.auth.conf
```
This means that any `export VAR=value` lines (or simple `VAR=value` lines for systemd EnvironmentFiles) in both the instance-specific `.conf` file and the `common.auth.conf` file will be loaded as environment variables for the `exportcliv2` service instance. Variables in the instance-specific file typically override those in the common file if names clash. This is useful for shared credentials or settings across all `exportcliv2` instances.
```