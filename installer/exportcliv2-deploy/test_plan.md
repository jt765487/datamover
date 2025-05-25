## Test Plan: exportcliv2 Deployment Suite

**Orchestrator Version:** v2.4.6
**Base Installer Version:** v1.3.2
**Service Manager Version:** v1.3.2
**Target System:** Oracle Linux 9 (or compatible)

---

### I. Environment Preparation

1.  **Clean System:**
    * Start with a clean Oracle Linux 9 system or a VM snapshot to ensure no remnants from previous tests interfere.
    * Ensure `sudo` access is available.

2.  **Required Packages:**
    * Verify/install `python3` and `python3-venv` (or the equivalent for your Python 3 version).
    * Ensure standard utilities like `flock`, `date`, `realpath`, `mktemp`, `sed`, `systemctl`, etc., are present. (The orchestrator's `dependency_check` function will verify its core needs).

3.  **Deployment Package (`exportcliv2-suite-vX.Y.Z.tar.gz`):**
    * Create a directory, e.g., `exportcliv2-suite-vTEST/`.
    * Place the latest `deploy_orchestrator.sh` (**v2.4.6**) in this directory.
    * Create the `exportcliv2-deploy/` subdirectory.
    * Inside `exportcliv2-deploy/`:
        * Place the latest versions of:
            * `install_base_exportcliv2.sh` (**v1.3.2**)
            * `configure_instance.sh` (ensure "Next Steps" point to `exportcli-manage`)
            * `manage_services.sh` (**v1.3.2**)
        * Create a sample `install-app.conf` with the following (adjust paths/names as needed for dummy files):
            ```ini
            # install-app.conf
            DEFAULT_INSTANCES_CONFIG="AAA BBB CCC" # For default install tests
            VERSIONED_APP_BINARY_FILENAME="exportcliv2-vDUMMY"
            VERSIONED_DATAMOVER_WHEEL_FILENAME="datamover-vDUMMY-py3-none-any.whl"
            REMOTE_HOST_URL_CONFIG="[http://127.0.0.1:8989/pcap](http://127.0.0.1:8989/pcap)" # Placeholder
            EXPORT_TIMEOUT_CONFIG="15"
            USER_CONFIG="exportcliv2_user"
            GROUP_CONFIG="datapipeline_group" # Ensure this matches what you expect
            BASE_DIR_CONFIG="/var/tmp/testme" # Or your preferred test base
            ```
        * Create dummy files for the binary and wheel, matching the names in `install-app.conf`:
            * `touch exportcliv2-deploy/exportcliv2-vDUMMY`
            * `touch exportcliv2-deploy/datamover-vDUMMY-py3-none-any.whl`
        * Create `exportcliv2-deploy/config_files/` and populate with your template files.
        * Create `exportcliv2-deploy/systemd_units/` and populate with your systemd unit templates.
    * (Optional) Include your `QUICK_START_GUIDE.md` and `USER_GUIDE.md` for guide testing.
    * Tar and gzip this directory for extraction tests, or work directly from the prepared directory.

4.  **Test Artifacts for Updates:**
    * Prepare separate dummy files for surgical updates, e.g.:
        * `/tmp/new_exportcliv2_v2` (`touch /tmp/new_exportcliv2_v2 && chmod +x /tmp/new_exportcliv2_v2`)
        * `/tmp/new_datamover_v2.whl` (`touch /tmp/new_datamover_v2.whl`)

---

### II. Test Scenarios

**General Verification for each test case:**
* No unexpected error messages in `stderr` or `stdout` (unless the test is designed to produce an error).
* Correct exit codes from scripts (0 for success, specific non-zero for expected failures).
* If `-v` is used, `set -x` output is informative and no "unbound variable" errors occur.
* Timestamps in logs are accurate.
* Colorized logging functions correctly.

---

**A. Fresh Installation (`--install`)**

**Test Case 1.1: Basic Install (Default Instances from `install-app.conf`, No Force)**
* **Objective:** Verify successful installation of base components, default instances (as defined by `DEFAULT_INSTANCES_CONFIG` in `install-app.conf`), and the `bitmover` service. Verify all these services are enabled and started.
* **Setup:** Clean system. `install-app.conf` correctly configured as per "Environment Preparation" (with `DEFAULT_INSTANCES_CONFIG="AAA BBB CCC"`).
* **Command:** `sudo ./deploy_orchestrator.sh --install`
* **Expected Results:**
    1.  Orchestrator logs "Using default instances from config file for --install: AAA BBB CCC".
    2.  Script prompts for confirmation (if TTY). User confirms 'y'.
    3.  Successful execution of `install_base_exportcliv2.sh` (v1.3.2), logs "Starting installation...". Generic restart advice is suppressed.
    4.  Successful execution of `configure_instance.sh` for AAA, BBB, CCC. Output advises using `exportcli-manage`.
    5.  Successful execution of `manage_services.sh` (via orchestrator) to enable and start `bitmover.service`, `exportcliv2@AAA.service` (+ path), `exportcliv2@BBB.service` (+ path), `exportcliv2@CCC.service` (+ path).
    6.  Directories, user (`exportcliv2_user`), group (`datapipeline_group`), files, symlinks created as expected.
    7.  Final "Orchestrator finished successfully" message. Exit code 0.
* **Verification:**
    1.  Check existence and permissions of created directories and files.
    2.  Verify user/group creation (`getent passwd exportcliv2_user`, `getent group datapipeline_group`).
    3.  `sudo exportcli-manage --status` (bitmover active).
    4.  `sudo exportcli-manage -i AAA --status` (instance active). Repeat for BBB, CCC.
    5.  `journalctl` for services.
    6.  `/usr/local/bin/exportcli-manage` symlink.

**Test Case 1.2: Install (Specific Instances via `-i`, No Force)**
* **Objective:** Verify successful installation with user-specified instances (overriding `DEFAULT_INSTANCES_CONFIG`), plus the global `bitmover` service.
* **Setup:** Clean system. `install-app.conf` configured (e.g., with `DEFAULT_INSTANCES_CONFIG="AAA BBB CCC"`).
* **Command:** `sudo ./deploy_orchestrator.sh --install -i "siteX,siteY"`
* **Expected Results:**
    1.  Orchestrator logs "Operating on specified instances from -i: siteX siteY".
    2.  Similar to 1.1, but instance-specific actions apply only to `siteX` and `siteY`.
    3.  `bitmover.service` is still enabled/started.
    4.  Services for AAA, BBB, CCC are *not* configured or started (unless siteX/siteY overlap).
* **Verification:** Check for `/etc/exportcliv2/siteX.conf`, `/etc/exportcliv2/siteY.conf`. `sudo exportcli-manage -i siteX --status` (active). `sudo exportcli-manage --status` (bitmover active). No configs/services for unlisted defaults like AAA.

**Test Case 1.3: Install (No Default Instances in `install-app.conf` - Error Expected)**
* **Objective:** Verify that if `-i` is not used and `DEFAULT_INSTANCES_CONFIG` in `install-app.conf` is empty or missing, the orchestrator exits with an error.
* **Setup:** Clean system. Modify `install-app.conf` to have `DEFAULT_INSTANCES_CONFIG=""` or comment it out.
* **Command:** `sudo ./deploy_orchestrator.sh --install`
* **Expected Results:** Orchestrator script exits with an error message like "DEFAULT_INSTANCES_CONFIG in '.../install-app.conf' is mandatory and must not be empty..." Exit code `EXIT_CODE_CONFIG_ERROR` (4).
* **Verification:** Check error message and exit code.

**Test Case 1.4: Re-Install with `--force` (Using Defaults from `install-app.conf`)**
* **Objective:** Verify `--force` allows overwriting of existing instance configurations.
* **Setup:** Successfully run Test Case 1.1. Manually edit `/etc/exportcliv2/ABC.conf` (if ABC is a default) to add a unique comment.
* **Command:** `sudo ./deploy_orchestrator.sh --install --force`
* **Expected Results:** Instance configs (e.g., ABC, DEF, GHI) are regenerated/overwritten (log shows `WARN` from `configure_instance.sh` about overwriting). Manual comment in `ABC.conf` is gone. Services re-enabled/re-started.
* **Verification:** Content of `/etc/exportcliv2/ABC.conf`. Service statuses as per 1.1.

**Test Case 1.5: Install with Dry Run (`-n`)**
* **Objective:** Verify no actual changes are made, and appropriate "\[DRY-RUN\]" messages are shown by the orchestrator and passed to sub-scripts.
* **Setup:** Clean system. `install-app.conf` configured.
* **Command:** `sudo ./deploy_orchestrator.sh --install -n`
* **Expected Results:** Log output shows "\[DRY-RUN\] Would execute..." for key operations from orchestrator and sub-scripts (which should receive `-n`). Confirmation prompt skipped. Final "Orchestration dry run scan completed."
* **Verification:** File system unchanged. Service statuses unchanged.

**Test Case 1.6: Install with Non-TTY and `--force`**
* **Objective:** Verify confirmation is skipped and installation proceeds.
* **Setup:** Clean system. `install-app.conf` configured.
* **Command:** `echo "y" | sudo ./deploy_orchestrator.sh --install --force` (or `< /dev/null`)
* **Expected Results:** Log message "Non-interactive mode (no TTY): Proceeding with operation due to --force flag." Installation completes as per 1.1.
* **Verification:** Same as Test Case 1.1.

**Test Case 1.7: Install with Non-TTY without `--force` (Failure Expected)**
* **Objective:** Verify script exits with error due to missing confirmation.
* **Setup:** Clean system. `install-app.conf` configured.
* **Command:** `sudo ./deploy_orchestrator.sh --install < /dev/null`
* **Expected Results:** Error message "Non-interactive mode (no TTY): Confirmation required...". Exit code `EXIT_CODE_USAGE_ERROR` (3).
* **Verification:** Check error message and exit code.

**Test Case 1.8: `list-default-instances` Option**
* **Objective:** Verify `--list-default-instances` correctly reads and displays default instances from `install-app.conf`.
* **Setup:** `install-app.conf` has `DEFAULT_INSTANCES_CONFIG="siteM siteN"`.
* **Command:** `./deploy_orchestrator.sh --list-default-instances`
* **Expected Results:** Output shows "Default instances configured in '.../install-app.conf' (via DEFAULT_INSTANCES_CONFIG): siteM siteN". Script exits successfully.
* **Setup 2:** `install-app.conf` has `DEFAULT_INSTANCES_CONFIG=""`.
* **Command 2:** `./deploy_orchestrator.sh --list-default-instances`
* **Expected Results 2:** Output shows "(None specified or list is empty)".
* **Setup 3 (Error case for this option):** `install-app.conf` is missing `DEFAULT_INSTANCES_CONFIG` line entirely.
* **Command 3:** `./deploy_orchestrator.sh --list-default-instances`
* **Expected Results 3:** Script should error out during config sourcing phase, complaining `DEFAULT_INSTANCES_CONFIG` is not set. Exit code `EXIT_CODE_CONFIG_ERROR` (4).
* **Verification:** Match output to expected.

---

**B. Update (`--update`)** (Option `-r` has been removed)

* **Baseline Setup for Update Tests:** Perform a successful fresh installation (Test Case 1.1) as a baseline.

**Test Case 2.1: Bundle Update (No specific new files, no -i)**
* **Objective:** Verify base components are updated using files from the current bundle. Verify user is clearly instructed to manually restart services.
* **Setup:** Successful install.
* **Command:** `sudo ./deploy_orchestrator.sh --update`
* **Expected Results:**
    1.  Confirmation prompt.
    2.  `install_base_exportcliv2.sh` (v1.3.2) runs, logs "Starting update...". Its generic restart advice *is shown* (correct for update context).
    3.  Orchestrator prints "IMPORTANT: Update complete. Services must be restarted manually..." with examples using `exportcli-manage` for both bitmover and instances (as it's a general bundle update).
    4.  "Orchestrator finished successfully".
* **Verification:** Timestamps of installed files. Manually restart services and verify.

**Test Case 2.2: Surgical Update (`--new-binary`)**
* **Objective:** Verify only the binary is updated. User instructed to restart `exportcliv2` instances.
* **Setup:** Successful install. `touch /tmp/new_exportcliv2_v2; chmod +x /tmp/new_exportcliv2_v2`.
* **Command:** `sudo ./deploy_orchestrator.sh --update --new-binary /tmp/new_exportcliv2_v2`
* **Expected Results:**
    1.  New binary used by `install_base_exportcliv2.sh` (log shows new binary name).
    2.  Orchestrator's "IMPORTANT: Update complete..." message specifically advises restarting `exportcliv2` instances (e.g., `sudo exportcli-manage -i <INSTANCE_NAME> --restart`), and *not* necessarily bitmover.
* **Verification:** Symlink target. Manually restart an instance; verify.

**Test Case 2.3: Surgical Update (`--new-wheel`)**
* **Objective:** Verify only the wheel is updated. User instructed to restart `bitmover.service`.
* **Setup:** Successful install. `touch /tmp/new_datamover_v2.whl`.
* **Command:** `sudo ./deploy_orchestrator.sh --update --new-wheel /tmp/new_datamover_v2.whl`
* **Expected Results:**
    1.  New wheel used by `install_base_exportcliv2.sh` (log shows new wheel name).
    2.  Orchestrator's "IMPORTANT: Update complete..." message specifically advises restarting `bitmover.service` (e.g., `sudo exportcli-manage --restart`), and *not* necessarily instances.
* **Verification:** Pip list in venv. Manually restart bitmover; verify.

**Test Case 2.4: Surgical Update (`--new-binary` and `--new-wheel`)**
* **Objective:** Verify both components updated. User instructed to restart both `bitmover.service` and `exportcliv2` instances.
* **Setup:** Successful install. Use dummy files from 2.2 and 2.3.
* **Command:** `sudo ./deploy_orchestrator.sh --update --new-binary /tmp/new_exportcliv2_v2 --new-wheel /tmp/new_datamover_v2.whl`
* **Expected Results:** Orchestrator's "IMPORTANT: Update complete..." message advises restarting both service types.
* **Verification:** Symlink target, pip list. Manually restart services; verify.

**Test Case 2.5: Update with Dry Run (`-n`)**
* **Objective:** Verify no actual changes. "\[DRY-RUN\]" messages shown.
* **Setup:** Successful install. Dummy new binary.
* **Command:** `sudo ./deploy_orchestrator.sh --update --new-binary /tmp/new_exportcliv2_v2 -n`
* **Expected Results:** Log output with "\[DRY-RUN\]" messages. Confirmation skipped. No files changed.
* **Verification:** File system, service status unchanged.

---

**C. Service Management (`exportcli-manage` v1.3.2)**
*(These tests largely remain the same as your successful runs, just re-confirming with the latest version that includes the restart warning)*

* **Baseline Setup:** Successful fresh install (Test Case 1.1).

**Test Case 3.1: Status Checks (Active and Inactive)**
* **Objective:** Verify correct reporting.
* **Commands & Expected:** As before, ensuring the `INFO: Service ... is inactive/dead` and successful script exit for inactive services.

**Test Case 3.2: Start/Stop/Restart Actions**
* **Objective:** Verify actions, especially the new warning message for `--restart`.
* **Commands:** `... --stop`, `... --start`, `... --restart`.
* **Expected for `--restart`:**
    * `INFO: Attempting to restart ...`
    * `INFO: This operation involves stopping and then starting ...`
    * `INFO: If a service is slow to stop, this command may appear to hang ... Please wait for completion...`
    * Service restarts successfully (assuming application behaves).
* **Verification:** `exportcli-manage --status`; `journalctl`.

**Test Case 3.3: Enable/Disable Actions**
* **Objective & Commands:** Same as before.
* **Verification:** `systemctl is-enabled`; optional reboot.

**Test Case 3.4: Logs and Logs-Follow Actions**
* **Objective & Commands:** Same as before.
* **Verification:** Compare with `journalctl`.

**Test Case 3.5: Dry Run (`-n`) for `exportcli-manage`**
* **Objective & Commands:** Same as before.
* **Verification:** "\[DRY-RUN\]" messages; service state unchanged.

---

**D. Error Handling and Edge Cases (Orchestrator `deploy_orchestrator.sh` v2.4.6)**
*(These tests also largely remain the same but verify against the newest orchestrator)*

**Test Case 4.1: Missing Sub-script** - Expected: Error `EXIT_CODE_FILE_ERROR`.
**Test Case 4.2: Missing `install-app.conf`** - Expected: Error `EXIT_CODE_CONFIG_ERROR`.
**Test Case 4.3: Invalid Instance Name Format in Orchestrator `-i` list** - Expected: Error `EXIT_CODE_USAGE_ERROR`.
**Test Case 4.3b: Invalid Instance Name Format in `DEFAULT_INSTANCES_CONFIG` in `install-app.conf`**
    * **Setup:** Edit `install-app.conf` to have `DEFAULT_INSTANCES_CONFIG="valid_name invalid!"`.
    * **Command:** `sudo ./deploy_orchestrator.sh --install`
    * **Expected:** Error message "Invalid default instance name format in DEFAULT_INSTANCES_CONFIG ('invalid!') ...". Exit code `EXIT_CODE_CONFIG_ERROR`.
**Test Case 4.4: Lock File Acquisition** - Expected: Error `EXIT_CODE_FATAL_ERROR`.
**Test Case 4.5: User Abort at Confirmation Prompt** - Expected: "User aborted operation." Exit code `EXIT_CODE_SUCCESS`.
**Test Case 4.6: Surgical Update with Missing External File** - Expected: Error `EXIT_CODE_FILE_ERROR`.
**Test Case 4.7: Mandatory `DEFAULT_INSTANCES_CONFIG` missing for default install**
    * **Setup:** Edit `install-app.conf`, comment out or make `DEFAULT_INSTANCES_CONFIG` empty.
    * **Command:** `sudo ./deploy_orchestrator.sh --install`
    * **Expected:** Error "DEFAULT_INSTANCES_CONFIG in '.../install-app.conf' is mandatory...". Exit code `EXIT_CODE_CONFIG_ERROR`.

---

**E. User Guide and Quick Start Guide Review**

**Test Case 5.1: Follow Quick Start Guide Precisely**
* **Objective:** Verify QSG aligns with v2.4.6 orchestrator (defaults from config, manual restart on update).
* **Steps & Verification:** As before, noting changes.

**Test Case 5.2: Follow Key User Guide Scenarios**
* **Objective:** Verify User Guide aligns with v2.4.6 orchestrator.
* **Steps & Verification:** As before, noting changes, particularly for default instance setup and update procedures.

