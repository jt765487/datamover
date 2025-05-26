#!/bin/bash
set -euo pipefail

# --- Default Configuration ---
# This will be overridden by pyproject.toml or an explicit command-line option
DEFAULT_RELEASE_VERSION="0.0.0-dev"

INSTALLER_DEV_DIR="./installer"      # Source dir for installer scripts & guides
DATAMOVER_WHEEL_DIR="./dist"         # Source dir for the datamover .whl file
PYPROJECT_TOML_PATH="./pyproject.toml" # Path to your pyproject.toml
STAGING_DIR="_release_staging"       # Temporary directory for bundling

SCRIPT_NAME=$(basename "$0")
VERBOSE_BUNDLE_SCRIPT=false # Set to true via an option if more bundler debug output is needed

# --- Logging Functions ---
info() { echo "[$SCRIPT_NAME INFO] $*"; }
warn() { echo >&2 "[$SCRIPT_NAME WARN] $*"; }
error_exit() { echo >&2 "[$SCRIPT_NAME ERROR] $*"; exit 1; }
debug_bundle() {
  if [[ "$VERBOSE_BUNDLE_SCRIPT" == true ]]; then
    echo "[$SCRIPT_NAME DEBUG] $*";
  fi
}

# --- Display Help Information ---
show_help() {
  cat <<EOF
Usage: $SCRIPT_NAME <path_to_external_app_binary> [OPTIONS]

Creates a distributable bundle for the exportcliv2 suite.
The bundle will have 'deploy_orchestrator.sh' and guides at the top level.
Shell scripts within the bundle will be made executable.

Arguments:
  <path_to_external_app_binary>   REQUIRED: Path to the external application binary.

Options:
  -r, --release-version VERSION  Optional: Explicitly set the release version for the bundle.
                                 If not set, attempts to read from '$PYPROJECT_TOML_PATH'.
  -k, --keep-staging             Optional: Do not delete the staging directory after bundling.
  --verbose-bundler              Optional: Enable verbose debug output from this bundling script.
  -h, --help                     Show this help message and exit.

Requirements:
  - The external application binary must exist at the specified path.
  - The datamover .whl file must exist in '$DATAMOVER_WHEEL_DIR'.
    Run 'uv build' in your datamover project if it's missing.
  - '$PYPROJECT_TOML_PATH' should exist and contain the project version if not overridden.
  - Key installer scripts like 'deploy_orchestrator.sh' must exist in '${INSTALLER_DEV_DIR}/exportcliv2-deploy/'.
EOF
}

# --- Argument Parsing ---
EXTERNAL_APP_BINARY_PATH=""
RELEASE_VERSION="" # Will be determined or taken from arg
KEEP_STAGING=false

# Parse options first
while [[ $# -gt 0 ]]; do
  case "$1" in
    -r|--release-version)
      if [[ -z "${2:-}" ]]; then error_exit "Option $1 requires a VERSION argument."; fi
      RELEASE_VERSION="$2"
      shift 2
      ;;
    -k|--keep-staging)
      KEEP_STAGING=true
      shift
      ;;
    --verbose-bundler)
      VERBOSE_BUNDLE_SCRIPT=true
      shift
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    -*)
      error_exit "Unknown option: $1. Use --help for usage."
      ;;
    *)
      if [[ -z "$EXTERNAL_APP_BINARY_PATH" ]]; then
        EXTERNAL_APP_BINARY_PATH="$1"
      else
        error_exit "Unexpected argument: '$1'. Use --help for usage."
      fi
      shift
      ;;
  esac
done

if [[ -z "$EXTERNAL_APP_BINARY_PATH" ]]; then
  show_help
  error_exit "Path to the external application binary is required."
fi

# --- Determine Release Version ---
if [[ -z "$RELEASE_VERSION" ]]; then # If not set by command line
  info "Attempting to determine release version from '$PYPROJECT_TOML_PATH'..."
  if [[ ! -f "$PYPROJECT_TOML_PATH" ]]; then
    error_exit "Cannot determine version: '$PYPROJECT_TOML_PATH' not found and --release-version not specified."
  fi
  PYPROJECT_VERSION=$(grep -E "^\s*version\s*=\s*\"[^\"]+\"" "$PYPROJECT_TOML_PATH" | sed -E 's/^\s*version\s*=\s*"([^"]+)"\s*$/\1/' | head -n 1)
  if [[ -z "$PYPROJECT_VERSION" ]]; then
    error_exit "Could not automatically determine version from '$PYPROJECT_TOML_PATH'.
Please ensure it's set (e.g., under [project] or [tool.poetry] as 'version = \"X.Y.Z\"') or use --release-version."
  fi
  RELEASE_VERSION="$PYPROJECT_VERSION"
  info "Using release version from pyproject.toml: $RELEASE_VERSION"
else
  info "Using release version from command line: $RELEASE_VERSION"
fi

# --- Derived Configuration ---
BUNDLE_TOP_DIR="exportcliv2-suite-v${RELEASE_VERSION}"
ARCHIVE_NAME="${BUNDLE_TOP_DIR}.tar.gz"

# --- Setup Trap for Cleanup ---
cleanup_staging() {
  if [[ "$KEEP_STAGING" == false && -d "$STAGING_DIR" ]]; then
    debug_bundle "Cleaning up staging directory: $STAGING_DIR"
    rm -rf "$STAGING_DIR"
  elif [[ -d "$STAGING_DIR" ]]; then
    info "Staging directory kept at: $STAGING_DIR"
  fi
}
trap cleanup_staging EXIT INT TERM

# --- Sanity Checks ---
info "Performing sanity checks..."
if [[ ! -f "$EXTERNAL_APP_BINARY_PATH" ]]; then
  error_exit "External application binary not found at: $EXTERNAL_APP_BINARY_PATH"
fi
EXTERNAL_APP_BINARY_FILENAME=$(basename "$EXTERNAL_APP_BINARY_PATH")

DEPLOY_ORCHESTRATOR_SOURCE_NAME="deploy_orchestrator.sh"
DEPLOY_ORCHESTRATOR_SOURCE="${INSTALLER_DEV_DIR}/exportcliv2-deploy/${DEPLOY_ORCHESTRATOR_SOURCE_NAME}"
if [[ ! -f "$DEPLOY_ORCHESTRATOR_SOURCE" ]]; then
  error_exit "Main installer script '${DEPLOY_ORCHESTRATOR_SOURCE_NAME}' not found at: $DEPLOY_ORCHESTRATOR_SOURCE"
fi


info "Looking for the datamover wheel file in '$DATAMOVER_WHEEL_DIR'..."
if [[ ! -d "$DATAMOVER_WHEEL_DIR" ]]; then
  error_exit "Datamover wheel directory '$DATAMOVER_WHEEL_DIR' not found. Please build the datamover project."
fi

datamover_wheel_file=$(find "$DATAMOVER_WHEEL_DIR" -maxdepth 1 -name "datamover*${RELEASE_VERSION}*.whl" -print -quit)
if [[ -z "$datamover_wheel_file" || ! -f "$datamover_wheel_file" ]]; then
  warn "Could not find datamover wheel matching version '$RELEASE_VERSION' directly in '$DATAMOVER_WHEEL_DIR'."
  info "Falling back to find any datamover*.whl file in '$DATAMOVER_WHEEL_DIR'..."
  datamover_wheel_file=$(find "$DATAMOVER_WHEEL_DIR" -maxdepth 1 -name "datamover*.whl" -print -quit)
fi

if [[ -z "$datamover_wheel_file" || ! -f "$datamover_wheel_file" ]]; then
  error_exit "Datamover .whl file not found in '$DATAMOVER_WHEEL_DIR'. Please ensure the project is built."
fi
DATAMOVER_WHEEL_FILENAME=$(basename "$datamover_wheel_file")

info "Verifying datamover wheel version..."
if [[ "$DATAMOVER_WHEEL_FILENAME" != *"$RELEASE_VERSION"* ]]; then
  error_exit "Version Mismatch: Datamover wheel filename '$DATAMOVER_WHEEL_FILENAME' does not match the determined release version '$RELEASE_VERSION'."
else
  info "Datamover wheel '$DATAMOVER_WHEEL_FILENAME' matches release version '$RELEASE_VERSION'."
fi

# --- Prepare Staging Area ---
info "Starting bundle creation for ${BUNDLE_TOP_DIR}"
STAGING_BUNDLE_ROOT="${STAGING_DIR}/${BUNDLE_TOP_DIR}"
STAGED_DEPLOY_SUBDIR="${STAGING_BUNDLE_ROOT}/exportcliv2-deploy"

info "Preparing staging directory: ${STAGING_BUNDLE_ROOT}"
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_BUNDLE_ROOT"
mkdir -p "$STAGED_DEPLOY_SUBDIR"

# --- Copy Files to Staging ---
info "Copying '${DEPLOY_ORCHESTRATOR_SOURCE_NAME}' to bundle root..."
cp "$DEPLOY_ORCHESTRATOR_SOURCE" "${STAGING_BUNDLE_ROOT}/${DEPLOY_ORCHESTRATOR_SOURCE_NAME}"

info "Copying guides to bundle root..."
cp "${INSTALLER_DEV_DIR}/QUICK_START_GUIDE.md" "${STAGING_BUNDLE_ROOT}/"
cp "${INSTALLER_DEV_DIR}/USER_GUIDE.md" "${STAGING_BUNDLE_ROOT}/"

info "Copying remaining 'exportcliv2-deploy' contents to '${STAGED_DEPLOY_SUBDIR}'..."
rsync -av --exclude="${DEPLOY_ORCHESTRATOR_SOURCE_NAME}" "${INSTALLER_DEV_DIR}/exportcliv2-deploy/" "$STAGED_DEPLOY_SUBDIR/"

info "Copying datamover wheel: $DATAMOVER_WHEEL_FILENAME to ${STAGED_DEPLOY_SUBDIR}"
cp "$datamover_wheel_file" "${STAGED_DEPLOY_SUBDIR}/${DATAMOVER_WHEEL_FILENAME}"

info "Copying external application binary: $EXTERNAL_APP_BINARY_FILENAME to ${STAGED_DEPLOY_SUBDIR}"
cp "$EXTERNAL_APP_BINARY_PATH" "${STAGED_DEPLOY_SUBDIR}/${EXTERNAL_APP_BINARY_FILENAME}"

# --- Update/Verify install-app.conf in the staged 'exportcliv2-deploy' subdirectory ---
STAGED_INSTALL_APP_CONF="${STAGED_DEPLOY_SUBDIR}/install-app.conf"
info "Ensuring correct filenames in staged configuration: $STAGED_INSTALL_APP_CONF"

if [[ ! -f "$STAGED_INSTALL_APP_CONF" ]]; then
    error_exit "Staged install-app.conf not found: $STAGED_INSTALL_APP_CONF. Check rsync copy."
fi

TEMP_INSTALL_APP_CONF="${STAGED_INSTALL_APP_CONF}.tmp.$(date +%s%N)" # More unique temp name
cp "$STAGED_INSTALL_APP_CONF" "$TEMP_INSTALL_APP_CONF"

APP_BINARY_REPLACEMENT_VALUE="\"$EXTERNAL_APP_BINARY_FILENAME\""
DATAMOVER_WHEEL_REPLACEMENT_VALUE="\"$DATAMOVER_WHEEL_FILENAME\""

if grep -q "^\s*VERSIONED_APP_BINARY_FILENAME\s*=" "$TEMP_INSTALL_APP_CONF"; then
    sed -E "s|^(\s*VERSIONED_APP_BINARY_FILENAME\s*=\s*).*|\1${APP_BINARY_REPLACEMENT_VALUE}|" "$TEMP_INSTALL_APP_CONF" > "$STAGED_INSTALL_APP_CONF"
else
    info "Appending VERSIONED_APP_BINARY_FILENAME to $STAGED_INSTALL_APP_CONF."
    echo "VERSIONED_APP_BINARY_FILENAME=${APP_BINARY_REPLACEMENT_VALUE}" >> "$STAGED_INSTALL_APP_CONF"
fi
cp "$STAGED_INSTALL_APP_CONF" "$TEMP_INSTALL_APP_CONF"

if grep -q "^\s*VERSIONED_DATAMOVER_WHEEL_FILENAME\s*=" "$TEMP_INSTALL_APP_CONF"; then
    sed -E "s|^(\s*VERSIONED_DATAMOVER_WHEEL_FILENAME\s*=\s*).*|\1${DATAMOVER_WHEEL_REPLACEMENT_VALUE}|" "$TEMP_INSTALL_APP_CONF" > "$STAGED_INSTALL_APP_CONF"
else
    info "Appending VERSIONED_DATAMOVER_WHEEL_FILENAME to $STAGED_INSTALL_APP_CONF."
    echo "VERSIONED_DATAMOVER_WHEEL_FILENAME=${DATAMOVER_WHEEL_REPLACEMENT_VALUE}" >> "$STAGED_INSTALL_APP_CONF"
fi
rm "$TEMP_INSTALL_APP_CONF"
info "Staged install-app.conf processed."

# --- Set Script Permissions ---
info "Setting executable permissions for .sh files in the bundle..."
# This find command will locate all files ending in .sh within the staged bundle root
# and make them executable. It will not affect .sh.template files.
find "${STAGING_BUNDLE_ROOT}" -type f -name "*.sh" -print0 | while IFS= read -r -d $'\0' script_file; do
  debug_bundle "Making executable: $script_file"
  chmod +x "$script_file"
done
info "Executable permissions set."


# --- Comprehensive File Check in Staging Area ---
info "Verifying contents of the staged bundle at '${STAGING_BUNDLE_ROOT}'..."
all_files_ok=true

declare -A expected_bundle_contents=(
    ["${DEPLOY_ORCHESTRATOR_SOURCE_NAME}"]="file"
    ["QUICK_START_GUIDE.md"]="file"
    ["USER_GUIDE.md"]="file"
    ["exportcliv2-deploy/install_base_exportcliv2.sh"]="file"
    ["exportcliv2-deploy/configure_instance.sh"]="file"
    ["exportcliv2-deploy/manage_services.sh"]="file"
    ["exportcliv2-deploy/install-app.conf"]="file"
    ["exportcliv2-deploy/${EXTERNAL_APP_BINARY_FILENAME}"]="file"
    ["exportcliv2-deploy/${DATAMOVER_WHEEL_FILENAME}"]="file"
    ["exportcliv2-deploy/config_files"]="dir"
    ["exportcliv2-deploy/config_files/common.auth.conf"]="file"
    ["exportcliv2-deploy/config_files/config.ini.template"]="file"
    ["exportcliv2-deploy/config_files/run_exportcliv2_instance.sh.template"]="file" # This is a template, not directly executable
    ["exportcliv2-deploy/systemd_units"]="dir"
    ["exportcliv2-deploy/systemd_units/bitmover.service.template"]="file"
    ["exportcliv2-deploy/systemd_units/exportcliv2@.service.template"]="file"
    ["exportcliv2-deploy/systemd_units/exportcliv2-restart@.path.template"]="file"
    ["exportcliv2-deploy/systemd_units/exportcliv2-restart@.service.template"]="file"
)

for item_path in "${!expected_bundle_contents[@]}"; do
    item_type="${expected_bundle_contents[$item_path]}"
    full_path="${STAGING_BUNDLE_ROOT}/${item_path}"

    check_passed=true
    if [[ "$item_type" == "file" && ! -f "$full_path" ]]; then
        check_passed=false
    elif [[ "$item_type" == "dir" && ! -d "$full_path" ]]; then
        check_passed=false
    fi

    if [[ "$check_passed" == false ]]; then
        warn "Bundle Verification FAILED: Expected $item_type missing at '$item_path' (full path: '$full_path')"
        all_files_ok=false
    else
        debug_bundle "Bundle Verification OK: Found $item_type at '$item_path'"
    fi
done

if [[ "$all_files_ok" == false ]]; then
    error_exit "Bundle verification failed. Critical files/directories are missing in the staging area."
else
    info "Bundle contents verified successfully in staging area."
fi

# --- Create Tarball ---
info "Creating tarball: ${ARCHIVE_NAME}"
(
  cd "$STAGING_DIR" || exit 1
  tar -czf "../${ARCHIVE_NAME}" "$BUNDLE_TOP_DIR"
) || error_exit "Failed to create tarball."

info "--- Bundle Created Successfully: ${ARCHIVE_NAME} ---"
info "Located at: $(pwd)/${ARCHIVE_NAME}"
info "To inspect contents (permissions visible with -tvf): tar -tzvf ${ARCHIVE_NAME}"
# EXIT trap handles cleanup_staging