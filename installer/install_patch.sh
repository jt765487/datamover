#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# install_patch.sh
# Purpose: Updates the current bundle directory with a new binary or wheel,
#          and modifies its install-app.conf accordingly.
#          This prepares the bundle for a standard '--update' via deploy_orchestrator.sh.
VERSION="1.0.0"

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
'./${DEPLOY_SUBDIR_NAME}/' directory and updates './${DEPLOY_SUBDIR_NAME}/${BASE_CONFIG_FILENAME}'
to reflect the change.

Run this script from the root of the bundle directory you wish to patch.

Options (one is required):
  --new-binary <PATH>   Absolute path to the new application binary file.
  --new-wheel <PATH>    Absolute path to the new datamover wheel file.
  -h, --help            Show this help message and exit.
  --version             Show script version and exit.

Example:
  cd /path/to/your/exportcliv2-suite-vX.Y.Z/
  sudo ./$(basename "$0") --new-binary /root/new_exportcliv2_binary
EOF
  exit "${1:-1}"
}

# --- Argument Parsing ---
NEW_COMPONENT_PATH=""
COMPONENT_TYPE="" # "binary" or "wheel"

if [[ $# -eq 0 ]]; then
  usage
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --new-binary)
      if [[ -n "$NEW_COMPONENT_PATH" ]]; then error_exit "Only one component type (--new-binary or --new-wheel) can be specified."; fi
      if [[ -z "${2:-}" || "$2" == -* ]]; then error_exit "Option $1 requires a PATH argument."; fi
      if [[ "$2" != /* ]]; then error_exit "$1 path must be absolute: $2"; fi
      NEW_COMPONENT_PATH="$2"; COMPONENT_TYPE="binary"; shift 2 ;;
    --new-wheel)
      if [[ -n "$NEW_COMPONENT_PATH" ]]; then error_exit "Only one component type (--new-binary or --new-wheel) can be specified."; fi
      if [[ -z "${2:-}" || "$2" == -* ]]; then error_exit "Option $1 requires a PATH argument."; fi
      if [[ "$2" != /* ]]; then error_exit "$1 path must be absolute: $2"; fi
      NEW_COMPONENT_PATH="$2"; COMPONENT_TYPE="wheel"; shift 2 ;;
    -h|--help)
      usage 0 ;;
    --version)
      echo "$(basename "$0") v$VERSION"; exit 0 ;;
    *)
      error_exit "Unknown option: $1. Use --help for usage." ;;
  esac
done

if [[ -z "$NEW_COMPONENT_PATH" ]]; then
  error_exit "Either --new-binary or --new-wheel must be specified. Use --help for usage."
fi

# --- Sanity Checks ---
info "Starting patch preparation for the current bundle..."

# Check if running from a plausible bundle directory
BUNDLE_DEPLOY_DIR="./${DEPLOY_SUBDIR_NAME}"
BUNDLE_CONFIG_FILE="${BUNDLE_DEPLOY_DIR}/${BASE_CONFIG_FILENAME}"

if [[ ! -d "$BUNDLE_DEPLOY_DIR" ]]; then
  error_exit "Directory './${DEPLOY_SUBDIR_NAME}/' not found. Please run this script from the root of the application bundle directory."
fi
if [[ ! -f "$BUNDLE_CONFIG_FILE" ]]; then
  error_exit "Configuration file '${BUNDLE_CONFIG_FILE}' not found. Please run this script from the root of the application bundle directory."
fi
info "Current bundle context verified: $(pwd)"

# Check new component file
if [[ ! -f "$NEW_COMPONENT_PATH" ]]; then
  error_exit "New component file not found: $NEW_COMPONENT_PATH"
fi
if [[ ! -r "$NEW_COMPONENT_PATH" ]]; then
  error_exit "New component file is not readable: $NEW_COMPONENT_PATH"
fi
info "Verified new component: $NEW_COMPONENT_PATH (type: $COMPONENT_TYPE)"

# --- Perform Update ---
NEW_COMPONENT_FILENAME=$(basename "$NEW_COMPONENT_PATH")
TARGET_COMPONENT_PATH_IN_BUNDLE="${BUNDLE_DEPLOY_DIR}/${NEW_COMPONENT_FILENAME}"

info "Copying '$NEW_COMPONENT_FILENAME' to '${TARGET_COMPONENT_PATH_IN_BUNDLE}'..."
cp "$NEW_COMPONENT_PATH" "$TARGET_COMPONENT_PATH_IN_BUNDLE" || error_exit "Failed to copy component into bundle."
chmod +r "$TARGET_COMPONENT_PATH_IN_BUNDLE" # Ensure readable, cp should preserve exec if source was exec

info "Updating configuration file: ${BUNDLE_CONFIG_FILE}"
CONFIG_KEY_TO_UPDATE=""
if [[ "$COMPONENT_TYPE" == "binary" ]]; then
  CONFIG_KEY_TO_UPDATE="VERSIONED_APP_BINARY_FILENAME"
elif [[ "$COMPONENT_TYPE" == "wheel" ]]; then
  CONFIG_KEY_TO_UPDATE="VERSIONED_DATAMOVER_WHEEL_FILENAME"
else
  error_exit "Internal error: Unknown component type '$COMPONENT_TYPE'." # Should not happen
fi

# Check if key exists before attempting to update
if ! grep -q "^\s*${CONFIG_KEY_TO_UPDATE}\s*=" "$BUNDLE_CONFIG_FILE"; then
    warn "Configuration key '${CONFIG_KEY_TO_UPDATE}' not found in '${BUNDLE_CONFIG_FILE}'. Appending it."
    # Ensure there's a newline at the end of the file if we are appending
    if [[ $(tail -c1 "$BUNDLE_CONFIG_FILE" | wc -l) -eq 0 ]]; then echo >> "$BUNDLE_CONFIG_FILE"; fi
    echo "${CONFIG_KEY_TO_UPDATE}=\"${NEW_COMPONENT_FILENAME}\"" >> "$BUNDLE_CONFIG_FILE"
else
    # Using '#' as sed delimiter to avoid issues with filenames containing '/'
    sed -i -E "s#^(\s*${CONFIG_KEY_TO_UPDATE}\s*=\s*).*#\1\"${NEW_COMPONENT_FILENAME}\"#" "$BUNDLE_CONFIG_FILE" || error_exit "Failed to update '${CONFIG_KEY_TO_UPDATE}' in '${BUNDLE_CONFIG_FILE}'."
fi

info "Successfully updated '${CONFIG_KEY_TO_UPDATE}' to '${NEW_COMPONENT_FILENAME}'."

# --- Completion Message ---
info "--------------------------------------------------------------------"
info "Bundle patch preparation complete!"
info "The current bundle directory ($(pwd)) has been updated with:"
info "  - New component: ./${DEPLOY_SUBDIR_NAME}/${NEW_COMPONENT_FILENAME}"
info "  - Configuration updated: ./${DEPLOY_SUBDIR_NAME}/${BASE_CONFIG_FILENAME}"
info ""
info "To deploy this patched version to the system, run the orchestrator"
info "from this directory:"
info "  sudo ./deploy_orchestrator.sh --update"
info "--------------------------------------------------------------------"

exit 0