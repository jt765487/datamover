#!/usr/bin/env bash
# shellcheck disable=SC1090,SC2154 # SC1090 for source, SC2154 for sourced variables
set -euo pipefail
IFS=$'\n\t'

# -----------------------------------------------------------------------------
# Base Installer for exportcliv2 + bitmover
# - Corrected CONFIG_FILE_PATH resolution to be relative to SCRIPT_DIR.
# - Improved dry-run output for environment variables file.
# - Added verbose mode (-v).
# - Added installation of manage_services.sh and symlink to /usr/local/bin.
# -----------------------------------------------------------------------------
VERSION_INSTALL_BASE="1.2.0" # Script version (incremented for new feature)

# --- Logging & Globals ---
_ts() { date -u +'%Y-%m-%dT%H:%M:%SZ'; }
info() { echo "$(_ts) [INFO]  $*"; } # Always shown
warn() { echo "$(_ts) [WARN]  $*"; } # Always shown
error_exit() { echo "$(_ts) [ERROR] $*" >&2; exit 1; } # Always shown

VERBOSE_MODE_BASE_INSTALLER=false # Global for verbose state

debug() {
  if [[ "$VERBOSE_MODE_BASE_INSTALLER" == true ]]; then
    echo "$(_ts) [DEBUG] $*";
  fi
}

cleanup() {
  local exit_code="${1:-$?}"
  if [[ "$exit_code" -ne 0 ]]; then
    warn "Installation script (install_base_exportcliv2.sh) failed or was interrupted (exit code: $exit_code)."
    warn "System may be in an inconsistent state. Please review logs."
  fi
}
trap 'cleanup $?' ERR

readonly APP_NAME="exportcliv2"

# --- Argument Parsing ---
CONFIG_FILE_NAME_ARG="install-app.conf" # Default filename, path will be resolved
DRY_RUN=""

usage() {
  cat <<EOF
Usage: $(basename "$0") [-c <config_filename>] [-n] [-v] [-h]

Installs or updates the '${APP_NAME}' application suite.
This script MUST be run as root or with sudo.
It expects to find resources (binaries, wheel, templates, manage_services.sh)
in its own directory or specified subdirectories.

Options:
  -c <config_filename> Configuration filename (default: install-app.conf).
                       Expected to be in the same directory as this script.
  -n                   Dry-run mode (print commands instead of executing).
  -v                   Verbose mode (show detailed step-by-step information).
  -h                   Show this help message and exit.
EOF
  exit 0
}

while getopts ":nhvc:" o; do
  case $o in
    c) CONFIG_FILE_NAME_ARG="$OPTARG" ;;
    n) DRY_RUN="echo" ;;
    v) VERBOSE_MODE_BASE_INSTALLER=true ;;
    h) usage ;;
    \?) error_exit "Invalid option: -$OPTARG. Use -h for help." ;;
    :) error_exit "Option -$OPTARG requires an argument. Use -h for help." ;;
  esac
done
shift $((OPTIND -1))

# --- Root Execution Check ---
if [[ "$(id -u)" -ne 0 ]]; then
  error_exit "This script must be run as root or with sudo."
fi

# SCRIPT_DIR is the absolute path to the directory where this script resides.
# This is crucial for finding sibling resources (config, templates, binaries, wheel, manage_services.sh).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
debug "Script directory determined as: $SCRIPT_DIR"

# --- Resolve and Load Configuration ---
# CONFIG_FILE_PATH will be the fully resolved path to the configuration file.
# It's expected to be in the same directory as this script.
CONFIG_FILE_PATH="${SCRIPT_DIR}/${CONFIG_FILE_NAME_ARG}"

debug "Attempting to load configuration from '$CONFIG_FILE_PATH' (resolved from filename '$CONFIG_FILE_NAME_ARG' in SCRIPT_DIR)."
if [[ -f "$CONFIG_FILE_PATH" ]]; then
  # shellcheck source=/dev/null
  source "$CONFIG_FILE_PATH"
  debug "Configuration loaded successfully from '$CONFIG_FILE_PATH'."
else
  error_exit "Configuration file not found at the expected location: '$CONFIG_FILE_PATH'. Ensure '$CONFIG_FILE_NAME_ARG' exists in '$SCRIPT_DIR'."
fi

# --- Validate Mandatory Configuration Variables ---
debug "Validating mandatory configuration variables from '$CONFIG_FILE_PATH'..."
: "${VERSIONED_APP_BINARY_FILENAME:?VERSIONED_APP_BINARY_FILENAME must be defined in $CONFIG_FILE_PATH}"
: "${VERSIONED_DATAMOVER_WHEEL_FILENAME:?VERSIONED_DATAMOVER_WHEEL_FILENAME must be defined in $CONFIG_FILE_PATH}"
: "${REMOTE_HOST_URL_CONFIG:?REMOTE_HOST_URL_CONFIG must be defined in $CONFIG_FILE_PATH}"
: "${EXPORT_TIMEOUT_CONFIG:?EXPORT_TIMEOUT_CONFIG must be defined in $CONFIG_FILE_PATH}"

if ! [[ "$REMOTE_HOST_URL_CONFIG" =~ ^https?:// ]]; then
  error_exit "REMOTE_HOST_URL_CONFIG ('$REMOTE_HOST_URL_CONFIG') in '$CONFIG_FILE_PATH' must start with http:// or https://"
fi
if ! [[ "$EXPORT_TIMEOUT_CONFIG" =~ ^[0-9]+$ ]]; then
  error_exit "EXPORT_TIMEOUT_CONFIG ('$EXPORT_TIMEOUT_CONFIG') in '$CONFIG_FILE_PATH' must be a non-negative integer."
fi
debug "Mandatory configuration variables validated."

# --- Derived Readonly Variables ---
# These paths are either absolute system paths or derived from SCRIPT_DIR (for source files)
# or BASE_DIR (for installation targets).
readonly APP_USER="${USER_CONFIG:-${APP_NAME}_user}"
readonly APP_GROUP="${GROUP_CONFIG:-${APP_NAME}_group}"
readonly BASE_DIR="${BASE_DIR_CONFIG:-/opt/${APP_NAME}}"
readonly ETC_DIR="/etc/${APP_NAME}"
readonly SYSTEMD_DIR="/etc/systemd/system"
readonly PYTHON_VENV_DIR_NAME="${PYTHON_VENV_DIR_NAME:-datamover_venv}"
readonly PYTHON_VENV_PATH="${BASE_DIR}/${PYTHON_VENV_DIR_NAME}"
readonly SYMLINK_EXECUTABLE_PATH="${BASE_DIR}/bin/${APP_NAME}"
readonly DEST_VERSIONED_APP_BINARY_PATH="${BASE_DIR}/bin/${VERSIONED_APP_BINARY_FILENAME}"
readonly COMMON_CONFIGS_SUBDIR="${COMMON_CONFIGS_SUBDIR:-config_files}" # Subdir within SCRIPT_DIR
readonly COMMON_CFG_DIR="${SCRIPT_DIR}/${COMMON_CONFIGS_SUBDIR}"
readonly WRAPPER_SCRIPT_TEMPLATE_NAME="run_exportcliv2_instance.sh.template"
readonly WRAPPER_TEMPLATE_PATH="${COMMON_CFG_DIR}/${WRAPPER_SCRIPT_TEMPLATE_NAME}"
readonly INSTALLED_WRAPPER_SCRIPT_NAME="run_exportcliv2_instance.sh"
readonly INSTALLED_WRAPPER_SCRIPT_PATH="${BASE_DIR}/bin/${INSTALLED_WRAPPER_SCRIPT_NAME}"
readonly SOURCE_DATA_DIR="${BASE_DIR}/source"       # Target installation directory
readonly CSV_DATA_DIR="${BASE_DIR}/csv"            # Target installation directory
readonly WORKER_DATA_DIR="${BASE_DIR}/worker"      # Target installation directory
readonly UPLOADED_DATA_DIR="${BASE_DIR}/uploaded"  # Target installation directory
readonly DEAD_LETTER_DATA_DIR="${BASE_DIR}/dead_letter" # Target installation directory
readonly SYSTEMD_TEMPLATES_SUBDIR="${SYSTEMD_TEMPLATES_SUBDIR:-systemd_units}" # Subdir within SCRIPT_DIR
readonly TEMPLATES_DIR="${SCRIPT_DIR}/${SYSTEMD_TEMPLATES_SUBDIR}"
readonly BITMOVER_LOG_DIR="${BITMOVER_LOG_DIR_CONFIG:-/var/log/${APP_NAME}/bitmover}"
readonly BITMOVER_CONFIG_FILE="${ETC_DIR}/config.ini"
readonly BASE_VARS_FILE="/etc/default/${APP_NAME}_base_vars"
readonly REMOTE_HOST_URL="${REMOTE_HOST_URL_CONFIG}"
# Source files are located relative to SCRIPT_DIR
readonly SOURCE_VERSIONED_APP_BINARY_FILE_PATH="${SCRIPT_DIR}/${VERSIONED_APP_BINARY_FILENAME}"
readonly SOURCE_VERSIONED_WHEEL_FILE_PATH="${SCRIPT_DIR}/${VERSIONED_DATAMOVER_WHEEL_FILENAME}"

# --- Pre-flight Checks ---
debug "Running pre-flight checks (source files expected in '$SCRIPT_DIR' or its subdirectories)..."
[[ -f "$SOURCE_VERSIONED_APP_BINARY_FILE_PATH" ]] || error_exit "Application binary not found: $SOURCE_VERSIONED_APP_BINARY_FILE_PATH"
[[ -f "$SOURCE_VERSIONED_WHEEL_FILE_PATH" ]]   || error_exit "Datamover wheel not found: $SOURCE_VERSIONED_WHEEL_FILE_PATH"
[[ -f "$WRAPPER_TEMPLATE_PATH" ]]               || error_exit "Wrapper script template not found: $WRAPPER_TEMPLATE_PATH (checked in $COMMON_CFG_DIR)"
[[ -d "$TEMPLATES_DIR" ]]                       || error_exit "Systemd templates directory not found: $TEMPLATES_DIR (checked as subdir of $SCRIPT_DIR)"
# Source for manage_services.sh will be checked in its installation function

shopt -s nullglob
mapfile -t systemd_template_files < <(find "$TEMPLATES_DIR" -maxdepth 1 -name "*.template" -print)
shopt -u nullglob
(( ${#systemd_template_files[@]} > 0 )) || error_exit "No .template files found in $TEMPLATES_DIR"
debug "Found ${#systemd_template_files[@]} systemd template(s)."

required_commands=(getent groupadd useradd install sed systemctl python3 find id chown ln basename pushd popd date mkdir printf)
for cmd in "${required_commands[@]}"; do
  command -v "$cmd" &>/dev/null || error_exit "Required command '$cmd' is not installed or not in PATH."
done
debug "Pre-flight checks passed."

# --- Helper Functions ---
create_group_if_not_exists() {
  local group_name="$1"
  if getent group "$group_name" &>/dev/null; then
    debug "Group '$group_name' already exists. Skipping creation."
  else
    debug "Creating system group '$group_name'..."
    $DRY_RUN groupadd -r "$group_name" || error_exit "Failed to create group '$group_name'."
  fi
}

create_user_if_not_exists() {
  local username="$1"; local primary_group="$2"; local home_dir="$3"
  if getent passwd "$username" &>/dev/null; then
    debug "User '$username' already exists. Skipping creation."
  else
    debug "Creating system user '$username' (group: '$primary_group', home: '$home_dir')..."
    $DRY_RUN useradd -r -g "$primary_group" -d "$home_dir" -s /sbin/nologin "$username" \
      || error_exit "Failed to create user '$username'."
  fi
}

ensure_directory() {
  local dir_path="$1"; local owner="$2"; local group="$3"; local perms="$4"
  debug "Ensuring directory '$dir_path' (Owner: $owner, Group: $group, Perms: $perms)..."
  $DRY_RUN mkdir -p "$dir_path" || error_exit "Failed to create directory '$dir_path'."
  $DRY_RUN chown "$owner:$group" "$dir_path" || error_exit "Failed to set ownership on '$dir_path'."
  $DRY_RUN chmod "$perms" "$dir_path" || error_exit "Failed to set permissions on '$dir_path'."
}

install_file_to_dest() {
  local src_file="$1"; local dest_file="$2"; local owner="$3"; local group="$4"; local perms="$5"
  debug "Installing file '$src_file' to '$dest_file' (Owner: $owner, Group: $group, Perms: $perms)..."
  $DRY_RUN install -T -o "$owner" -g "$group" -m "$perms" "$src_file" "$dest_file" \
    || error_exit "Failed to install file '$src_file' to '$dest_file'."
}

setup_python_venv() {
  local venv_path="$1"; local wheel_to_install="$2"; local venv_owner="$3"; local venv_group="$4"
  ensure_directory "$(dirname "$venv_path")" "$venv_owner" "$venv_group" "0755"
  local pip_executable="${venv_path}/bin/pip"
  local pip_opts=()
  if [[ "$VERBOSE_MODE_BASE_INSTALLER" != true && -z "$DRY_RUN" ]]; then
      pip_opts+=("-q")
  fi

  if [[ -f "$pip_executable" ]]; then
    debug "Python virtual environment likely exists at '$venv_path'."
  else
    debug "Creating Python virtual environment at '$venv_path'..."
    $DRY_RUN python3 -m venv "$venv_path" || error_exit "Failed to create Python venv."
  fi
  debug "Upgrading pip and installing/upgrading wheel '$wheel_to_install' into '$venv_path'..."
  $DRY_RUN "$pip_executable" install "${pip_opts[@]}" --upgrade pip || error_exit "Failed to upgrade pip."
  $DRY_RUN "$pip_executable" install "${pip_opts[@]}" --upgrade "$wheel_to_install" || error_exit "Failed to install/upgrade wheel."

  if [[ -z "$DRY_RUN" ]]; then
    chown -R "$venv_owner:$venv_group" "$venv_path" || error_exit "Failed to set venv ownership."
  else
    echo "$DRY_RUN chown -R \"$venv_owner:$venv_group\" \"$venv_path\""
  fi
  debug "Python setup complete for '$venv_path'."
}

deploy_wrapper_script() {
  debug "Deploying wrapper script '$INSTALLED_WRAPPER_SCRIPT_NAME' to '$INSTALLED_WRAPPER_SCRIPT_PATH'"
  local sed_replacements_wrapper=(
    -e "s|{{APP_NAME}}|${APP_NAME}|g"
    -e "s|{{APP_USER}}|${APP_USER}|g"
    -e "s|{{BASE_DIR}}|${BASE_DIR}|g"
    -e "s|{{ETC_DIR}}|${ETC_DIR}|g"
    -e "s|{{SYMLINK_EXECUTABLE_PATH}}|${SYMLINK_EXECUTABLE_PATH}|g"
    -e "s|{{SOURCE_DATA_DIR}}|${SOURCE_DATA_DIR}|g"
    -e "s|{{CSV_DATA_DIR}}|${CSV_DATA_DIR}|g"
  )
  $DRY_RUN sed "${sed_replacements_wrapper[@]}" "$WRAPPER_TEMPLATE_PATH" > "$INSTALLED_WRAPPER_SCRIPT_PATH" \
    || error_exit "Failed to process wrapper script template '$WRAPPER_TEMPLATE_PATH'."
  $DRY_RUN chmod 0750 "$INSTALLED_WRAPPER_SCRIPT_PATH"
  $DRY_RUN chown "${APP_USER}:${APP_GROUP}" "$INSTALLED_WRAPPER_SCRIPT_PATH"
  debug "Wrapper script deployed."
}

deploy_systemd_units() {
  debug "Deploying systemd units to '$SYSTEMD_DIR'"
  ensure_directory "$SYSTEMD_DIR" "root" "root" "0755"
  local sed_replacements_systemd=(
    -e "s|{{APP_NAME}}|${APP_NAME}|g"
    -e "s|{{APP_USER}}|${APP_USER}|g"
    -e "s|{{APP_GROUP}}|${APP_GROUP}|g"
    -e "s|{{BASE_DIR}}|${BASE_DIR}|g"
    -e "s|{{ETC_DIR}}|${ETC_DIR}|g"
    -e "s|{{PYTHON_VENV_PATH}}|${PYTHON_VENV_PATH}|g"
    -e "s|{{BITMOVER_CONFIG_FILE}}|${BITMOVER_CONFIG_FILE}|g"
    -e "s|{{BITMOVER_LOG_DIR}}|${BITMOVER_LOG_DIR}|g"
    -e "s|{{INSTALLED_WRAPPER_SCRIPT_PATH}}|${INSTALLED_WRAPPER_SCRIPT_PATH}|g"
    -e "s|{{SOURCE_DATA_DIR}}|${SOURCE_DATA_DIR}|g"
    -e "s|{{CSV_DATA_DIR}}|${CSV_DATA_DIR}|g"
    -e "s|{{WORKER_DATA_DIR}}|${WORKER_DATA_DIR}|g"
    -e "s|{{UPLOADED_DATA_DIR}}|${UPLOADED_DATA_DIR}|g"
    -e "s|{{DEAD_LETTER_DATA_DIR}}|${DEAD_LETTER_DATA_DIR}|g"
    -e "s#{{REMOTE_HOST_URL}}#${REMOTE_HOST_URL}#g" # Use # as delimiter for URL
  )
  for template_file in "${systemd_template_files[@]}"; do
    local unit_name; unit_name=$(basename "${template_file%.template}")
    local output_file="${SYSTEMD_DIR}/${unit_name}"
    debug "  Processing systemd template '$template_file' -> '$output_file'..."
    $DRY_RUN sed "${sed_replacements_systemd[@]}" "$template_file" > "$output_file" \
      || error_exit "Failed to process systemd template '$template_file'."
    $DRY_RUN chmod 0644 "$output_file"
  done
  debug "Reloading systemd daemon..."
  $DRY_RUN systemctl daemon-reload || error_exit "Failed to reload systemd daemon."
  debug "Systemd units deployed."
}

deploy_application_configs() {
  debug "Deploying application configurations to '$ETC_DIR'"
  ensure_directory "$ETC_DIR" "root" "root" "0755"
  shopt -s nullglob
  local common_configs_to_deploy=()
  # COMMON_CFG_DIR is SCRIPT_DIR/config_files
  for f_path in "$COMMON_CFG_DIR"/*; do
    if [[ -f "$f_path" && $(basename "$f_path") != "$WRAPPER_SCRIPT_TEMPLATE_NAME" && $(basename "$f_path") != "config.ini.template" ]]; then
      common_configs_to_deploy+=("$f_path")
    fi
  done
  shopt -u nullglob

  if (( ${#common_configs_to_deploy[@]} > 0 )); then
    for src_cfg_file in "${common_configs_to_deploy[@]}"; do
      install_file_to_dest "$src_cfg_file" "$ETC_DIR/$(basename "$src_cfg_file")" "root" "$APP_GROUP" "0640"
    done
  else
    debug "No additional common config files (excluding templates) found in '$COMMON_CFG_DIR' to deploy."
  fi

  local bitmover_template_path="$COMMON_CFG_DIR/config.ini.template"
  if [[ -f "$bitmover_template_path" ]]; then
    debug "Deploying Bitmover config from template '$bitmover_template_path' to '$BITMOVER_CONFIG_FILE'..."
    ensure_directory "$BITMOVER_LOG_DIR" "$APP_USER" "$APP_GROUP" "0770"
    local sed_replacements_bitmover_cfg=(
      -e "s|{{BASE_DIR}}|${BASE_DIR}|g"
      -e "s|{{BITMOVER_LOG_DIR}}|${BITMOVER_LOG_DIR}|g"
      -e "s#{{REMOTE_HOST_URL}}#${REMOTE_HOST_URL}#g" # Use # as delimiter for URL
    )
    $DRY_RUN sed "${sed_replacements_bitmover_cfg[@]}" "$bitmover_template_path" > "$BITMOVER_CONFIG_FILE" \
      || error_exit "Failed to generate '$BITMOVER_CONFIG_FILE' from template."
    $DRY_RUN chmod 0640 "$BITMOVER_CONFIG_FILE"
    $DRY_RUN chown "$APP_USER:$APP_GROUP" "$BITMOVER_CONFIG_FILE"
    debug "Bitmover config deployed."
  else
    warn "Bitmover config template 'config.ini.template' not found in '$COMMON_CFG_DIR'. Skipping its deployment."
  fi
  debug "Application configurations deployment finished."
}

save_environment_variables_file() {
  debug "Saving base environment variables to '$BASE_VARS_FILE'"

  local file_content
  file_content=$(cat <<EOF
export APP_NAME="${APP_NAME}"
export APP_USER="${APP_USER}"
export APP_GROUP="${APP_GROUP}"
export BASE_DIR="${BASE_DIR}"
export ETC_DIR="${ETC_DIR}"
export SYMLINK_EXECUTABLE_PATH="${SYMLINK_EXECUTABLE_PATH}"
export INSTALLED_VERSIONED_APP_BINARY_FILENAME="${VERSIONED_APP_BINARY_FILENAME}"
export DEST_VERSIONED_APP_BINARY_PATH="${DEST_VERSIONED_APP_BINARY_PATH}"
export INSTALLED_WRAPPER_SCRIPT_PATH="${INSTALLED_WRAPPER_SCRIPT_PATH}"
export SOURCE_DATA_DIR="${SOURCE_DATA_DIR}"
export CSV_DATA_DIR="${CSV_DATA_DIR}"
export WORKER_DATA_DIR="${WORKER_DATA_DIR}"
export UPLOADED_DATA_DIR="${UPLOADED_DATA_DIR}"
export DEAD_LETTER_DATA_DIR="${DEAD_LETTER_DATA_DIR}"
export PYTHON_VENV_PATH="${PYTHON_VENV_PATH}"
export INSTALLED_VERSIONED_WHEEL_FILENAME="${VERSIONED_DATAMOVER_WHEEL_FILENAME}"
export BITMOVER_LOG_DIR="${BITMOVER_LOG_DIR}"
export BITMOVER_CONFIG_FILE="${BITMOVER_CONFIG_FILE}"
export REMOTE_HOST_URL="${REMOTE_HOST_URL}"
export DEFAULT_CONFIGURE_INSTANCE_EXPORT_TIMEOUT="${EXPORT_TIMEOUT_CONFIG}"
EOF
)

  if [[ -n "$DRY_RUN" ]]; then
    echo "$DRY_RUN ensure_directory \"$(dirname "$BASE_VARS_FILE")\" \"root\" \"root\" \"0755\""
    info "DRY RUN: Would write the following content to '$BASE_VARS_FILE':"
    echo "${file_content}"
    echo "$DRY_RUN chmod 0644 \"$BASE_VARS_FILE\""
  else
    ensure_directory "$(dirname "$BASE_VARS_FILE")" "root" "root" "0755"
    printf "%s\n" "$file_content" > "$BASE_VARS_FILE" || error_exit "Failed to write to '$BASE_VARS_FILE'"
    chmod 0644 "$BASE_VARS_FILE" || error_exit "Failed to set permissions on '$BASE_VARS_FILE'"
  fi
  debug "Base environment variables file processed."
}

install_management_script_and_symlink() {
  local source_manage_services_script_name="manage_services.sh"
  local source_manage_services_path="${SCRIPT_DIR}/${source_manage_services_script_name}" # Source from bundle

  local app_bin_dir="${BASE_DIR}/bin" # e.g., /opt/exportcliv2/bin/
  local installed_manage_services_path="${app_bin_dir}/${source_manage_services_script_name}" # e.g., /opt/exportcliv2/bin/manage_services.sh

  local symlink_command_name="exportcli-manage" # The command users will type
  local symlink_standard_dir="/usr/local/bin"
  local symlink_full_path="${symlink_standard_dir}/${symlink_command_name}"

  debug "Starting installation of management script '${source_manage_services_script_name}' and symlink '${symlink_command_name}'."

  if [[ ! -f "$source_manage_services_path" ]]; then
    warn "Source management script '$source_manage_services_path' not found. Skipping its installation and symlink creation."
    return 0 # Non-fatal, installation can continue
  fi

  # 1. Ensure the application's bin directory exists (e.g., /opt/exportcliv2/bin)
  #    This is also done in main(), but having it here makes the function more self-contained.
  ensure_directory "$app_bin_dir" "root" "$APP_GROUP" "0755"

  # 2. Install (copy) manage_services.sh to the application's bin directory
  #    Make it executable (0755) so root can execute, and APP_GROUP can read.
  debug "Installing '${source_manage_services_path}' to '${installed_manage_services_path}'."
  install_file_to_dest "$source_manage_services_path" "$installed_manage_services_path" "root" "$APP_GROUP" "0755"

  # 3. Create the symlink in /usr/local/bin
  debug "Attempting to create symlink: '${symlink_full_path}' -> '${installed_manage_services_path}'."
  if [[ -n "$DRY_RUN" ]]; then
    echo "$DRY_RUN mkdir -p \"$symlink_standard_dir\"" # Should exist, but good practice
    echo "$DRY_RUN ln -snf \"$installed_manage_services_path\" \"$symlink_full_path\""
  else
    # Ensure /usr/local/bin exists (it almost certainly will)
    if ! mkdir -p "$symlink_standard_dir"; then
      warn "Failed to ensure system symlink directory '$symlink_standard_dir' exists. Skipping symlink creation for '$symlink_command_name'."
      # Continue, as the script is still available at its direct path
      return 0 # Non-fatal
    fi

    if ln -snf "$installed_manage_services_path" "$symlink_full_path"; then
      info "Successfully created symlink: ${symlink_full_path} -> ${installed_manage_services_path}"
      info "The command '${symlink_command_name}' should now be available system-wide for root."
    else
      warn "Failed to create symlink '$symlink_full_path'. Please check permissions for '$symlink_standard_dir'."
      warn "The management script is still available at: $installed_manage_services_path"
      # Continue, not a fatal error for the whole installation
    fi
  fi
  debug "Management script and symlink processing finished."
}

# --- Main ---
main() {
  info "Starting installation/update of the '${APP_NAME}' application suite (v${VERSION_INSTALL_BASE})..."
  if [[ -n "$DRY_RUN" ]]; then
      warn "DRY RUN MODE ENABLED: No changes will be made to the system."
  elif [[ "$VERBOSE_MODE_BASE_INSTALLER" == true ]]; then
      info "Verbose mode enabled for base installer."
  fi

  create_group_if_not_exists "$APP_GROUP"
  create_user_if_not_exists "$APP_USER" "$APP_GROUP" "$BASE_DIR"

  ensure_directory "$ETC_DIR"                 "root"      "$APP_GROUP" "0755"
  ensure_directory "$BASE_DIR"                "$APP_USER" "$APP_GROUP" "0750"
  ensure_directory "${BASE_DIR}/bin"          "root"      "$APP_GROUP" "0755" # Crucial for main app and manage_services.sh
  ensure_directory "$SOURCE_DATA_DIR"         "$APP_USER" "$APP_GROUP" "0770"
  ensure_directory "$CSV_DATA_DIR"            "$APP_USER" "$APP_GROUP" "0770"
  ensure_directory "$WORKER_DATA_DIR"         "$APP_USER" "$APP_GROUP" "0770"
  ensure_directory "$UPLOADED_DATA_DIR"       "$APP_USER" "$APP_GROUP" "0770"
  ensure_directory "$DEAD_LETTER_DATA_DIR"    "$APP_USER" "$APP_GROUP" "0770"

  install_file_to_dest "$SOURCE_VERSIONED_APP_BINARY_FILE_PATH" "$DEST_VERSIONED_APP_BINARY_PATH" \
               "root" "$APP_GROUP" "0750"

  debug "Creating/updating symlink '$SYMLINK_EXECUTABLE_PATH' -> '$VERSIONED_APP_BINARY_FILENAME'"
  $DRY_RUN pushd "${BASE_DIR}/bin" >/dev/null
  $DRY_RUN ln -snf "$VERSIONED_APP_BINARY_FILENAME" "$APP_NAME"
  $DRY_RUN popd >/dev/null
  debug "Symlink processed."

  deploy_wrapper_script
  setup_python_venv "$PYTHON_VENV_PATH" "$SOURCE_VERSIONED_WHEEL_FILE_PATH" "$APP_USER" "$APP_GROUP"
  deploy_systemd_units
  deploy_application_configs
  save_environment_variables_file

  # Install management script and create symlink
  install_management_script_and_symlink

  info "Installation/update of '${APP_NAME}' application suite processing complete."
  info "  Main binary: '$VERSIONED_APP_BINARY_FILENAME' -> '$DEST_VERSIONED_APP_BINARY_PATH' (linked via '$SYMLINK_EXECUTABLE_PATH')"
  info "  Wrapper script for instances: '$INSTALLED_WRAPPER_SCRIPT_PATH'"
  info "  Datamover wheel: '$VERSIONED_DATAMOVER_WHEEL_FILENAME' in '$PYTHON_VENV_PATH'"
  info "  Management script: '${BASE_DIR}/bin/manage_services.sh' (symlinked as 'exportcli-manage' in /usr/local/bin if successful)"
  info "  Default instance EXPORT_TIMEOUT (from $CONFIG_FILE_NAME_ARG): '${EXPORT_TIMEOUT_CONFIG}' seconds (stored in '$BASE_VARS_FILE')"

  if [[ -z "$DRY_RUN" ]]; then
    info "To apply changes, services might need to be (re)started if not handled by an orchestrator."
    info "Use the 'exportcli-manage' command (if symlink creation was successful) or '${BASE_DIR}/bin/manage_services.sh'."
    info "For example:"
    info "  sudo exportcli-manage --restart                            # To restart the main bitmover service"
    info "  sudo exportcli-manage -i your_instance_name --restart      # To restart a specific application instance"
    info "Alternatively, use the full path:"
    info "  sudo ${BASE_DIR}/bin/manage_services.sh --restart"
  fi

  if [[ -n "$DRY_RUN" ]]; then
    warn "DRY RUN MODE was enabled. No actual changes were made to the system."
  fi
  info "-------------------- INSTALLATION SCRIPT FINISHED (v${VERSION_INSTALL_BASE}) --------------------"
}

# --- Execute Main ---
main "$@"