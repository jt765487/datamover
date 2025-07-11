## README: exportcliv2 Application Suite (v1.0.7)

This guide walks you through installing the `exportcliv2` application suite, which includes the `exportcliv2` data
export client and the Bitmover service. This version also includes an **automatic self-healing feature** for
`exportcliv2` instances, which detects and restarts unresponsive processes.

**Quick Steps Overview:**

*   **Step 0: Prerequisites & Preparation:** Ensure system compatibility, tools, and dedicated ext4 filesystem.
*   **Step 1: Unpack Bundle:** Extract the installation package.
*   **Step 2: Review Bundle Configs:** Check `install-app.conf` and optionally edit `app.conf.template`.
*   **Step 3: Run Installation:** Execute `deploy_orchestrator.sh --install`.
*   **Step 4: Configure Instance:** Edit the live system's instance configs (e.g., `AAA.conf`).
*   **Step 5: Restart Instance:** Apply instance config changes.
*   **Step 6: Verify Services:** Check `bitmover` and `exportcliv2` instance status.
*   **Step 7: Understand Paths:** Learn key directory locations.
*   **Step 8: Check Logs:** View service and application logs.
*   **Step 9: Prepare Bundle Patch:** Use `install_patch.sh` to update the bundle.
*   **Step 10: Deploy Patched Bundle:** Use `deploy_orchestrator.sh --update`.
*   **Step 11: Update Credentials:** Modify `common.auth.conf` if needed.

---

**Required Privileges & User:**
All installation, patching, and service management commands in this guide **must be executed as the `root` user.**

*   Log in directly as `root`, or from a non-root user with sudo privileges, switch to a root shell:
    ```bash
    sudo su -
    ```
*   Once you are `root`, you can run the script commands directly (e.g., `./deploy_orchestrator.sh --install`).

---

**Step 0: Prerequisites and System Preparation**
*(Ensure system compatibility and required tools are ready.)*

1.  **System Compatibility:** Oracle Linux 9 or compatible (RHEL 9, AlmaLinux 9, etc.).
2.  **System Updates & Repository Access:** Ensure the system is up-to-date (`dnf update -y`).
3.  **Installation Package:** Have the `exportcliv2-suite-v1.0.0.tar.gz` package.
4.  **Prepare Dedicated ext4 Filesystem (Crucial Prerequisite):**
    *   It is **essential** to create a dedicated **ext4** filesystem for the application's data. This filesystem **must be mounted** at the `BASE_DIR_CONFIG` path (default: `/opt/bitmover`) **before you run the main installation script (Step 3)**. Refer to the full `USER_GUIDE.md` for detailed commands.
5.  **Python 3 Environment:** Ensure Python 3 and its `venv` module are installed (`dnf install python3 -y`).

---

**Step 1: Prepare the Installation Package**
*(Unpack the suite to access installer scripts.)*

1.  Copy `exportcliv2-suite-v1.0.0.tar.gz` to your server.
2.  Extract the archive: `tar vxf exportcliv2-suite-v1.0.0.tar.gz`
3.  Navigate into the extracted directory: `cd exportcliv2-suite-v1.0.0/`
    > **Important:** All subsequent commands must be run from within this extracted bundle directory.

---

**Step 2: Review Bundle Configurations (Before Installation)**
*(Check and optionally modify the bundle's default settings before installation.)*

There are two levels of pre-installation configuration you can perform within the bundle.

**2.1. Review Main Installer Configuration (`install-app.conf`)**

The primary installer configuration is `exportcliv2-deploy/install-app.conf`. **You must ensure the `BASE_DIR_CONFIG` value here matches the mount point of your prepared ext4 filesystem.**

*   **View the config:**
    ```bash
    cat exportcliv2-deploy/install-app.conf
    ```
*   **Edit (Optional):** If you need to change deployment-wide settings like `REMOTE_HOST_URL_CONFIG` or `BASE_DIR_CONFIG` before the first install, edit this file:
    ```bash
    vi exportcliv2-deploy/install-app.conf
    ```

**2.2. Review Application Config Template (Optional)**

The installer creates an application-specific configuration (`<INSTANCE_NAME>_app.conf`) for each instance by copying a template from the bundle.

*   **To change the default values for all instances created during this installation**, edit the template file *before* running the installer:
    ```bash
    vi exportcliv2-deploy/config_files/app.conf.template
    ```
*   For example, you could change `mining_delta_sec=120` to `mining_delta_sec=180` in the template. Now, every instance created by `deploy_orchestrator.sh --install` will start with this new default value.

---

**Step 3: Run the Installation**
*(Execute the main deployment script to install base components and default instances.)*

**Prerequisite Check:** Before running this step, **double-check that your dedicated ext4 filesystem is prepared and mounted at the `BASE_DIR_CONFIG` path** (default: `/opt/bitmover`).

1.  From within the `exportcliv2-suite-v1.0.0/` directory, execute:
    ```bash
    ./deploy_orchestrator.sh --install
    ```2.  Confirm when prompted. Upon completion, you will see `▶ Orchestrator finished successfully.`

---

**Step 4: Post-Installation Configuration (Instance Specific)**
*(Configure the live system's settings for each `exportcliv2` instance, e.g., "AAA".)*

You **must** edit the system configuration files for each instance in `/etc/exportcliv2/`.

1.  **Edit the Instance Environment Configuration File:**
    For instance "AAA", edit the generated defaults for the data source target:
    ```bash
    vi /etc/exportcliv2/AAA.conf
    ```
    Locate and update `EXPORT_IP` and `EXPORT_PORTID` for your environment.

2.  **Review/Edit the Application-Specific Configuration File (if needed):**
    For instance "AAA", the file `/etc/exportcliv2/AAA_app.conf` was created using the template you reviewed in Step 2.2. If you need to give this *specific* instance a different setting from the default, you can edit it now:
    ```bash
    vi /etc/exportcliv2/AAA_app.conf
    ```

3.  Save your changes.

---

**Step 5: Restart the `exportcliv2` Instance "AAA"**
*(Apply the instance configuration changes.)*

For the changes to take effect, restart the instance:
```bash
exportcli-manage -i AAA --restart
```

---

**Step 6: Verify Services are Running**
*(Check that both the Bitmover service and your `exportcliv2` instance are active.)*

1.  **Check the Bitmover service status:**
    ```bash
    exportcli-manage --status
    ```
2.  **Check the `exportcliv2` instance "AAA" status:**
    ```bash
    exportcli-manage -i AAA --status
    ```
3.  **Check the Health Check Timer status (Optional):**
    ```bash
    systemctl list-timers 'exportcliv2-healthcheck@*.timer'
    ```

---

**(Steps 7 through 11 remain the same)**

...

---

**Further Information**

For more detailed information, including advanced troubleshooting for the Purger and Health Check features, refer to the
full **`USER_GUIDE.md`** document included in this bundle.