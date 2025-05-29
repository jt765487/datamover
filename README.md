## First-Time Installation Guide for DataMover Application Suite (v0.1.2)

This guide will walk you through installing the DataMover application suite, which includes the `exportcliv2` data export client and the `bitmover` PCAP upload service. We'll set up a single instance named "AAA" as a primary example.

**Installation Steps Overview:**

1.  **Before You Begin:** Prerequisites and system checks.
2.  **Step 1: Prepare the Installation Package:** Unpack the suite.
3.  **Step 2: Configure the Installer:** Set up `install-app.conf`.
4.  **Step 3: Run the Installation:** Execute `deploy_orchestrator.sh`.
5.  **Step 4: Post-Installation Configuration (Instance Specific):** Configure `AAA.conf`.
6.  **Step 5: Restart the `exportcliv2` Instance "AAA".**
7.  **Step 6: Verify Services are Running.**
8.  **Step 7: Understanding Key Directories and Files.**
9.  **Step 8: Checking Logs.**
10. **Step 9: Update/Switch `exportcliv2` Binary and Credentials (IMPORTANT).**

---

**Before You Begin:**

1.  **System Compatibility:**
    *   Ensure you are on an Oracle Linux 9 system or a compatible RHEL 9 derivative (e.g., AlmaLinux 9, Rocky Linux 9).

2.  **Required Privileges:**
    *   You will need `sudo` access or to be logged in as the `root` user for installation and service management tasks.

3.  **Installation Package:**
    *   Have the application suite package ready: `exportcliv2-suite-v0.1.2.tar.gz`.

4.  **Python 3 Environment:**
    *   The DataMover component requires Python 3 (typically Python 3.9.x, which is the system default on Oracle Linux 9) with its standard `venv` module.
    *   **Verify Python 3 Installation:**
        ```bash
        python3 --version
        ```
    *   **Verify `venv` Module Availability:**
        ```bash
        python3 -m venv --help
        ```
        If this command displays help information for the `venv` module, your Python 3 environment is correctly set up.
    *   **If Python 3 is missing or `venv` is unavailable:**
        Install or ensure the main Python 3 package is fully installed:
        ```bash
        sudo dnf install python3
        ```
        On Oracle Linux 9, this command typically installs Python 3.9 and includes the necessary `venv` module.

---

**Step 1: Prepare the Installation Package**

1.  Copy the `exportcliv2-suite-v0.1.2.tar.gz` package to your server, for example, in the `/root` directory.
2.  Log in to your server and navigate to where you placed the package:
    ```bash
    # Example if you are not already root and the package is in /root
    # sudo -i
    # cd /root

    pwd
    ```
    Output should be `/root` if you followed the example.
3.  Extract the archive. The following shell session shows this process:
    ```bash
    [root@vbox ~]# ll
    total <SIZE_BEFORE_EXTRACT>
    # ... other files ...
    -rw-r--r-- 1 root root <TAR_SIZE> May 28 <TIME> exportcliv2-suite-v0.1.2.tar.gz
    [root@vbox ~]# tar vxf exportcliv2-suite-v0.1.2.tar.gz
    exportcliv2-suite-v0.1.2/
    exportcliv2-suite-v0.1.2/exportcliv2-deploy/
    # ... (tar output shortened for brevity) ...
    exportcliv2-suite-v0.1.2/QUICK_START_GUIDE.md
    exportcliv2-suite-v0.1.2/USER_GUIDE.md
    [root@vbox ~]# ll
    total <SIZE_AFTER_EXTRACT>
    # ... other files ...
    drwxr-xr-x <N> <USER> <GROUP>    <DIR_SIZE> May 28 <TIME> exportcliv2-suite-v0.1.2
    -rw-r--r-- 1 root    root    <TAR_SIZE> May 28 <TIME> exportcliv2-suite-v0.1.2.tar.gz
    ```
4.  Navigate into the extracted directory:
    ```bash
    cd exportcliv2-suite-v0.1.2/
    [root@vbox exportcliv2-suite-v0.1.2]# pwd
    /root/exportcliv2-suite-v0.1.2
    ```
    All subsequent commands will be run from this `exportcliv2-suite-v0.1.2/` directory.

---

**Step 2: Configure the Installer (`install-app.conf`)**

The main configuration file for the installer is `exportcliv2-deploy/install-app.conf`. This file is pre-configured by the `create_bundle.sh` script when the package is made. For a typical first-time installation where a production binary was included in the bundle, it will look similar to this. You generally do not need to edit it unless instructed for specific advanced scenarios.

1.  You can view the configuration with `cat exportcliv2-deploy/install-app.conf`. Key settings include:

    ```ini
    # install-app.conf

    # ... (comments omitted for brevity) ...

    # MANDATORY: Space-separated list of instance names for default installation.
    DEFAULT_INSTANCES_CONFIG="AAA" # Example, will install instance "AAA"

    # MANDATORY: The filename of the VERSIONED main application binary.
    # This is set by the 'create_bundle.sh' script to the initially active binary.
    # If a production binary was provided when creating the bundle (and --use-emulator-initially was not set),
    # it will be the production binary's filename.
    # Example if production binary 'exportcliv2-.4.0-B1771-24.11.15' was made active:
    VERSIONED_APP_BINARY_FILENAME="exportcliv2-.4.0-B1771-24.11.15"

    # MANDATORY: The filename of the VERSIONED DataMover Python wheel.
    VERSIONED_DATAMOVER_WHEEL_FILENAME="datamover-0.1.2-py3-none-any.whl"

    # MANDATORY: The remote URL for the Bitmover component to upload data to.
    # Ensure this is reachable from your server.
    REMOTE_HOST_URL_CONFIG="http://192.168.0.180:8989/pcap"

    # MANDATORY: Timeout (-t) in seconds for exportcliv2 instances.
    EXPORT_TIMEOUT_CONFIG="15"

    # MANDATORY (for offline installer fallback): Subdirectory for dependency wheels.
    WHEELHOUSE_SUBDIR="wheelhouse"

    # --- Optional Overrides (Defaults are usually suitable for first install) ---
    USER_CONFIG="exportcliv2_user"
    GROUP_CONFIG="datapipeline_group"
    BASE_DIR_CONFIG="/var/tmp/testme" # Example base installation directory

    # ... (other optional settings) ...
    ```
    **Note:** The `WHEELHOUSE_SUBDIR="wheelhouse"` line is crucial for the installer's ability to perform offline installations of Python dependencies if network access is unavailable.

2.  If specific changes are required (e.g., changing `DEFAULT_INSTANCES_CONFIG` or `BASE_DIR_CONFIG` before installation), edit the file using `vi`:
    ```bash
    # Ensure you are in the /root/exportcliv2-suite-v0.1.2 directory
    sudo vi exportcliv2-deploy/install-app.conf
    ```

---

**Step 3: Run the Installation**

Execute the main deployment script to install the base application components.

1.  From the `exportcliv2-suite-v0.1.2/` directory, run:
    ```bash
    sudo ./deploy_orchestrator.sh --install
    ```
2.  The script will perform checks and then ask for confirmation, listing the instances to be configured based on `DEFAULT_INSTANCES_CONFIG`:
    ```
    2025-05-28T18:56:56Z [INFO] Operation Mode: install
    2025-05-28T18:56:56Z [INFO] Using default instances from config file for --install: AAA
    Proceed with install for instances: (AAA) using source '/root/exportcliv2-suite-v0.1.2'? [y/N]
    ```
    Type `y` and press Enter.
3.  The installer will proceed, creating users/groups, directories, installing components, and setting up systemd services. You'll see output similar to:
    ```
    2025-05-28T18:56:59Z [INFO] User confirmed. Proceeding.
    2025-05-28T18:56:59Z [INFO] ▶ Orchestrator v2.4.6 starting (Mode: install)
    # ... (base installer output: user/group creation, file copying, Python venv setup) ...
    2025-05-28T18:57:04Z [INFO] ▶ Base Installation Script (install_base_exportcliv2.sh) finished successfully.
    2025-05-28T18:57:04Z [INFO] ▶ Configuring instances...
    2025-05-28T18:57:04Z [INFO] --- Configuring instance: AAA ---
    # ... (instance configuration output for AAA) ...
    2025-05-28T18:57:04Z [INFO] Default configurations were generated. Please review and edit them as needed:
    2025-05-28T18:57:04Z [INFO]     - /etc/exportcliv2/AAA.conf (especially EXPORT_IP, EXPORT_PORTID)
    # ... (service enabling and starting output for bitmover and instance AAA) ...
    2025-05-28T18:57:05Z [INFO] ▶ Orchestrator finished successfully.
    ```
    This process installs:
    *   The `bitmover` service (DataMover Python application).
    *   The `exportcliv2` instance "AAA" (using the binary specified by `VERSIONED_APP_BINARY_FILENAME` in `install-app.conf`).
    *   The watcher service for restarting instance "AAA".
    *   The `exportcli-manage` command-line tool (symlinked to `/usr/local/bin/exportcli-manage`).

---

**Step 4: Post-Installation Configuration (Critical for `exportcliv2` Instance)**

The installer sets up default configuration files. You **must** edit the instance-specific configuration for "AAA" to define its data source and other operational parameters.

1.  Edit the instance environment configuration file for "AAA":
    ```bash
    sudo vi /etc/exportcliv2/AAA.conf
    ```
2.  This file contains environment variables for the `exportcliv2` client. Key variables to update are `EXPORT_IP` and `EXPORT_PORTID`:
    ```ini
    # Generated by configure_instance.sh ...
    EXPORT_TIMEOUT="15" # From EXPORT_TIMEOUT_CONFIG in install-app.conf
    EXPORT_SOURCE="AAA" # Default, a unique tag for this instance's data
    EXPORT_STARTTIME_OFFSET_SPEC="3 minutes ago" # Default
    EXPORT_ENDTIME="-1" # Default
    # ---- EDIT THESE TWO LINES FOR YOUR ENVIRONMENT ----
    EXPORT_IP="10.0.0.1" # Change this to the actual IP address of your data source
    EXPORT_PORTID="1"    # Change this to the actual port/interface ID for your data source
    # -------------------------------------------------
    EXPORT_APP_CONFIG_FILE_PATH="/etc/exportcliv2/AAA_app.conf" # Default path to instance-specific app config
    ```
3.  Save the file and exit `vi` (e.g., press `Esc`, then type `:wq` and Enter).
4.  Also, review the application-specific configuration file for the instance, which might contain parameters like `mining_delta_sec` (if applicable to your `exportcliv2` binary):
    ```bash
    # sudo vi /etc/exportcliv2/AAA_app.conf (if needed)
    ```

---

**Step 5: Restart the `exportcliv2` Instance "AAA"**

Since you've likely modified its configuration, restart the "AAA" instance for the changes to take effect:
```bash
sudo exportcli-manage -i AAA --restart
```
You'll see output like:
```
2025-05-28T18:57:04Z [INFO] Performing 'restart' on exportcliv2 instance 'AAA' (Dry-run: false)
# ... (service restart messages) ...
2025-05-28T18:57:04Z [INFO] ▶ Service Management Script (exportcli-manage) finished successfully.
```
*Note: The restart might take a moment as it stops and starts the service.*

---

**Step 6: Verify Services are Running**

Use the `exportcli-manage` tool to check the status of the services.

1.  **Check the `bitmover` service (main data uploader):**
    ```bash
    sudo exportcli-manage --status
    ```
    Look for `Active: active (running)` in the output for `bitmover.service`.
    Example snippet:
    ```
    ● bitmover.service - Bitmover - PCAP Upload Service for exportcliv2
         Loaded: loaded (/etc/systemd/system/bitmover.service; enabled; preset: disabled)
         Active: active (running) since Mon 2025-05-28 <TIME> <TIMEZONE>; ...
    ```

2.  **Check the `exportcliv2` instance "AAA":**
    ```bash
    sudo exportcli-manage -i AAA --status
    ```
    Look for `Active: active (running)` for `exportcliv2@AAA.service` and `Active: active (waiting)` for `exportcliv2-restart@AAA.path`.
    Example snippet for `exportcliv2@AAA.service`:
    ```
    ● exportcliv2@AAA.service - exportcliv2 instance AAA
         Loaded: loaded (/etc/systemd/system/exportcliv2@.service; enabled; preset: disabled)
         Active: active (running) since Mon 2025-05-28 <TIME> <TIMEZONE>; ...
       Main PID: <PID_NUMBER> (name_of_active_binary)
    ```
    And for the path unit:
    ```
    ● exportcliv2-restart@AAA.path - Path watcher to trigger restart for exportcliv2 instance AAA
         Loaded: loaded (/etc/systemd/system/exportcliv2-restart@.path; enabled; preset: disabled)
         Active: active (waiting) since Mon 2025-05-28 <TIME> <TIMEZONE>; ...
    ```

---

**Step 7: Understanding Key Directories and Files**

The application installs its components and working directories under the path specified by `BASE_DIR_CONFIG` in `install-app.conf` (e.g., `/var/tmp/testme/`). Here's a simplified overview:

*   **Base Directory** (e.g., `/var/tmp/testme/`):
    *   `bin/`: Contains all bundled `exportcliv2` executables (e.g., `exportcliv2-.4.0-B1771-24.11.15`, `exportcliv8`). A symlink named `exportcliv2` points to the currently active binary. This directory also includes the `run_exportcliv2_instance.sh` wrapper script and the `manage_services.sh` utility.
        ```
        [root@vbox base_dir]# ls -l bin/
        total <SIZE>
        lrwxrwxrwx 1 root             root                    <X> May 28 <TIME> exportcliv2 -> <active_binary_filename>
        -rwxr-x--- 1 root             datapipeline_group <SIZE> May 28 <TIME> <production_binary_filename_if_bundled>
        -rwxr-x--- 1 root             datapipeline_group <SIZE> May 28 <TIME> exportcliv8 # (emulator_if_bundled)
        -rwxr-xr-x 1 root             datapipeline_group  <SIZE> May 28 <TIME> manage_services.sh
        -rwxr-x--- 1 exportcliv2_user datapipeline_group  <SIZE> May 28 <TIME> run_exportcliv2_instance.sh
        ```
    *   `csv/`: Holds CSV metadata files generated by `exportcliv2` instances (e.g., `AAA.csv`). The `exportcliv2-restart@INSTANCE.path` service also monitors this directory for `INSTANCE.restart` files to trigger instance restarts.
        ```
        [root@vbox base_dir]# ls -l csv/
        total <SIZE>
        -rw-r----- 1 exportcliv2_user datapipeline_group <SIZE> May 28 <TIME> AAA.csv
        ```
    *   `datamover_venv/`: Python virtual environment for the `bitmover` (DataMover) service.
    *   `source/`: Directory where `exportcliv2` instances place generated PCAP files. `bitmover` monitors this directory.
    *   `worker/`: Staging directory where `bitmover` moves files from `source/` before attempting uploads.
    *   `uploaded/`: Directory where successfully uploaded PCAP files are moved by `bitmover`.
        ```
        [root@vbox base_dir]# ls -l uploaded/ | head
        total <SIZE>
        -rw-r----- 1 exportcliv2_user datapipeline_group <SIZE> May 28 <TIME> AAA-<TIMESTAMP>.pcap
        # ... more files
        ```
    *   `dead_letter/`: Directory where PCAP files that failed to upload (due to non-retriable errors) are moved by `bitmover`.

---

**Step 8: Checking Logs**

Logs are crucial for troubleshooting.

1.  **Log Directory Structure:**
    The main log directory is `/var/log/exportcliv2/` (this can be changed for the `bitmover` component's logs via `BITMOVER_LOG_DIR_CONFIG` in `install-app.conf`).
    ```bash
    [root@vbox ~]# ls -lR /var/log/exportcliv2/
    /var/log/exportcliv2/:
    total <SIZE>
    drwxr-x--- <N> exportcliv2_user datapipeline_group <SIZE> May 28 <TIME> AAA  # Working dir for instance AAA
    drwxrwx--- <N> exportcliv2_user datapipeline_group <SIZE> May 28 <TIME> bitmover # Logs for bitmover service
    # ... (directories for other configured instances like DEF, GHI) ...

    /var/log/exportcliv2/AAA: # Example for instance AAA
    total <SIZE>
    -rw-r----- 1 <USER> <GROUP> <SIZE> May 28 <TIME> exportcliv2_<DATE>.log # Instance-specific log

    /var/log/exportcliv2/bitmover:
    total <SIZE>
    -rw-r----- 1 exportcliv2_user datapipeline_group <SIZE> May 28 <TIME> app.log.jsonl
    -rw-r----- 1 exportcliv2_user datapipeline_group <SIZE> May 28 <TIME> audit.log.jsonl
    ```
    *   **`bitmover` service logs:**
        *   `/var/log/exportcliv2/bitmover/app.log.jsonl`: Main application log (JSONL format), contains detailed operational messages, errors, and debug information.
        *   `/var/log/exportcliv2/bitmover/audit.log.jsonl`: Audit log (JSONL format), specifically records details of file upload attempts.
    *   **`exportcliv2` instance ("AAA") logs:** These are primarily handled by `systemd-journald`. Additionally, the instance wrapper script may direct output to a file like `/var/log/exportcliv2/AAA/exportcliv2_<DATE>.log`.

2.  **Viewing Logs with `exportcli-manage`:**
    The `exportcli-manage` tool is the primary way to view service logs.

    *   **Follow `bitmover` main application logs (`app.log.jsonl` via journald):**
        ```bash
        sudo exportcli-manage --logs-follow
        ```
        (Press `Ctrl+C` to stop following)
    *   **Follow `exportcliv2` instance "AAA" logs (from journald):**
        ```bash
        sudo exportcli-manage -i AAA --logs-follow
        ```
    *   **Show recent `bitmover` main application logs:**
        ```bash
        sudo exportcli-manage --logs
        ```
    *   **Show recent `exportcliv2` instance "AAA" logs:**
        ```bash
        sudo exportcli-manage -i AAA --logs
        ```
        (You can add options like `--since "10m"` to these commands).
    *   **To view the `bitmover` audit log or instance-specific file logs directly:**
        Use standard Linux commands:
        ```bash
        sudo tail -f /var/log/exportcliv2/bitmover/audit.log.jsonl
        sudo less /var/log/exportcliv2/AAA/exportcliv2_<DATE>.log
        ```

---

**Step 9: Update/Switch `exportcliv2` Binary and Credentials (IMPORTANT)**

The installation package may include multiple `exportcliv2` binaries (e.g., a production version and a test emulator like `exportcliv8`). This step guides you on how to switch which binary is active for the instances or update to a newer binary version, and how to manage associated credentials.

1.  **Identify Available Binaries:**
    The bundled binaries are located in the application's `bin` directory (e.g., `/var/tmp/testme/bin/`). List them to see what's available:
    ```bash
    ls -l /var/tmp/testme/bin/
    ```
    You will see the files for the production binary, the `exportcliv8` emulator (if bundled), and a symlink `exportcliv2` pointing to the currently active one.

2.  **Switching to a Different Bundled Binary (e.g., to `exportcliv8` emulator):**
    Navigate to your original installation package directory (e.g., `/root/exportcliv2-suite-v0.1.2/`). Use the `deploy_orchestrator.sh` script with the `--update` and `--new-binary` flags, specifying the *filename* of the binary you want to make active (it must be one of the filenames present in the application's `bin` directory).

    Example: To make `exportcliv8` the active binary:
    ```bash
    # Ensure you are in the extracted suite directory, e.g., /root/exportcliv2-suite-v0.1.2/
    sudo ./deploy_orchestrator.sh --update --new-binary exportcliv8
    ```
    The script will prompt for confirmation. This updates the `exportcliv2` symlink and related system records.

3.  **Updating with an Externally Provided New Binary:**
    If you have a new version of an `exportcliv2` binary that was not part of the original package:
    *   First, copy the new binary to an accessible location on the server (e.g., `/opt/software_staging/new_exportcliv2_binary`).
    *   Then, run the orchestrator update from your installation package directory:
        ```bash
        # Ensure you are in the extracted suite directory
        sudo ./deploy_orchestrator.sh --update --new-binary /opt/software_staging/new_exportcliv2_binary
        ```

4.  **Update Authentication Credentials (CRITICAL if changing binary type or requirements):**
    The `exportcliv2` instances use shared authentication credentials from `/etc/exportcliv2/common.auth.conf`. If the new active binary requires different credentials (e.g., switching from an emulator with placeholder credentials to a production binary needing real ones), you **must** update this file.

    *   **View current credentials:**
        ```bash
        cat /etc/exportcliv2/common.auth.conf
        ```
    *   **Edit the credentials file:**
        ```bash
        sudo vi /etc/exportcliv2/common.auth.conf
        ```
        Update `EXPORT_AUTH_TOKEN_U` and `EXPORT_AUTH_TOKEN_P` as required:
        ```ini
        # Common authentication tokens
        EXPORT_AUTH_TOKEN_U="your_correct_username"
        EXPORT_AUTH_TOKEN_P="your_correct_password"
        ```
        Save and exit (e.g., `Esc`, `:wq`, Enter in `vi`).

5.  **Restart All Affected `exportcliv2` Instances:**
    For the new active binary and/or credentials to take effect, all `exportcliv2` instances must be restarted.

    *   **Restart instance "AAA":**
        ```bash
        sudo exportcli-manage -i AAA --restart
        ```
    *   **Restart other configured instances as needed (e.g., "DEF", "GHI"):**
        ```bash
        # sudo exportcli-manage -i DEF --restart
        # sudo exportcli-manage -i GHI --restart
        ```

6.  **Verify Operation with New Active Binary:**
    Check the status of an instance:
    ```bash
    sudo exportcli-manage -i AAA --status -l
    ```
    *   Confirm `Active: active (running)`.
    *   Verify the `Main PID` for `exportcliv2@AAA.service` is running the correct binary (e.g., `exportcliv8` or your production binary name). Check the symlink target: `ls -l /var/tmp/testme/bin/exportcliv2`.
    *   **Crucially, monitor instance logs for successful operation or any errors:**
        ```bash
        sudo exportcli-manage -i AAA --logs-follow
        ```
