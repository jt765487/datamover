## Quick Start Guide: Basic `exportcliv2` and `bitmover` Setup

This guide will walk you through the minimal steps to get a basic `exportcliv2` environment (with one default instance) and the `bitmover` service up and running. For detailed explanations, advanced configurations, or troubleshooting, please refer to the full "Application Suite Deployment and Management Guide."

**Goal:** Install the application suite and start `bitmover` and one default `exportcliv2` instance (e.g., "AAA").

**Prerequisites:**

1.  You have `sudo` (root) access on an Oracle Linux 9 (or compatible) system.
2.  The full deployment package (containing all scripts, templates, binary, and wheel) is unpacked in a directory (e.g., `~/deployment_package`).
3.  Required system utilities (like `python3-venv`, `flock`) are installed.

**Steps:**

**Step 1: Navigate to Your Deployment Package Directory**

Open your terminal and change to the directory where you unpacked the deployment files:
```bash
cd ~/deployment_package
```

**Step 2: Configure `install-app.conf` (Minimal Changes)**

Open the `install-app.conf` file in this directory with a text editor. You **must** update these lines:

*   **`VERSIONED_APP_BINARY_FILENAME`**:
    Set this to the exact filename of your `exportcliv2` binary.
    Example: `VERSIONED_APP_BINARY_FILENAME="exportcliv2-v1.0.0"`

*   **`VERSIONED_DATAMOVER_WHEEL_FILENAME`**:
    Set this to the exact filename of your `datamover` (bitmover) Python wheel.
    Example: `VERSIONED_DATAMOVER_WHEEL_FILENAME="datamover-0.2.1-py3-none-any.whl"`

*   **`REMOTE_HOST_URL_CONFIG`**:
    Set this to the URL where `bitmover` should send data. For a quick test, this can be a placeholder if you're not immediately testing uploads, but it's required by the script.
    Example: `REMOTE_HOST_URL_CONFIG="http://localhost:8000/upload"` (if you had a local test server)

*   **`EXPORT_TIMEOUT_CONFIG`**:
    This sets a default timeout for `exportcliv2` instances. The script requires it.
    Example: `EXPORT_TIMEOUT_CONFIG="15"`

Save the `install-app.conf` file. For this quick start, we'll use the other defaults provided in the file (like installation paths and user/group names).

**Step 3: Run the Orchestrator for Installation**

Execute the main deployment script with the `--install` flag. This will use the default instance "AAA" (or the first one in `DEFAULT_INSTANCES` in the script).
```bash
sudo ./deploy_orchestrator.sh --install
```
The script will:
*   Check dependencies and acquire a lock.
*   Ask for confirmation: Type `y` and press Enter to proceed.
*   Run the base installer (`install_base_exportcliv2.sh`).
*   Run the instance configurator (`configure_instance.sh`) for the default instance(s).
*   Run the service manager (`manage_services.sh`) to enable and start `bitmover` and the default `exportcliv2` instance(s).

**Step 4: Post-Installation: Minimal Instance Configuration**

The default `exportcliv2` instance (e.g., "AAA") needs a few critical values to function.

*   Edit the instance configuration file. Assuming default paths and `APP_NAME="exportcliv2"`, for instance "AAA", this would be:
    ```bash
    sudo nano /etc/exportcliv2/AAA.conf
    ```
*   **Update these lines** with values appropriate for your test environment:
    *   `EXPORT_IP="<IP_address_for_AAA_to_monitor>"`
    *   `EXPORT_PORTID="<port_or_interface_for_AAA>"`
    *   `EXPORT_SOURCE="<unique_source_tag_for_AAA>"` (e.g., "test_feed")
*   Save the file.

**Step 5: Restart the `exportcliv2` Instance**

For the changes in `AAA.conf` to take effect, restart the instance:
```bash
sudo ./manage_services.sh -i AAA --restart
```

**Step 6: Verify Services are Running**

Check the status of the services:

*   **Bitmover:**
    ```bash
    sudo ./manage_services.sh --status
    ```
    Look for `Active: active (running)`.

*   **`exportcliv2` Instance (e.g., AAA):**
    ```bash
    sudo ./manage_services.sh -i AAA --status
    ```
    Look for `Active: active (running)` for `exportcliv2@AAA.service`. You'll also see the status of its related path and restart units.

**Congratulations!** You should now have a basic `bitmover` service and an `exportcliv2` instance running.

**Next Steps:**

*   **View Logs:**
    ```bash
    sudo ./manage_services.sh -i AAA --logs-follow
    sudo ./manage_services.sh --logs-follow
    ```
*   **Further Configuration:** Refer to the **full Application Suite Deployment and Management Guide** for details on:
    *   Customizing installation paths, users, and groups.
    *   Configuring multiple `exportcliv2` instances.
    *   Advanced `bitmover` settings in `/etc/exportcliv2/config.ini`.
    *   Updating the application components.
    *   Detailed troubleshooting.
