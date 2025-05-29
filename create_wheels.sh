#!/bin/bash
set -euo pipefail

SCRIPT_NAME=$(basename "$0")
PROJECT_ROOT_DIR="." # Assuming the script is run from the root of your datamover project
DIST_DIR="${PROJECT_ROOT_DIR}/dist"
OFFLINE_WHEELS_DIR="${PROJECT_ROOT_DIR}/offline_package/wheels"
PYPROJECT_TOML_PATH="${PROJECT_ROOT_DIR}/pyproject.toml"
VENV_PYTHON="${PROJECT_ROOT_DIR}/.venv/bin/python"

# --- Logging Functions ---
info() { echo "[$SCRIPT_NAME INFO] $*"; }
warn() { echo >&2 "[$SCRIPT_NAME WARN] $*"; }
error_exit() { echo >&2 "[$SCRIPT_NAME ERROR] $*"; exit 1; }

# --- Help Function ---
show_help() {
cat << EOF
Usage: $SCRIPT_NAME [OPTIONS]

Prepares a directory with all necessary Python wheels for an offline installation
of the 'datamover' project.

This script will:
1. Clean and create the offline wheels directory (default: ./offline_package/wheels).
2. Ensure the 'uv' virtual environment (.venv) is created/up-to-date.
3. Ensure 'pip' is installed in the virtual environment (adding it if necessary).
4. Build the 'datamover' project using 'uv build'.
5. Copy the built 'datamover' wheel to the offline wheels directory.
6. Download all dependencies of 'datamover' into the offline wheels directory.
7. Explicitly download 'pip', 'setuptools', and 'wheel' into the directory.

Options:
  -h, --help        Show this help message and exit.
  --wheels-dir DIR  Specify a custom directory for storing the offline wheels.
                    Default: "${OFFLINE_WHEELS_DIR}"
  --dist-dir DIR    Specify a custom directory for build artifacts (from 'uv build').
                    Default: "${DIST_DIR}"
EOF
}

# --- Argument Parsing for options ---
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

# --- Ensure Prerequisite tools ---
if ! command -v uv &> /dev/null; then
    error_exit "'uv' command not found. Please install uv (https://github.com/astral-sh/uv)."
fi

# --- Main Logic ---
info "Starting preparation of offline wheels..."
info "Target offline wheels directory: ${OFFLINE_WHEELS_DIR}"
info "Build artifacts (dist) directory: ${DIST_DIR}"

# 1. Clean and Create Target Directories
info "Cleaning and creating offline wheels directory: ${OFFLINE_WHEELS_DIR}"
rm -rf "${OFFLINE_WHEELS_DIR}"
mkdir -p "${OFFLINE_WHEELS_DIR}"

info "Ensuring build artifacts (dist) directory exists: ${DIST_DIR}"
mkdir -p "${DIST_DIR}" # Also ensure dist dir exists before build

# 2. Sync/Create Virtual Environment & Ensure Pip  <<< MOVED EARLIER
info "Ensuring virtual environment is up-to-date with 'uv sync'..."
# If 'pip' is a dev dependency, you might use 'uv sync --extra dev' or similar
if ! uv sync; then
    error_exit "'uv sync' failed. Ensure your pyproject.toml and uv.lock are consistent."
fi
info "Virtual environment synced."

info "Ensuring 'pip' is available in the virtual environment..."
if ! "${VENV_PYTHON}" -m pip --version &> /dev/null; then
    info "'pip' not found in venv, attempting to install with 'uv add pip'..."
    if ! uv add pip; then
        error_exit "Failed to add 'pip' to the project using 'uv add pip'."
    fi
    info "'pip' added to the project and installed in the virtual environment."
else
    info "'pip' is already available in the virtual environment."
fi

# 3. Build the project
info "Building 'datamover' project using 'uv build'..."
if ! uv build --out-dir "${DIST_DIR}"; then
    error_exit "Failed to build project with 'uv build'."
fi
info "Project built successfully. Artifacts in ${DIST_DIR}"

# 4. Find and Copy the project wheel
info "Looking for the datamover wheel in '${DIST_DIR}'..."
project_version=""
if [[ -f "$PYPROJECT_TOML_PATH" ]]; then
    project_version=$(grep -E "^\s*version\s*=\s*\"[^\"]+\"" "$PYPROJECT_TOML_PATH" | sed -E 's/^\s*version\s*=\s*"([^"]+)"\s*$/\1/' | head -n 1)
fi

datamover_wheel_file=""
if [[ -n "$project_version" ]]; then
    datamover_wheel_file=$(find "$DIST_DIR" -maxdepth 1 -name "datamover*${project_version}*.whl" -print -quit 2>/dev/null)
fi

if [[ -z "$datamover_wheel_file" || ! -f "$datamover_wheel_file" ]]; then
  warn "Could not find datamover wheel strictly matching version '$project_version' in '$DIST_DIR'."
  info "Falling back to find any datamover*.whl file in '$DIST_DIR'..."
  datamover_wheel_file=$(find "$DIST_DIR" -maxdepth 1 -name "datamover*.whl" -print -quit 2>/dev/null)
fi

if [[ -z "$datamover_wheel_file" || ! -f "$datamover_wheel_file" ]]; then
  error_exit "Datamover .whl file not found in '$DIST_DIR' after build. Please check the build process."
fi
datamover_wheel_filename=$(basename "$datamover_wheel_file")
info "Found datamover wheel: $datamover_wheel_filename. Copying to ${OFFLINE_WHEELS_DIR}..."
cp "$datamover_wheel_file" "${OFFLINE_WHEELS_DIR}/"

# 5. Download project dependencies
info "Downloading dependencies for the current project ('.') to ${OFFLINE_WHEELS_DIR}..."
if ! "${VENV_PYTHON}" -m pip download --dest "${OFFLINE_WHEELS_DIR}" .; then
    error_exit "Failed to download project dependencies."
fi
info "Project dependencies downloaded."

# 6. Explicitly download pip, setuptools, and wheel
info "Downloading 'pip', 'setuptools', and 'wheel' to ${OFFLINE_WHEELS_DIR}..."
if ! "${VENV_PYTHON}" -m pip download --dest "${OFFLINE_WHEELS_DIR}" pip setuptools wheel; then
    error_exit "Failed to download pip, setuptools, or wheel."
fi
info "pip, setuptools, and wheel downloaded."

# 7. Verification
info "Offline wheels preparation complete. Contents of ${OFFLINE_WHEELS_DIR}:"
ls -l "${OFFLINE_WHEELS_DIR}"

info "--- Successfully prepared offline wheels in ${OFFLINE_WHEELS_DIR} ---"