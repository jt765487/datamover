## First-Time Installation Guide for DataMover Application Suite

This guide will walk you through installing the DataMover application suite, which includes the `exportcliv2` data export client and the `bitmover` PCAP upload service. We'll set up a single instance named "AAA" as per your test environment.

**Before You Begin:**

1.  **System:** Ensure you're on an Oracle Linux 9 (or compatible RHEL 9 derivative) system.
2.  **Privileges:** You'll need `sudo` or `root` access for installation and service management.
3.  **Package:** You should have the `exportcliv2-suite-v0.1.1.tar.gz` package.
4.  **Dependencies:** Make sure `python3-venv` is installed (`sudo dnf install python3-venv`). Other common utilities are usually present.

**Step 1: Prepare the Installation Package**

1.  Copy the `exportcliv2-suite-v0.1.1.tar.gz` package to your server, for example, in the `/root` directory.
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
    total 1768
    -rw-r--r-- 1 root root    1364 May 23 03:28 chrony.conf.bak
    -rw-r--r-- 1 root root    1364 May 23 03:28 chrony.conf.orig
    -rw-r--r-- 1 root root 1796699 May 26 03:00 exportcliv2-suite-v0.1.1.tar.gz
    [root@vbox ~]# tar vxf exportcliv2-suite-v0.1.1.tar.gz
    exportcliv2-suite-v0.1.1/
    exportcliv2-suite-v0.1.1/exportcliv2-deploy/
    # ... (tar output shortened for brevity) ...
    exportcliv2-suite-v0.1.1/QUICK_START_GUIDE.md
    exportcliv2-suite-v0.1.1/USER_GUIDE.md
    [root@vbox ~]# ll
    total 1772
    -rw-r--r-- 1 root    root       1364 May 23 03:28 chrony.conf.bak
    -rw-r--r-- 1 root    root       1364 May 23 03:28 chrony.conf.orig
    drwxr-xr-x 3 ngenius ngenius    4096 May 26 02:39 exportcliv2-suite-v0.1.1 # Ownership might vary
    -rw-r--r-- 1 root    root    1796699 May 26 03:00 exportcliv2-suite-v0.1.1.tar.gz
    ```
4.  Navigate into the extracted directory:
    ```bash
    cd exportcliv2-suite-v0.1.1/
    [root@vbox exportcliv2-suite-v0.1.1]# pwd
    /root/exportcliv2-suite-v0.1.1
    ```
    All subsequent commands will be run from this `exportcliv2-suite-v0.1.1/` directory.

**Step 2: Configure the Installer (`install-app.conf`)**

The main configuration file for the installer is `exportcliv2-deploy/install-app.conf`. We'll ensure it's set up for your test environment.

1.  Your notes indicate you've already modified this file. Let's verify the key settings. You can view it with `cat exportcliv2-deploy/install-app.conf`. The important lines for this first install should look like this:

    ```ini
    # install-app.conf (NEW PROPOSED FORMAT)

    # ... (comments omitted for brevity) ...

    # MANDATORY: Space-separated list of instance names.
    DEFAULT_INSTANCES_CONFIG="AAA"

    # MANDATORY: The filename of the VERSIONED main application binary.
    # (This is your Rust emulator)
    VERSIONED_APP_BINARY_FILENAME="exportcliv8"

    # MANDATORY: The filename of the VERSIONED DataMover Python wheel.
    VERSIONED_DATAMOVER_WHEEL_FILENAME="datamover-0.1.1-py3-none-any.whl"

    # MANDATORY: The remote URL for the Bitmover component to upload data to.
    # Ensure this is reachable from your server.
    REMOTE_HOST_URL_CONFIG="http://192.168.0.180:8989/pcap"

    # MANDATORY: Timeout (-t) in seconds for exportcliv2 instances.
    EXPORT_TIMEOUT_CONFIG="15"

    # --- Optional Overrides ---
    # USER_CONFIG: Overrides the default service user name.
    USER_CONFIG="exportcliv2_user"

    # GROUP_CONFIG: Overrides the default service group name.
    GROUP_CONFIG="datapipeline_group"

    # BASE_DIR_CONFIG: Overrides the default base installation directory.
    BASE_DIR_CONFIG="/var/tmp/testme"

    # ... (other optional settings can be left as default for now) ...
    ```
2.  If you need to make changes, edit the file:
    ```bash
    # cd exportcliv2-deploy/  (if you are in /root/exportcliv2-suite-v0.1.1)
    # vi install-app.conf
    # cd .. (back to /root/exportcliv2-suite-v0.1.1)
    ```
    Or, from `/root/exportcliv2-suite-v0.1.1`:
    ```bash
    vi exportcliv2-deploy/install-app.conf
    ```

**Step 3: Run the Installation**

Now, execute the main deployment script to install the application.

1.  From the `exportcliv2-suite-v0.1.1/` directory, run:
    ```bash
    sudo ./deploy_orchestrator.sh --install
    ```
2.  The script will perform checks and then ask for confirmation:
    ```
    2025-05-26T07:23:07Z [INFO] Operation Mode: install
    2025-05-26T07:23:07Z [INFO] Using default instances from config file for --install: AAA
    Proceed with install for instances: (AAA) using source '/root/exportcliv2-suite-v0.1.1'? [y/N]
    ```
    Type `y` and press Enter.
3.  The installer will proceed, creating users/groups, directories, installing components, and setting up systemd services. You'll see output similar to this:
    ```
    2025-05-26T07:23:14Z [INFO] User confirmed. Proceeding.
    2025-05-26T07:23:14Z [INFO] ▶ Orchestrator v2.4.6 starting (Mode: install)
    # ... (lots of informative output) ...
    2025-05-26T07:23:19Z [INFO] Starting instance configuration for 'AAA' (v4.1.0)...
    # ...
    2025-05-26T07:23:19Z [INFO] Default configurations were generated. Please review and edit them as needed:
    2025-05-26T07:23:19Z [INFO]     - /etc/exportcliv2/AAA.conf (especially EXPORT_IP, EXPORT_PORTID)
    # ...
    2025-05-26T07:23:19Z [INFO] --- Enabling main Bitmover service ---
    # ...
    2025-05-26T07:23:19Z [INFO] --- Starting main Bitmover service ---
    # ...
    2025-05-26T07:23:19Z [INFO] --- Enabling services for instance: AAA ---
    # ...
    2025-05-26T07:23:20Z [INFO] --- Starting services for instance: AAA ---
    # ...
    2025-05-26T07:23:20Z [INFO] ▶ Orchestrator finished successfully.
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
3.  Save the file (`Ctrl+O`, Enter, then `Ctrl+X` in `nano`).

**Step 5: Restart the `exportcliv2` Instance**

Since you've changed its configuration, restart the "AAA" instance:
```bash
sudo exportcli-manage -i AAA --restart
```
You'll see output like:
```
2025-05-26T07:44:17Z [INFO] Performing 'restart' on exportcliv2 instance 'AAA' (Dry-run: false)
# ... (service restart messages) ...
2025-05-26T07:44:17Z [INFO] ▶ Service Management Script (exportcli-manage) finished successfully.
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
         Active: active (running) since Mon 2025-05-26 03:23:19 EDT; ...
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
         Active: active (running) since Mon 2025-05-26 03:44:17 EDT; ...
       Main PID: 4729 (exportcliv2)
    ```
    And for the path unit:
    ```
    ● exportcliv2-restart@AAA.path - Path watcher to trigger restart for exportcliv2 instance AAA
         Loaded: loaded (/etc/systemd/system/exportcliv2-restart@.path; enabled; preset: disabled)
         Active: active (waiting) since Mon 2025-05-26 03:23:20 EDT; ...
    ```

**Step 7: Understanding Key Directories and Files**

The application installs its components and working directories under `/var/tmp/testme/` (as configured in `install-app.conf`). Here's a simplified overview:

*   `/var/tmp/testme/`: Base directory.
    *   `bin/`: Contains the `exportcliv2` executable (symlinked as `exportcliv2` pointing to `exportcliv8` initially), `run_exportcliv2_instance.sh` wrapper, and `manage_services.sh`.
        ```
        [root@vbox testme]# ls -l bin/
        total 5840
        lrwxrwxrwx 1 root             root                    11 May 26 03:23 exportcliv2 -> exportcliv8
        -rwxr-x--- 1 root             datapipeline_group 5942320 May 26 03:23 exportcliv8
        -rwxr-xr-x 1 root             datapipeline_group   19638 May 26 03:23 manage_services.sh
        -rwxr-x--- 1 exportcliv2_user datapipeline_group    3329 May 26 03:23 run_exportcliv2_instance.sh
        ```
    *   `csv/`: Holds CSV hash files generated by `exportcliv2` instances (e.g., `AAA.csv`). Also, creating a file like `AAA.restart` here will trigger a restart of the "AAA" instance (the file is deleted quickly).
        ```
        [root@vbox testme]# ls -l csv/
        total 4
        -rw-r----- 1 exportcliv2_user datapipeline_group 3224 May 26 03:29 AAA.csv
        ```
    *   `datamover_venv/`: Python virtual environment for the `bitmover` service.
    *   `source/`: `exportcliv2` instances will place generated PCAP files here. `bitmover` picks them up.
    *   `worker/`: `bitmover` moves files from `source/` to here while processing and attempting uploads.
    *   `uploaded/`: Successfully uploaded PCAP files are moved here.
        ```
        [root@vbox testme]# ls -l uploaded/ | head
        total 108
        -rw-r----- 1 exportcliv2_user datapipeline_group 26 May 26 03:23 AAA-20250526-032335.pcap
        # ... more files
        ```
    *   `dead_letter/`: PCAP files that failed to upload (due to non-retriable errors) go here.

**Step 8: Checking Logs**

Logs are crucial for troubleshooting.

1.  **Log Directory Structure:**
    As per your setup, logs are in `/var/log/exportcliv2/`.
    ```
    [root@vbox exportcliv2-suite-v0.1.1]# ls -lR /var/log/exportcliv2/
    /var/log/exportcliv2/:
    total 8
    drwxr-x--- 2 exportcliv2_user datapipeline_group 4096 May 26 03:23 AAA
    drwxrwx--- 2 exportcliv2_user datapipeline_group 4096 May 26 03:23 bitmover

    /var/log/exportcliv2/AAA:
    total 0  # Systemd journal handles logs for exportcliv2@AAA by default.
             # The directory itself is for WorkingDirectory and systemd LogsDirectory=

    /var/log/exportcliv2/bitmover:
    total 148
    -rw-r----- 1 exportcliv2_user datapipeline_group 145815 May 26 03:26 app.log.jsonl
    ```
    *   **`bitmover` service logs:** `/var/log/exportcliv2/bitmover/app.log.jsonl` (JSONL format).
    *   **`exportcliv2` instance ("AAA") logs:** These are primarily handled by `systemd-journald`. The directory `/var/log/exportcliv2/AAA/` is its working directory.

2.  **Viewing Logs with `exportcli-manage`:**

    *   **Follow `bitmover` logs:**
        ```bash
        sudo exportcli-manage --logs-follow
        ```
        (Press `Ctrl+C` to stop following)
    *   **Follow `exportcliv2` instance "AAA" logs:**
        ```bash
        sudo exportcli-manage -i AAA --logs-follow
        ```
    *   **Show recent `bitmover` logs:**
        ```bash
        sudo exportcli-manage --logs
        ```
    *   **Show recent `exportcliv2` instance "AAA" logs:**
        ```bash
        sudo exportcli-manage -i AAA --logs
        ```
        (You can add `--since "10m"` or similar timeframes to these commands).

**Optional: Updating the `exportcliv2` Binary**

If you later need to use a different `exportcliv2` binary (e.g., the official Netscout one instead of your emulator):

1.  Place the new binary somewhere accessible, e.g., `/root/exportcliv2-real.bin`.
2.  Run the orchestrator in update mode from the `exportcliv2-suite-v0.1.1/` directory:
    ```bash
    sudo ./deploy_orchestrator.sh --update --new-binary /root/exportcliv2-real.bin
    ```
    Confirm when prompted.
3.  After the update script finishes, you **must restart** the affected `exportcliv2` instances:
    ```bash
    sudo exportcli-manage -i AAA --restart
    # Repeat for other instances if you have them:
    # sudo exportcli-manage -i DEF --restart
    # sudo exportcli-manage -i GHI --restart
    ```
4.  Verify the instance is running with the new binary by checking the status (`sudo exportcli-manage -i AAA --status -l`). The command line for the process will show the new binary path if the symlink was updated correctly.
