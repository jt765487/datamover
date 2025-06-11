#!/bin/bash
set -euo pipefail
IFS=$'\n\t' # For safe looping over find results, though find -print0 is preferred.

# Script V1.1 to create a distributable bundle for the exportcliv2 suite.
# V1.1: Removed Python dependency for pyproject.toml version parsing.

# --- Default Configuration (relative to script's location if not overridden) ---
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT_DIR="$SCRIPT_DIR" # Assuming script is in project root

INSTALLER_SOURCE_DIR="${PROJECT_ROOT_DIR}/installer" # Source dir for installer scripts & USER_GUIDE.md
README_SOURCE_FILE="${PROJECT_ROOT_DIR}/README.md"   # Source for README.md at project root
DATAMOVER_WHEEL_SOURCE_DIR="${PROJECT_ROOT_DIR}/dist" # Source dir for the datamover .whl file
OFFLINE_WHEELS_SOURCE_DIR_DEFAULT="${PROJECT_ROOT_DIR}/offline_package/wheels"
PYPROJECT_TOML_PATH="${PROJECT_ROOT_DIR}/pyproject.toml"
STAGING_DIR_NAME="_release_staging" # Name of the top-level staging directory
PATCH_SCRIPT_NAME="install_patch.sh" # Name of the patch script within the installer source
UNINSTALL_SCRIPT_NAME="uninstall.sh" # Name of the uninstall script

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
                                 If not set, attempts to read from '$PYPROJECT_TOML_PATH' using grep/sed.
  -k, --keep-staging             Optional: Do not delete the staging directory after bundling.
  --offline-wheels-dir DIR       Optional: Override the directory for offline Python dependency wheels.
                                 Default: '${OFFLINE_WHEELS_SOURCE_DIR_DEFAULT}'
  --installer-src-dir DIR        Optional: Override the directory for installer scripts & USER_GUIDE.md.
                                 Default: '${INSTALLER_SOURCE_DIR}'
  --datamover-wheel-src-dir DIR  Optional: Override the directory containing the datamover .whl file.
                                 Default: '${DATAMOVER_WHEEL_SOURCE_DIR}'
  --readme-src <PATH>            Optional: Override the path to the README.md file.
                                 Default: '${README_SOURCE_FILE}'
  --verbose-bundler              Optional: Enable verbose debug output from this bundling script.
  -h, --help                     Show this help message and exit.

Requirements:
  - '--production-binary' must be specified.
  - Paths provided for binaries must exist and be executable.
  - The datamover .whl file must exist in the specified datamover wheel source directory.
  - Dependency wheels should exist in the offline wheels source directory.
  - '$PYPROJECT_TOML_PATH' should exist if --release-version is not specified.
  - Key installer scripts must exist (e.g., in '${INSTALLER_SOURCE_DIR}/exportcliv2-deploy/').
  - The '${PATCH_SCRIPT_NAME}' must exist (e.g., in '${INSTALLER_SOURCE_DIR}/').
  - The '${UNINSTALL_SCRIPT_NAME}' must exist (e.g., in '${INSTALLER_SOURCE_DIR}/exportcliv2-deploy/').
  - The README.md file must exist at its specified source path.
EOF
}

# --- Initialize Variables ---
PRODUCTION_BINARY_PATH=""
EMULATOR_BINARY_PATH=""
RELEASE_VERSION=""
KEEP_STAGING=false
# Initialize with defaults, will be updated by options if provided
EFFECTIVE_OFFLINE_WHEELS_SOURCE_DIR="$OFFLINE_WHEELS_SOURCE_DIR_DEFAULT"
EFFECTIVE_INSTALLER_SOURCE_DIR="$INSTALLER_SOURCE_DIR"
EFFECTIVE_DATAMOVER_WHEEL_SOURCE_DIR="$DATAMOVER_WHEEL_SOURCE_DIR"
EFFECTIVE_README_SOURCE_FILE="$README_SOURCE_FILE"


# --- Argument Parsing ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --production-binary)
      if [[ -z "${2:-}" ]]; then error_exit "Option $1 requires a PATH argument."; fi
      PRODUCTION_BINARY_PATH=$(realpath "$2"); shift 2 ;; # Resolve to absolute path
    --emulator-binary)
      if [[ -z "${2:-}" ]]; then error_exit "Option $1 requires a PATH argument."; fi
      EMULATOR_BINARY_PATH=$(realpath "$2"); shift 2 ;; # Resolve to absolute path
    -r|--release-version)
      if [[ -z "${2:-}" ]]; then error_exit "Option $1 requires a VERSION argument."; fi
      RELEASE_VERSION="$2"; shift 2 ;;
    -k|--keep-staging)
      KEEP_STAGING=true; shift ;;
    --offline-wheels-dir)
      if [[ -z "${2:-}" ]]; then error_exit "Option $1 requires a DIRECTORY argument."; fi
      EFFECTIVE_OFFLINE_WHEELS_SOURCE_DIR=$(realpath "$2"); shift 2 ;;
    --installer-src-dir)
      if [[ -z "${2:-}" ]]; then error_exit "Option $1 requires a DIRECTORY argument."; fi
      EFFECTIVE_INSTALLER_SOURCE_DIR=$(realpath "$2"); shift 2 ;;
    --datamover-wheel-src-dir)
      if [[ -z "${2:-}" ]]; then error_exit "Option $1 requires a DIRECTORY argument."; fi
      EFFECTIVE_DATAMOVER_WHEEL_SOURCE_DIR=$(realpath "$2"); shift 2 ;;
    --readme-src)
      if [[ -z "${2:-}" ]]; then error_exit "Option $1 requires a PATH argument."; fi
      EFFECTIVE_README_SOURCE_FILE=$(realpath "$2"); shift 2 ;;
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
  info "Attempting to determine release version from '$PYPROJECT_TOML_PATH' using grep/awk/sed..."
  if [[ ! -f "$PYPROJECT_TOML_PATH" ]]; then
    error_exit "Cannot determine version: '$PYPROJECT_TOML_PATH' not found and --release-version not specified."
  fi

  PYPROJECT_VERSION=""
  # Try to extract version from [project] table (PEP 621)
  # awk: find line starting with [project]. Set flag p=1. On next lines, if p=1 and line matches version pattern, extract and print version, then exit awk.
  # If another section like [foo] starts, reset flag p=0.
  PYPROJECT_VERSION=$(awk '/^\[project\]/{p=1;next} /^\[tool\.poetry\]/{p=0;next} /^\[/{p=0} p && /^\s*version\s*=\s*"/ {gsub(/^.*version\s*=\s*"|"$/,""); print; exit}' "$PYPROJECT_TOML_PATH")

  # If not found, try under [tool.poetry] (for Poetry projects)
  if [[ -z "$PYPROJECT_VERSION" ]]; then
    debug_bundle "Version not found under [project] in '$PYPROJECT_TOML_PATH'. Trying [tool.poetry]..."
    PYPROJECT_VERSION=$(awk '/^\[tool\.poetry\]/{p=1;next} /^\[project\]/{p=0;next} /^\[/{p=0} p && /^\s*version\s*=\s*"/ {gsub(/^.*version\s*=\s*"|"$/,""); print; exit}' "$PYPROJECT_TOML_PATH")
  fi

  # If still not found, try a more general grep/sed as a last resort
  # This is less specific and might pick up other "version" lines if they exist.
  if [[ -z "$PYPROJECT_VERSION" ]]; then
    debug_bundle "Version not found under [tool.poetry] in '$PYPROJECT_TOML_PATH'. Trying general grep..."
    # The subshell with `|| echo ""` ensures that if grep finds nothing, PYPROJECT_VERSION becomes empty
    # instead of the script exiting due to `set -e` and `pipefail`.
    PYPROJECT_VERSION=$( (grep -E "^\s*version\s*=\s*\"[^\"]+\"" "$PYPROJECT_TOML_PATH" | \
                         sed -E 's/^\s*version\s*=\s*"([^"]+)"\s*$/\1/' | \
                         head -n 1) || echo "" )
  fi

  if [[ -z "$PYPROJECT_VERSION" ]]; then
    error_exit "Could not automatically determine version from '$PYPROJECT_TOML_PATH' using grep/awk/sed. Use --release-version or ensure 'version = \"x.y.z\"' is present in a recognized location (e.g., under [project] or [tool.poetry])."
  fi
  RELEASE_VERSION="$PYPROJECT_VERSION"
  info "Using release version from pyproject.toml (via grep/awk/sed): $RELEASE_VERSION"
else
  info "Using release version from command line: $RELEASE_VERSION"
fi

# --- Derived Configuration ---
BUNDLE_TOP_DIR_NAME="exportcliv2-suite-v${RELEASE_VERSION}"
ARCHIVE_NAME="${BUNDLE_TOP_DIR_NAME}.tar.gz"
WHEELHOUSE_TARGET_SUBDIR_NAME="wheelhouse" # Name of the wheelhouse dir inside exportcliv2-deploy
DEPLOY_SUBDIR_NAME="exportcliv2-deploy"    # Name of the main deployment scripts subdirectory

# --- Setup Trap for Cleanup ---
# shellcheck disable=SC2317
cleanup_staging() {
  if [[ "$KEEP_STAGING" == false && -d "${PROJECT_ROOT_DIR}/${STAGING_DIR_NAME}" ]]; then
    debug_bundle "Cleaning up staging directory: ${PROJECT_ROOT_DIR}/${STAGING_DIR_NAME}"
    rm -rf "${PROJECT_ROOT_DIR}/${STAGING_DIR_NAME}"
  elif [[ -d "${PROJECT_ROOT_DIR}/${STAGING_DIR_NAME}" ]]; then
    info "Staging directory kept at: ${PROJECT_ROOT_DIR}/${STAGING_DIR_NAME}"
  fi
}
trap cleanup_staging EXIT INT TERM

# --- Sanity Checks for Paths and Files ---
info "Performing sanity checks for inputs..."
PRODUCTION_BINARY_FILENAME=""
EMULATOR_BINARY_FILENAME=""
CONFIGURED_APP_BINARY_FILENAME="" # This will be the one set in install-app.conf

# Production Binary (Mandatory)
if [[ ! -f "$PRODUCTION_BINARY_PATH" ]]; then error_exit "Production binary not found at: $PRODUCTION_BINARY_PATH"; fi
if [[ ! -x "$PRODUCTION_BINARY_PATH" ]]; then
  warn "Production binary at '$PRODUCTION_BINARY_PATH' is not executable. Attempting to make it executable."
  chmod +x "$PRODUCTION_BINARY_PATH" || error_exit "Failed to make production binary executable."
fi
PRODUCTION_BINARY_FILENAME=$(basename "$PRODUCTION_BINARY_PATH")
CONFIGURED_APP_BINARY_FILENAME="$PRODUCTION_BINARY_FILENAME" # Default active binary is production
info "Production binary (will be active): '$PRODUCTION_BINARY_FILENAME' (from $PRODUCTION_BINARY_PATH)"
if [[ "$PRODUCTION_BINARY_FILENAME" != *"$RELEASE_VERSION"* && "$PRODUCTION_BINARY_FILENAME" != *"${RELEASE_VERSION//./-}"* ]]; then
    warn "Potential Version Mismatch: Production binary filename '$PRODUCTION_BINARY_FILENAME' does not appear to contain the release version '$RELEASE_VERSION'."
fi

# Emulator Binary (Optional)
if [[ -n "$EMULATOR_BINARY_PATH" ]]; then
  if [[ ! -f "$EMULATOR_BINARY_PATH" ]]; then error_exit "Emulator binary not found at: $EMULATOR_BINARY_PATH"; fi
  if [[ ! -x "$EMULATOR_BINARY_PATH" ]]; then
    warn "Emulator binary at '$EMULATOR_BINARY_PATH' is not executable. Attempting to make it executable."
    chmod +x "$EMULATOR_BINARY_PATH" || error_exit "Failed to make emulator binary executable."
  fi
  EMULATOR_BINARY_FILENAME=$(basename "$EMULATOR_BINARY_PATH")
  info "Emulator binary (for inclusion): '$EMULATOR_BINARY_FILENAME' (from $EMULATOR_BINARY_PATH)"
fi

# Installer Scripts and Guides Source
if [[ ! -d "$EFFECTIVE_INSTALLER_SOURCE_DIR" ]]; then error_exit "Installer source directory not found: $EFFECTIVE_INSTALLER_SOURCE_DIR"; fi
if [[ ! -d "${EFFECTIVE_INSTALLER_SOURCE_DIR}/${DEPLOY_SUBDIR_NAME}" ]]; then error_exit "Subdirectory '${DEPLOY_SUBDIR_NAME}' not found in installer source: ${EFFECTIVE_INSTALLER_SOURCE_DIR}/${DEPLOY_SUBDIR_NAME}"; fi
DEPLOY_ORCHESTRATOR_SOURCE_NAME="deploy_orchestrator.sh" # Assumed to be in DEPLOY_SUBDIR_NAME
DEPLOY_ORCHESTRATOR_SOURCE="${EFFECTIVE_INSTALLER_SOURCE_DIR}/${DEPLOY_SUBDIR_NAME}/${DEPLOY_ORCHESTRATOR_SOURCE_NAME}"
if [[ ! -f "$DEPLOY_ORCHESTRATOR_SOURCE" ]]; then
  error_exit "Main deployment script '${DEPLOY_ORCHESTRATOR_SOURCE_NAME}' not found at: $DEPLOY_ORCHESTRATOR_SOURCE"
fi
PATCH_SCRIPT_SOURCE="${EFFECTIVE_INSTALLER_SOURCE_DIR}/${PATCH_SCRIPT_NAME}" # Assumed to be in INSTALLER_SOURCE_DIR root
if [[ ! -f "$PATCH_SCRIPT_SOURCE" ]]; then
  error_exit "Patch script '${PATCH_SCRIPT_NAME}' not found at: $PATCH_SCRIPT_SOURCE"
fi
UNINSTALL_SCRIPT_SOURCE_PATH="${EFFECTIVE_INSTALLER_SOURCE_DIR}/${DEPLOY_SUBDIR_NAME}/${UNINSTALL_SCRIPT_NAME}"
if [[ ! -f "$UNINSTALL_SCRIPT_SOURCE_PATH" ]]; then
  error_exit "Uninstall script '${UNINSTALL_SCRIPT_NAME}' not found at its source: $UNINSTALL_SCRIPT_SOURCE_PATH"
fi
if [[ ! -f "$EFFECTIVE_README_SOURCE_FILE" ]]; then error_exit "README.md not found at: $EFFECTIVE_README_SOURCE_FILE"; fi
if [[ -f "${EFFECTIVE_INSTALLER_SOURCE_DIR}/USER_GUIDE.md" ]]; then
  info "USER_GUIDE.md found in installer source directory."
else
  warn "USER_GUIDE.md not found in '${EFFECTIVE_INSTALLER_SOURCE_DIR}'. Bundle will not include it."
fi


# Wheels Sources
if [[ ! -d "$EFFECTIVE_OFFLINE_WHEELS_SOURCE_DIR" ]]; then error_exit "Offline wheels source directory not found at: '$EFFECTIVE_OFFLINE_WHEELS_SOURCE_DIR'"; fi
if ! ls "${EFFECTIVE_OFFLINE_WHEELS_SOURCE_DIR}"/*.whl &> /dev/null; then
    warn "No .whl files found in offline wheels source directory: '$EFFECTIVE_OFFLINE_WHEELS_SOURCE_DIR'. The wheelhouse in the bundle will be empty."
fi
info "Looking for the datamover wheel file in '$EFFECTIVE_DATAMOVER_WHEEL_SOURCE_DIR'..."
if [[ ! -d "$EFFECTIVE_DATAMOVER_WHEEL_SOURCE_DIR" ]]; then error_exit "Datamover wheel directory '$EFFECTIVE_DATAMOVER_WHEEL_SOURCE_DIR' not found."; fi

# Use find with head for better portability than -quit
datamover_wheel_file=$(find "$EFFECTIVE_DATAMOVER_WHEEL_SOURCE_DIR" -maxdepth 1 -type f -name "datamover*${RELEASE_VERSION}*.whl" -print | head -n 1)
if [[ -z "$datamover_wheel_file" || ! -f "$datamover_wheel_file" ]]; then
  warn "Could not find datamover wheel strictly matching version '$RELEASE_VERSION' in '$EFFECTIVE_DATAMOVER_WHEEL_SOURCE_DIR'."
  info "Falling back to find any datamover*.whl file in '$EFFECTIVE_DATAMOVER_WHEEL_SOURCE_DIR'..."
  datamover_wheel_file=$(find "$EFFECTIVE_DATAMOVER_WHEEL_SOURCE_DIR" -maxdepth 1 -type f -name "datamover*.whl" -print | head -n 1)
fi
if [[ -z "$datamover_wheel_file" || ! -f "$datamover_wheel_file" ]]; then error_exit "Datamover .whl file not found in '$EFFECTIVE_DATAMOVER_WHEEL_SOURCE_DIR'."; fi
DATAMOVER_WHEEL_FILENAME=$(basename "$datamover_wheel_file")
info "Found datamover wheel: $DATAMOVER_WHEEL_FILENAME"
if [[ "$DATAMOVER_WHEEL_FILENAME" != *"$RELEASE_VERSION"* && "$DATAMOVER_WHEEL_FILENAME" != *"${RELEASE_VERSION//./-}"* ]]; then
    warn "Potential Version Mismatch: Datamover wheel filename '$DATAMOVER_WHEEL_FILENAME' does not explicitly contain release version '$RELEASE_VERSION'."
fi

# --- Prepare Staging Area ---
STAGING_TOP_LEVEL_DIR="${PROJECT_ROOT_DIR}/${STAGING_DIR_NAME}"
STAGING_BUNDLE_ROOT="${STAGING_TOP_LEVEL_DIR}/${BUNDLE_TOP_DIR_NAME}"
STAGED_DEPLOY_SUBDIR="${STAGING_BUNDLE_ROOT}/${DEPLOY_SUBDIR_NAME}"
STAGED_WHEELHOUSE_DIR="${STAGED_DEPLOY_SUBDIR}/${WHEELHOUSE_TARGET_SUBDIR_NAME}"

info "Preparing staging directory: ${STAGING_BUNDLE_ROOT}"
rm -rf "$STAGING_TOP_LEVEL_DIR" # Clean entire top-level staging dir
mkdir -p "$STAGING_BUNDLE_ROOT"
mkdir -p "$STAGED_DEPLOY_SUBDIR"
mkdir -p "$STAGED_WHEELHOUSE_DIR"

# --- Copy Files to Staging ---
info "Copying '${DEPLOY_ORCHESTRATOR_SOURCE_NAME}' to bundle root '${STAGING_BUNDLE_ROOT}'..."
cp "$DEPLOY_ORCHESTRATOR_SOURCE" "${STAGING_BUNDLE_ROOT}/${DEPLOY_ORCHESTRATOR_SOURCE_NAME}"

info "Copying '${PATCH_SCRIPT_NAME}' to bundle root '${STAGING_BUNDLE_ROOT}'..."
cp "$PATCH_SCRIPT_SOURCE" "${STAGING_BUNDLE_ROOT}/${PATCH_SCRIPT_NAME}"

info "Copying '${UNINSTALL_SCRIPT_NAME}' from '${UNINSTALL_SCRIPT_SOURCE_PATH}' to bundle root '${STAGING_BUNDLE_ROOT}'..."
cp "$UNINSTALL_SCRIPT_SOURCE_PATH" "${STAGING_BUNDLE_ROOT}/${UNINSTALL_SCRIPT_NAME}"

info "Copying README.md to bundle root '${STAGING_BUNDLE_ROOT}'..."
cp "$EFFECTIVE_README_SOURCE_FILE" "${STAGING_BUNDLE_ROOT}/README.md"

if [[ -f "${EFFECTIVE_INSTALLER_SOURCE_DIR}/USER_GUIDE.md" ]]; then
    info "Copying USER_GUIDE.md to bundle root '${STAGING_BUNDLE_ROOT}'..."
    cp "${EFFECTIVE_INSTALLER_SOURCE_DIR}/USER_GUIDE.md" "${STAGING_BUNDLE_ROOT}/USER_GUIDE.md"
fi

info "Copying remaining '${DEPLOY_SUBDIR_NAME}' contents from '${EFFECTIVE_INSTALLER_SOURCE_DIR}/${DEPLOY_SUBDIR_NAME}/' to '${STAGED_DEPLOY_SUBDIR}'..."
rsync -av --checksum \
  --exclude="${DEPLOY_ORCHESTRATOR_SOURCE_NAME}" \
  --exclude="${UNINSTALL_SCRIPT_NAME}" \
  --exclude="*~" \
  --exclude="*.bak" \
  --exclude="*-org.sh" \
  --exclude="*.swp" \
  --exclude="test_plan.md" \
  "${EFFECTIVE_INSTALLER_SOURCE_DIR}/${DEPLOY_SUBDIR_NAME}/" "$STAGED_DEPLOY_SUBDIR/" # Note trailing slashes

info "Copying datamover wheel '$DATAMOVER_WHEEL_FILENAME' to '${STAGED_DEPLOY_SUBDIR}'"
cp "$datamover_wheel_file" "${STAGED_DEPLOY_SUBDIR}/${DATAMOVER_WHEEL_FILENAME}"

info "Copying production binary '$PRODUCTION_BINARY_FILENAME' to '${STAGED_DEPLOY_SUBDIR}'"
cp "$PRODUCTION_BINARY_PATH" "${STAGED_DEPLOY_SUBDIR}/${PRODUCTION_BINARY_FILENAME}"

if [[ -n "$EMULATOR_BINARY_FILENAME" ]]; then
  info "Copying emulator binary '$EMULATOR_BINARY_FILENAME' to '${STAGED_DEPLOY_SUBDIR}'"
  cp "$EMULATOR_BINARY_PATH" "${STAGED_DEPLOY_SUBDIR}/${EMULATOR_BINARY_FILENAME}"
fi

info "Copying dependency wheels from '${EFFECTIVE_OFFLINE_WHEELS_SOURCE_DIR}' to staged wheelhouse '${STAGED_WHEELHOUSE_DIR}'..."
if ls "${EFFECTIVE_OFFLINE_WHEELS_SOURCE_DIR}"/*.whl &> /dev/null; then
    cp "${EFFECTIVE_OFFLINE_WHEELS_SOURCE_DIR}"/*.whl "${STAGED_WHEELHOUSE_DIR}/"
    info "Dependency wheels copied."
else
    warn "No .whl files found in '${EFFECTIVE_OFFLINE_WHEELS_SOURCE_DIR}' to copy to wheelhouse. Wheelhouse might be empty."
fi

# --- Update install-app.conf in Staging Area ---
STAGED_INSTALL_APP_CONF="${STAGED_DEPLOY_SUBDIR}/install-app.conf"
info "Updating staged configuration: $STAGED_INSTALL_APP_CONF"
if [[ ! -f "$STAGED_INSTALL_APP_CONF" ]]; then error_exit "Staged install-app.conf not found: $STAGED_INSTALL_APP_CONF. Check rsync copy."; fi

update_or_append_config() {
    local key="$1"
    local value="$2"
    local config_file="$3"
    local temp_file_suffix="_update_config_temp"
    local temp_file
    temp_file=$(mktemp "${config_file}${temp_file_suffix}.XXXXXX")

    cp "$config_file" "$temp_file"
    if grep -q -E "^\s*${key}\s*=" "$temp_file"; then
        sed -E "s#^(\s*${key}\s*=\s*).*#\1${value}#" "$temp_file" > "$config_file"
        debug_bundle "Updated '$key' in $config_file."
    else
        info "Key '$key' not found, appending '$key=${value}' to $config_file."
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
info "Setting executable permissions for .sh files and binaries in the bundle..."
find "${STAGING_BUNDLE_ROOT}" -maxdepth 1 -type f -name "*.sh" -print0 | xargs -0 -I {} chmod +x {}
find "${STAGED_DEPLOY_SUBDIR}" -type f -name "*.sh" -print0 | xargs -0 -I {} chmod +x {}

chmod +x "${STAGED_DEPLOY_SUBDIR}/${PRODUCTION_BINARY_FILENAME}"
debug_bundle "Made executable: ${STAGED_DEPLOY_SUBDIR}/${PRODUCTION_BINARY_FILENAME}"
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
    ["${UNINSTALL_SCRIPT_NAME}"]="file" # uninstall.sh now in bundle root
    ["README.md"]="file"
    ["${DEPLOY_SUBDIR_NAME}/install_base_exportcliv2.sh"]="file"
    ["${DEPLOY_SUBDIR_NAME}/configure_instance.sh"]="file"
    ["${DEPLOY_SUBDIR_NAME}/manage_services.sh"]="file"
    # uninstall.sh is no longer expected in DEPLOY_SUBDIR_NAME
    ["${DEPLOY_SUBDIR_NAME}/install-app.conf"]="file"
    ["${DEPLOY_SUBDIR_NAME}/${DATAMOVER_WHEEL_FILENAME}"]="file"
    ["${DEPLOY_SUBDIR_NAME}/config_files"]="dir"
    ["${DEPLOY_SUBDIR_NAME}/config_files/common.auth.conf"]="file"
    ["${DEPLOY_SUBDIR_NAME}/config_files/config.ini.template"]="file"
    ["${DEPLOY_SUBDIR_NAME}/config_files/run_exportcliv2_instance.sh.template"]="file"
    ["${DEPLOY_SUBDIR_NAME}/systemd_units"]="dir"
    ["${DEPLOY_SUBDIR_NAME}/systemd_units/bitmover.service.template"]="file"
    ["${DEPLOY_SUBDIR_NAME}/systemd_units/exportcliv2@.service.template"]="file"
    ["${DEPLOY_SUBDIR_NAME}/systemd_units/exportcliv2-restart@.path.template"]="file"
    ["${DEPLOY_SUBDIR_NAME}/systemd_units/exportcliv2-restart@.service.template"]="file"
    ["${DEPLOY_SUBDIR_NAME}/${WHEELHOUSE_TARGET_SUBDIR_NAME}"]="dir"
)
if [[ -f "${EFFECTIVE_INSTALLER_SOURCE_DIR}/USER_GUIDE.md" ]]; then
  expected_bundle_contents["USER_GUIDE.md"]="file"
fi
expected_bundle_contents["${DEPLOY_SUBDIR_NAME}/${PRODUCTION_BINARY_FILENAME}"]="file"
if [[ -n "$EMULATOR_BINARY_FILENAME" ]]; then
  expected_bundle_contents["${DEPLOY_SUBDIR_NAME}/${EMULATOR_BINARY_FILENAME}"]="file"
fi

for item_path_rel_to_bundle_root in "${!expected_bundle_contents[@]}"; do
    item_type="${expected_bundle_contents[$item_path_rel_to_bundle_root]}"
    full_path_in_staging="${STAGING_BUNDLE_ROOT}/${item_path_rel_to_bundle_root}"
    check_passed=true
    if [[ "$item_type" == "file" && ! -f "$full_path_in_staging" ]]; then check_passed=false
    elif [[ "$item_type" == "dir" && ! -d "$full_path_in_staging" ]]; then check_passed=false
    fi

    if [[ "$check_passed" == false ]]; then
        warn "Bundle Verification FAILED: Expected $item_type missing at bundle path '$item_path_rel_to_bundle_root' (checked as '$full_path_in_staging')"
        all_files_ok=false
    else
        debug_bundle "Bundle Verification OK: Found $item_type at bundle path '$item_path_rel_to_bundle_root'"
    fi
done

if [[ "$all_files_ok" == true && -d "${STAGED_WHEELHOUSE_DIR}" ]]; then
    source_had_wheels=false
    if ls "${EFFECTIVE_OFFLINE_WHEELS_SOURCE_DIR}"/*.whl &> /dev/null; then
        source_had_wheels=true
    fi
    if [[ "$source_had_wheels" == true ]]; then
        if ! ls "${STAGED_WHEELHOUSE_DIR}"/*.whl &> /dev/null; then
            warn "Bundle Verification WARNING: Wheelhouse dir '${STAGED_WHEELHOUSE_DIR}' is empty, but source '${EFFECTIVE_OFFLINE_WHEELS_SOURCE_DIR}' had wheels."
        else
            debug_bundle "Bundle Verification OK: Wheelhouse contains .whl files as expected."
        fi
    fi
fi

if [[ "$all_files_ok" == false ]]; then
    error_exit "Bundle verification failed. Critical files/directories are missing in the staging area. Check warnings above."
else
    info "Bundle contents verified successfully in staging area."
fi

# --- Create Tarball ---
info "Creating tarball: ${ARCHIVE_NAME} in $(realpath "${PROJECT_ROOT_DIR}")"
(
  cd "$STAGING_TOP_LEVEL_DIR" || { error_exit "Failed to cd into staging dir '$STAGING_TOP_LEVEL_DIR' for tar creation."; }
  tar -czf "${PROJECT_ROOT_DIR}/${ARCHIVE_NAME}" "$BUNDLE_TOP_DIR_NAME"
) || error_exit "Failed to create tarball."

info "--- Bundle Created Successfully: ${PROJECT_ROOT_DIR}/${ARCHIVE_NAME} ---"
info "To inspect contents (permissions visible with -tvf): tar -tzvf \"${PROJECT_ROOT_DIR}/${ARCHIVE_NAME}\""

exit 0