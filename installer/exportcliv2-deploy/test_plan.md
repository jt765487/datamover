## Test Plan: exportcliv2 Deployment Suite (Revised)

**Orchestrator (`deploy_orchestrator.sh`):** v2.4.8
**Patch Script (`install_patch.sh`):** v1.0.0
**Bundle Creator (`create_bundle.sh`):** (Use latest version that includes `install_patch.sh`)
**Base Installer (`install_base_exportcliv2.sh`):** v1.3.2 (or latest)
**Instance Configurator (`configure_instance.sh`):** v4.1.0 (or latest)
**Service Manager (`manage_services.sh`):** v1.3.2 (or latest)

**Target System:** Oracle Linux 9 (or compatible)

---

### I. Environment Preparation

1.  **Clean System:**
    *   Start with a clean Oracle Linux 9 system or a VM snapshot.
    *   Ensure `sudo` access.

2.  **Required Packages:**
    *   Verify/install `python3` and `python3-venv`.
    *   Standard utilities (`flock`, `date`, `realpath`, `mktemp`, `sed`, `systemctl`, etc.).

3.  **Deployment Package (`exportcliv2-suite-vX.Y.Z.tar.gz`):**
    *   Use `create_bundle.sh` (latest version) to generate the test bundle.
    *   Ensure `install_patch.sh` (**v1.0.0**) is included in the bundle root.
    *   Ensure `deploy_orchestrator.sh` (**v2.4.8**) is in the bundle root.
    *   `exportcliv2-deploy/` subdirectory with latest versions of:
        *   `install_base_exportcliv2.sh`
        *   `configure_instance.sh`
        *   `manage_services.sh`
    *   `exportcliv2-deploy/install-app.conf` with:
        ```ini
        # install-app.conf for testing
        DEFAULT_INSTANCES_CONFIG="AAA BBB" # For default install tests (reduced for brevity)
        VERSIONED_APP_BINARY_FILENAME="exportcliv2-vDUMMY"
        VERSIONED_DATAMOVER_WHEEL_FILENAME="datamover-vDUMMY-py3-none-any.whl"
        REMOTE_HOST_URL_CONFIG="http://127.0.0.1:8989/pcap"
        EXPORT_TIMEOUT_CONFIG="15" # This is now sourced by base_installer from here
        USER_CONFIG="exportcliv2_user"
        GROUP_CONFIG="datapipeline_group"
        BASE_DIR_CONFIG="/var/tmp/testme_suite" # Changed to avoid conflict with single script tests
        LOG_DIR_CONFIG="/var/log/exportcliv2_suite"
        WHEELHOUSE_SUBDIR="wheelhouse"
        # Add any new defaults from BASE_VARS_FILE that configure_instance.sh might use
        DEFAULT_INSTANCE_STARTTIME_OFFSET="3 minutes ago"
        DEFAULT_INSTANCE_ENDTIME_VALUE="-1"
        DEFAULT_INSTANCE_APP_CONFIG_CONTENT="mining_delta_sec=120"
        ```
    *   Dummy files in `exportcliv2-deploy/`:
        *   `touch exportcliv2-deploy/exportcliv2-vDUMMY && chmod +x exportcliv2-deploy/exportcliv2-vDUMMY`
        *   `touch exportcliv2-deploy/datamover-vDUMMY-py3-none-any.whl`
    *   Populate `exportcliv2-deploy/config_files/` and `exportcliv2-deploy/systemd_units/` with templates.
    *   Include guides.
    *   Tar and gzip for extraction tests, or work directly from the prepared directory.

4.  **Test Artifacts for Patching:**
    *   Prepare separate dummy files for `install_patch.sh`, e.g.:
        *   `/tmp/exportcliv2_PATCHED_v1` (`touch /tmp/exportcliv2_PATCHED_v1 && chmod +x /tmp/exportcliv2_PATCHED_v1`)
        *   `/tmp/datamover_PATCHED_v1.whl` (`touch /tmp/datamover_PATCHED_v1.whl`)

---

### II. Test Scenarios

**General Verification for each test case:**
*   No unexpected error messages.
*   Correct exit codes.
*   If `-v` is used, `set -x` output is informative, no "unbound variable" errors.
*   Timestamps in logs are accurate.
*   Colorized logging functions correctly.

---

**A. Fresh Installation (`deploy_orchestrator.sh --install`)**

**Test Case 1.1: Basic Install (Default Instances from `install-app.conf`)**
*   **Objective:** Verify successful installation of base components and default instances (defined by `DEFAULT_INSTANCES_CONFIG`). Verify services enabled and started.
*   **Setup:** Clean system. Bundle prepared as per "Environment Preparation" (e.g., `DEFAULT_INSTANCES_CONFIG="AAA BBB"`). `cd` into the unpacked bundle directory.
*   **Command:** `sudo ./deploy_orchestrator.sh --install`
*   **Expected Results:**
    1.  Orchestrator logs "Using default instances from config file for --install: AAA BBB".
    2.  Script prompts for confirmation. User confirms 'y'.
    3.  Successful execution of `install_base_exportcliv2.sh`.
    4.  Successful execution of `configure_instance.sh` for AAA, BBB.
    5.  Successful execution of `manage_services.sh` to enable and start `bitmover.service`, `exportcliv2@AAA.service` (+ path), `exportcliv2@BBB.service` (+ path).
    6.  Directories, user, group, files, symlinks created. `BASE_VARS_FILE` (`/etc/default/exportcliv2_base_vars`) created and populated.
    7.  Final "Orchestrator finished successfully" message. Exit code 0.
*   **Verification:**
    1.  Check created directories/files (e.g., `/var/tmp/testme_suite`, `/etc/exportcliv2_suite`, `/var/log/exportcliv2_suite`).
    2.  Verify user/group.
    3.  `sudo exportcli-manage --status` (bitmover active).
    4.  `sudo exportcli-manage -i AAA --status` (instance active). Repeat for BBB.
    5.  `journalctl` for services.
    6.  `/usr/local/bin/exportcli-manage` symlink.
    7.  Content of `/etc/default/exportcliv2_base_vars` (should contain `APP_NAME`, `ETC_DIR`, `LOG_DIR`, `BASE_DIR`, `APP_USER`, `APP_GROUP`, `DEFAULT_CONFIGURE_INSTANCE_EXPORT_TIMEOUT`, and new instance defaults).
    8.  Content of `/etc/exportcliv2_suite/AAA.conf` (should use defaults like `DEFAULT_INSTANCE_STARTTIME_OFFSET` if they were added to `install-app.conf` and sourced by `base_vars` creation).

**Test Case 1.2: Install (No Default Instances in `install-app.conf` - Error Expected)**
*   **Objective:** Verify orchestrator exits with an error if `DEFAULT_INSTANCES_CONFIG` is empty or missing.
*   **Setup:** Clean system. Modify `install-app.conf` in bundle to have `DEFAULT_INSTANCES_CONFIG=""` or comment it out. `cd` into bundle.
*   **Command:** `sudo ./deploy_orchestrator.sh --install`
*   **Expected Results:** Orchestrator script exits with error: "DEFAULT_INSTANCES_CONFIG in '.../install-app.conf' is mandatory and must not be empty...". Exit code `EXIT_CODE_CONFIG_ERROR` (4).
*   **Verification:** Check error message and exit code.

**Test Case 1.3: Re-Install with `--force`**
*   **Objective:** Verify `--force` allows overwriting of existing instance configurations.
*   **Setup:** Successfully run Test Case 1.1. Manually edit `/etc/exportcliv2_suite/AAA.conf` to add a unique comment. `cd` into bundle.
*   **Command:** `sudo ./deploy_orchestrator.sh --install --force`
*   **Expected Results:** Instance configs (AAA, BBB) are regenerated/overwritten. Manual comment in `AAA.conf` is gone. Services re-enabled/re-started.
*   **Verification:** Content of `/etc/exportcliv2_suite/AAA.conf`. Service statuses as per 1.1.

**Test Case 1.4: Install with Dry Run (`-n`)**
*   **Objective:** Verify no actual changes are made, "\[DRY-RUN\]" messages shown.
*   **Setup:** Clean system. `cd` into bundle.
*   **Command:** `sudo ./deploy_orchestrator.sh --install -n`
*   **Expected Results:** "\[DRY-RUN\] Would execute..." messages. Confirmation prompt skipped.
*   **Verification:** File system unchanged. Service statuses unchanged.

**Test Case 1.5: Install with Non-TTY and `--force`**
*   **Objective:** Verify confirmation is skipped and installation proceeds.
*   **Setup:** Clean system. `cd` into bundle.
*   **Command:** `echo "y" | sudo ./deploy_orchestrator.sh --install --force` (or `< /dev/null`)
*   **Expected Results:** Log message "Non-interactive mode (no TTY): Proceeding...". Installation completes.
*   **Verification:** Same as Test Case 1.1.

**Test Case 1.6: Install with Non-TTY without `--force` (Failure Expected)**
*   **Objective:** Verify script exits with error.
*   **Setup:** Clean system. `cd` into bundle.
*   **Command:** `sudo ./deploy_orchestrator.sh --install < /dev/null`
*   **Expected Results:** Error "Non-interactive mode (no TTY): Confirmation required...". Exit code `EXIT_CODE_USAGE_ERROR` (3).
*   **Verification:** Check error message and exit code.

**Test Case 1.7: `list-default-instances` Option**
*   **Objective:** Verify correct display of default instances.
*   **Setup 1:** Bundle `install-app.conf` has `DEFAULT_INSTANCES_CONFIG="siteM siteN"`. `cd` into bundle.
*   **Command 1:** `./deploy_orchestrator.sh --list-default-instances`
*   **Expected Results 1:** Output: "... siteM siteN". Exit 0.
*   **Setup 2:** Bundle `install-app.conf` has `DEFAULT_INSTANCES_CONFIG=""`. `cd` into bundle.
*   **Command 2:** `./deploy_orchestrator.sh --list-default-instances`
*   **Expected Results 2:** Output: "...(None specified or list is empty)". Exit 0.
*   **Setup 3 (Error):** `install-app.conf` is missing `DEFAULT_INSTANCES_CONFIG` line. `cd` into bundle.
*   **Command 3:** `./deploy_orchestrator.sh --list-default-instances`
*   **Expected Results 3:** Error during config sourcing (`DEFAULT_INSTANCES_CONFIG` unset). Exit `EXIT_CODE_CONFIG_ERROR` (4).
*   **Verification:** Match output.

---

**B. Patch Preparation (`install_patch.sh`)**

*   **Baseline Setup for Patch Tests:** Use the bundle directory created in "Environment Preparation".

**Test Case 2.1: Patch Binary Successfully**
*   **Objective:** Verify `install_patch.sh` copies new binary and updates `install-app.conf` in the bundle.
*   **Setup:** `cd` into the bundle directory. Test binary `/tmp/exportcliv2_PATCHED_v1` exists.
*   **Command:** `sudo ./install_patch.sh --new-binary /tmp/exportcliv2_PATCHED_v1`
*   **Expected Results:**
    1.  Success messages from `install_patch.sh`.
    2.  File `./exportcliv2-deploy/exportcliv2_PATCHED_v1` created in the bundle.
    3.  `./exportcliv2-deploy/install-app.conf` updated: `VERSIONED_APP_BINARY_FILENAME="exportcliv2_PATCHED_v1"`.
    4.  Instructions to run `deploy_orchestrator.sh --update`. Exit code 0.
*   **Verification:** Check file existence and content of `install-app.conf` within the bundle.

**Test Case 2.2: Patch Wheel Successfully**
*   **Objective:** Verify `install_patch.sh` copies new wheel and updates `install-app.conf` in the bundle.
*   **Setup:** `cd` into bundle. Test wheel `/tmp/datamover_PATCHED_v1.whl` exists. (May need to revert `install-app.conf` if running after 2.1).
*   **Command:** `sudo ./install_patch.sh --new-wheel /tmp/datamover_PATCHED_v1.whl`
*   **Expected Results:**
    1.  Success messages.
    2.  File `./exportcliv2-deploy/datamover_PATCHED_v1.whl` created.
    3.  `./exportcliv2-deploy/install-app.conf` updated: `VERSIONED_DATAMOVER_WHEEL_FILENAME="datamover_PATCHED_v1.whl"`.
    4.  Instructions to run `deploy_orchestrator.sh --update`. Exit code 0.
*   **Verification:** Check file and `install-app.conf` content in bundle.

**Test Case 2.3: `install_patch.sh` - Missing Component File**
*   **Objective:** Verify error if specified patch file doesn't exist.
*   **Setup:** `cd` into bundle.
*   **Command:** `sudo ./install_patch.sh --new-binary /tmp/non_existent_binary`
*   **Expected Results:** Error "New component file not found...". Exit code 1 (or specific error code from script).
*   **Verification:** Error message, exit code. Bundle unchanged.

**Test Case 2.4: `install_patch.sh` - Not in Bundle Directory**
*   **Objective:** Verify error if run from outside a bundle directory.
*   **Setup:** `cd /tmp`. Copy `install_patch.sh` to `/tmp/`.
*   **Command:** `sudo /tmp/install_patch.sh --new-binary /tmp/exportcliv2_PATCHED_v1`
*   **Expected Results:** Error "Directory './exportcliv2-deploy/' not found...". Exit code 1.
*   **Verification:** Error message, exit code.

**Test Case 2.5: `install_patch.sh` - No Arguments**
*   **Objective:** Verify usage message is shown.
*   **Setup:** `cd` into bundle.
*   **Command:** `sudo ./install_patch.sh`
*   **Expected Results:** Usage message. Exit code 1 (or 0 if usage exits 0 by design for `-h`).
*   **Verification:** Output.

---

**C. Update (`deploy_orchestrator.sh --update` after using `install_patch.sh`)**

*   **Baseline Setup for Update Tests:** Perform a successful fresh installation (Test Case 1.1). Then, use `install_patch.sh` (Test Case 2.1 or 2.2) to modify the *original bundle directory*.

**Test Case 3.1: Update with Patched Binary**
*   **Objective:** Verify base components and specifically the binary are updated using the bundle modified by `install_patch.sh`.
*   **Setup:**
    1.  Successful install (Test Case 1.1). Original binary is `exportcliv2-vDUMMY`.
    2.  `cd` into the original bundle directory.
    3.  Run `sudo ./install_patch.sh --new-binary /tmp/exportcliv2_PATCHED_v1`. (Bundle now points to `exportcliv2_PATCHED_v1`).
*   **Command:** `sudo ./deploy_orchestrator.sh --update` (from the same bundle directory)
*   **Expected Results:**
    1.  Confirmation prompt for "bundle update".
    2.  `install_base_exportcliv2.sh` runs, uses `exportcliv2_PATCHED_v1` from the bundle.
    3.  Orchestrator prints "IMPORTANT: Update complete. Services must be restarted..." with general advice, possibly highlighting instance restarts.
*   **Verification:**
    1.  Symlink for main binary (e.g., `/usr/local/bin/exportcliv2` or `/var/tmp/testme_suite/bin/exportcliv2`) now points to the system copy of `exportcliv2_PATCHED_v1`.
    2.  Manually restart services (e.g., `sudo exportcli-manage -i AAA --restart`) and verify new binary is in use (if possible to tell, e.g., version flag if binary supports it, or by checking process path).

**Test Case 3.2: Update with Patched Wheel**
*   **Objective:** Verify wheel is updated using the bundle modified by `install_patch.sh`.
*   **Setup:**
    1.  Successful install (Test Case 1.1). Original wheel is `datamover-vDUMMY-...whl`.
    2.  `cd` into original bundle directory.
    3.  Run `sudo ./install_patch.sh --new-wheel /tmp/datamover_PATCHED_v1.whl`. (Bundle now points to `datamover_PATCHED_v1.whl`).
*   **Command:** `sudo ./deploy_orchestrator.sh --update`
*   **Expected Results:**
    1.  Confirmation for "bundle update".
    2.  `install_base_exportcliv2.sh` runs, installs `datamover_PATCHED_v1.whl`.
    3.  Orchestrator prints "IMPORTANT: Update complete..." with general advice, possibly highlighting bitmover service restart.
*   **Verification:**
    1.  Check Python venv (`/var/tmp/testme_suite/datamover_venv`) for `datamover_PATCHED_v1`.
    2.  Manually restart bitmover service (`sudo exportcli-manage --restart`) and verify.

**Test Case 3.3: Update with Dry Run (`-n`)**
*   **Objective:** Verify no actual changes. "\[DRY-RUN\]" messages.
*   **Setup:** After Test Case 3.1 setup (bundle is patched).
*   **Command:** `sudo ./deploy_orchestrator.sh --update -n`
*   **Expected Results:** "\[DRY-RUN\]" messages. Confirmation skipped. No system files changed.
*   **Verification:** File system, service status unchanged from before this dry run.

---

**D. Service Management (`exportcli-manage` v1.3.2)**
*   These tests remain critical. Run them after a successful install (e.g., Test Case 1.1).
*   **Test Cases 4.1 - 4.5:** Status, Start/Stop/Restart (confirm restart warning), Enable/Disable, Logs/Logs-Follow, Dry Run.
    *   Verify as previously, especially the correct behavior for inactive services and the restart warning.

---

**E. Error Handling and Edge Cases (`deploy_orchestrator.sh` v2.4.8)**

*   **Test Case 5.1: Missing Sub-script** - Expected: Error `EXIT_CODE_FILE_ERROR`.
*   **Test Case 5.2: Missing `install-app.conf`** - Expected: Error `EXIT_CODE_CONFIG_ERROR`.
*   **Test Case 5.3: Invalid Instance Name Format in `DEFAULT_INSTANCES_CONFIG`** - Expected: Error `EXIT_CODE_CONFIG_ERROR`.
*   **Test Case 5.4: Lock File Acquisition** - Expected: Error `EXIT_CODE_FATAL_ERROR`.
*   **Test Case 5.5: User Abort at Confirmation Prompt** - Expected: "User aborted...". Exit `EXIT_CODE_SUCCESS`.
*   **Test Case 5.6: Mandatory `DEFAULT_INSTANCES_CONFIG` empty/missing for `--install`** - Expected: Error "DEFAULT_INSTANCES_CONFIG ... mandatory...". Exit `EXIT_CODE_CONFIG_ERROR`.

---

**F. User Guide and Quick Start Guide Review**

**Test Case 6.1: Follow Quick Start Guide Precisely**
*   **Objective:** Verify QSG aligns with the new simplified workflow (no `-i` for orchestrator, `install_patch.sh` for patches before `--update`).
*   **Steps & Verification:** Follow guide, noting any discrepancies or areas needing update.

**Test Case 6.2: Follow Key User Guide Scenarios**
*   **Objective:** Verify User Guide accurately reflects current script functionalities.
*   **Steps & Verification:** Focus on installation, default instance setup, and the new update/patching procedure.
 the `install_patch.sh` script and the simplified `deploy_orchestrator.sh`. It should provide comprehensive coverage. Remember to adjust dummy filenames and paths as per your actual test artifacts. Good luck with the testing!