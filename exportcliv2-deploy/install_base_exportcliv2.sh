#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# -----------------------------------------------------------------------------
# Base Installer for exportcliv2 + bitmover
# Enhanced for Production Use - APP_NAME is internally fixed to "exportcliv2"
# Allows configurable source binary filename via install-app.conf
# Enforces root execution. Includes URL validation and error trap.
# Script Name: install_base_exportcliv2.sh
# -----------------------------------------------------------------------------

# --- Logging ---
_ts()   { date -u +'%Y-%m-%dT%H:%M:%SZ'; }
info()  { echo "$(_ts) [INFO]  $*"; }
warn()  { echo "$(_ts) [WARN]  $*"; }
error_exit() { echo "$(_ts) [ERROR] $*" >&2; exit 1; }

# --- Cleanup function for error trap ---
cleanup() {
  local exit_code=$?
  if [[ $exit_code -ne 0 ]]; then
    warn "Installation failed or was interrupted (exit code: $exit_code)."
    warn "The system might be in an inconsistent state."
    warn "Please review logs and manually clean up if necessary."
  fi
}
trap cleanup EXIT # Catches normal exit and exit due to set -e

# --- Enforce Root Execution ---
if [[ "$(id -u)" -ne 0 ]]; then
  error_exit "This script must be run as root or with sudo."
fi

# --- Defaults & CLI Argument Parsing ---
# Default config file name.
CONFIG_FILE_PATH="install-app.conf"
DRY_RUN=""

# The application name for directory structures, services, users etc. is fixed.
APP_NAME="exportcliv2" # This is THE application name for internal logic and paths

while getopts "c:nh" o; do
  case $o in
    c) CONFIG_FILE_PATH="$OPTARG" ;; # User specifies the config file path
    n) DRY_RUN="echo"   ;;
    h)
      cat <<EOF
Usage: $0 [-c <config_file_path>] [-n] [-h]

Installs the base system for the '${APP_NAME}' application suite.
This script MUST be run as root or with sudo.
The configuration file ('${CONFIG_FILE_PATH}' by default) is mandatory.
It must define APPLICATION_BINARY_FILENAME and REMOTE_HOST_URL_CONFIG.

Options:
  -c <config_file_path> Configuration file to use.
                        (default: ./install-app.conf)
  -n                    Dry-run mode. Print commands instead of executing them.
  -h                    Display this help message and exit.
EOF
      exit 0
      ;;
    *) error_exit "Invalid option. Use -h for help." ;;
  esac
done
shift $((OPTIND - 1))

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Load Configuration (Mandatory) ---
info "Attempting to load configuration from '$CONFIG_FILE_PATH'..."
if [[ -f "$CONFIG_FILE_PATH" ]]; then
  # shellcheck disable=SC1090
  source "$CONFIG_FILE_PATH"
  info "Successfully loaded configuration from '$CONFIG_FILE_PATH'."
else
  error_exit "Configuration file '$CONFIG_FILE_PATH' not found. This file is required. Please create it or use the -c option to specify its path."
fi

# --- Validate Essential Configuration & Derive Variables ---
info "Validating essential variables sourced from configuration..."
info "Using fixed APP_NAME (for paths/services): '$APP_NAME'"

# APPLICATION_BINARY_FILENAME must be set in the configuration file.
if [[ -z "${APPLICATION_BINARY_FILENAME:-}" ]]; then
  error_exit "APPLICATION_BINARY_FILENAME is not defined in the configuration file ('$CONFIG_FILE_PATH'). This variable is mandatory and specifies the source binary file name."
fi
info "Using source application binary filename: '$APPLICATION_BINARY_FILENAME'"
SOURCE_BINARY_FILE_PATH="${SCRIPT_DIR}/${APPLICATION_BINARY_FILENAME}"


# REMOTE_HOST_URL_CONFIG must be set in the configuration file.
if [[ -z "${REMOTE_HOST_URL_CONFIG:-}" ]]; then
  error_exit "REMOTE_HOST_URL_CONFIG is not defined in the configuration file ('$CONFIG_FILE_PATH'). This variable is mandatory."
fi
# Validate the format of REMOTE_HOST_URL_CONFIG
if ! [[ "$REMOTE_HOST_URL_CONFIG" =~ ^https?:// ]]; then
  error_exit "REMOTE_HOST_URL_CONFIG in '$CONFIG_FILE_PATH' ('$REMOTE_HOST_URL_CONFIG') must start with http:// or https://"
fi
info "Using REMOTE_HOST_URL_CONFIG: '$REMOTE_HOST_URL_CONFIG'"

# --- Derive other variables ---
# These variables use values from the config file (if set there and sourced),
# or script-defined defaults if not provided by the config.
# APP_NAME is the fixed internal variable for consistent system paths.

APP_USER=${USER_CONFIG:-${APP_NAME}_user}
APP_GROUP=${GROUP_CONFIG:-${APP_NAME}_group}
BASE_DIR="${BASE_DIR_CONFIG:-/opt/${APP_NAME}}"

ETC_DIR="/etc/${APP_NAME}"
SYSTEMD_DIR="/etc/systemd/system"

PYTHON_VENV_DIR_NAME="${PYTHON_VENV_DIR_NAME:-datamover_venv}"
PYTHON_VENV_PATH="${BASE_DIR}/${PYTHON_VENV_DIR_NAME}"

DATAMOVER_WHEEL_NAME="${DATAMOVER_WHEEL_NAME:-datamover-0.1.0-py3-none-any.whl}"
WHEEL_PATH="${SCRIPT_DIR}/${DATAMOVER_WHEEL_NAME}"

SOURCE_DATA_DIR="${BASE_DIR}/source"
CSV_DATA_DIR="${BASE_DIR}/csv"
# TARGET_BINARY_PATH is the fixed location where the binary will be installed.
# Systemd units will point to this fixed path.
TARGET_BINARY_PATH="${BASE_DIR}/bin/${APP_NAME}" # e.g., /opt/exportcliv2/bin/exportcliv2

SYSTEMD_TEMPLATES_SUBDIR="${SYSTEMD_TEMPLATES_SUBDIR:-systemd_units}"
TEMPLATES_DIR="${SCRIPT_DIR}/${SYSTEMD_TEMPLATES_SUBDIR}"

COMMON_CONFIGS_SUBDIR="${COMMON_CONFIGS_SUBDIR:-config_files}"
COMMON_CFG_DIR="${SCRIPT_DIR}/${COMMON_CONFIGS_SUBDIR}"

BITMOVER_LOG_DIR="${BITMOVER_LOG_DIR_CONFIG:-/var/log/${APP_NAME}/bitmover}"

REMOTE_HOST_URL="${REMOTE_HOST_URL_CONFIG}" # Value already validated
BASE_VARS_FILE="/etc/default/${APP_NAME}_base_vars"


# --- Pre-flight Checks (Fail Fast) ---
info "Performing pre-flight checks..."
# Check for the source application binary itself, using the name from config
if [[ ! -f "$SOURCE_BINARY_FILE_PATH" ]]; then
  error_exit "Application source binary '$APPLICATION_BINARY_FILENAME' not found at: '$SOURCE_BINARY_FILE_PATH'. Check APPLICATION_BINARY_FILENAME in '$CONFIG_FILE_PATH'."
fi
info "Application source binary '$APPLICATION_BINARY_FILENAME' found at '$SOURCE_BINARY_FILE_PATH'."

[[ -f "$WHEEL_PATH" ]] || error_exit "Application wheel '${DATAMOVER_WHEEL_NAME}' not found at: $WHEEL_PATH"
[[ -d "$TEMPLATES_DIR" ]] || error_exit "Systemd templates directory not found: $TEMPLATES_DIR (expected from SYSTEMD_TEMPLATES_SUBDIR='${SYSTEMD_TEMPLATES_SUBDIR}')"

shopt -s nullglob
mapfile -t systemd_template_files < <(find "$TEMPLATES_DIR" -maxdepth 1 -name "*.template" -print)
shopt -u nullglob
(( ${#systemd_template_files[@]} )) || error_exit "No .template files found in $TEMPLATES_DIR"
info "Found ${#systemd_template_files[@]} systemd template(s)."

declare -a required_commands=("getent" "groupadd" "useradd" "install" "sed" "systemctl" "python3" "find" "id")
for cmd in "${required_commands[@]}"; do
  command -v "$cmd" &>/dev/null || error_exit "Required command '$cmd' is not installed or not in PATH."
done
info "All required commands are available."

# --- Helper Functions ---
create_group_if_not_exists(){
  local group_name="$1"
  if getent group "$group_name" &>/dev/null; then
    info "Group '$group_name' already exists. Skipping creation."
  else
    info "Creating system group '$group_name'..."
    $DRY_RUN groupadd -r "$group_name" || error_exit "Failed to create group '$group_name'."
  fi
}

create_user_if_not_exists(){
  local username="$1"
  local primary_group="$2"
  local home_dir="$3"
  if getent passwd "$username" &>/dev/null; then
    info "User '$username' already exists. Skipping creation."
  else
    info "Creating system user '$username' (group: '$primary_group', home: '$home_dir')..."
    $DRY_RUN useradd -r -g "$primary_group" -d "$home_dir" -s /sbin/nologin "$username" \
      || error_exit "Failed to create user '$username'."
  fi
}

ensure_directory(){
  local dir_path="$1"
  local owner="$2"
  local group="$3"
  local perms="$4"
  info "Ensuring directory '$dir_path' (Owner: $owner, Group: $group, Perms: $perms)..."
  $DRY_RUN install -d -o "$owner" -g "$group" -m "$perms" "$dir_path" \
    || error_exit "Failed to create or set permissions for directory '$dir_path'."
}

install_file(){
  local src_file="$1"
  local dest_file="$2"
  local owner="$3"
  local group="$4"
  local perms="$5"
  info "Installing file '$src_file' to '$dest_file' (Owner: $owner, Group: $group, Perms: $perms)..."
  $DRY_RUN install -T -o "$owner" -g "$group" -m "$perms" "$src_file" "$dest_file" \
    || error_exit "Failed to install file '$src_file' to '$dest_file'."
}

setup_python_venv(){
  local venv_path="$1"
  local wheel_to_install="$2"
  local venv_owner="$3"
  local venv_group="$4"

  ensure_directory "$(dirname "$venv_path")" "$venv_owner" "$venv_group" "0755"

  local pip_executable="${venv_path}/bin/pip"
  if [[ -x "$pip_executable" ]]; then
    info "Python virtual environment already exists at '$venv_path'. Skipping creation."
  else
    info "Creating Python virtual environment at '$venv_path'..."
    $DRY_RUN python3 -m venv "$venv_path" \
      || error_exit "Failed to create Python venv. Ensure 'python3-venv' (or equivalent) is installed."
    info "Python venv created."
  fi

  info "Upgrading pip and installing wheel '$wheel_to_install' into '$venv_path'..."
  $DRY_RUN "$pip_executable" install --upgrade pip \
    || error_exit "Failed to upgrade pip in '$venv_path'."
  $DRY_RUN "$pip_executable" install "$wheel_to_install" \
    || error_exit "Failed to install wheel '$wheel_to_install' into '$venv_path'."
  info "Python setup complete for '$venv_path'."
}

deploy_systemd_units(){
  info "Deploying systemd units to '$SYSTEMD_DIR'..."
  ensure_directory "$SYSTEMD_DIR" "root" "root" "0755"

  local sed_replacements=(
    -e "s|{{APP_NAME}}|${APP_NAME}|g"
    -e "s|{{APP_USER}}|${APP_USER}|g"
    -e "s|{{APP_GROUP}}|${APP_GROUP}|g"
    -e "s|{{BASE_DIR}}|${BASE_DIR}|g"
    -e "s|{{ETC_DIR}}|${ETC_DIR}|g"
    -e "s|{{TARGET_BINARY_PATH}}|${TARGET_BINARY_PATH}|g"
    -e "s|{{SOURCE_DATA_DIR}}|${SOURCE_DATA_DIR}|g"
    -e "s|{{CSV_DATA_DIR}}|${CSV_DATA_DIR}|g"
    -e "s|{{PYTHON_VENV_PATH}}|${PYTHON_VENV_PATH}|g"
    -e "s|{{BITMOVER_CONFIG_FILE}}|${ETC_DIR}/config.ini|g"
    -e "s#{{REMOTE_HOST_URL}}#${REMOTE_HOST_URL}#g"
  )

  for template_file in "${systemd_template_files[@]}"; do
    local unit_name
    unit_name=$(basename "${template_file%.template}")
    local output_file="${SYSTEMD_DIR}/${unit_name}"
    info "  Processing template '$template_file' -> '$output_file'..."
    $DRY_RUN sed "${sed_replacements[@]}" "$template_file" > "$output_file" \
      || error_exit "Failed to process template '$template_file'."
    $DRY_RUN chmod 0644 "$output_file" \
      || error_exit "Failed to set permissions on '$output_file'."
  done

  info "Reloading systemd daemon..."
  $DRY_RUN systemctl daemon-reload \
    || warn "Failed to reload systemd daemon. Manual reload may be required."
  info "Systemd units deployed."
}

deploy_application_configs(){
  info "Deploying application configurations to '$ETC_DIR'..."
  ensure_directory "$ETC_DIR" "root" "root" "0755"

  shopt -s nullglob
  local common_config_files=("$COMMON_CFG_DIR"/*)
  shopt -u nullglob

  for src_cfg_file in "${common_config_files[@]}"; do
    if [[ -f "$src_cfg_file" && $(basename "$src_cfg_file") != "config.ini.template" ]]; then
      install_file "$src_cfg_file" "${ETC_DIR}/$(basename "$src_cfg_file")" \
                   "root" "$APP_GROUP" "0640"
    fi
  done

  local bitmover_template_path="${COMMON_CFG_DIR}/config.ini.template"
  local bitmover_config_path="${ETC_DIR}/config.ini"
  if [[ -f "$bitmover_template_path" ]]; then
    info "Deploying Bitmover config from template '$bitmover_template_path' to '$bitmover_config_path'..."
    ensure_directory "$BITMOVER_LOG_DIR" "$APP_USER" "$APP_GROUP" "0770"

    local sed_replacements=(
      -e "s|{{BASE_DIR}}|${BASE_DIR}|g"
      -e "s|{{BITMOVER_LOG_DIR}}|${BITMOVER_LOG_DIR}|g"
      -e "s#{{REMOTE_HOST_URL}}#${REMOTE_HOST_URL}#g"
    )
    $DRY_RUN sed "${sed_replacements[@]}" "$bitmover_template_path" > "$bitmover_config_path" \
      || error_exit "Failed to generate '$bitmover_config_path' from template."
    $DRY_RUN chmod 0640 "$bitmover_config_path"
    $DRY_RUN chown "$APP_USER:$APP_GROUP" "$bitmover_config_path"
    info "Bitmover config '$bitmover_config_path' deployed."
  else
    warn "Bitmover config template '$bitmover_template_path' not found. Skipping config.ini deployment."
  fi
  info "Application configurations deployed."
}

save_environment_variables_file(){
  info "Saving base environment variables to '$BASE_VARS_FILE'..."
  local script_name
  script_name=$(basename "$0")
  local content
  content=$(cat <<EOF
# Base environment variables for ${APP_NAME}
# Generated by ${script_name} on $(_ts)
export APP_NAME="${APP_NAME}"
export APP_USER="${APP_USER}"
export APP_GROUP="${APP_GROUP}"
export BASE_DIR="${BASE_DIR}"
export ETC_DIR="${ETC_DIR}"
export TARGET_BINARY_PATH="${TARGET_BINARY_PATH}" # This is the fixed runtime path
export SOURCE_DATA_DIR="${SOURCE_DATA_DIR}"
export CSV_DATA_DIR="${CSV_DATA_DIR}"
export PYTHON_VENV_PATH="${PYTHON_VENV_PATH}"
export BITMOVER_LOG_DIR="${BITMOVER_LOG_DIR}"
export REMOTE_HOST_URL="${REMOTE_HOST_URL}"
# Note: The actual source binary filename used for this install was: ${APPLICATION_BINARY_FILENAME:-Not Set or Error}
EOF
)
  $DRY_RUN printf "%s\n" "$content" > "$BASE_VARS_FILE" \
    || error_exit "Failed to write environment variables to '$BASE_VARS_FILE'."
  $DRY_RUN chmod 0644 "$BASE_VARS_FILE" \
    || error_exit "Failed to set permissions on '$BASE_VARS_FILE'."
  info "Base environment variables saved."
}

# ---- Main Installation Logic ----
main(){
  info "Starting installation of the '${APP_NAME}' application suite..."
  info "Application User: $APP_USER, Application Group: $APP_GROUP"
  info "Base Directory:   $BASE_DIR"
  [[ -n "$DRY_RUN" ]] && warn "DRY RUN MODE ENABLED: No changes will be made to the system."

  # 1. Create User and Group
  create_group_if_not_exists "$APP_GROUP"
  create_user_if_not_exists "$APP_USER" "$APP_GROUP" "$BASE_DIR"

  # 2. Create Core Application Directories
  ensure_directory "$ETC_DIR" "root" "root" "0755"
  ensure_directory "$BASE_DIR"              "$APP_USER" "$APP_GROUP" "0750"
  ensure_directory "${BASE_DIR}/bin"        "$APP_USER" "$APP_GROUP" "0750"
  ensure_directory "$SOURCE_DATA_DIR"       "$APP_USER" "$APP_GROUP" "0770"
  ensure_directory "$CSV_DATA_DIR"          "$APP_USER" "$APP_GROUP" "0770"
  ensure_directory "${BASE_DIR}/worker"     "$APP_USER" "$APP_GROUP" "0770"
  ensure_directory "${BASE_DIR}/uploaded"   "$APP_USER" "$APP_GROUP" "0770"
  ensure_directory "${BASE_DIR}/dead_letter" "$APP_USER" "$APP_GROUP" "0770"

  # 3. Install Application Binary
  # Source is $SOURCE_BINARY_FILE_PATH (e.g. .../exportcliv2-v1.2.3)
  # Destination is $TARGET_BINARY_PATH (e.g. /opt/exportcliv2/bin/exportcliv2)
  install_file "$SOURCE_BINARY_FILE_PATH" "$TARGET_BINARY_PATH" \
               "root" "$APP_GROUP" "0750"

  # 4. Setup Python Virtual Environment and Install Dependencies
  setup_python_venv "$PYTHON_VENV_PATH" "$WHEEL_PATH" "$APP_USER" "$APP_GROUP"

  # 5. Deploy Systemd Unit Files
  deploy_systemd_units

  # 6. Deploy Application Configuration Files
  deploy_application_configs

  # 7. Save Base Environment Variables
  save_environment_variables_file

  info "-----------------------------------------------------------------------"
  info "Installation of '${APP_NAME}' application suite complete!"
  info "Source binary used: '$APPLICATION_BINARY_FILENAME'"
  info "Installed to: '$TARGET_BINARY_PATH'"
  if [[ -n "$DRY_RUN" ]]; then
    warn "DRY RUN MODE was enabled. No actual changes were made."
  else
    info "Review systemd unit status and start/enable services as needed."
    info "Example for bitmover: systemctl enable bitmover.service && systemctl start bitmover.service"
    info "Use configure_instance.sh to set up and manage '${APP_NAME}' instances."
  fi
  info "-----------------------------------------------------------------------"
}

# --- Execute Main ---
main "$@"
