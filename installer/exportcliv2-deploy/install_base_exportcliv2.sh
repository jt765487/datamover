#!/usr/bin/env bash
# shellcheck disable=SC1090,SC2154 # SC1090 for source, SC2154 for sourced variables
set -euo pipefail
IFS=$'\n\t'

# -----------------------------------------------------------------------------
# Base Installer for exportcliv2 + bitmover
# Standardized argument parsing, logging, dry-run, error handling.
# -----------------------------------------------------------------------------
VERSION_INSTALL_BASE="1.3.0" # Script version

# --- Colorized Logging (Standardized) ---
CSI=$'\033['
C_RESET="${CSI}0m"
C_INFO="${CSI}32m"  # Green
C_WARN="${CSI}33m"  # Yellow
C_ERROR="${CSI}31m" # Red
C_DEBUG="${CSI}36m" # Cyan for debug messages

# --- Exit Codes (Standardized) ---
readonly EXIT_CODE_SUCCESS=0
readonly EXIT_CODE_FATAL_ERROR=1       # General fatal error
readonly EXIT_CODE_PARTIAL_SUCCESS=2   # Operation completed with non-fatal errors
readonly EXIT_CODE_USAGE_ERROR=3       # Command line usage error
readonly EXIT_CODE_CONFIG_ERROR=4      # Configuration file or value error
readonly EXIT_CODE_PREREQUISITE_ERROR=5 # Missing dependency or unmet prerequisite
readonly EXIT_CODE_FILE_ERROR=6        # File operation error (copy, chmod, etc.)
readonly EXIT_CODE_ACTION_FAILED=7     # A specific action (like service start) failed

# --- Logging Functions (Standardized) ---
_ts() { date -u +'%Y-%m-%dT%H:%M:%SZ'; }
_log_msg() {
    local log_level_name="$1"; local color_var_name="C_${log_level_name}"; local color_code="${!color_var_name}"; shift;
    echo -e "${color_code}$(_ts) [${log_level_name^^}] $*${C_RESET}" >&2;
}
info()       { _log_msg "INFO" "$*"; }
warn()       { _log_msg "WARN" "$*"; }
debug() { if [[ "${VERBOSE_MODE:-false}" == true ]]; then _log_msg "DEBUG" "$*"; fi; }
error_exit() { local message="$1"; local exit_code="${2:-$EXIT_CODE_FATAL_ERROR}"; _log_msg "ERROR" "$message"; exit "$exit_code"; }

# --- Globals (Standardized where applicable) ---
VERBOSE_MODE=false
DRY_RUN=false
SCRIPT_SUCCESSFUL=false # Set to true at the end of successful main execution
HELP_OR_VERSION_EXIT=false
FAIL_COUNT=0 # For non-fatal errors tracked by run helper

readonly APP_NAME="exportcliv2"
CONFIG_FILE_NAME_ARG="install-app.conf" # Default filename

# --- Trap Handling (Standardized) ---
# shellcheck disable=SC2317
_cleanup_on_error_base() {
    local exit_code="$1"
    local line_no="$2"
    local command="$3"
    echo
    warn "--- BASE INSTALLER ERROR DETECTED ---"
    error_exit "Error on or near line ${line_no} in $(basename "${BASH_SOURCE[0]}"): command '${command}' returned exit code ${exit_code}." "${exit_code:-$EXIT_CODE_FATAL_ERROR}"
}
# shellcheck disable=SC2317
_cleanup_on_exit_base() {
    local exit_code=$?
    if [[ "$HELP_OR_VERSION_EXIT" == true ]]; then return; fi
    echo
    if [[ "$exit_code" -eq "$EXIT_CODE_SUCCESS" && "$SCRIPT_SUCCESSFUL" == true ]]; then
        info "▶ Base Installation Script ($(basename "${BASH_SOURCE[0]}")) finished successfully."
    elif [[ "$exit_code" -eq "$EXIT_CODE_PARTIAL_SUCCESS" || ("$exit_code" -eq "$EXIT_CODE_SUCCESS" && "$FAIL_COUNT" -gt 0 && "$SCRIPT_SUCCESSFUL" == true) ]]; then
        warn "▶ Base Installation Script ($(basename "${BASH_SOURCE[0]}")) finished with $FAIL_COUNT non-fatal error(s). Review output."
    elif [[ "$exit_code" -ne "$EXIT_CODE_SUCCESS" ]]; then
        echo -e "${C_ERROR}$(_ts) [ERROR] ▶ Base Installation Script ($(basename "${BASH_SOURCE[0]}")) failed. Review error messages above.${C_RESET}" >&2
    else
        warn "▶ Base Installation Script ($(basename "${BASH_SOURCE[0]}")) finished. Status unclear (exit code 0, but not marked successful)."
    fi
}
trap '_cleanup_on_error_base "$?" "$LINENO" "$BASH_COMMAND"' ERR
trap '_cleanup_on_exit_base' EXIT
trap 'error_exit "Script $(basename "${BASH_SOURCE[0]}") interrupted by signal." "$EXIT_CODE_FATAL_ERROR"' INT TERM


# --- Standardized run Helper ---
run() {
  local cmd_array=("$@")
  local cmd_display
  printf -v cmd_display '%q ' "${cmd_array[@]}"
  debug "Executing: $cmd_display"
  if [[ "$DRY_RUN" == true ]]; then
    info "[DRY-RUN] Would execute: $cmd_display"
    return "$EXIT_CODE_SUCCESS"
  fi
  "${cmd_array[@]}"
  local ec=$?
  if [[ $ec -ne 0 ]]; then
    warn "Command failed with exit code $ec: $cmd_display"
    ((FAIL_COUNT++)) # Increment global fail count for non-fatal tracking
    return $ec      # Propagate specific error code
  fi
  return "$EXIT_CODE_SUCCESS"
}

# --- Argument Parsing (Standardized to while/case) ---
usage() {
  HELP_OR_VERSION_EXIT=true
  local script_name
  script_name=$(basename "$0")
  cat <<EOF
Usage: $script_name [OPTIONS]

Installs or updates the '${APP_NAME}' application suite components.
This script MUST be run as root or with sudo.
It expects to find resources (binaries, wheel, templates, manage_services.sh)
in its own directory or specified subdirectories.

Options:
  -c, --config FILENAME Configuration filename (default: ${CONFIG_FILE_NAME_ARG}).
                        Expected to be in the same directory as this script.
  -n, --dry-run         Dry-run mode (print commands instead of executing).
  -v, --verbose         Verbose mode (enables debug messages and command tracing 'set -x').
  -h, --help            Show this help message and exit.
  --version             Show script version and exit.
EOF
  exit "${1:-$EXIT_CODE_SUCCESS}" # Exit 0 for help/version
}

# Pre-scan for help/version
for arg_pre_scan in "$@"; do
  case "$arg_pre_scan" in
    --version) echo "$(basename "$0") v${VERSION_INSTALL_BASE}"; HELP_OR_VERSION_EXIT=true; exit "$EXIT_CODE_SUCCESS";;
    -h|--help) usage "$EXIT_CODE_SUCCESS";;
  esac
done

TEMP_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -c|--config)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then error_exit "Option $1 requires a FILENAME argument." "$EXIT_CODE_USAGE_ERROR"; fi
      CONFIG_FILE_NAME_ARG="$2"; shift 2;;
    -n|--dry-run)
      DRY_RUN=true; shift;;
    -v|--verbose)
      VERBOSE_MODE=true; shift;;
    *)
      TEMP_ARGS+=("$1"); shift;; # Collect unknown options
  esac
done

# Handle unknown options
if (( ${#TEMP_ARGS[@]} > 0 )); then
  error_exit "Unknown option or argument: ${TEMP_ARGS[0]}. Use --help for usage." "$EXIT_CODE_USAGE_ERROR"
fi

# Activate verbose tracing if enabled
if [[ "$VERBOSE_MODE" == true ]]; then
  info "Verbose mode enabled (command tracing 'set -x' activated)."
  set -x
fi

# --- Root Execution Check ---
if [[ "$(id -u)" -ne 0 ]]; then
  error_exit "This script must be run as root or with sudo." "$EXIT_CODE_PREREQUISITE_ERROR"
fi

# SCRIPT_DIR is the absolute path to the directory where this script resides.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
debug "Script directory determined as: $SCRIPT_DIR"

# --- Resolve and Load Configuration ---
CONFIG_FILE_PATH="${SCRIPT_DIR}/${CONFIG_FILE_NAME_ARG}"
debug "Attempting to load configuration from '$CONFIG_FILE_PATH' (resolved from filename '$CONFIG_FILE_NAME_ARG' in SCRIPT_DIR)."
if [[ -f "$CONFIG_FILE_PATH" ]]; then
  # shellcheck source=/dev/null
  source "$CONFIG_FILE_PATH"
  debug "Configuration loaded successfully from '$CONFIG_FILE_PATH'."
else
  error_exit "Configuration file not found at the expected location: '$CONFIG_FILE_PATH'. Ensure '$CONFIG_FILE_NAME_ARG' exists in '$SCRIPT_DIR'." "$EXIT_CODE_CONFIG_ERROR"
fi

# --- Validate Mandatory Configuration Variables ---
debug "Validating mandatory configuration variables from '$CONFIG_FILE_PATH'..."
: "${VERSIONED_APP_BINARY_FILENAME:?VERSIONED_APP_BINARY_FILENAME must be defined in $CONFIG_FILE_PATH}" "$EXIT_CODE_CONFIG_ERROR"
: "${VERSIONED_DATAMOVER_WHEEL_FILENAME:?VERSIONED_DATAMOVER_WHEEL_FILENAME must be defined in $CONFIG_FILE_PATH}" "$EXIT_CODE_CONFIG_ERROR"
: "${REMOTE_HOST_URL_CONFIG:?REMOTE_HOST_URL_CONFIG must be defined in $CONFIG_FILE_PATH}" "$EXIT_CODE_CONFIG_ERROR"
: "${EXPORT_TIMEOUT_CONFIG:?EXPORT_TIMEOUT_CONFIG must be defined in $CONFIG_FILE_PATH}" "$EXIT_CODE_CONFIG_ERROR"

if ! [[ "$REMOTE_HOST_URL_CONFIG" =~ ^https?:// ]]; then
  error_exit "REMOTE_HOST_URL_CONFIG ('$REMOTE_HOST_URL_CONFIG') in '$CONFIG_FILE_PATH' must start with http:// or https://" "$EXIT_CODE_CONFIG_ERROR"
fi
if ! [[ "$EXPORT_TIMEOUT_CONFIG" =~ ^[0-9]+$ ]]; then
  error_exit "EXPORT_TIMEOUT_CONFIG ('$EXPORT_TIMEOUT_CONFIG') in '$CONFIG_FILE_PATH' must be a non-negative integer." "$EXIT_CODE_CONFIG_ERROR"
fi
debug "Mandatory configuration variables validated."

# --- Derived Readonly Variables (No change in logic) ---
readonly APP_USER="${USER_CONFIG:-${APP_NAME}_user}"
readonly APP_GROUP="${GROUP_CONFIG:-${APP_NAME}_group}"
readonly BASE_DIR="${BASE_DIR_CONFIG:-/opt/${APP_NAME}}"
# ... (rest of derived variables are the same, ensure they use $APP_NAME, $SCRIPT_DIR, $BASE_DIR correctly)
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


# --- Pre-flight Checks (No change in logic, just uses error_exit) ---
debug "Running pre-flight checks..."
[[ -f "$SOURCE_VERSIONED_APP_BINARY_FILE_PATH" ]] || error_exit "App binary not found: $SOURCE_VERSIONED_APP_BINARY_FILE_PATH" "$EXIT_CODE_CONFIG_ERROR"
[[ -f "$SOURCE_VERSIONED_WHEEL_FILE_PATH" ]]   || error_exit "Datamover wheel not found: $SOURCE_VERSIONED_WHEEL_FILE_PATH" "$EXIT_CODE_CONFIG_ERROR"
[[ -f "$WRAPPER_TEMPLATE_PATH" ]]               || error_exit "Wrapper template not found: $WRAPPER_TEMPLATE_PATH" "$EXIT_CODE_CONFIG_ERROR"
[[ -d "$TEMPLATES_DIR" ]]                       || error_exit "Systemd templates dir not found: $TEMPLATES_DIR" "$EXIT_CODE_CONFIG_ERROR"
shopt -s nullglob
mapfile -t systemd_template_files < <(find "$TEMPLATES_DIR" -maxdepth 1 -name "*.template" -print)
shopt -u nullglob
(( ${#systemd_template_files[@]} > 0 )) || error_exit "No .template files found in $TEMPLATES_DIR" "$EXIT_CODE_CONFIG_ERROR"
debug "Found ${#systemd_template_files[@]} systemd template(s)."
required_commands=(getent groupadd useradd install sed systemctl python3 find id chown ln basename pushd popd date mkdir printf)
for cmd in "${required_commands[@]}"; do
  command -v "$cmd" &>/dev/null || error_exit "Required command '$cmd' not found." "$EXIT_CODE_PREREQUISITE_ERROR"
done
debug "Pre-flight checks passed."

# --- Helper Functions (Adapted to use new 'run' helper) ---
create_group_if_not_exists() {
  local group_name="$1"
  if getent group "$group_name" &>/dev/null; then
    debug "Group '$group_name' already exists."
  else
    debug "Creating system group '$group_name'..."
    run groupadd -r "$group_name" || error_exit "Failed to create group '$group_name'." "$EXIT_CODE_FILE_ERROR"
  fi
}

create_user_if_not_exists() {
  local username="$1"; local primary_group="$2"; local home_dir="$3"
  if getent passwd "$username" &>/dev/null; then
    debug "User '$username' already exists."
  else
    debug "Creating system user '$username' (group: '$primary_group', home: '$home_dir')..."
    run useradd -r -g "$primary_group" -d "$home_dir" -s /sbin/nologin "$username" \
      || error_exit "Failed to create user '$username'." "$EXIT_CODE_FILE_ERROR"
  fi
}

ensure_directory() {
  local dir_path="$1"; local owner="$2"; local group="$3"; local perms="$4"
  debug "Ensuring directory '$dir_path' (Owner: $owner, Group: $group, Perms: $perms)..."
  run mkdir -p "$dir_path" || error_exit "Failed to create dir '$dir_path'." "$EXIT_CODE_FILE_ERROR"
  run chown "$owner:$group" "$dir_path" || error_exit "Failed to chown dir '$dir_path'." "$EXIT_CODE_FILE_ERROR"
  run chmod "$perms" "$dir_path" || error_exit "Failed to chmod dir '$dir_path'." "$EXIT_CODE_FILE_ERROR"
}

install_file_to_dest() {
  local src_file="$1"; local dest_file="$2"; local owner="$3"; local group="$4"; local perms="$5"
  debug "Installing file '$src_file' to '$dest_file' (Owner: $owner, Group: $group, Perms: $perms)..."
  run install -T -o "$owner" -g "$group" -m "$perms" "$src_file" "$dest_file" \
    || error_exit "Failed to install file '$src_file' to '$dest_file'." "$EXIT_CODE_FILE_ERROR"
}

setup_python_venv() {
  local venv_path="$1"; local wheel_to_install="$2"; local venv_owner="$3"; local venv_group="$4"
  ensure_directory "$(dirname "$venv_path")" "$venv_owner" "$venv_group" "0755"
  local pip_executable="${venv_path}/bin/pip"
  local pip_opts=()
  # For pip, -q is added directly if not verbose and not dry_run, not via the run helper's dry run.
  if [[ "$VERBOSE_MODE" != true && "$DRY_RUN" != true ]]; then pip_opts+=("-q"); fi

  if [[ -f "$pip_executable" ]]; then
    debug "Python venv likely exists at '$venv_path'."
  else
    debug "Creating Python venv at '$venv_path'..."
    run python3 -m venv "$venv_path" || error_exit "Failed to create Python venv." "$EXIT_CODE_ACTION_FAILED"
  fi
  debug "Upgrading pip and installing/upgrading wheel '$wheel_to_install' into '$venv_path'..."
  run "$pip_executable" install "${pip_opts[@]}" --upgrade pip || error_exit "Failed to upgrade pip." "$EXIT_CODE_ACTION_FAILED"
  run "$pip_executable" install "${pip_opts[@]}" --upgrade "$wheel_to_install" || error_exit "Failed to install/upgrade wheel." "$EXIT_CODE_ACTION_FAILED"

  if [[ "$DRY_RUN" != true ]]; then # Direct chown, not via run, as run doesn't fit recursive chown well for display
    chown -R "$venv_owner:$venv_group" "$venv_path" || error_exit "Failed to set venv ownership." "$EXIT_CODE_FILE_ERROR"
  else
    info "[DRY-RUN] Would execute: chown -R \"$venv_owner:$venv_group\" \"$venv_path\""
  fi
  debug "Python setup complete for '$venv_path'."
}

deploy_wrapper_script() {
  debug "Deploying wrapper script '$INSTALLED_WRAPPER_SCRIPT_NAME' to '$INSTALLED_WRAPPER_SCRIPT_PATH'"
  local temp_wrapper_file
  temp_wrapper_file=$(mktemp "/tmp/${INSTALLED_WRAPPER_SCRIPT_NAME}.tmp.XXXXXX")
  # Defer cleanup of temp_wrapper_file using a local trap or by adding to a global list if many such files.
  # For a single file, direct rm after use is also fine.
  # trap 'rm -f "$temp_wrapper_file"' RETURN # Bash 3.2+ for local trap on function return

  # Build sed command parts
  local sed_expr_app_name="s|{{APP_NAME}}|${APP_NAME}|g"
  local sed_expr_app_user="s|{{APP_USER}}|${APP_USER}|g"
  # ... add all other sed expressions ...
  local sed_expr_base_dir="s|{{BASE_DIR}}|${BASE_DIR}|g"
  local sed_expr_etc_dir="s|{{ETC_DIR}}|${ETC_DIR}|g"
  local sed_expr_symlink_exec="s|{{SYMLINK_EXECUTABLE_PATH}}|${SYMLINK_EXECUTABLE_PATH}|g"
  local sed_expr_source_data="s|{{SOURCE_DATA_DIR}}|${SOURCE_DATA_DIR}|g"
  local sed_expr_csv_data="s|{{CSV_DATA_DIR}}|${CSV_DATA_DIR}|g"

  run sed \
    -e "$sed_expr_app_name" \
    -e "$sed_expr_app_user" \
    -e "$sed_expr_base_dir" \
    -e "$sed_expr_etc_dir" \
    -e "$sed_expr_symlink_exec" \
    -e "$sed_expr_source_data" \
    -e "$sed_expr_csv_data" \
    "$WRAPPER_TEMPLATE_PATH" > "$temp_wrapper_file" \
    || error_exit "Failed to process wrapper script template '$WRAPPER_TEMPLATE_PATH'." "$EXIT_CODE_FILE_ERROR"

  run install -T -o "${APP_USER}" -g "${APP_GROUP}" -m 0750 "$temp_wrapper_file" "$INSTALLED_WRAPPER_SCRIPT_PATH" \
    || error_exit "Failed to install processed wrapper script to '$INSTALLED_WRAPPER_SCRIPT_PATH'." "$EXIT_CODE_FILE_ERROR"
  rm -f "$temp_wrapper_file" # Clean up temp file

  debug "Wrapper script deployed."
}

deploy_systemd_units() {
  debug "Deploying systemd units to '$SYSTEMD_DIR'"
  ensure_directory "$SYSTEMD_DIR" "root" "root" "0755"
  # Build array of sed expressions
  local sed_expressions_systemd=(
    -e "s|{{APP_NAME}}|${APP_NAME}|g"
    -e "s|{{APP_USER}}|${APP_USER}|g"
    # ... add all other sed expressions from original script ...
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
    -e "s#{{REMOTE_HOST_URL}}#${REMOTE_HOST_URL}#g"
  )

  for template_file in "${systemd_template_files[@]}"; do
    local unit_name; unit_name=$(basename "${template_file%.template}")
    local output_file="${SYSTEMD_DIR}/${unit_name}"
    local temp_unit_file; temp_unit_file=$(mktemp "/tmp/${unit_name}.tmp.XXXXXX")
    debug "  Processing systemd template '$template_file' -> '$output_file' (via '$temp_unit_file')"

    run sed "${sed_expressions_systemd[@]}" "$template_file" > "$temp_unit_file" \
      || error_exit "Failed to process systemd template '$template_file'." "$EXIT_CODE_FILE_ERROR"

    run install -T -o root -g root -m 0644 "$temp_unit_file" "$output_file" \
      || error_exit "Failed to install processed systemd unit to '$output_file'." "$EXIT_CODE_FILE_ERROR"
    rm -f "$temp_unit_file"
  done
  debug "Reloading systemd daemon..."
  run systemctl daemon-reload || error_exit "Failed to reload systemd daemon." "$EXIT_CODE_ACTION_FAILED"
  debug "Systemd units deployed."
}

deploy_application_configs() {
  # ... (logic for finding common_configs_to_deploy is same) ...
  # ... (loop for install_file_to_dest is same) ...
  # For bitmover_template_path:
  debug "Deploying application configurations to '$ETC_DIR'"
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
    debug "No additional common config files found in '$COMMON_CFG_DIR' to deploy."
  fi

  local bitmover_template_path="$COMMON_CFG_DIR/config.ini.template"
  if [[ -f "$bitmover_template_path" ]]; then
    debug "Deploying Bitmover config from template '$bitmover_template_path' to '$BITMOVER_CONFIG_FILE'..."
    ensure_directory "$BITMOVER_LOG_DIR" "$APP_USER" "$APP_GROUP" "0770"
    local temp_bitmover_cfg; temp_bitmover_cfg=$(mktemp "/tmp/bitmover_cfg.tmp.XXXXXX")

    local sed_expr_base_dir_bm="s|{{BASE_DIR}}|${BASE_DIR}|g"
    local sed_expr_log_dir_bm="s|{{BITMOVER_LOG_DIR}}|${BITMOVER_LOG_DIR}|g"
    local sed_expr_remote_url_bm="s#{{REMOTE_HOST_URL}}#${REMOTE_HOST_URL}#g"

    run sed \
      -e "$sed_expr_base_dir_bm" \
      -e "$sed_expr_log_dir_bm" \
      -e "$sed_expr_remote_url_bm" \
      "$bitmover_template_path" > "$temp_bitmover_cfg" \
      || error_exit "Failed to generate '$BITMOVER_CONFIG_FILE' from template." "$EXIT_CODE_FILE_ERROR"

    run install -T -o "$APP_USER" -g "$APP_GROUP" -m 0640 "$temp_bitmover_cfg" "$BITMOVER_CONFIG_FILE" \
        || error_exit "Failed to install processed bitmover config to '$BITMOVER_CONFIG_FILE'." "$EXIT_CODE_FILE_ERROR"
    rm -f "$temp_bitmover_cfg"
    debug "Bitmover config deployed."
  else
    warn "Bitmover config template 'config.ini.template' not found. Skipping its deployment."
  fi
  debug "Application configurations deployment finished."
}

save_environment_variables_file() {
  debug "Saving base environment variables to '$BASE_VARS_FILE'"
  local file_content # ... (file_content generation same) ...
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

  if [[ "$DRY_RUN" == true ]]; then
    info "[DRY-RUN] Would ensure directory $(dirname "$BASE_VARS_FILE")"
    info "[DRY-RUN] Would write the following content to '$BASE_VARS_FILE':"
    echo "${file_content}" # Show content directly
    info "[DRY-RUN] Would chmod 0644 \"$BASE_VARS_FILE\""
  else
    ensure_directory "$(dirname "$BASE_VARS_FILE")" "root" "root" "0755" # ensure_directory uses 'run'
    printf "%s\n" "$file_content" > "$BASE_VARS_FILE" || error_exit "Failed to write to '$BASE_VARS_FILE'" "$EXIT_CODE_FILE_ERROR"
    # chmod is direct here as it's after a direct write, not through 'run' for the printf part
    chmod 0644 "$BASE_VARS_FILE" || error_exit "Failed to set permissions on '$BASE_VARS_FILE'" "$EXIT_CODE_FILE_ERROR"
  fi
  debug "Base environment variables file processed."
}

install_management_script_and_symlink() {
  local source_manage_services_script_name="manage_services.sh"
  local source_manage_services_path="${SCRIPT_DIR}/${source_manage_services_script_name}"
  local app_bin_dir="${BASE_DIR}/bin"
  local installed_manage_services_path="${app_bin_dir}/${source_manage_services_script_name}"
  local symlink_command_name="exportcli-manage"
  local symlink_standard_dir="/usr/local/bin"
  local symlink_full_path="${symlink_standard_dir}/${symlink_command_name}"

  debug "Starting installation of management script and symlink."
  if [[ ! -f "$source_manage_services_path" ]]; then
    warn "Source management script '$source_manage_services_path' not found. Skipping."
    return 0
  fi
  ensure_directory "$app_bin_dir" "root" "$APP_GROUP" "0755"
  install_file_to_dest "$source_manage_services_path" "$installed_manage_services_path" "root" "$APP_GROUP" "0755"
  debug "Attempting to create symlink: '${symlink_full_path}' -> '${installed_manage_services_path}'."
  if [[ "$DRY_RUN" == true ]]; then
    info "[DRY-RUN] Would mkdir -p \"$symlink_standard_dir\""
    info "[DRY-RUN] Would ln -snf \"$installed_manage_services_path\" \"$symlink_full_path\""
  else
    mkdir -p "$symlink_standard_dir" || { warn "Failed to ensure dir '$symlink_standard_dir'. Skipping symlink."; return 0; }
    if ln -snf "$installed_manage_services_path" "$symlink_full_path"; then
      info "Symlink created: ${symlink_full_path} -> ${installed_manage_services_path}"
      info "Command '${symlink_command_name}' should be available."
    else
      warn "Failed to create symlink '$symlink_full_path'. Available at '$installed_manage_services_path'."
    fi
  fi
  debug "Management script and symlink processed."
}

# --- Main ---
main() {
  info "Starting installation/update of '${APP_NAME}' application suite (v${VERSION_INSTALL_BASE})..."
  # DRY_RUN/VERBOSE_MODE info messages handled by argument parsing section

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

  debug "Creating/updating symlink '$SYMLINK_EXECUTABLE_PATH' -> '$VERSIONED_APP_BINARY_FILENAME'"
  if [[ "$DRY_RUN" == true ]]; then
    info "[DRY-RUN] Would pushd to \"${BASE_DIR}/bin\""
    info "[DRY-RUN] Would ln -snf \"$VERSIONED_APP_BINARY_FILENAME\" \"$APP_NAME\""
    info "[DRY-RUN] Would popd"
  else
    pushd "${BASE_DIR}/bin" >/dev/null || error_exit "Failed to pushd to ${BASE_DIR}/bin" "$EXIT_CODE_FILE_ERROR"
    ln -snf "$VERSIONED_APP_BINARY_FILENAME" "$APP_NAME" || error_exit "Failed to create symlink for $APP_NAME" "$EXIT_CODE_FILE_ERROR"
    popd >/dev/null || error_exit "Failed to popd from ${BASE_DIR}/bin" "$EXIT_CODE_FILE_ERROR"
  fi
  debug "Symlink processed."

  deploy_wrapper_script
  setup_python_venv "$PYTHON_VENV_PATH" "$SOURCE_VERSIONED_WHEEL_FILE_PATH" "$APP_USER" "$APP_GROUP"
  deploy_systemd_units
  deploy_application_configs
  save_environment_variables_file
  install_management_script_and_symlink

  info "Installation/update of '${APP_NAME}' application suite processing complete."
  info "  Main binary: '$VERSIONED_APP_BINARY_FILENAME' -> '$DEST_VERSIONED_APP_BINARY_PATH' (linked via '$SYMLINK_EXECUTABLE_PATH')"
  info "  Wrapper script for instances: '$INSTALLED_WRAPPER_SCRIPT_PATH'"
  info "  Datamover wheel: '$VERSIONED_DATAMOVER_WHEEL_FILENAME' in '$PYTHON_VENV_PATH'"
  info "  Management script: '${BASE_DIR}/bin/manage_services.sh' (symlinked as 'exportcli-manage' in /usr/local/bin if successful)"
  info "  Default instance EXPORT_TIMEOUT (from $CONFIG_FILE_NAME_ARG): '${EXPORT_TIMEOUT_CONFIG}' seconds (stored in '$BASE_VARS_FILE')"

  if [[ "$DRY_RUN" != true ]]; then # Corrected DRY_RUN check
    info "To apply changes, services might need to be (re)started if not handled by an orchestrator."
    info "Use the 'exportcli-manage' command (if symlink creation was successful) or '${BASE_DIR}/bin/manage_services.sh'."
    info "For example:"
    info "  sudo exportcli-manage --restart                            # To restart the main bitmover service"
    info "  sudo exportcli-manage -i your_instance_name --restart      # To restart a specific application instance"
    info "Alternatively, use the full path:"
    info "  sudo ${BASE_DIR}/bin/manage_services.sh --restart"

  fi
  # No "DRY RUN MODE was enabled" message here, as it's part of the initial info if set.
  SCRIPT_SUCCESSFUL=true # Mark as successful at the end of main operations
}

# --- Execute Main ---
main "$@"
# Final exit code determined by SCRIPT_SUCCESSFUL and FAIL_COUNT handled by EXIT trap's call to _final_summary_message