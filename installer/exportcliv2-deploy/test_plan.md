## Test Plan: exportcliv2 Deployment Suite

**Orchestrator Version:** v2.4.4 (and relevant sub-script versions)
**Target System:** Oracle Linux 9 (or compatible)

---

### I. Environment Preparation

1.  **Clean System:**
    * Start with a clean Oracle Linux 9 system or a VM snapshot to ensure no remnants from previous tests interfere.
    * Ensure `sudo` access is available.

2.  **Required Packages:**
    * Verify/install `python3` and `python3-venv` (or the equivalent for your Python 3 version).
    * Ensure standard utilities like `flock`, `date`, `realpath`, `mktemp`, `sed`, `systemctl`, etc., are present. (The orchestrator's `dependency_check` function will verify its core needs).

3.  **Mock Deployment Package (`exportcliv2-suite-vTEST.tar.gz`):**
    * Create a directory, e.g., `exportcliv2-suite-vTEST/`.
    * Place the latest `deploy_orchestrator.sh` (v2.4.4) in this directory.
    * Create the `exportcliv2-deploy/` subdirectory.
    * Inside `exportcliv2-deploy/`:
        * Place the latest versions of:
            * `install_base_exportcliv2.sh`
            * `configure_instance.sh`
            * `manage_services.sh` (the version with fixes for `systemctl status` handling)
        * Create a sample `install-app.conf` (see Appendix A.1 of your User Guide for a template). Ensure placeholders are ready for test-specific values.
            * **Crucial:** For initial tests, ensure `VERSIONED_APP_BINARY_FILENAME` and `VERSIONED_DATAMOVER_WHEEL_FILENAME` are set.
        * Create dummy files for the binary and wheel, matching the names in `install-app.conf`:
            * `touch exportcliv2-deploy/exportcliv2-vDUMMY`
            * `touch exportcliv2-deploy/datamover-vDUMMY-py3-none-any.whl`
        * Create `exportcliv2-deploy/config_files/` and populate with your template files (e.g., `config.ini.template`, `run_exportcliv2_instance.sh.template`).
        * Create `exportcliv2-deploy/systemd_units/` and populate with your systemd unit templates.
    * (Optional) Include your `QUICK_START_GUIDE.md` and `USER_GUIDE.md` for guide testing.
    * Tar and gzip this directory to simulate the distribution package for extraction tests, or work directly from the prepared directory.

4.  **Test Artifacts for Updates:**
    * Prepare separate dummy files for surgical updates, e.g.:
        * `/tmp/new_exportcliv2_v2` (for `--new-binary` tests)
        * `/tmp/new_datamover_v2.whl` (for `--new-wheel` tests)

---

### II. Test Scenarios

**General Verification for each test case:**
* No unexpected error messages in `stderr` or `stdout` (unless the test is designed to produce an error).
* Correct exit codes from scripts (0 for success, specific non-zero for expected failures).
* If `-v` is used, `set -x` output is informative.
* Timestamps in logs are accurate.
* Colorized logging functions correctly.

---

**A. Fresh Installation (`--install`)**

**Test Case 1.1: Basic Install (Default Instances, No Force)**
* **Objective:** Verify successful installation of base components, default instances (AAA, BBB, CCC as defined in `DEFAULT_INSTANCES` in the orchestrator), and the `bitmover` service. Verify all these services are enabled and started.
* **Setup:** Clean system. `install-app.conf` correctly configured with valid (dummy) binary/wheel filenames and a `REMOTE_HOST_URL_CONFIG`. `DEFAULT_INSTANCES` in orchestrator is `(AAA BBB CCC)`.
* **Command:** `sudo ./deploy_orchestrator.sh --install`
* **Expected Results:**
    1.  Script prompts for confirmation (if TTY). User confirms 'y'.
    2.  Successful execution of `install_base_exportcliv2.sh`.
    3.  Successful execution of `configure_instance.sh` for AAA, BBB, CCC.
    4.  Successful execution of `manage_services.sh` to enable and start `bitmover.service`, `exportcliv2@AAA.service` (+ path), `exportcliv2@BBB.service` (+ path), `exportcliv2@CCC.service` (+ path).
    5.  Directories created (e.g., `/opt/exportcliv2/bin`, `/etc/exportcliv2`, `/var/tmp/testme/source/AAA` if `BASE_DIR_CONFIG` is `/var/tmp/testme`).
    6.  User/group created (e.g., `exportcliv2_user`).
    7.  Binary/wheel copied to install locations, symlinks created (e.g., `/opt/exportcliv2/bin/exportcliv2`).
    8.  Python venv for bitmover created and wheel installed.
    9.  Instance config files (`AAA.conf`, `AAA_app.conf`, etc.) created in `/etc/exportcliv2/`.
    10. `exportcli-manage` symlink created in `/usr/local/bin/`.
    11. Final "Orchestrator finished successfully" message. Exit code 0.
* **Verification:**
    1.  Check existence and permissions of created directories and files.
    2.  Verify user/group creation (`getent passwd exportcliv2_user`, `getent group exportcliv2_group`).
    3.  `sudo exportcli-manage --status` (should show `bitmover.service` active).
    4.  `sudo exportcli-manage -i AAA --status` (should show `exportcliv2@AAA.service` active and related units). Repeat for BBB, CCC.
    5.  Check `journalctl` for startup logs of these services.
    6.  Verify `/usr/local/bin/exportcli-manage` exists and is executable.

**Test Case 1.2: Install (Specific Instances, No Force)**
* **Objective:** Verify successful installation with user-specified instances, plus the global `bitmover` service.
* **Setup:** Clean system. `install-app.conf` configured.
* **Command:** `sudo ./deploy_orchestrator.sh --install -i "siteX,siteY"`
* **Expected Results:** Similar to 1.1, but instance-specific actions (configuration, service enable/start) apply only to `siteX` and `siteY`. `bitmover.service` is still enabled/started.
* **Verification:** Check for `/etc/exportcliv2/siteX.conf`, `/etc/exportcliv2/siteY.conf`. `sudo exportcli-manage -i siteX --status` (active). `sudo exportcli-manage --status` (bitmover active). No configs/services for AAA, BBB, CCC unless they were also in the `-i` list.

**Test Case 1.3: Install (No Instances - by emptying `DEFAULT_INSTANCES`)**
* **Objective:** Verify installation of base components and `bitmover` service only, when no instances are specified and no defaults are configured in the orchestrator.
* **Setup:** Clean system. `install-app.conf` configured. **Modify `deploy_orchestrator.sh` to have `DEFAULT_INSTANCES=()`.**
* **Command:** `sudo ./deploy_orchestrator.sh --install`
* **Expected Results:** Base installation successful. Only `bitmover.service` is enabled and started. No instance-specific configuration or service actions occur.
* **Verification:** `sudo exportcli-manage --status` (bitmover active). No files in `/etc/exportcliv2/` like `AAA.conf`. `sudo exportcli-manage -i AAA --status` should indicate service not found or similar (as AAA was not configured).

**Test Case 1.4: Re-Install with `--force` (Default Instances)**
* **Objective:** Verify `--force` allows overwriting of existing instance configurations during a re-install.
* **Setup:** Successfully run Test Case 1.1. Then, manually edit `/etc/exportcliv2/AAA.conf` to add a unique comment.
* **Command:** `sudo ./deploy_orchestrator.sh --install --force` (ensure `DEFAULT_INSTANCES` is back to `(AAA BBB CCC)`)
* **Expected Results:** Installation proceeds. The `configure_instance.sh` script for AAA, BBB, CCC runs with `--force`. The manual comment in `AAA.conf` should be gone (file overwritten with defaults). Services re-enabled/re-started.
* **Verification:** Check content of `/etc/exportcliv2/AAA.conf` (manual comment should be absent). Service statuses as per 1.1.

**Test Case 1.5: Install with Dry Run (`-n`)**
* **Objective:** Verify no actual changes are made to the system, and script outputs "[DRY-RUN] Would execute..." messages.
* **Setup:** Clean system. `install-app.conf` configured.
* **Command:** `sudo ./deploy_orchestrator.sh --install -n`
* **Expected Results:** Extensive log output showing "[DRY-RUN]" messages for file operations, script executions, service actions. No directories/files created on the filesystem (beyond temporary orchestrator items like lockfile placeholders if any). No services started/enabled. Final "Orchestration dry run scan completed" and "Orchestrator finished successfully" messages. Exit code 0.
* **Verification:** Check key installation paths (e.g., `/opt/exportcliv2`, `/etc/exportcliv2`) – they should not exist or be empty. `systemctl status bitmover.service` (should be not found or inactive).

**Test Case 1.6: Install with Non-TTY and `--force`**
* **Objective:** Verify the confirmation prompt is skipped and installation proceeds in a non-interactive environment.
* **Setup:** Clean system. `install-app.conf` configured.
* **Command:** `echo "y" | sudo ./deploy_orchestrator.sh --install --force` (or `sudo ./deploy_orchestrator.sh --install --force < /dev/null` if script handles EOF on prompt correctly)
* **Expected Results:** No interactive confirmation prompt. Installation completes successfully as per Test Case 1.1.
* **Verification:** Same as Test Case 1.1.

**Test Case 1.7: Install with Non-TTY without `--force` (Failure Expected)**
* **Objective:** Verify the script exits with a usage error if run non-interactively without `--force`.
* **Setup:** Clean system. `install-app.conf` configured.
* **Command:** `sudo ./deploy_orchestrator.sh --install < /dev/null`
* **Expected Results:** Error message "Non-interactive mode (no TTY): Confirmation required...". Script exits with `EXIT_CODE_USAGE_ERROR` (3).
* **Verification:** Check error message and script exit code (`echo $?`).

---

**B. Update (`--update`)**

* **Baseline Setup for Update Tests:** Before each update test (unless specified otherwise), ensure a successful fresh installation has been performed (e.g., by running Test Case 1.1). This provides an existing environment to update.

**Test Case 2.1: Bundle Update (No specific new files, no -i)**
* **Objective:** Verify base components are updated using files from the current bundle (simulating an update where the bundle itself is the "new" version). Verify user is clearly instructed to manually restart services.
* **Setup:** Successful install (from 1.1). For this test, the "update" will effectively re-process the same binary/wheel unless you have a vCurrent and vNext bundle. If using the same bundle, the effect is re-running the base installer logic.
* **Command:** `sudo ./deploy_orchestrator.sh --update`
* **Expected Results:**
    1.  Confirmation prompt (if TTY). User confirms 'y'.
    2.  `install_base_exportcliv2.sh` runs. Symlinks might be updated, systemd units re-processed, bitmover venv potentially re-installed/upgraded.
    3.  **Crucially:** Clear "IMPORTANT: Update complete. Services must be restarted manually..." message with examples for restarting `bitmover.service` and `exportcliv2` instances using `exportcli-manage`.
    4.  No automatic service restarts by the orchestrator.
    5.  "Orchestrator finished successfully" message. Exit code 0.
* **Verification:** Check timestamps of key installed files (e.g., target of `/opt/exportcliv2/bin/exportcliv2` symlink, files in bitmover venv). Manually restart services as per the script's instructions and verify their status using `exportcli-manage`.

**Test Case 2.2: Surgical Update (`--new-binary`)**
* **Objective:** Verify only the application binary is updated, and the user is clearly instructed to manually restart relevant `exportcliv2` instance services.
* **Setup:** Successful install. Create a dummy new binary file, e.g., `touch /tmp/exportcliv2_vNEW; chmod +x /tmp/exportcliv2_vNEW`.
* **Command:** `sudo ./deploy_orchestrator.sh --update --new-binary /tmp/exportcliv2_vNEW`
* **Expected Results:**
    1.  Confirmation prompt. User confirms 'y'.
    2.  The `/tmp/exportcliv2_vNEW` binary is staged into `exportcliv2-deploy/` and used by `install_base_exportcliv2.sh`.
    3.  The main application symlink (e.g., `/opt/exportcliv2/bin/exportcliv2`) now points to a versioned binary corresponding to `exportcliv2_vNEW`.
    4.  Clear "IMPORTANT: Update complete..." message, specifically highlighting the need to restart `exportcliv2` instances (e.g., `sudo exportcli-manage -i <INSTANCE_NAME> --restart`).
    5.  No automatic service restarts.
* **Verification:** Check the target of the `/opt/exportcliv2/bin/exportcliv2` symlink. Manually restart an instance (e.g., `AAA`) and verify (if possible through logs or a mock binary's version output) that it's using the new binary.

**Test Case 2.3: Surgical Update (`--new-wheel`)**
* **Objective:** Verify only the datamover wheel is updated, and the user is clearly instructed to manually restart the `bitmover.service`.
* **Setup:** Successful install. Create a dummy new wheel file, e.g., `touch /tmp/datamover_vNEW.whl`.
* **Command:** `sudo ./deploy_orchestrator.sh --update --new-wheel /tmp/datamover_vNEW.whl`
* **Expected Results:**
    1.  Confirmation prompt. User confirms 'y'.
    2.  The `/tmp/datamover_vNEW.whl` is staged and used to upgrade the package in the bitmover Python virtual environment.
    3.  Clear "IMPORTANT: Update complete..." message, specifically highlighting the need to restart the `bitmover.service` (e.g., `sudo exportcli-manage --restart`).
    4.  No automatic service restarts.
* **Verification:** Check the installed packages in the bitmover venv (e.g., using `pip list` within the venv). Manually restart `bitmover.service` and check its status/logs.

**Test Case 2.4: Surgical Update (`--new-binary` and `--new-wheel`)**
* **Objective:** Verify both components are updated, and the user is instructed to manually restart all relevant services.
* **Setup:** Successful install. Use dummy files from 2.2 and 2.3.
* **Command:** `sudo ./deploy_orchestrator.sh --update --new-binary /tmp/exportcliv2_vNEW --new-wheel /tmp/datamover_vNEW.whl`
* **Expected Results:** Combination of 2.2 and 2.3. The "IMPORTANT: Update complete..." message should provide examples for restarting both `bitmover.service` and `exportcliv2` instances.
* **Verification:** Combination of 2.2 and 2.3.

**Test Case 2.5: Update with Dry Run (`-n`)**
* **Objective:** Verify no actual changes are made during an update dry run, and appropriate "[DRY-RUN]" messages are shown for staging, file operations, and sub-script calls.
* **Setup:** Successful install. Use a dummy new binary file.
* **Command:** `sudo ./deploy_orchestrator.sh --update --new-binary /tmp/exportcliv2_vNEW -n`
* **Expected Results:** Log output showing "[DRY-RUN]" messages. No files actually copied or modified in the installation directories. No temporary config file left behind (trap should clean placeholder).
* **Verification:** Check timestamps and content of installed files (should be unchanged). Service statuses unchanged.

---

**C. Service Management (`exportcli-manage`)**

* **Baseline Setup for Service Management Tests:** Perform a successful fresh install (Test Case 1.1) to ensure services are installed and initially running.

**Test Case 3.1: Status Checks (Active and Inactive)**
* **Objective:** Verify `exportcli-manage --status` correctly reports active and inactive services without script failure.
* **Commands & Expected Sequence:**
    1.  `sudo exportcli-manage --status` (for bitmover) -> Expect `bitmover.service` active.
    2.  `sudo exportcli-manage -i AAA --status` -> Expect `exportcliv2@AAA.service` active.
    3.  `sudo exportcli-manage -i AAA --stop` -> Stop instance AAA.
    4.  `sudo exportcli-manage -i AAA --status` -> Expect `exportcliv2@AAA.service` inactive. Crucially, the script should output "INFO: Service 'exportcliv2@AAA.service' is inactive/dead." and finish with "Service Management Script (...) finished successfully." (Exit code 0).
    5.  `sudo exportcli-manage -i NONEXISTENT --status` -> Expect "Service 'exportcliv2@NONEXISTENT.service' not found..." and a non-zero exit code from `manage_services.sh` (which `run` in orchestrator would catch if orchestrator called it, but here `manage_services.sh` itself exits non-zero). The `FAIL_COUNT` in `manage_services.sh` should be incremented, and it should exit with error.
* **Verification:** Match output with actual `systemctl status` results. Verify script exit codes.

**Test Case 3.2: Start/Stop/Restart Actions**
* **Objective:** Verify `exportcli-manage` can correctly start, stop, and restart global and instance services.
* **Commands:**
    * `sudo exportcli-manage -i AAA --stop` (Verify with status)
    * `sudo exportcli-manage -i AAA --start` (Verify with status)
    * `sudo exportcli-manage -i AAA --restart` (Verify with status & check logs for restart indication)
    * Repeat similar sequence for global `bitmover.service`: `sudo exportcli-manage --stop`, `... --start`, `... --restart`.
* **Verification:** Use `exportcli-manage --status` after each action. Check `journalctl` for relevant log entries indicating start/stop/restart.

**Test Case 3.3: Enable/Disable Actions**
* **Objective:** Verify `exportcli-manage` can correctly enable and disable services for starting at boot.
* **Commands & Verification:**
    1.  `sudo exportcli-manage -i AAA --disable`
    2.  `sudo systemctl is-enabled exportcliv2@AAA.service` -> Expect "disabled".
    3.  `sudo exportcli-manage -i AAA --enable`
    4.  `sudo systemctl is-enabled exportcliv2@AAA.service` -> Expect "enabled".
    5.  (Optional but thorough) Reboot the system after disabling a service and verify it does not start. Reboot after enabling and verify it does start.
* **Repeat for global `bitmover.service`.**

**Test Case 3.4: Logs and Logs-Follow Actions**
* **Objective:** Verify `exportcli-manage` can retrieve and follow logs for global and instance services.
* **Commands:**
    * `sudo exportcli-manage --logs`
    * `sudo exportcli-manage -i AAA --logs --since "5 minutes ago"`
    * `sudo exportcli-manage -i BBB --logs-follow` (Observe for a short period, then Ctrl-C; expect "Journal follow interrupted by user").
* **Verification:** Compare output with direct `journalctl` commands. Ensure `--since` filtering works.

**Test Case 3.5: Dry Run (`-n`) for `exportcli-manage`**
* **Objective:** Verify that `-n` prevents actual service state changes and shows "[DRY-RUN]" messages.
* **Commands:**
    * `sudo exportcli-manage -i AAA --start -n`
    * `sudo exportcli-manage --stop -n`
* **Expected Results:** Output includes "[DRY-RUN] Would execute systemctl..." messages. The actual state of the services remains unchanged.
* **Verification:** Check service status using `exportcli-manage -i AAA --status` (or for global) before and after the dry-run command.

---

**D. Error Handling and Edge Cases (Orchestrator `deploy_orchestrator.sh`)**

**Test Case 4.1: Missing Sub-script**
* **Setup:** From the deployment bundle, temporarily rename or move `exportcliv2-deploy/install_base_exportcliv2.sh`.
* **Command:** `sudo ./deploy_orchestrator.sh --install`
* **Expected Results:** Script exits early with an error message like "Missing required script: .../exportcliv2-deploy/install_base_exportcliv2.sh". Exit code `EXIT_CODE_FILE_ERROR` (6).
* **Verification:** Check error message and exit code (`echo $?`). Restore the sub-script.

**Test Case 4.2: Missing `install-app.conf` (for install/bundle update)**
* **Setup:** Rename or move `exportcliv2-deploy/install-app.conf`.
* **Command:** `sudo ./deploy_orchestrator.sh --install` (or `--update` without surgical flags)
* **Expected Results:** Error message "Effective base configuration file not found: .../install-app.conf". Exit code `EXIT_CODE_CONFIG_ERROR` (4).
* **Verification:** Check error message and exit code. Restore the config file.

**Test Case 4.3: Invalid Instance Name Format in Orchestrator**
* **Command:** `sudo ./deploy_orchestrator.sh --install -i "instance/invalid!,goodName"`
* **Expected Results:** Error message "Invalid instance name format: 'instance/invalid!'...". Exit code `EXIT_CODE_USAGE_ERROR` (3).
* **Verification:** Check error message and exit code.

**Test Case 4.4: Lock File Acquisition (Simulate Conflict)**
* **Setup:** In one terminal, manually acquire the lock: `(flock -x 200; echo "Manual lock PID $$"; sleep 120) 200>/tmp/deploy_orchestrator.lock &`
* **Command:** In another terminal, attempt to run: `sudo ./deploy_orchestrator.sh --install` (while the manual lock is held).
* **Expected Results:** Error message "Another instance is running (lockfile: /tmp/deploy_orchestrator.lock, reported locker PID: ...)." Exit code `EXIT_CODE_FATAL_ERROR` (1).
* **Verification:** Check error message and exit code. Ensure the manual lock process is killed or finishes to release the lock.

**Test Case 4.5: User Abort at Confirmation Prompt**
* **Command:** `sudo ./deploy_orchestrator.sh --install`
* **Action:** When prompted "Proceed with install...", type `N` and press Enter.
* **Expected Results:** Script outputs "User aborted operation." and exits cleanly. Exit code `EXIT_CODE_SUCCESS` (0) as it's a graceful user-initiated exit.
* **Verification:** Check output message and exit code.

**Test Case 4.6: Surgical Update with Missing External File**
* **Command:** `sudo ./deploy_orchestrator.sh --update --new-binary /tmp/non_existent_binary`
* **Expected Results:** Error message "New binary file not found: /tmp/non_existent_binary". Exit code `EXIT_CODE_FILE_ERROR` (6).
* **Verification:** Check error message and exit code.

---

**E. User Guide and Quick Start Guide Review**

**Test Case 5.1: Follow Quick Start Guide Precisely**
* **Objective:** Verify a new user can successfully complete all steps in the Quick Start Guide and achieve the stated goal.
* **Setup:** Clean system. Prepare the deployment package as a new user would receive it.
* **Steps:** Meticulously follow each instruction in the `QUICK_START_GUIDE.md`.
* **Expected Results:** The system state at the end matches the "Congratulations!" section of the Quick Start Guide (e.g., instance AAA and bitmover running).
* **Verification:** Perform all verification steps mentioned in the Quick Start Guide.

**Test Case 5.2: Follow Key User Guide Scenarios**
* **Objective:** Verify the accuracy and clarity of more complex procedures from the main `USER_GUIDE.md`.
* **Setup:** As required by the chosen User Guide scenario (e.g., an existing installation for an update scenario).
* **Steps:** Select 2-3 significant scenarios from the User Guide, for example:
    * Section 5: Post-Installation Configuration (configure a second instance, e.g., BBB).
    * Section 6.2: Surgical Update Workflow (apply a dummy binary and a dummy wheel).
    * A specific troubleshooting step from Section 8.
* **Expected Results:** The outcome of following the guide's steps matches the descriptions in the guide.
* **Verification:** Verify system state, service status, and configuration files as appropriate for the chosen scenario.
