#!/bin/bash
set -euo pipefail
IFS=$'\n\t' # IFS not strictly needed at the top if not immediately used, but good practice.

# --- Default Configuration ---
INSTALLER_DEV_DIR="./installer"      # Source dir for installer scripts & guides
DATAMOVER_WHEEL_DIR="./dist"         # Source dir for the datamover .whl file
OFFLINE_WHEELS_SOURCE_DIR="./offline_package/wheels"
PYPROJECT_TOML_PATH="./pyproject.toml"
STAGING_DIR="_release_staging"
PATCH_SCRIPT_NAME="install_patch.sh" # Name of the new patch script

SCRIPT_NAME=$(basename "$0")
VERBOSE_BUNDLE_SCRIPT=false

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
Usage: $SCRIPT_NAME [OPTIONS]

Creates a distributable bundle for the exportcliv2 suite, including the
application binary, necessary Python components, and management scripts.
Shell scripts within the bundle will be made executable.

The binary specified by --production-binary will be configured as the
active application binary in the generated install-app.conf.

Arguments & Options:
  --production-binary <PATH>   Path to the production 'exportcliv2' binary.
                                 (Required). This binary will be set as the active one.
  --emulator-binary <PATH>     Path to an alternative/emulator 'exportcliv2' binary.
                                 (Optional, for inclusion in the package).
  -r, --release-version VERSION  Optional: Explicitly set the release version for the bundle.
                                 If not set, attempts to read from '$PYPROJECT_TOML_PATH'.
  -k, --keep-staging             Optional: Do not delete the staging directory after bundling.
  --offline-wheels-dir DIR       Optional: Override the default directory for offline Python dependency wheels.
                                 Default: '$OFFLINE_WHEELS_SOURCE_DIR'
  --verbose-bundler              Optional: Enable verbose debug output from this bundling script.
  -h, --help                     Show this help message and exit.

Requirements:
  - '--production-binary' must be specified.
  - Paths provided for binaries must exist and be executable.
  - The datamover .whl file must exist in '$DATAMOVER_WHEEL_DIR'.
  - Dependency wheels must exist in the offline wheels directory.
  - '$PYPROJECT_TOML_PATH' should exist if --release-version is not specified.
  - Key installer scripts must exist (e.g., in '${INSTALLER_DEV_DIR}/exportcliv2-deploy/').
  - The '${PATCH_SCRIPT_NAME}' must exist (e.g., in '${INSTALLER_DEV_DIR}/').
EOF
}

# --- Argument Parsing ---
PRODUCTION_BINARY_PATH=""
EMULATOR_BINARY_PATH=""
RELEASE_VERSION=""
KEEP_STAGING=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --production-binary)
      if [[ -z "${2:-}" ]]; then error_exit "Option $1 requires a PATH argument."; fi
      PRODUCTION_BINARY_PATH="$2"; shift 2 ;;
    --emulator-binary)
      if [[ -z "${2:-}" ]]; then error_exit "Option $1 requires a PATH argument."; fi
      EMULATOR_BINARY_PATH="$2"; shift 2 ;;
    -r|--release-version)
      if [[ -z "${2:-}" ]]; then error_exit "Option $1 requires a VERSION argument."; fi
      RELEASE_VERSION="$2"; shift 2 ;;
    -k|--keep-staging)
      KEEP_STAGING=true; shift ;;
    --offline-wheels-dir)
      if [[ -z "${2:-}" ]]; then error_exit "Option $1 requires a DIRECTORY argument."; fi
      OFFLINE_WHEELS_SOURCE_DIR="$2"; shift 2 ;;
    --verbose-bundler)
      VERBOSE_BUNDLE_SCRIPT=true; shift ;;
    -h|--help)
      show_help; exit 0 ;;
    *)
      error_exit "Unknown option or argument: $1. Use --help for usage." ;;
  esac
done

if [[ -z "$PRODUCTION_BINARY_PATH" ]]; then
  show_help
  error_exit "--production-binary must be specified."
fi

# --- Determine Release Version ---
if [[ -z "$RELEASE_VERSION" ]]; then
  info "Attempting to determine release version from '$PYPROJECT_TOML_PATH'..."
  if [[ ! -f "$PYPROJECT_TOML_PATH" ]]; then
    error_exit "Cannot determine version: '$PYPROJECT_TOML_PATH' not found and --release-version not specified."
  fi
  PYPROJECT_VERSION=$(grep -E "^\s*version\s*=\s*\"[^\"]+\"" "$PYPROJECT_TOML_PATH" | sed -E 's/^\s*version\s*=\s*"([^"]+)"\s*$/\1/' | head -n 1)
  if [[ -z "$PYPROJECT_VERSION" ]]; then
    error_exit "Could not automatically determine version from '$PYPROJECT_TOML_PATH'. Use --release-version."
  fi
  RELEASE_VERSION="$PYPROJECT_VERSION"
  info "Using release version from pyproject.toml: $RELEASE_VERSION"
else
  info "Using release version from command line: $RELEASE_VERSION"
fi

# --- Derived Configuration ---
BUNDLE_TOP_DIR="exportcliv2-suite-v${RELEASE_VERSION}"
ARCHIVE_NAME="${BUNDLE_TOP_DIR}.tar.gz"
WHEELHOUSE_TARGET_SUBDIR_NAME="wheelhouse"

# --- Setup Trap for Cleanup ---
# shellcheck disable=SC2317
cleanup_staging() {
  if [[ "$KEEP_STAGING" == false && -d "$STAGING_DIR" ]]; then
    debug_bundle "Cleaning up staging directory: $STAGING_DIR"
    rm -rf "$STAGING_DIR"
  elif [[ -d "$STAGING_DIR" ]]; then
    info "Staging directory kept at: $STAGING_DIR"
  fi
}
trap cleanup_staging EXIT INT TERM

# --- Sanity Checks and Determine Filenames ---
info "Performing sanity checks for provided binaries..."
PRODUCTION_BINARY_FILENAME=""
EMULATOR_BINARY_FILENAME=""
CONFIGURED_APP_BINARY_FILENAME=""

if [[ -n "$PRODUCTION_BINARY_PATH" ]]; then
  if [[ ! -f "$PRODUCTION_BINARY_PATH" ]]; then error_exit "Production binary not found at: $PRODUCTION_BINARY_PATH"; fi
  if [[ ! -x "$PRODUCTION_BINARY_PATH" ]]; then warn "Production binary at '$PRODUCTION_BINARY_PATH' is not executable. Attempting to make it executable."; chmod +x "$PRODUCTION_BINARY_PATH" || error_exit "Failed to make production binary executable."; fi
  PRODUCTION_BINARY_FILENAME=$(basename "$PRODUCTION_BINARY_PATH")
  CONFIGURED_APP_BINARY_FILENAME="$PRODUCTION_BINARY_FILENAME"
  info "Production binary (will be active): '$PRODUCTION_BINARY_FILENAME' (from $PRODUCTION_BINARY_PATH)"
fi

if [[ -n "$EMULATOR_BINARY_PATH" ]]; then
  if [[ ! -f "$EMULATOR_BINARY_PATH" ]]; then error_exit "Emulator binary not found at: $EMULATOR_BINARY_PATH"; fi
  if [[ ! -x "$EMULATOR_BINARY_PATH" ]]; then warn "Emulator binary at '$EMULATOR_BINARY_PATH' is not executable. Attempting to make it executable."; chmod +x "$EMULATOR_BINARY_PATH" || error_exit "Failed to make emulator binary executable."; fi
  EMULATOR_BINARY_FILENAME=$(basename "$EMULATOR_BINARY_PATH")
  info "Emulator binary (for inclusion): '$EMULATOR_BINARY_FILENAME' (from $EMULATOR_BINARY_PATH)"
fi

DEPLOY_ORCHESTRATOR_SOURCE_NAME="deploy_orchestrator.sh"
DEPLOY_ORCHESTRATOR_SOURCE="${INSTALLER_DEV_DIR}/exportcliv2-deploy/${DEPLOY_ORCHESTRATOR_SOURCE_NAME}"
if [[ ! -f "$DEPLOY_ORCHESTRATOR_SOURCE" ]]; then
  error_exit "Main installer script '${DEPLOY_ORCHESTRATOR_SOURCE_NAME}' not found at: $DEPLOY_ORCHESTRATOR_SOURCE"
fi

PATCH_SCRIPT_SOURCE="${INSTALLER_DEV_DIR}/${PATCH_SCRIPT_NAME}"
if [[ ! -f "$PATCH_SCRIPT_SOURCE" ]]; then
  error_exit "Patch script '${PATCH_SCRIPT_NAME}' not found at: $PATCH_SCRIPT_SOURCE"
fi

if [[ ! -d "$OFFLINE_WHEELS_SOURCE_DIR" ]]; then error_exit "Offline wheels source directory not found at: '$OFFLINE_WHEELS_SOURCE_DIR'"; fi
if ! ls "${OFFLINE_WHEELS_SOURCE_DIR}"/*.whl &> /dev/null; then
    warn "No .whl files found in offline wheels source directory: '$OFFLINE_WHEELS_SOURCE_DIR'. The wheelhouse in the bundle might be empty."
fi

info "Looking for the datamover wheel file in '$DATAMOVER_WHEEL_DIR'..."
if [[ ! -d "$DATAMOVER_WHEEL_DIR" ]]; then error_exit "Datamover wheel directory '$DATAMOVER_WHEEL_DIR' not found."; fi
datamover_wheel_file=$(find "$DATAMOVER_WHEEL_DIR" -maxdepth 1 -name "datamover*${RELEASE_VERSION}*.whl" -print -quit 2>/dev/null)
if [[ -z "$datamover_wheel_file" || ! -f "$datamover_wheel_file" ]]; then
  warn "Could not find datamover wheel strictly matching version '$RELEASE_VERSION' in '$DATAMOVER_WHEEL_DIR'."
  info "Falling back to find any datamover wheel file in '$DATAMOVER_WHEEL_DIR'..."
  datamover_wheel_file=$(find "$DATAMOVER_WHEEL_DIR" -maxdepth 1 -name "datamover*.whl" -print -quit 2>/dev/null)
fi
if [[ -z "$datamover_wheel_file" || ! -f "$datamover_wheel_file" ]]; then error_exit "Datamover .whl file not found in '$DATAMOVER_WHEEL_DIR'."; fi
DATAMOVER_WHEEL_FILENAME=$(basename "$datamover_wheel_file")
info "Found datamover wheel: $DATAMOVER_WHEEL_FILENAME"
if [[ "$DATAMOVER_WHEEL_FILENAME" != *"$RELEASE_VERSION"* ]]; then warn "Potential Version Mismatch: Datamover wheel filename '$DATAMOVER_WHEEL_FILENAME' does not explicitly contain '$RELEASE_VERSION'."; fi

# --- Prepare Staging Area ---
info "Starting bundle creation for ${BUNDLE_TOP_DIR}"
STAGING_BUNDLE_ROOT="${STAGING_DIR}/${BUNDLE_TOP_DIR}"
STAGED_DEPLOY_SUBDIR="${STAGING_BUNDLE_ROOT}/exportcliv2-deploy"
STAGED_WHEELHOUSE_DIR="${STAGED_DEPLOY_SUBDIR}/${WHEELHOUSE_TARGET_SUBDIR_NAME}"

info "Preparing staging directory: ${STAGING_BUNDLE_ROOT}"
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_BUNDLE_ROOT"
mkdir -p "$STAGED_DEPLOY_SUBDIR"
mkdir -p "$STAGED_WHEELHOUSE_DIR"

# --- Copy Files to Staging ---
info "Copying '${DEPLOY_ORCHESTRATOR_SOURCE_NAME}' to bundle root..."
cp "$DEPLOY_ORCHESTRATOR_SOURCE" "${STAGING_BUNDLE_ROOT}/${DEPLOY_ORCHESTRATOR_SOURCE_NAME}"

info "Copying '${PATCH_SCRIPT_NAME}' to bundle root..."
cp "$PATCH_SCRIPT_SOURCE" "${STAGING_BUNDLE_ROOT}/${PATCH_SCRIPT_NAME}"

info "Copying guides to bundle root..."
cp "${INSTALLER_DEV_DIR}/QUICK_START_GUIDE.md" "${STAGING_BUNDLE_ROOT}/"
cp "${INSTALLER_DEV_DIR}/USER_GUIDE.md" "${STAGING_BUNDLE_ROOT}/"

info "Copying remaining 'exportcliv2-deploy' contents to '${STAGED_DEPLOY_SUBDIR}'..."
rsync -av \
  --exclude="${DEPLOY_ORCHESTRATOR_SOURCE_NAME}" \
  --exclude="*~" \
  --exclude="*.bak" \
  --exclude="*-org.sh" \
  --exclude="*.swp" \
  "${INSTALLER_DEV_DIR}/exportcliv2-deploy/" "$STAGED_DEPLOY_SUBDIR/"

info "Copying datamover wheel '$DATAMOVER_WHEEL_FILENAME' to '${STAGED_DEPLOY_SUBDIR}'"
cp "$datamover_wheel_file" "${STAGED_DEPLOY_SUBDIR}/${DATAMOVER_WHEEL_FILENAME}"

if [[ -n "$PRODUCTION_BINARY_PATH" ]]; then
  info "Copying production binary '$PRODUCTION_BINARY_FILENAME' to '${STAGED_DEPLOY_SUBDIR}'"
  cp "$PRODUCTION_BINARY_PATH" "${STAGED_DEPLOY_SUBDIR}/${PRODUCTION_BINARY_FILENAME}"
fi
if [[ -n "$EMULATOR_BINARY_PATH" ]]; then
  info "Copying emulator binary '$EMULATOR_BINARY_FILENAME' to '${STAGED_DEPLOY_SUBDIR}'"
  cp "$EMULATOR_BINARY_PATH" "${STAGED_DEPLOY_SUBDIR}/${EMULATOR_BINARY_FILENAME}"
fi

info "Copying dependency wheels from '${OFFLINE_WHEELS_SOURCE_DIR}' to staged wheelhouse '${STAGED_WHEELHOUSE_DIR}'..."
if ls "${OFFLINE_WHEELS_SOURCE_DIR}"/*.whl &> /dev/null; then
    cp "${OFFLINE_WHEELS_SOURCE_DIR}"/*.whl "${STAGED_WHEELHOUSE_DIR}/"
    info "Dependency wheels copied."
else
    warn "No .whl files found in '${OFFLINE_WHEELS_SOURCE_DIR}' to copy to wheelhouse. Wheelhouse might be empty."
fi

# --- Update install-app.conf in Staging Area ---
STAGED_INSTALL_APP_CONF="${STAGED_DEPLOY_SUBDIR}/install-app.conf"
info "Updating staged configuration: $STAGED_INSTALL_APP_CONF"
if [[ ! -f "$STAGED_INSTALL_APP_CONF" ]]; then error_exit "Staged install-app.conf not found: $STAGED_INSTALL_APP_CONF."; fi

update_or_append_config() {
    local key="$1"
    local value="$2"
    local config_file="$3"
    local temp_file="${config_file}.tmpvalupdate" # Unique temp file for this function call

    cp "$config_file" "$temp_file"
    if grep -q "^\s*${key}\s*=" "$temp_file"; then
        sed -E "s#^(\s*${key}\s*=\s*).*#\1${value}#" "$temp_file" > "$config_file"
        debug_bundle "Updated '$key' in $config_file."
    else
        info "Appending '$key=${value}' to $config_file."
        # Ensure newline if appending to a file that might not end with one
        if [[ $(tail -c1 "$config_file" | wc -l) -eq 0 && -s "$config_file" ]]; then echo >> "$config_file"; fi
        echo "${key}=${value}" >> "$config_file"
    fi
    rm "$temp_file"
}

CONFIGURED_APP_BINARY_REPLACEMENT_VALUE="\"$CONFIGURED_APP_BINARY_FILENAME\""
DATAMOVER_WHEEL_REPLACEMENT_VALUE="\"$DATAMOVER_WHEEL_FILENAME\""
WHEELHOUSE_SUBDIR_REPLACEMENT_VALUE="\"${WHEELHOUSE_TARGET_SUBDIR_NAME}\""

update_or_append_config "VERSIONED_APP_BINARY_FILENAME" "$CONFIGURED_APP_BINARY_REPLACEMENT_VALUE" "$STAGED_INSTALL_APP_CONF"
update_or_append_config "VERSIONED_DATAMOVER_WHEEL_FILENAME" "$DATAMOVER_WHEEL_REPLACEMENT_VALUE" "$STAGED_INSTALL_APP_CONF"
update_or_append_config "WHEELHOUSE_SUBDIR" "$WHEELHOUSE_SUBDIR_REPLACEMENT_VALUE" "$STAGED_INSTALL_APP_CONF"

info "Staged install-app.conf processed."

# --- Set Script Permissions ---
info "Setting executable permissions for .sh files in the bundle..."
find "${STAGING_BUNDLE_ROOT}" -maxdepth 1 -type f -name "*.sh" -print0 | while IFS= read -r -d $'\0' script_file; do
  debug_bundle "Making executable (bundle root): $script_file"
  chmod +x "$script_file"
done
find "${STAGED_DEPLOY_SUBDIR}" -type f -name "*.sh" -print0 | while IFS= read -r -d $'\0' script_file; do
  debug_bundle "Making executable (deploy subdir): $script_file"
  chmod +x "$script_file"
done

if [[ -n "$PRODUCTION_BINARY_FILENAME" ]]; then
    chmod +x "${STAGED_DEPLOY_SUBDIR}/${PRODUCTION_BINARY_FILENAME}"
    debug_bundle "Made executable: ${STAGED_DEPLOY_SUBDIR}/${PRODUCTION_BINARY_FILENAME}"
fi
if [[ -n "$EMULATOR_BINARY_FILENAME" ]]; then
    chmod +x "${STAGED_DEPLOY_SUBDIR}/${EMULATOR_BINARY_FILENAME}"
    debug_bundle "Made executable: ${STAGED_DEPLOY_SUBDIR}/${EMULATOR_BINARY_FILENAME}"
fi
info "Executable permissions set."

# --- Comprehensive File Check in Staging Area ---
info "Verifying contents of the staged bundle at '${STAGING_BUNDLE_ROOT}'..."
all_files_ok=true
declare -A expected_bundle_contents=(
    ["${DEPLOY_ORCHESTRATOR_SOURCE_NAME}"]="file"
    ["${PATCH_SCRIPT_NAME}"]="file"
    ["QUICK_START_GUIDE.md"]="file"
    ["USER_GUIDE.md"]="file"
    ["exportcliv2-deploy/install_base_exportcliv2.sh"]="file"
    ["exportcliv2-deploy/configure_instance.sh"]="file"
    ["exportcliv2-deploy/manage_services.sh"]="file"
    ["exportcliv2-deploy/install-app.conf"]="file"
    ["exportcliv2-deploy/${DATAMOVER_WHEEL_FILENAME}"]="file"
    ["exportcliv2-deploy/config_files"]="dir"
    ["exportcliv2-deploy/config_files/common.auth.conf"]="file"
    ["exportcliv2-deploy/config_files/config.ini.template"]="file"
    ["exportcliv2-deploy/config_files/run_exportcliv2_instance.sh.template"]="file"
    ["exportcliv2-deploy/systemd_units"]="dir"
    ["exportcliv2-deploy/systemd_units/bitmover.service.template"]="file"
    ["exportcliv2-deploy/systemd_units/exportcliv2@.service.template"]="file"
    ["exportcliv2-deploy/systemd_units/exportcliv2-restart@.path.template"]="file"
    ["exportcliv2-deploy/systemd_units/exportcliv2-restart@.service.template"]="file"
    ["exportcliv2-deploy/${WHEELHOUSE_TARGET_SUBDIR_NAME}"]="dir"
)
if [[ -n "$PRODUCTION_BINARY_FILENAME" ]]; then
  expected_bundle_contents["exportcliv2-deploy/${PRODUCTION_BINARY_FILENAME}"]="file"
fi
if [[ -n "$EMULATOR_BINARY_FILENAME" ]]; then
  expected_bundle_contents["exportcliv2-deploy/${EMULATOR_BINARY_FILENAME}"]="file"
fi

for item_path in "${!expected_bundle_contents[@]}"; do
    item_type="${expected_bundle_contents[$item_path]}"
    full_path="${STAGING_BUNDLE_ROOT}/${item_path}"
    check_passed=true
    if [[ "$item_type" == "file" && ! -f "$full_path" ]]; then check_passed=false
    elif [[ "$item_type" == "dir" && ! -d "$full_path" ]]; then check_passed=false
    fi
    if [[ "$check_passed" == false ]]; then
        warn "Bundle Verification FAILED: Expected $item_type missing at '$item_path' (full: '$full_path')"
        all_files_ok=false
    else
        debug_bundle "Bundle Verification OK: Found $item_type at '$item_path'"
    fi
done

if [[ "$all_files_ok" == true && -d "${STAGED_WHEELHOUSE_DIR}" ]]; then
    if ls "${OFFLINE_WHEELS_SOURCE_DIR}"/*.whl &> /dev/null; then
        if ! ls "${STAGED_WHEELHOUSE_DIR}"/*.whl &> /dev/null; then
            warn "Bundle Verification WARNING: Wheelhouse dir '${STAGED_WHEELHOUSE_DIR}' is empty, but source '${OFFLINE_WHEELS_SOURCE_DIR}' had wheels."
        else
            debug_bundle "Bundle Verification OK: Wheelhouse contains .whl files."
        fi
    fi
fi

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

exit 0