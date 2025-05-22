#!/usr/bin/env bash
# shellcheck disable=SC1090,SC2154 # SC1090 for source, SC2154 for sourced variables
set -euo pipefail
IFS=$'\n\t'

# -----------------------------------------------------------------------------
# Base Installer for exportcliv2 + bitmover
# Improved dry-run output for environment variables file.
# -----------------------------------------------------------------------------

# --- Logging & Globals ---
_ts()  { date -u +'%Y-%m-%dT%H:%M:%SZ'; }
info() { echo "$(_ts) [INFO]  $*"; }
warn() { echo "$(_ts) [WARN]  $*"; }
error_exit() { echo "$(_ts) [ERROR] $*" >&2; exit 1; }

cleanup() {
  local exit_code="${1:-$?}"
  if [[ "$exit_code" -ne 0 ]]; then
    warn "Installation failed or was interrupted (passed exit code: $exit_code)."
    warn "System may be in an inconsistent state. Please review logs."
  fi
}

trap 'cleanup $?' ERR
trap 'cleanup 0' EXIT # Ensures cleanup runs on normal exit too, can be used for temp file removal etc.

readonly APP_NAME="exportcliv2"

# --- Argument Parsing ---
CONFIG_FILE_PATH="install-app.conf"
DRY_RUN=""

usage() {
  cat <<EOF
Usage: $(basename "$0") [-c <config_file>] [-n] [-h]

Installs or updates the '${APP_NAME}' application suite.
This script MUST be run as root or with sudo.

Options:
  -c <config_file>  Configuration file to use (default: ./install-app.conf).
  -n                Dry-run mode (print commands instead of executing).
  -h                Show this help message and exit.
EOF
  exit 0
}

while getopts ":nhc:" o; do # Flags first, then options requiring arguments
  case $o in
    c) CONFIG_FILE_PATH="$OPTARG" ;;
    n) DRY_RUN="echo" ;;
    # r) RESTART_SERVICES=true ;; # Removed
    # l) LOG_FILE="$OPTARG" ;;    # Removed
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

# CORRECTED: readonly SCRIPT_DIR assignment order
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR

# --- Load Configuration ---
info "Loading configuration from '$CONFIG_FILE_PATH'..."
if [[ -f "$CONFIG_FILE_PATH" ]]; then
  source "$CONFIG_FILE_PATH"
  info "Configuration loaded successfully from '$CONFIG_FILE_PATH'."
else
  error_exit "Configuration file '$CONFIG_FILE_PATH' not found."
fi

# --- Validate Mandatory Configuration Variables ---
info "Validating mandatory configuration variables..."
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
info "Mandatory configuration variables validated."

# --- Derived Readonly Variables ---
readonly APP_USER="${USER_CONFIG:-${APP_NAME}_user}"
readonly APP_GROUP="${GROUP_CONFIG:-${APP_NAME}_group}"
readonly BASE_DIR="${BASE_DIR_CONFIG:-/opt/${APP_NAME}}"
readonly ETC_DIR="/etc/${APP_NAME}"
readonly SYSTEMD_DIR="/etc/systemd/system"
readonly PYTHON_VENV_DIR_NAME="${PYTHON_VENV_DIR_NAME:-datamover_venv}"
readonly PYTHON_VENV_PATH="${BASE_DIR}/${PYTHON_VENV_DIR_NAME}"
readonly SYMLINK_EXECUTABLE_PATH="${BASE_DIR}/bin/${APP_NAME}"
readonly DEST_VERSIONED_APP_BINARY_PATH="${BASE_DIR}/bin/${VERSIONED_APP_BINARY_FILENAME}"
readonly COMMON_CONFIGS_SUBDIR="${COMMON_CONFIGS_SUBDIR:-config_files}"
readonly COMMON_CFG_DIR="${SCRIPT_DIR}/${COMMON_CONFIGS_SUBDIR}"
readonly WRAPPER_SCRIPT_TEMPLATE_NAME="run_exportcliv2_instance.sh.template"
readonly WRAPPER_TEMPLATE_PATH="${COMMON_CFG_DIR}/${WRAPPER_SCRIPT_TEMPLATE_NAME}"
readonly INSTALLED_WRAPPER_SCRIPT_NAME="run_exportcliv2_instance.sh"
readonly INSTALLED_WRAPPER_SCRIPT_PATH="${BASE_DIR}/bin/${INSTALLED_WRAPPER_SCRIPT_NAME}"
readonly SOURCE_DATA_DIR="${BASE_DIR}/source"
readonly CSV_DATA_DIR="${BASE_DIR}/csv"
readonly WORKER_DATA_DIR="${BASE_DIR}/worker"
readonly UPLOADED_DATA_DIR="${BASE_DIR}/uploaded"
readonly DEAD_LETTER_DATA_DIR="${BASE_DIR}/dead_letter"
readonly SYSTEMD_TEMPLATES_SUBDIR="${SYSTEMD_TEMPLATES_SUBDIR:-systemd_units}"
readonly TEMPLATES_DIR="${SCRIPT_DIR}/${SYSTEMD_TEMPLATES_SUBDIR}"
readonly BITMOVER_LOG_DIR="${BITMOVER_LOG_DIR_CONFIG:-/var/log/${APP_NAME}/bitmover}"
readonly BITMOVER_CONFIG_FILE="${ETC_DIR}/config.ini"
readonly BASE_VARS_FILE="/etc/default/${APP_NAME}_base_vars"
readonly REMOTE_HOST_URL="${REMOTE_HOST_URL_CONFIG}"
readonly SOURCE_VERSIONED_APP_BINARY_FILE_PATH="${SCRIPT_DIR}/${VERSIONED_APP_BINARY_FILENAME}"
readonly SOURCE_VERSIONED_WHEEL_FILE_PATH="${SCRIPT_DIR}/${VERSIONED_DATAMOVER_WHEEL_FILENAME}"

# --- Pre-flight Checks ---
info "Running pre-flight checks..."
[[ -f "$SOURCE_VERSIONED_APP_BINARY_FILE_PATH" ]] || error_exit "Application binary not found: $SOURCE_VERSIONED_APP_BINARY_FILE_PATH"
[[ -f "$SOURCE_VERSIONED_WHEEL_FILE_PATH" ]]   || error_exit "Datamover wheel not found: $SOURCE_VERSIONED_WHEEL_FILE_PATH"
[[ -f "$WRAPPER_TEMPLATE_PATH" ]]               || error_exit "Wrapper script template not found: $WRAPPER_TEMPLATE_PATH"
[[ -d "$TEMPLATES_DIR" ]]                       || error_exit "Systemd templates directory not found: $TEMPLATES_DIR"

shopt -s nullglob
mapfile -t systemd_template_files < <(find "$TEMPLATES_DIR" -maxdepth 1 -name "*.template" -print)
shopt -u nullglob
(( ${#systemd_template_files[@]} > 0 )) || error_exit "No .template files found in $TEMPLATES_DIR"
info "Found ${#systemd_template_files[@]} systemd template(s)."

required_commands=(getent groupadd useradd install sed systemctl python3 find id chown ln basename pushd popd date mkdir printf)
for cmd in "${required_commands[@]}"; do
  command -v "$cmd" &>/dev/null || error_exit "Required command '$cmd' is not installed or not in PATH."
done
info "Pre-flight checks passed."

# --- Helper Functions ---
create_group_if_not_exists() {
  local group_name="$1"
  if getent group "$group_name" &>/dev/null; then
    info "Group '$group_name' already exists. Skipping creation."
  else
    info "Creating system group '$group_name'..."
    $DRY_RUN groupadd -r "$group_name" || error_exit "Failed to create group '$group_name'."
  fi
}

create_user_if_not_exists() {
  local username="$1"; local primary_group="$2"; local home_dir="$3"
  if getent passwd "$username" &>/dev/null; then
    info "User '$username' already exists. Skipping creation."
  else
    info "Creating system user '$username' (group: '$primary_group', home: '$home_dir')..."
    $DRY_RUN useradd -r -g "$primary_group" -d "$home_dir" -s /sbin/nologin "$username" \
      || error_exit "Failed to create user '$username'."
  fi
}

ensure_directory() {
  local dir_path="$1"; local owner="$2"; local group="$3"; local perms="$4"
  info "Ensuring directory '$dir_path' (Owner: $owner, Group: $group, Perms: $perms)..."
  $DRY_RUN mkdir -p "$dir_path" || error_exit "Failed to create directory '$dir_path'."
  $DRY_RUN chown "$owner:$group" "$dir_path" || error_exit "Failed to set ownership on '$dir_path'."
  $DRY_RUN chmod "$perms" "$dir_path" || error_exit "Failed to set permissions on '$dir_path'."
}

install_file_to_dest() {
  local src_file="$1"; local dest_file="$2"; local owner="$3"; local group="$4"; local perms="$5"
  info "Installing file '$src_file' to '$dest_file' (Owner: $owner, Group: $group, Perms: $perms)..."
  $DRY_RUN install -T -o "$owner" -g "$group" -m "$perms" "$src_file" "$dest_file" \
    || error_exit "Failed to install file '$src_file' to '$dest_file'."
}

setup_python_venv() {
  local venv_path="$1"; local wheel_to_install="$2"; local venv_owner="$3"; local venv_group="$4"
  ensure_directory "$(dirname "$venv_path")" "$venv_owner" "$venv_group" "0755" # Base dir for venv
  local pip_executable="${venv_path}/bin/pip"
  if [[ -f "$pip_executable" ]]; then
    info "Python virtual environment likely exists at '$venv_path'."
  else
    info "Creating Python virtual environment at '$venv_path'..."
    $DRY_RUN python3 -m venv "$venv_path" || error_exit "Failed to create Python venv."
  fi
  info "Upgrading pip and installing/upgrading wheel '$wheel_to_install' into '$venv_path'..."
  $DRY_RUN "$pip_executable" install --upgrade pip || error_exit "Failed to upgrade pip."
  $DRY_RUN "$pip_executable" install --upgrade "$wheel_to_install" || error_exit "Failed to install/upgrade wheel."
  $DRY_RUN chown -R "$venv_owner:$venv_group" "$venv_path" || error_exit "Failed to set venv ownership."
  info "Python setup complete for '$venv_path'."
}

deploy_wrapper_script() {
  info "Deploying wrapper script '$INSTALLED_WRAPPER_SCRIPT_NAME' to '$INSTALLED_WRAPPER_SCRIPT_PATH'"
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
  info "Wrapper script deployed."
}

deploy_systemd_units() {
  info "Deploying systemd units to '$SYSTEMD_DIR'"
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
    -e "s#{{REMOTE_HOST_URL}}#${REMOTE_HOST_URL}#g" # Use # as delimiter for URLs
  )
  for template_file in "${systemd_template_files[@]}"; do
    local unit_name; unit_name=$(basename "${template_file%.template}")
    local output_file="${SYSTEMD_DIR}/${unit_name}"
    info "  Processing systemd template '$template_file' -> '$output_file'..."
    $DRY_RUN sed "${sed_replacements_systemd[@]}" "$template_file" > "$output_file" \
      || error_exit "Failed to process systemd template '$template_file'."
    $DRY_RUN chmod 0644 "$output_file"
  done
  info "Reloading systemd daemon..."
  $DRY_RUN systemctl daemon-reload || error_exit "Failed to reload systemd daemon."
  info "Systemd units deployed."
}

deploy_application_configs() {
  info "Deploying application configurations to '$ETC_DIR'"
  ensure_directory "$ETC_DIR" "root" "root" "0755"
  shopt -s nullglob
  local common_configs_to_deploy=()
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
    info "No additional common config files (excluding templates) found in '$COMMON_CFG_DIR' to deploy."
  fi

  local bitmover_template_path="$COMMON_CFG_DIR/config.ini.template"
  if [[ -f "$bitmover_template_path" ]]; then
    info "Deploying Bitmover config from template '$bitmover_template_path' to '$BITMOVER_CONFIG_FILE'..."
    ensure_directory "$BITMOVER_LOG_DIR" "$APP_USER" "$APP_GROUP" "0770"
    local sed_replacements_bitmover_cfg=(
      -e "s|{{BASE_DIR}}|${BASE_DIR}|g"
      -e "s|{{BITMOVER_LOG_DIR}}|${BITMOVER_LOG_DIR}|g"
      -e "s#{{REMOTE_HOST_URL}}#${REMOTE_HOST_URL}#g" # Use # as delimiter for URLs
    )
    $DRY_RUN sed "${sed_replacements_bitmover_cfg[@]}" "$bitmover_template_path" > "$BITMOVER_CONFIG_FILE" \
      || error_exit "Failed to generate '$BITMOVER_CONFIG_FILE' from template."
    $DRY_RUN chmod 0640 "$BITMOVER_CONFIG_FILE"
    $DRY_RUN chown "$APP_USER:$APP_GROUP" "$BITMOVER_CONFIG_FILE"
    info "Bitmover config deployed."
  else
    warn "Bitmover config template 'config.ini.template' not found in '$COMMON_CFG_DIR'. Skipping its deployment."
  fi
  info "Application configurations deployment finished."
}

save_environment_variables_file() {
  info "Saving base environment variables to '$BASE_VARS_FILE'"

  # Prepare the content for the environment variables file
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
    # In DRY_RUN, echo the ensure_directory command and the content
    echo "DRY RUN: ensure_directory \"$(dirname "$BASE_VARS_FILE")\" \"root\" \"root\" \"0755\""
    info "DRY RUN: Would write the following content to '$BASE_VARS_FILE':"
    echo "$file_content" # This will be captured by script's main logging if any
    echo "DRY RUN: chmod 0644 \"$BASE_VARS_FILE\""
  else
    ensure_directory "$(dirname "$BASE_VARS_FILE")" "root" "root" "0755"
    # Use printf to write the content to the file
    printf "%s\n" "$file_content" > "$BASE_VARS_FILE" || error_exit "Failed to write to '$BASE_VARS_FILE'"
    chmod 0644 "$BASE_VARS_FILE" || error_exit "Failed to set permissions on '$BASE_VARS_FILE'"
  fi
  info "Base environment variables file processed."
}

# --- Main ---
main() {
  info "Starting installation/update of the '${APP_NAME}' application suite..."
  [[ -n "$DRY_RUN" ]] && warn "DRY RUN MODE ENABLED: No changes will be made to the system."

  create_group_if_not_exists "$APP_GROUP"
  create_user_if_not_exists "$APP_USER" "$APP_GROUP" "$BASE_DIR"

  ensure_directory "$ETC_DIR"                 "root"      "$APP_GROUP" "0755"
  ensure_directory "$BASE_DIR"                "$APP_USER" "$APP_GROUP" "0750"
  ensure_directory "${BASE_DIR}/bin"          "root"      "$APP_GROUP" "0755"
  ensure_directory "$SOURCE_DATA_DIR"         "$APP_USER" "$APP_GROUP" "0770"
  ensure_directory "$CSV_DATA_DIR"            "$APP_USER" "$APP_GROUP" "0770"
  ensure_directory "$WORKER_DATA_DIR"         "$APP_USER" "$APP_GROUP" "0770"
  ensure_directory "$UPLOADED_DATA_DIR"       "$APP_USER" "$APP_GROUP" "0770"
  ensure_directory "$DEAD_LETTER_DATA_DIR"    "$APP_USER" "$APP_GROUP" "0770"

  install_file_to_dest "$SOURCE_VERSIONED_APP_BINARY_FILE_PATH" "$DEST_VERSIONED_APP_BINARY_PATH" \
               "root" "$APP_GROUP" "0750"
  info "Creating/updating symlink '$SYMLINK_EXECUTABLE_PATH' -> '$VERSIONED_APP_BINARY_FILENAME'"
  $DRY_RUN pushd "${BASE_DIR}/bin" >/dev/null
  $DRY_RUN ln -snf "$VERSIONED_APP_BINARY_FILENAME" "$APP_NAME"
  $DRY_RUN popd >/dev/null
  info "Symlink processed."

  deploy_wrapper_script
  setup_python_venv "$PYTHON_VENV_PATH" "$SOURCE_VERSIONED_WHEEL_FILE_PATH" "$APP_USER" "$APP_GROUP"
  deploy_systemd_units
  deploy_application_configs
  save_environment_variables_file

  info "Installation/update of '${APP_NAME}' application suite processing complete."
  info "  Main binary: '$VERSIONED_APP_BINARY_FILENAME' -> '$DEST_VERSIONED_APP_BINARY_PATH' (linked via '$SYMLINK_EXECUTABLE_PATH')"
  info "  Wrapper script for instances: '$INSTALLED_WRAPPER_SCRIPT_PATH'"
  info "  Datamover wheel: '$VERSIONED_DATAMOVER_WHEEL_FILENAME' in '$PYTHON_VENV_PATH'"
  info "  Default instance EXPORT_TIMEOUT (from install-app.conf): '${EXPORT_TIMEOUT_CONFIG}' seconds (stored in '$BASE_VARS_FILE')"

  # Removed service restart block
  if [[ -z "$DRY_RUN" ]]; then
    info "To apply changes, services might need to be (re)started manually."
    info "Example: systemctl restart bitmover.service && systemctl restart ${APP_NAME}@your_instance.service"
  fi

  if [[ -n "$DRY_RUN" ]]; then
    warn "DRY RUN MODE was enabled. No actual changes were made to the system."
  fi
  info "-------------------- INSTALLATION SCRIPT FINISHED --------------------"
}

# --- Execute Main ---
main "$@"
