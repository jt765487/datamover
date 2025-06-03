#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# install_patch.sh
# Purpose: Updates the current bundle directory with a new binary or wheel,
#          and modifies its install-app.conf accordingly.
#          This prepares the bundle for a standard '--update' via deploy_orchestrator.sh.
VERSION="1.0.1" # Incremented version for the fix

# --- Configuration ---
readonly DEPLOY_SUBDIR_NAME="exportcliv2-deploy"
readonly BASE_CONFIG_FILENAME="install-app.conf" # Config file within DEPLOY_SUBDIR_NAME

# --- Logging Functions ---
SCRIPT_NAME=$(basename "$0")
info() { echo "[$SCRIPT_NAME INFO] $*"; }
warn() { echo >&2 "[$SCRIPT_NAME WARN] $*"; }
error_exit() { echo >&2 "[$SCRIPT_NAME ERROR] $*"; exit 1; }

# --- Usage ---
usage() {
  cat <<EOF
Usage: $SCRIPT_NAME --new-binary <PATH_TO_BINARY> | --new-wheel <PATH_TO_WHEEL>

This script updates the current application bundle (in the current directory)
with a new binary or wheel file. It copies the new component into the
'./${DEPLOY_SUBDIR_NAME}/' directory (if it's a different file) and updates
'./${DEPLOY_SUBDIR_NAME}/${BASE_CONFIG_FILENAME}' to reflect the change.

Run this script from the root of the bundle directory you wish to patch.

Options (one is required):
  --new-binary <PATH>   Absolute path to the new application binary file.
  --new-wheel <PATH>    Absolute path to the new datamover wheel file.
  -h, --help            Show this help message and exit.
  --version             Show script version and exit.

Example:
  cd /path/to/your/exportcliv2-suite-vX.Y.Z/
  sudo ./$(basename "$0") --new-binary /root/new_exportcliv2_binary
  sudo ./$(basename "$0") --new-binary ./exportcliv2-deploy/existing_other_binary # (Needs absolute path)
EOF
  exit "${1:-1}"
}

# --- Argument Parsing ---
NEW_COMPONENT_PATH_ARG="" # Store the argument as given
COMPONENT_TYPE="" # "binary" or "wheel"

if [[ $# -eq 0 ]]; then
  usage
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --new-binary)
      if [[ -n "$NEW_COMPONENT_PATH_ARG" ]]; then error_exit "Only one component type (--new-binary or --new-wheel) can be specified."; fi
      if [[ -z "${2:-}" || "$2" == -* ]]; then error_exit "Option $1 requires a PATH argument."; fi
      if [[ "$2" != /* ]]; then error_exit "$1 path must be absolute: $2"; fi
      NEW_COMPONENT_PATH_ARG="$2"; COMPONENT_TYPE="binary"; shift 2 ;;
    --new-wheel)
      if [[ -n "$NEW_COMPONENT_PATH_ARG" ]]; then error_exit "Only one component type (--new-binary or --new-wheel) can be specified."; fi
      if [[ -z "${2:-}" || "$2" == -* ]]; then error_exit "Option $1 requires a PATH argument."; fi
      if [[ "$2" != /* ]]; then error_exit "$1 path must be absolute: $2"; fi
      NEW_COMPONENT_PATH_ARG="$2"; COMPONENT_TYPE="wheel"; shift 2 ;;
    -h|--help)
      usage 0 ;;
    --version)
      echo "$(basename "$0") v$VERSION"; exit 0 ;;
    *)
      error_exit "Unknown option: $1. Use --help for usage." ;;
  esac
done

if [[ -z "$NEW_COMPONENT_PATH_ARG" ]]; then
  error_exit "Either --new-binary or --new-wheel must be specified. Use --help for usage."
fi

# --- Sanity Checks ---
info "Starting patch preparation for the current bundle..."

# Check if running from a plausible bundle directory
BUNDLE_DEPLOY_DIR_RELATIVE="./${DEPLOY_SUBDIR_NAME}"
BUNDLE_CONFIG_FILE_RELATIVE="${BUNDLE_DEPLOY_DIR_RELATIVE}/${BASE_CONFIG_FILENAME}"

if [[ ! -d "$BUNDLE_DEPLOY_DIR_RELATIVE" ]]; then
  error_exit "Directory '${BUNDLE_DEPLOY_DIR_RELATIVE}/' not found. Please run this script from the root of the application bundle directory."
fi
if [[ ! -f "$BUNDLE_CONFIG_FILE_RELATIVE" ]]; then
  error_exit "Configuration file '${BUNDLE_CONFIG_FILE_RELATIVE}' not found. Please run this script from the root of the application bundle directory."
fi
info "Current bundle context verified: $(pwd)"

# Resolve the new component path to its absolute, canonical form ONCE.
RESOLVED_NEW_COMPONENT_PATH=$(realpath "$NEW_COMPONENT_PATH_ARG") || error_exit "Failed to resolve path for new component: $NEW_COMPONENT_PATH_ARG"

# Check new component file (using the resolved path)
if [[ ! -f "$RESOLVED_NEW_COMPONENT_PATH" ]]; then
  error_exit "New component file not found: $RESOLVED_NEW_COMPONENT_PATH (from argument $NEW_COMPONENT_PATH_ARG)"
fi
if [[ ! -r "$RESOLVED_NEW_COMPONENT_PATH" ]]; then
  error_exit "New component file is not readable: $RESOLVED_NEW_COMPONENT_PATH"
fi
info "Verified new component: $RESOLVED_NEW_COMPONENT_PATH (type: $COMPONENT_TYPE)"

# --- Perform Update ---
NEW_COMPONENT_FILENAME=$(basename "$RESOLVED_NEW_COMPONENT_PATH") # Filename from resolved path
TARGET_COMPONENT_PATH_IN_BUNDLE_RELATIVE="${BUNDLE_DEPLOY_DIR_RELATIVE}/${NEW_COMPONENT_FILENAME}"

# Resolve the target path to its absolute, canonical form for comparison
# Suppress error if it doesn't exist yet, realpath will return non-zero in that case.
RESOLVED_TARGET_COMPONENT_PATH_IN_BUNDLE_ABS=$(realpath "$TARGET_COMPONENT_PATH_IN_BUNDLE_RELATIVE" 2>/dev/null)

if [[ -n "$RESOLVED_TARGET_COMPONENT_PATH_IN_BUNDLE_ABS" && "$RESOLVED_NEW_COMPONENT_PATH" == "$RESOLVED_TARGET_COMPONENT_PATH_IN_BUNDLE_ABS" ]]; then
  info "New component '$NEW_COMPONENT_FILENAME' is already in the target location '${TARGET_COMPONENT_PATH_IN_BUNDLE_RELATIVE}'. Skipping copy."
  # Ensure permissions on the existing file
  chmod +r "$TARGET_COMPONENT_PATH_IN_BUNDLE_RELATIVE" || error_exit "Failed to ensure existing component '$TARGET_COMPONENT_PATH_IN_BUNDLE_RELATIVE' is readable."
  if [[ "$COMPONENT_TYPE" == "binary" ]]; then
    if [[ ! -x "$TARGET_COMPONENT_PATH_IN_BUNDLE_RELATIVE" ]]; then # Only chmod if not already executable
        chmod +x "$TARGET_COMPONENT_PATH_IN_BUNDLE_RELATIVE" || error_exit "Failed to ensure existing binary '$TARGET_COMPONENT_PATH_IN_BUNDLE_RELATIVE' is executable."
    fi
  fi
else
  info "Copying '$NEW_COMPONENT_FILENAME' to '${TARGET_COMPONENT_PATH_IN_BUNDLE_RELATIVE}'..."
  cp "$RESOLVED_NEW_COMPONENT_PATH" "$TARGET_COMPONENT_PATH_IN_BUNDLE_RELATIVE" || error_exit "Failed to copy component into bundle."
  chmod +r "$TARGET_COMPONENT_PATH_IN_BUNDLE_RELATIVE" || error_exit "Failed to make copied component '$TARGET_COMPONENT_PATH_IN_BUNDLE_RELATIVE' readable."
  if [[ "$COMPONENT_TYPE" == "binary" ]]; then
    chmod +x "$TARGET_COMPONENT_PATH_IN_BUNDLE_RELATIVE" || error_exit "Failed to make copied binary '$TARGET_COMPONENT_PATH_IN_BUNDLE_RELATIVE' executable."
  fi
fi

info "Updating configuration file: ${BUNDLE_CONFIG_FILE_RELATIVE}"
CONFIG_KEY_TO_UPDATE=""
if [[ "$COMPONENT_TYPE" == "binary" ]]; then
  CONFIG_KEY_TO_UPDATE="VERSIONED_APP_BINARY_FILENAME"
elif [[ "$COMPONENT_TYPE" == "wheel" ]]; then
  CONFIG_KEY_TO_UPDATE="VERSIONED_DATAMOVER_WHEEL_FILENAME"
else
  error_exit "Internal error: Unknown component type '$COMPONENT_TYPE'." # Should not happen
fi

# Check if key exists before attempting to update
if ! grep -q "^\s*${CONFIG_KEY_TO_UPDATE}\s*=" "$BUNDLE_CONFIG_FILE_RELATIVE"; then
    warn "Configuration key '${CONFIG_KEY_TO_UPDATE}' not found in '${BUNDLE_CONFIG_FILE_RELATIVE}'. Appending it."
    # Ensure there's a newline at the end of the file if we are appending
    if [[ $(tail -c1 "$BUNDLE_CONFIG_FILE_RELATIVE" | wc -l) -eq 0 && -s "$BUNDLE_CONFIG_FILE_RELATIVE" ]]; then echo >> "$BUNDLE_CONFIG_FILE_RELATIVE"; fi
    echo "${CONFIG_KEY_TO_UPDATE}=\"${NEW_COMPONENT_FILENAME}\"" >> "$BUNDLE_CONFIG_FILE_RELATIVE"
else
    # Using '#' as sed delimiter to avoid issues with filenames containing '/'
    sed -i -E "s#^(\s*${CONFIG_KEY_TO_UPDATE}\s*=\s*).*#\1\"${NEW_COMPONENT_FILENAME}\"#" "$BUNDLE_CONFIG_FILE_RELATIVE" || error_exit "Failed to update '${CONFIG_KEY_TO_UPDATE}' in '${BUNDLE_CONFIG_FILE_RELATIVE}'."
fi

info "Successfully updated '${CONFIG_KEY_TO_UPDATE}' to '${NEW_COMPONENT_FILENAME}'."

# --- Completion Message ---
info "--------------------------------------------------------------------"
info "Bundle patch preparation complete!"
info "The current bundle directory ($(pwd)) has been updated with:"
info "  - Component: ${TARGET_COMPONENT_PATH_IN_BUNDLE_RELATIVE} (filename: ${NEW_COMPONENT_FILENAME})"
info "  - Configuration updated: ${BUNDLE_CONFIG_FILE_RELATIVE}"
info ""
info "To deploy this patched version to the system, run the orchestrator"
info "from this directory:"
info "  sudo ./deploy_orchestrator.sh --update"
info "--------------------------------------------------------------------"

exit 0