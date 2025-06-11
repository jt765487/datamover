# Notes for Paul: Working with the Datamover Project

Hi Paul,

Here's a guide to help you work with the Datamover project on the VM while I'm away.

## 1. VM Access & Initial Setup

* **VM Details:** `<INSERT_VM_DETAILS_HERE>` (e.g., IP address, credentials if not shared elsewhere)
* **Working Directory:** All work should be done within `/root/WORK_HERE` on the VM.
* **Existing `exportcliv2` Binary:** I've placed a version of the `exportcliv2` binary from Mark in this directory:
    * Path: `/root/WORK_HERE/exportcliv2-.4.0-B1771-24.11.15`
    * Permissions & Size:
      ```shell
      [root@ip-172-31-17-71 WORK_HERE]# pwd
      /root/WORK_HERE
      [root@ip-172-31-17-71 WORK_HERE]# ll
      total 5096
      -rwx--x--x 1 ngenius ngenius 5203528 Jun 11 08:37 exportcliv2-.4.0-B1771-24.11.15
      ```

## 2. Getting the Datamover Project Code

The project code is managed in a Git repository.

* **Clone the Repository:**
  Navigate to the working directory and clone the repository:
  ```shell
  cd /root/WORK_HERE
  git clone https://github.com/jt765487/datamover
  ```
  This will create a `datamover` subdirectory: `/root/WORK_HERE/datamover`.

* **Updating the Code (if needed):**
  If I make any changes and push them to the `main` branch, you can update your local copy. **Make sure you are inside
  the `datamover` directory before running `git pull`**:
  ```shell
  cd /root/WORK_HERE/datamover
  git pull origin main
  ```
  *(Note: The `fatal: not a git repository` error you saw previously was because you were in `/root/WORK_HERE` instead
  of `/root/WORK_HERE/datamover` when trying to pull).*

## 3. Project Dependencies (`uv`)

This project uses `uv` for Python package management and building.

* **Install `uv` (if not already present):**
  I have already installed it on the machine, but if for some reason it's missing, you can reinstall it with:
  ```shell
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
  Follow any instructions from the installer, such as adding `uv` to your `PATH`.

## 4. Building the Project Components

There are two main scripts within the `/root/WORK_HERE/datamover/` directory for building:

1. `create_wheels.sh`: Builds the Python wheels for the project and its dependencies for an offline installation.
2. `create_bundle.sh`: Creates the final distributable `tar.gz` bundle.

### 4.1. Step 1: Create Offline Wheels (`create_wheels.sh`)

This script gathers all necessary Python packages.

* **Navigate to the project directory:**
  ```shell
  cd /root/WORK_HERE/datamover
  ```
* **Run the script:**
  ```shell
  ./create_wheels.sh
  ```
* **Expected Output (summary):**
  You should see output similar to this, indicating that a virtual environment is created/synced, the `datamover`
  project is built, and its dependencies (plus `pip`, `setuptools`, `wheel`) are downloaded into the
  `offline_package/wheels/` directory.

  ```
  [create_wheels.sh INFO] Starting preparation of offline wheels for the 'datamover' project.
  ...
  [create_wheels.sh INFO] Ensuring virtual environment is up-to-date and 'pip' is available (using 'uv sync --extra dev')...
  ...
  [create_wheels.sh INFO] Building 'datamover' project using 'uv build'...
  Successfully built dist/datamover-1.0.5.tar.gz
  Successfully built dist/datamover-1.0.5-py3-none-any.whl
  ...
  [create_wheels.sh INFO] Downloading dependencies for the current project ('.') to .../offline_package/wheels using venv 'pip download'...
  ...
  [create_wheels.sh INFO] Downloading 'pip', 'setuptools', and 'wheel' to .../offline_package/wheels using venv 'pip download'...
  ...
  [create_wheels.sh INFO] Offline wheels preparation complete. Contents of /root/WORK_HERE/datamover/offline_package/wheels:
  total 3820
  -rw-r--r-- 1 root root  159618 Jun 11 09:15 certifi-2025.4.26-py3-none-any.whl
  -rw-r--r-- 1 root root  149536 Jun 11 09:15 charset_normalizer-3.4.2-cp39-cp39-manylinux_2_17_x86_64.manylinux2014_x86_64.whl
  -rw-r--r-- 1 root root  100433 Jun 11 09:15 datamover-1.0.5-py3-none-any.whl
  -rw-r--r-- 1 root root   70442 Jun 11 09:15 idna-3.10-py3-none-any.whl
  -rw-r--r-- 1 root root 1825227 Jun 11 09:15 pip-25.1.1-py3-none-any.whl
  -rw-r--r-- 1 root root   64847 Jun 11 09:15 requests-2.32.4-py3-none-any.whl
  -rw-r--r-- 1 root root 1201486 Jun 11 09:15 setuptools-80.9.0-py3-none-any.whl
  -rw-r--r-- 1 root root  128680 Jun 11 09:15 urllib3-2.4.0-py3-none-any.whl
  -rw-r--r-- 1 root root   79078 Jun 11 09:15 watchdog-6.0.0-py3-none-manylinux2014_x86_64.whl
  -rw-r--r-- 1 root root   72494 Jun 11 09:15 wheel-0.45.1-py3-none-any.whl
  [create_wheels.sh INFO] --- Successfully prepared offline wheels in /root/WORK_HERE/datamover/offline_package/wheels ---
  ```

### 4.2. Step 2: Create the Distributable Bundle (`create_bundle.sh`)

This script packages everything into a `tar.gz` file for deployment.

* **Version Source:** The script gets the release version from the `pyproject.toml` file (currently `1.0.5`).
* **Required Argument:** You **must** provide the path to the "production" `exportcliv2` binary.
* **Navigate to the project directory (if not already there):**
  ```shell
  cd /root/WORK_HERE/datamover
  ```
* **Run the script:**
  Use the `exportcliv2` binary located in `/root/WORK_HERE/`:
  ```shell
  ./create_bundle.sh --production-binary /root/WORK_HERE/exportcliv2-.4.0-B1771-24.11.15
  ```
* **Expected Output (summary):**
  The script will perform various checks and copy operations, then create the tarball.
  ```
  ... (various INFO and DEBUG messages) ...
  [create_bundle.sh INFO] Creating tarball: exportcliv2-suite-v1.0.5.tar.gz in /root/WORK_HERE/datamover
  [create_bundle.sh INFO] --- Bundle Created Successfully: /root/WORK_HERE/datamover/exportcliv2-suite-v1.0.5.tar.gz ---
  [create_bundle.sh INFO] To inspect contents (permissions visible with -tvf): tar -tzvf "/root/WORK_HERE/datamover/exportcliv2-suite-v1.0.5.tar.gz"
  ```
  The key output is the final `.tar.gz` file (e.g., `exportcliv2-suite-v1.0.5.tar.gz`). This is the distributable
  artifact.

## 5. Documentation

The main documentation files are in the `datamover` project directory:

* `README.md`: General overview and setup instructions.
* `USER_GUIDE.md`: More detailed guide on installation and usage of the bundled application.

These should be up-to-date.

---

Hopefully, you won't need to do much of the rebuilding, but these are the steps if required. Let me know if you have any
questions!