#!/bin/bash
set -euo pipefail

# Script V1.0.2 to prepare offline Python wheels for the 'datamover' project using 'uv'.
# Uses venv pip for download as 'uv pip download' is not available in all uv versions.

# --- Configuration ---
SCRIPT_NAME=$(basename "$0")
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT_DIR="$SCRIPT_DIR"

DEFAULT_OFFLINE_WHEELS_DIR="${PROJECT_ROOT_DIR}/offline_package/wheels"
DEFAULT_DIST_DIR="${PROJECT_ROOT_DIR}/dist"
PYPROJECT_TOML_PATH="${PROJECT_ROOT_DIR}/pyproject.toml"
VENV_PYTHON="${PROJECT_ROOT_DIR}/.venv/bin/python" # Standard uv venv path

OFFLINE_WHEELS_DIR="${DEFAULT_OFFLINE_WHEELS_DIR}"
DIST_DIR="${DEFAULT_DIST_DIR}"

# --- Logging Functions ---
info() { echo "[$SCRIPT_NAME INFO] $*"; }
warn() { echo >&2 "[$SCRIPT_NAME WARN] $*"; }
error_exit() { echo >&2 "[$SCRIPT_NAME ERROR] $*"; exit 1; }

# --- Help Function ---
show_help() {
cat << EOF
Usage: $SCRIPT_NAME [OPTIONS]

Prepares a directory with all necessary Python wheels for an offline installation
of the 'datamover' project using 'uv' for environment management and build,
and the virtual environment's 'pip' for downloading wheels.

This script will:
1. Clean and create the offline wheels directory.
2. Clean and create the build artifacts (dist) directory.
3. Ensure the 'uv' virtual environment (.venv) is created/up-to-date using 'uv sync --extra dev'
   (to ensure 'pip' from dev dependencies is available in the venv).
4. Build the 'datamover' project using 'uv build'.
5. Copy the built 'datamover' wheel to the offline wheels directory.
6. Download all dependencies of 'datamover' into the offline wheels directory using the venv's 'pip download'.
7. Explicitly download 'pip', 'setuptools', and 'wheel' into the directory using the venv's 'pip download'.

Options:
  -h, --help        Show this help message and exit.
  --wheels-dir DIR  Specify a custom directory for storing the offline wheels.
                    Default: "${DEFAULT_OFFLINE_WHEELS_DIR}"
  --dist-dir DIR    Specify a custom directory for build artifacts (from 'uv build').
                    Default: "${DEFAULT_DIST_DIR}"
EOF
}

# --- Argument Parsing ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      show_help
      exit 0
      ;;
    --wheels-dir)
      if [[ -z "${2:-}" ]]; then error_exit "Option $1 requires a DIRECTORY argument."; fi
      OFFLINE_WHEELS_DIR="$2"
      shift 2
      ;;
    --dist-dir)
      if [[ -z "${2:-}" ]]; then error_exit "Option $1 requires a DIRECTORY argument."; fi
      DIST_DIR="$2"
      shift 2
      ;;
    *)
      error_exit "Unknown option: $1. Use --help for usage."
      ;;
  esac
done

# --- Prerequisite Checks ---
if ! command -v uv &> /dev/null; then
    error_exit "'uv' command not found. Please install uv (https://github.com/astral-sh/uv) and ensure it's in your PATH."
fi
if [[ ! -f "$PYPROJECT_TOML_PATH" ]]; then
    error_exit "pyproject.toml not found at expected location: ${PYPROJECT_TOML_PATH}."
fi

# --- Main Logic ---
info "Starting preparation of offline wheels for the 'datamover' project."
info "Project root directory: ${PROJECT_ROOT_DIR}"
info "Target offline wheels directory: ${OFFLINE_WHEELS_DIR}"
info "Build artifacts (dist) directory: ${DIST_DIR}"

# 1. Clean and Create Target Directories
info "Cleaning and creating offline wheels directory: ${OFFLINE_WHEELS_DIR}"
rm -rf "${OFFLINE_WHEELS_DIR}"
mkdir -p "${OFFLINE_WHEELS_DIR}"
info "Cleaning and creating build artifacts (dist) directory: ${DIST_DIR}"
rm -rf "${DIST_DIR}"
mkdir -p "${DIST_DIR}"

# 2. Sync/Create Virtual Environment & Ensure Pip
info "Ensuring virtual environment is up-to-date and 'pip' is available (using 'uv sync --extra dev')..."
if ! (cd "${PROJECT_ROOT_DIR}" && uv sync --extra dev); then
    warn "'uv sync --extra dev' failed. This might mean 'pip' (from dev dependencies) is not installed in the venv."
    warn "Attempting 'uv sync' without dev dependencies and then trying to install pip manually if needed."
    if ! (cd "${PROJECT_ROOT_DIR}" && uv sync); then
        error_exit "'uv sync' (basic) also failed. Ensure pyproject.toml and uv.lock are consistent."
    fi
fi
info "Virtual environment sync process completed."

# Explicitly check if pip is callable from the venv
info "Checking for 'pip' in the virtual environment (${VENV_PYTHON})..."
if ! "${VENV_PYTHON}" -m pip --version &> /dev/null; then
    info "'pip' not found or not executable in venv. Attempting to install it using 'uv pip install pip'."
    # This command installs pip into the venv without modifying pyproject.toml
    if ! (cd "${PROJECT_ROOT_DIR}" && uv pip install pip); then # 'uv pip install' should exist
        error_exit "Failed to install 'pip' into the virtual environment using 'uv pip install pip'."
    fi
    info "'pip' installed into the virtual environment."
else
    info "'pip' is available in the virtual environment."
fi


# 3. Build the project
info "Building 'datamover' project using 'uv build'..."
if ! (cd "${PROJECT_ROOT_DIR}" && uv build --out-dir "${DIST_DIR}"); then
    error_exit "Failed to build project with 'uv build'."
fi
info "Project built successfully. Artifacts in ${DIST_DIR}"

# 4. Find and Copy the project wheel
info "Looking for the 'datamover' wheel in '${DIST_DIR}'..."
datamover_wheel_file=$(find "$DIST_DIR" -maxdepth 1 -type f -name "datamover*.whl" -print | head -n 1)
if [[ -z "$datamover_wheel_file" || ! -f "$datamover_wheel_file" ]]; then
  error_exit "'datamover' .whl file not found in '${DIST_DIR}' after build."
fi
datamover_wheel_filename=$(basename "$datamover_wheel_file")
info "Found 'datamover' wheel: $datamover_wheel_filename. Copying to ${OFFLINE_WHEELS_DIR}..."
cp "$datamover_wheel_file" "${OFFLINE_WHEELS_DIR}/"

# 5. Download project dependencies using venv pip
info "Downloading dependencies for the current project ('.') to ${OFFLINE_WHEELS_DIR} using venv 'pip download'..."
if ! (cd "${PROJECT_ROOT_DIR}" && "${VENV_PYTHON}" -m pip download --dest "${OFFLINE_WHEELS_DIR}" .); then
    error_exit "Failed to download project dependencies using venv 'pip download'."
fi
info "Project dependencies downloaded."

# 6. Explicitly download pip, setuptools, and wheel using venv pip
info "Downloading 'pip', 'setuptools', and 'wheel' to ${OFFLINE_WHEELS_DIR} using venv 'pip download'..."
if ! (cd "${PROJECT_ROOT_DIR}" && "${VENV_PYTHON}" -m pip download --dest "${OFFLINE_WHEELS_DIR}" pip setuptools wheel); then
    error_exit "Failed to download 'pip', 'setuptools', or 'wheel' using venv 'pip download'."
fi
info "'pip', 'setuptools', and 'wheel' downloaded."

# 7. Verification
info "Offline wheels preparation complete. Contents of ${OFFLINE_WHEELS_DIR}:"
ls -l "${OFFLINE_WHEELS_DIR}"

info "--- Successfully prepared offline wheels in ${OFFLINE_WHEELS_DIR} ---"