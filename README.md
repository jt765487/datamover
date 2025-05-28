## First-Time Installation Guide for DataMover Application Suite

This guide will walk you through installing the DataMover application suite, which includes the `exportcliv2` data export client and the `bitmover` PCAP upload service. We'll set up a single instance named "AAA" as per your test environment.

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

**Step 2: Configure the Installer (`install-app.conf`)**

The main configuration file for the installer is `exportcliv2-deploy/install-app.conf`. We'll ensure it's set up for your test environment.

1.  Your notes indicate you've already modified this file. Let's verify the key settings. You can view it with `cat exportcliv2-deploy/install-app.conf`. The important lines for this first install should look like this:

    ```ini
    # install-app.conf

    # ... (comments omitted for brevity) ...

    # MANDATORY: Space-separated list of instance names.
    DEFAULT_INSTANCES_CONFIG="AAA"

    # MANDATORY: The filename of the VERSIONED main application binary.
    # (This is your Rust emulator)
    VERSIONED_APP_BINARY_FILENAME="exportcliv8"

    # MANDATORY: The filename of the VERSIONED DataMover Python wheel.
    VERSIONED_DATAMOVER_WHEEL_FILENAME="datamover-0.1.2-py3-none-any.whl"

    # MANDATORY: The remote URL for the Bitmover component to upload data to.
    # Ensure this is reachable from your server.
    REMOTE_HOST_URL_CONFIG="http://192.168.0.180:8989/pcap"

    # MANDATORY: Timeout (-t) in seconds for exportcliv2 instances.
    EXPORT_TIMEOUT_CONFIG="15"

    # MANDATORY (for offline installer fallback): Subdirectory for dependency wheels.
    WHEELHOUSE_SUBDIR="wheelhouse"

    # --- Optional Overrides ---
    # USER_CONFIG: Overrides the default service user name.
    USER_CONFIG="exportcliv2_user"

    # GROUP_CONFIG: Overrides the default service group name.
    GROUP_CONFIG="datapipeline_group"

    # BASE_DIR_CONFIG: Overrides the default base installation directory.
    BASE_DIR_CONFIG="/var/tmp/testme"

    # ... (other optional settings can be left as default for now) ...
    ```
    **Note:** Ensure the `WHEELHOUSE_SUBDIR="wheelhouse"` line is present as it's crucial for the offline installation capabilities.

2.  If you need to make changes, edit the file:
    ```bash
    # cd exportcliv2-deploy/  (if you are in /root/exportcliv2-suite-v0.1.2)
    # vi install-app.conf
    # cd .. (back to /root/exportcliv2-suite-v0.1.2)
    ```
    Or, from `/root/exportcliv2-suite-v0.1.2`:
    ```bash
    vi exportcliv2-deploy/install-app.conf
    ```

**Step 3: Run the Installation**

Now, execute the main deployment script to install the application.

1.  From the `exportcliv2-suite-v0.1.2/` directory, run:
    ```bash
    sudo ./deploy_orchestrator.sh --install
    ```
2.  The script will perform checks and then ask for confirmation:
    ```
    2025-05-28T13:22:07Z [INFO] Operation Mode: install
    2025-05-28T13:22:07Z [INFO] Using default instances from config file for --install: AAA
    Proceed with install for instances: (AAA) using source '/root/exportcliv2-suite-v0.1.2'? [y/N]
    ```
    Type `y` and press Enter.
3.  The installer will proceed, creating users/groups, directories, installing components, and setting up systemd services. You'll see output similar to your successful installation log:
    ```
    2025-05-28T13:22:09Z [INFO] User confirmed. Proceeding.
    2025-05-28T13:22:09Z [INFO] ▶ Orchestrator v2.4.6 starting (Mode: install)
    # ... (lots of informative output as seen in your test run) ...
    2025-05-28T13:22:13Z [INFO] Starting instance configuration for 'AAA' (v4.1.0)...
    # ...
    2025-05-28T13:22:13Z [INFO] Default configurations were generated. Please review and edit them as needed:
    2025-05-28T13:22:13Z [INFO]     - /etc/exportcliv2/AAA.conf (especially EXPORT_IP, EXPORT_PORTID)
    # ...
    2025-05-28T13:22:13Z [INFO] --- Enabling main Bitmover service ---
    # ...
    2025-05-28T13:22:13Z [INFO] --- Starting main Bitmover service ---
    # ...
    2025-05-28T13:22:13Z [INFO] --- Enabling services for instance: AAA ---
    # ...
    2025-05-28T13:22:14Z [INFO] --- Starting services for instance: AAA ---
    # ...
    2025-05-28T13:22:14Z [INFO] ▶ Orchestrator finished successfully.
    ```
    This process installs:
    *   The `bitmover` service.
    *   The `exportcliv2` instance "AAA".
    *   The watcher service for restarting instance "AAA".
    *   The `exportcli-manage` command-line tool (symlinked to `/usr/local/bin/exportcli-manage`).

**Step 4: Post-Installation Configuration (Critical for `exportcliv2` Instance)**

The installer sets up default configuration files. You **must** edit the instance-specific configuration for "AAA" to point to your actual data source.

1.  Edit the instance configuration file for "AAA":
    ```bash
    sudo nano /etc/exportcliv2/AAA.conf
    ```
    (You can use `vi` or any other text editor if you prefer.)
2.  This file contains environment variables for the `exportcliv2` client. You need to update `EXPORT_IP` and `EXPORT_PORTID`:
    ```ini
    # Generated by configure_instance.sh ...
    EXPORT_TIMEOUT="15" # From EXPORT_TIMEOUT_CONFIG in install-app.conf
    EXPORT_SOURCE="AAA" # Default, a unique tag for this instance's data
    EXPORT_STARTTIME_OFFSET_SPEC="3 minutes ago" # Default
    EXPORT_ENDTIME="-1" # Default
    # ---- EDIT THESE TWO LINES ----
    EXPORT_IP="10.0.0.1" # Change this to the actual IP address of your data source
    EXPORT_PORTID="1"    # Change this to the actual port/interface ID for your data source
    # -----------------------------
    EXPORT_APP_CONFIG_FILE_PATH="/etc/exportcliv2/AAA_app.conf" # Default path
    ```
3.  Save the file (e.g., `Ctrl+O`, Enter, then `Ctrl+X` in `nano`).

**Step 5: Restart the `exportcliv2` Instance**

Since you've changed its configuration, restart the "AAA" instance:
```bash
sudo exportcli-manage -i AAA --restart
```
You'll see output like:
```
2025-05-28T13:22:14Z [INFO] Performing 'restart' on exportcliv2 instance 'AAA' (Dry-run: false)
# ... (service restart messages) ...
2025-05-28T13:22:14Z [INFO] ▶ Service Management Script (exportcli-manage) finished successfully.
```
*Note: The restart might take a moment as it stops and starts the service.*

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
       Main PID: <PID_NUMBER> (exportcliv8)
    ```
    And for the path unit:
    ```
    ● exportcliv2-restart@AAA.path - Path watcher to trigger restart for exportcliv2 instance AAA
         Loaded: loaded (/etc/systemd/system/exportcliv2-restart@.path; enabled; preset: disabled)
         Active: active (waiting) since Mon 2025-05-28 <TIME> <TIMEZONE>; ...
    ```

**Step 7: Understanding Key Directories and Files**

The application installs its components and working directories under `/var/tmp/testme/` (as configured in `install-app.conf`). Here's a simplified overview:

*   `/var/tmp/testme/`: Base directory.
    *   `bin/`: Contains the `exportcliv2` executable (symlinked as `exportcliv2` pointing to `exportcliv8` initially), `run_exportcliv2_instance.sh` wrapper, and `manage_services.sh`.
        ```
        [root@vbox testme]# ls -l bin/
        total <SIZE>
        lrwxrwxrwx 1 root             root                    <X> May 28 <TIME> exportcliv2 -> exportcliv8
        -rwxr-x--- 1 root             datapipeline_group <SIZE> May 28 <TIME> exportcliv8
        -rwxr-xr-x 1 root             datapipeline_group  <SIZE> May 28 <TIME> manage_services.sh
        -rwxr-x--- 1 exportcliv2_user datapipeline_group  <SIZE> May 28 <TIME> run_exportcliv2_instance.sh
        ```    *   `csv/`: Holds CSV hash files generated by `exportcliv2` instances (e.g., `AAA.csv`). Also, creating a file like `AAA.restart` here will trigger a restart of the "AAA" instance (the file is deleted quickly).
        ```
        [root@vbox testme]# ls -l csv/
        total <SIZE>
        -rw-r----- 1 exportcliv2_user datapipeline_group <SIZE> May 28 <TIME> AAA.csv
        ```
    *   `datamover_venv/`: Python virtual environment for the `bitmover` service.
    *   `source/`: `exportcliv2` instances will place generated PCAP files here. `bitmover` picks them up.
    *   `worker/`: `bitmover` moves files from `source/` to here while processing and attempting uploads.
    *   `uploaded/`: Successfully uploaded PCAP files are moved here.
        ```
        [root@vbox testme]# ls -l uploaded/ | head
        total <SIZE>
        -rw-r----- 1 exportcliv2_user datapipeline_group <SIZE> May 28 <TIME> AAA-<TIMESTAMP>.pcap
        # ... more files
        ```
    *   `dead_letter/`: PCAP files that failed to upload (due to non-retriable errors) go here.

**Step 8: Checking Logs**

Logs are crucial for troubleshooting.

1.  **Log Directory Structure:**
    As per your setup, logs are in `/var/log/exportcliv2/`.
    ```bash
    [root@vbox ~]# ls -lR /var/log/exportcliv2/
    /var/log/exportcliv2/:
    total <SIZE>
    drwxr-x--- 2 exportcliv2_user datapipeline_group <SIZE> May 28 <TIME> AAA
    drwxrwx--- 2 exportcliv2_user datapipeline_group <SIZE> May 28 <TIME> bitmover

    /var/log/exportcliv2/AAA:
    total 0  # Systemd journal handles logs for exportcliv2@AAA by default.
             # This directory is its WorkingDirectory; systemd may also use LogsDirectory= here.

    /var/log/exportcliv2/bitmover:
    total <SIZE>
    -rw-r----- 1 exportcliv2_user datapipeline_group <SIZE> May 28 <TIME> app.log.jsonl
    -rw-r----- 1 exportcliv2_user datapipeline_group <SIZE> May 28 <TIME> audit.log.jsonl
    ```
    *   **`bitmover` service logs:**
        *   `/var/log/exportcliv2/bitmover/app.log.jsonl`: Main application log (JSONL format), contains detailed operational messages, errors, and debug information.
        *   `/var/log/exportcliv2/bitmover/audit.log.jsonl`: Audit log (JSONL format), specifically records details of file upload attempts (successes and failures), including timestamps, filenames, sizes, destination URLs, and status codes.
    *   **`exportcliv2` instance ("AAA") logs:** These are primarily handled by `systemd-journald`. The directory `/var/log/exportcliv2/AAA/` is its working directory.

2.  **Viewing Logs with `exportcli-manage`:**
    The `exportcli-manage` tool primarily targets the main application logs.

    *   **Follow `bitmover` main application logs (`app.log.jsonl`):**
        ```bash
        sudo exportcli-manage --logs-follow
        ```
        (Press `Ctrl+C` to stop following)
    *   **Follow `exportcliv2` instance "AAA" logs:**
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
        (You can add `--since "10m"` or similar timeframes to these commands).
    *   **To view the `bitmover` audit log directly:**
        You can use standard Linux commands like `cat`, `less`, `tail`, or `grep` on `/var/log/exportcliv2/bitmover/audit.log.jsonl`. For example:
        ```bash
        sudo tail -n 20 /var/log/exportcliv2/bitmover/audit.log.jsonl
        sudo less /var/log/exportcliv2/bitmover/audit.log.jsonl
        ```

**Optional: Updating the `exportcliv2` Binary (e.g., Switching to Official Binary)**

If you later need to use a different `exportcliv2` binary (for example, switching from the bundled Rust emulator to an official Netscout binary), follow these steps:

1.  **Place the New Binary:**
    Copy the new `exportcliv2` binary to an accessible location on your server. For example:
    `/root/exportcliv2-official-vx.y.z`

2.  **Run the Orchestrator Update:**
    From your installation directory (e.g., `/root/exportcliv2-suite-v0.1.2/`), run the `deploy_orchestrator.sh` script with the `--update` and `--new-binary` flags:
    ```bash
    sudo ./deploy_orchestrator.sh --update --new-binary /root/exportcliv2-official-vx.y.z
    ```
    The script will prompt for confirmation. Type `y` and press Enter.
    This will copy the new binary into the application's `bin` directory (e.g., `/var/tmp/testme/bin/`) and update the `exportcliv2` symlink to point to this new binary.

3.  **Update Credentials (IMPORTANT):**
    The `exportcliv2` instances use credentials stored in `/etc/exportcliv2/common.auth.conf`. If you are switching to an official binary, you will likely need to update these from any placeholder/emulator values to real credentials.

    *   Check the current credentials:
        ```bash
        cat /etc/exportcliv2/common.auth.conf
        ```
        You might see something like:
        ```ini
        # Common authentication tokens
        EXPORT_AUTH_TOKEN_U="shared_user"
        EXPORT_AUTH_TOKEN_P="shared_password"
        ```
    *   Edit the file to input the correct username and password for the new binary:
        ```bash
        sudo nano /etc/exportcliv2/common.auth.conf
        ```
        Update the `EXPORT_AUTH_TOKEN_U` and `EXPORT_AUTH_TOKEN_P` values:
        ```ini
        # Common authentication tokens
        EXPORT_AUTH_TOKEN_U="your_actual_username"
        EXPORT_AUTH_TOKEN_P="your_actual_password"
        ```
        Save the file (`Ctrl+O`, Enter, then `Ctrl+X` in `nano`).

4.  **Restart Affected `exportcliv2` Instances:**
    After the binary update and credential update, you **must restart** any `exportcliv2` instances that use this binary for the changes to take effect:
    ```bash
    sudo exportcli-manage -i AAA --restart
    ```
    If you have other instances (e.g., DEF, GHI) that were also using the previous binary, restart them as well:
    ```bash
    # sudo exportcli-manage -i DEF --restart
    # sudo exportcli-manage -i GHI --restart
    ```
    *Note: The restart might take a moment as it stops and starts the service.*

5.  **Verify Operation:**
    Check the status of the instance to ensure it's running with the new binary and (implicitly) using the new credentials. Use the `-l` flag for more detailed output, which can sometimes show the full command line of the running process.
    ```bash
    sudo exportcli-manage -i AAA --status -l
    ```
    Look for `Active: active (running)`. The `Main PID` line in the status output for `exportcliv2@AAA.service` should show the `exportcliv2` process. Examining the full command line (if shown by `-l` or in `/proc/<PID>/cmdline`) would confirm the new binary path is being used. More importantly, check the instance logs for successful operation or any authentication errors:
    ```bash
    sudo exportcli-manage -i AAA --logs-follow
    ```
