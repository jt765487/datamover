#!/usr/bin/env bash
# shellcheck disable=SC1090,SC2154 # SC1090 for source, SC2154 for sourced variables
set -euo pipefail
IFS=$'\n\t'

# -----------------------------------------------------------------------------
# Base Installer for exportcliv2 + bitmover
# Standardized argument parsing, logging, dry-run, error handling.
# v1.3.1: Improved error handling for group/user creation.
# v1.3.2: Added --operation-type flag handling for context-aware logging
#         and conditional display of restart advice.
# -----------------------------------------------------------------------------
VERSION_INSTALL_BASE="1.3.2" # Script version

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
SCRIPT_SUCCESSFUL=false
HELP_OR_VERSION_EXIT=false
FAIL_COUNT=0

readonly APP_NAME="exportcliv2"
CONFIG_FILE_NAME_ARG="install-app.conf"
OPERATION_TYPE_CONTEXT="" # Set by --operation-type from orchestrator

# --- Trap Handling (Standardized) ---
# shellcheck disable=SC2317
_cleanup_on_error_base() {
    local exit_code="$1"; local line_no="$2"; local command="$3"; echo;
    warn "--- BASE INSTALLER ERROR DETECTED ---"
    error_exit "Error on or near line ${line_no} in $(basename "${BASH_SOURCE[0]}"): command '${command}' returned exit code ${exit_code}." "${exit_code:-$EXIT_CODE_FATAL_ERROR}"
}
# shellcheck disable=SC2317
_cleanup_on_exit_base() {
    local exit_code=$?
    if [[ "$HELP_OR_VERSION_EXIT" == true ]]; then return; fi
    echo
    local script_name_for_log; script_name_for_log=$(basename "${BASH_SOURCE[0]}")
    local main_action_verb_for_log="Operation"
    if [[ "$OPERATION_TYPE_CONTEXT" == "install" ]]; then main_action_verb_for_log="Installation";
    elif [[ "$OPERATION_TYPE_CONTEXT" == "update" ]]; then main_action_verb_for_log="Update";
    fi

    if [[ "$exit_code" -eq "$EXIT_CODE_SUCCESS" && "$SCRIPT_SUCCESSFUL" == true ]]; then
        info "▶ Base ${main_action_verb_for_log} Script (${script_name_for_log}) finished successfully."
    elif [[ "$exit_code" -eq "$EXIT_CODE_PARTIAL_SUCCESS" || ("$exit_code" -eq "$EXIT_CODE_SUCCESS" && "$FAIL_COUNT" -gt 0 && "$SCRIPT_SUCCESSFUL" == true) ]]; then
        warn "▶ Base ${main_action_verb_for_log} Script (${script_name_for_log}) finished with $FAIL_COUNT non-fatal error(s). Review output."
    elif [[ "$exit_code" -ne "$EXIT_CODE_SUCCESS" ]]; then
        echo -e "${C_ERROR}$(_ts) [ERROR] ▶ Base ${main_action_verb_for_log} Script (${script_name_for_log}) failed. Review error messages above.${C_RESET}" >&2
    else
        warn "▶ Base ${main_action_verb_for_log} Script (${script_name_for_log}) finished. Status unclear (exit code 0, but not marked successful)."
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
    ((FAIL_COUNT++))
    return $ec
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
  -c, --config FILENAME   Configuration filename (default: ${CONFIG_FILE_NAME_ARG}).
                          Expected to be in the same directory as this script.
  --operation-type MODE   (Internal) Sets context if called by orchestrator.
                          MODE can be 'install' or 'update'. Affects logging.
  -n, --dry-run           Dry-run mode (print commands instead of executing).
  -v, --verbose           Verbose mode (enables debug messages and command tracing 'set -x').
  -h, --help              Show this help message and exit.
  --version               Show script version and exit.
EOF
  exit "${1:-$EXIT_CODE_SUCCESS}"
}

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
    --operation-type)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then error_exit "Option $1 requires a MODE ('install' or 'update')." "$EXIT_CODE_USAGE_ERROR"; fi
      if [[ "$2" != "install" && "$2" != "update" ]]; then error_exit "Invalid mode for $1: '$2'. Must be 'install' or 'update'." "$EXIT_CODE_USAGE_ERROR"; fi
      OPERATION_TYPE_CONTEXT="$2"; shift 2;;
    -n|--dry-run)
      DRY_RUN=true; shift;;
    -v|--verbose)
      VERBOSE_MODE=true; shift;;
    *)
      TEMP_ARGS+=("$1"); shift;;
  esac
done

if (( ${#TEMP_ARGS[@]} > 0 )); then
  error_exit "Unknown option or argument: ${TEMP_ARGS[0]}. Use --help for usage." "$EXIT_CODE_USAGE_ERROR"
fi

if [[ "$VERBOSE_MODE" == true ]]; then
  info "Verbose mode enabled (command tracing 'set -x' activated)."
  set -x
fi

if [[ "$(id -u)" -ne 0 ]]; then
  error_exit "This script must be run as root or with sudo." "$EXIT_CODE_PREREQUISITE_ERROR"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
debug "Script directory determined as: $SCRIPT_DIR"

CONFIG_FILE_PATH="${SCRIPT_DIR}/${CONFIG_FILE_NAME_ARG}"
debug "Attempting to load configuration from '$CONFIG_FILE_PATH'..."
if [[ -f "$CONFIG_FILE_PATH" ]]; then
  source "$CONFIG_FILE_PATH"
  debug "Configuration loaded successfully from '$CONFIG_FILE_PATH'."
else
  error_exit "Configuration file not found: '$CONFIG_FILE_PATH'." "$EXIT_CODE_CONFIG_ERROR"
fi

debug "Validating mandatory configuration variables from '$CONFIG_FILE_PATH'..."
: "${VERSIONED_APP_BINARY_FILENAME:?VERSIONED_APP_BINARY_FILENAME must be defined in $CONFIG_FILE_PATH}" "$EXIT_CODE_CONFIG_ERROR"
: "${VERSIONED_DATAMOVER_WHEEL_FILENAME:?VERSIONED_DATAMOVER_WHEEL_FILENAME must be defined in $CONFIG_FILE_PATH}" "$EXIT_CODE_CONFIG_ERROR"
: "${REMOTE_HOST_URL_CONFIG:?REMOTE_HOST_URL_CONFIG must be defined in $CONFIG_FILE_PATH}" "$EXIT_CODE_CONFIG_ERROR"
: "${EXPORT_TIMEOUT_CONFIG:?EXPORT_TIMEOUT_CONFIG must be defined in $CONFIG_FILE_PATH}" "$EXIT_CODE_CONFIG_ERROR"
: "${WHEELHOUSE_SUBDIR:?WHEELHOUSE_SUBDIR must be defined in $CONFIG_FILE_PATH for offline installs}"

if ! [[ "$REMOTE_HOST_URL_CONFIG" =~ ^https?:// ]]; then
  error_exit "REMOTE_HOST_URL_CONFIG ('$REMOTE_HOST_URL_CONFIG') must start with http:// or https://" "$EXIT_CODE_CONFIG_ERROR"
fi
if ! [[ "$EXPORT_TIMEOUT_CONFIG" =~ ^[0-9]+$ ]]; then
  error_exit "EXPORT_TIMEOUT_CONFIG ('$EXPORT_TIMEOUT_CONFIG') must be a non-negative integer." "$EXIT_CODE_CONFIG_ERROR"
fi
debug "Mandatory configuration variables validated."

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
readonly LOCAL_WHEELHOUSE_DIR="${SCRIPT_DIR}/${WHEELHOUSE_SUBDIR}"

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

create_group_if_not_exists() {
  local group_name="$1"
  if getent group "$group_name" &>/dev/null; then
    debug "Group '$group_name' already exists."
  else
    debug "Creating system group '$group_name'..."
    if ! run groupadd -r "$group_name"; then
        error_exit "CRITICAL FAILURE: Could not create system group '$group_name'. Check permissions and if 'groupadd' is functional." "$EXIT_CODE_FILE_ERROR"
    fi
    info "System group '$group_name' created successfully."
  fi
}

create_user_if_not_exists() {
  local username="$1"; local primary_group="$2"; local home_dir="$3"
  if getent passwd "$username" &>/dev/null; then
    debug "User '$username' already exists."
  else
    debug "Creating system user '$username' (group: '$primary_group', home: '$home_dir')..."
    if ! getent group "$primary_group" &>/dev/null; then
        warn "Primary group '$primary_group' for user '$username' does not appear to exist. User creation may fail or behave unexpectedly."
    fi
    if ! run useradd -r -g "$primary_group" -d "$home_dir" -s /sbin/nologin -c "${APP_NAME} service account" "$username"; then
        error_exit "CRITICAL FAILURE: Could not create system user '$username'. Check permissions, if 'useradd' is functional, and if group '$primary_group' exists." "$EXIT_CODE_FILE_ERROR"
    fi
    info "System user '$username' created successfully."
  fi
}

ensure_directory() {
  local dir_path="$1"; local owner="$2"; local group="$3"; local perms="$4"
  debug "Ensuring directory '$dir_path' (Owner: $owner, Group: $group, Perms: $perms)..."
  if ! run mkdir -p "$dir_path"; then error_exit "Failed to create dir '$dir_path'." "$EXIT_CODE_FILE_ERROR"; fi
  if ! run chown "$owner:$group" "$dir_path"; then error_exit "Failed to chown dir '$dir_path'." "$EXIT_CODE_FILE_ERROR"; fi
  if ! run chmod "$perms" "$dir_path"; then error_exit "Failed to chmod dir '$dir_path'." "$EXIT_CODE_FILE_ERROR"; fi
}

install_file_to_dest() {
  local src_file="$1"; local dest_file="$2"; local owner="$3"; local group="$4"; local perms="$5"
  debug "Installing file '$src_file' to '$dest_file' (Owner: $owner, Group: $group, Perms: $perms)..."
  if ! run install -T -o "$owner" -g "$group" -m "$perms" "$src_file" "$dest_file"; then
    error_exit "Failed to install file '$src_file' to '$dest_file'." "$EXIT_CODE_FILE_ERROR"
  fi
}

#setup_python_venv() {
#  local venv_path="$1"; local wheel_to_install="$2"; local venv_owner="$3"; local venv_group="$4"
#  ensure_directory "$(dirname "$venv_path")" "$venv_owner" "$venv_group" "0755"
#  local pip_executable="${venv_path}/bin/pip"
#  local pip_opts=()
#  if [[ "$VERBOSE_MODE" != true && "$DRY_RUN" != true ]]; then pip_opts+=("-q"); fi
#
#  if [[ -f "$pip_executable" && "$DRY_RUN" != true ]]; then
#    debug "Python venv likely exists at '$venv_path'."
#  elif [[ "$DRY_RUN" == true ]]; then
#    info "[DRY-RUN] Would check for Python venv at '$venv_path' and create if not found."
#  fi
#
#  if [[ "$DRY_RUN" == true || ! -f "$pip_executable" ]]; then
#      debug "Creating Python venv at '$venv_path' (or simulating for dry_run)..."
#      if ! run python3 -m venv "$venv_path"; then error_exit "Failed to create Python venv." "$EXIT_CODE_ACTION_FAILED"; fi
#  fi
#
#  debug "Upgrading pip and installing/upgrading wheel '$wheel_to_install' into '$venv_path'..."
#  if ! run "$pip_executable" install "${pip_opts[@]}" --upgrade pip; then error_exit "Failed to upgrade pip." "$EXIT_CODE_ACTION_FAILED"; fi
#  if ! run "$pip_executable" install "${pip_opts[@]}" --upgrade "$wheel_to_install"; then error_exit "Failed to install/upgrade wheel." "$EXIT_CODE_ACTION_FAILED"; fi
#
#  if [[ "$DRY_RUN" != true ]]; then
#    info "Setting venv ownership for '$venv_path' to '$venv_owner:$venv_group'..."
#    chown -R "$venv_owner:$venv_group" "$venv_path" || error_exit "Failed to set venv ownership on '$venv_path'." "$EXIT_CODE_FILE_ERROR"
#  else
#    info "[DRY-RUN] Would execute: chown -R \"$venv_owner:$venv_group\" \"$venv_path\""
#  fi
#  debug "Python setup complete for '$venv_path'."
#}

setup_python_venv() {
  local venv_path="$1"
  # This is the FILENAME of the main application wheel (e.g., datamover-vX.Y.Z-py3-none-any.whl)
  # It's assumed to be in $SCRIPT_DIR
  local app_wheel_filename="$2"
  local venv_owner="$3"
  local venv_group="$4"

  # Full path to the application wheel (expected in the same directory as the script)
  local app_wheel_source_path="${SCRIPT_DIR}/${app_wheel_filename}"

  ensure_directory "$(dirname "$venv_path")" "$venv_owner" "$venv_group" "0755"
  local pip_executable="${venv_path}/bin/pip"
  local python_executable="${venv_path}/bin/python" # For bootstrapping pip if needed

  local online_install_fully_succeeded=false
  local pip_online_opts=() # Options for online attempts (e.g., can include -q)
  local pip_offline_opts=("--no-cache-dir") # Options for offline attempts

  if [[ "$VERBOSE_MODE" != true && "$DRY_RUN" != true ]]; then
    pip_online_opts+=("-q")
    pip_offline_opts+=("-q")
  fi

  # --- Create venv (or ensure it exists) ---
  if [[ -f "$pip_executable" && "$DRY_RUN" != true ]]; then
    debug "Python venv with pip likely exists at '$venv_path'."
  elif [[ "$DRY_RUN" == true ]]; then
    info "[DRY-RUN] Would check for Python venv at '$venv_path' and create if not found."
  fi

  if [[ "$DRY_RUN" == true || ! -f "$pip_executable" ]]; then
      debug "Creating Python venv at '$venv_path' (or simulating for dry_run)..."
      if ! run python3 -m venv "$venv_path"; then
          error_exit "Failed to create Python venv at '$venv_path'." "$EXIT_CODE_ACTION_FAILED"
      fi
      if [[ "$DRY_RUN" != true && ! -x "$pip_executable" ]]; then
          # This case is unusual but means venv creation succeeded but pip is missing.
          # The fallback logic will handle bootstrapping pip from the wheelhouse.
          warn "pip executable not found in venv after creation. Online attempts may fail, relying on offline bootstrap."
      fi
  fi

  # --- Attempt 1: Online Installation ---
  if [[ "$DRY_RUN" != true ]]; then
    info "Attempting online installation/upgrade of Python packages..."

    # 1a. Upgrade pip (online)
    info "Attempting to upgrade pip from online sources..."
    if run "$pip_executable" install "${pip_online_opts[@]}" --upgrade pip; then
      info "pip upgraded successfully from online sources."

      # 1b. Install application wheel (online, dependencies from online)
      info "Attempting to install application wheel '$app_wheel_filename' (from '$app_wheel_source_path') with online dependencies..."
      if [[ ! -f "$app_wheel_source_path" ]]; then
         warn "Application wheel '$app_wheel_source_path' not found. Skipping online app install attempt."
      elif run "$pip_executable" install "${pip_online_opts[@]}" --upgrade "$app_wheel_source_path"; then
        info "Application wheel '$app_wheel_filename' and its dependencies installed successfully using online sources."
        online_install_fully_succeeded=true # Mark full success
      else
        warn "Online installation of application wheel '$app_wheel_filename' failed. Will attempt offline fallback."
      fi
    else
      warn "Online upgrade of pip failed. Will attempt offline fallback for all Python packages."
    fi
  elif [[ "$DRY_RUN" == true ]]; then
    info "[DRY-RUN] Simulating Python package installation..."
    info "[DRY-RUN] Would attempt online upgrade of pip."
    info "[DRY-RUN] Would attempt online install of '$app_wheel_filename' from '$app_wheel_source_path' (fetching dependencies online)."
    info "[DRY-RUN] If any online step were to fail, script would fall back to offline installation using wheelhouse: '$LOCAL_WHEELHOUSE_DIR'."
    # For dry run, we don't actually know if online would succeed, so we'll just proceed to describe offline steps too.
  fi

  # --- Attempt 2: Offline Fallback Installation ---
  if [[ ("$online_install_fully_succeeded" == false && "$DRY_RUN" != true) || "$DRY_RUN" == true ]]; then
    if [[ "$DRY_RUN" != true ]]; then # Only log actual fallback if not in dry_run mode already showing this path
        info "Falling back to offline installation using local application wheel and wheelhouse: '$LOCAL_WHEELHOUSE_DIR'."
    elif [[ "$DRY_RUN" == true ]]; then # For dry_run, explicitly state we are now describing offline part
        info "[DRY-RUN] Describing offline installation fallback:"
    fi

    if [[ ! -d "$LOCAL_WHEELHOUSE_DIR" ]]; then
        error_exit "Offline fallback required, but wheelhouse directory '$LOCAL_WHEELHOUSE_DIR' not found." "$EXIT_CODE_CONFIG_ERROR"
    fi

    # 2a. Ensure pip, setuptools, wheel are installed/upgraded from wheelhouse
    # This ensures we have a known good pip for the rest of the offline operations.
    # Find the latest versions of core wheels in the wheelhouse.
    local pip_wheel_in_wh; pip_wheel_in_wh=$(find "$LOCAL_WHEELHOUSE_DIR" -name "pip-*.whl" -type f | sort -V | tail -n 1)
    local setuptools_wheel_in_wh; setuptools_wheel_in_wh=$(find "$LOCAL_WHEELHOUSE_DIR" -name "setuptools-*.whl" -type f | sort -V | tail -n 1)
    local wheel_pkg_wheel_in_wh; wheel_pkg_wheel_in_wh=$(find "$LOCAL_WHEELHOUSE_DIR" -name "wheel-*.whl" -type f | sort -V | tail -n 1) # The 'wheel' package itself

    if [[ -z "$pip_wheel_in_wh" ]]; then
        error_exit "Core 'pip' wheel not found in '$LOCAL_WHEELHOUSE_DIR' for offline installation." "$EXIT_CODE_PREREQUISITE_ERROR"
    fi

    local core_wheels_to_install_offline=("$pip_wheel_in_wh")
    if [[ -n "$setuptools_wheel_in_wh" ]]; then core_wheels_to_install_offline+=("$setuptools_wheel_in_wh"); fi
    if [[ -n "$wheel_pkg_wheel_in_wh" ]]; then core_wheels_to_install_offline+=("$wheel_pkg_wheel_in_wh"); fi

    info "Ensuring/upgrading pip, setuptools, wheel from wheelhouse using: ${core_wheels_to_install_offline[*]}"
    # Prefer using the venv's python to install/bootstrap pip to avoid issues with a potentially broken existing pip.
    if ! run "$python_executable" -m pip install "${pip_offline_opts[@]}" --no-index --find-links "$LOCAL_WHEELHOUSE_DIR" --upgrade "${core_wheels_to_install_offline[@]}"; then
        error_exit "Failed to install/upgrade pip/setuptools/wheel from wheelhouse '$LOCAL_WHEELHOUSE_DIR' using '$python_executable -m pip'." "$EXIT_CODE_ACTION_FAILED"
    fi
    info "Core tools (pip, setuptools, wheel) installed/upgraded from wheelhouse."

    # 2b. Install application wheel (offline, dependencies from wheelhouse)
    info "Installing application wheel '$app_wheel_filename' (from '$app_wheel_source_path') with dependencies from wheelhouse '$LOCAL_WHEELHOUSE_DIR'..."
    if [[ ! -f "$app_wheel_source_path" ]]; then
       error_exit "Application wheel '$app_wheel_source_path' not found for offline installation." "$EXIT_CODE_CONFIG_ERROR"
    fi

    # The app wheel itself is specified by its direct path. --find-links is for its dependencies from the wheelhouse.
    if ! run "$pip_executable" install "${pip_offline_opts[@]}" --no-index --find-links "$LOCAL_WHEELHOUSE_DIR" --upgrade "$app_wheel_source_path"; then
      error_exit "Offline installation of application wheel '$app_wheel_filename' failed. Ensure all dependencies are in '$LOCAL_WHEELHOUSE_DIR'." "$EXIT_CODE_ACTION_FAILED"
    fi
    info "Application wheel '$app_wheel_filename' and its dependencies installed successfully using offline sources."
    if [[ "$DRY_RUN" != true ]]; then online_install_fully_succeeded=true; fi # Mark success if offline path completes
  fi

  # Final check: If not in dry_run and no method succeeded
  if [[ "$DRY_RUN" != true && "$online_install_fully_succeeded" == false ]]; then
    error_exit "All attempts to install Python packages (online and offline) failed." "$EXIT_CODE_ACTION_FAILED"
  fi

  # --- Set Ownership ---
  if [[ "$DRY_RUN" != true ]]; then
    info "Setting venv ownership for '$venv_path' to '$venv_owner:$venv_group'..."
    if ! chown -R "$venv_owner:$venv_group" "$venv_path"; then # Directly call, run() is for commands we want to log failure for / increment FAIL_COUNT
        error_exit "Failed to set venv ownership on '$venv_path'." "$EXIT_CODE_FILE_ERROR"
    fi
  else
    info "[DRY-RUN] Would execute: chown -R \"$venv_owner:$venv_group\" \"$venv_path\""
  fi
  debug "Python virtual environment setup complete for '$venv_path'."
}

deploy_wrapper_script() {
  debug "Deploying wrapper script '$INSTALLED_WRAPPER_SCRIPT_NAME' to '$INSTALLED_WRAPPER_SCRIPT_PATH'"
  local temp_wrapper_file
  if [[ "$DRY_RUN" == true ]]; then
      temp_wrapper_file="${SCRIPT_DIR}/${INSTALLED_WRAPPER_SCRIPT_NAME}.tmp.DRYRUN"
      info "[DRY-RUN] Would use temporary wrapper file: $temp_wrapper_file"
      touch "$temp_wrapper_file" || warn "[DRY-RUN] Failed to touch placeholder '$temp_wrapper_file'."
  else
      temp_wrapper_file=$(mktemp "/tmp/${INSTALLED_WRAPPER_SCRIPT_NAME}.tmp.XXXXXX")
  fi
  trap 'rm -f '"$temp_wrapper_file"' &>/dev/null' RETURN

  local sed_expr_app_name="s|{{APP_NAME}}|${APP_NAME}|g"
  local sed_expr_app_user="s|{{APP_USER}}|${APP_USER}|g"
  local sed_expr_base_dir="s|{{BASE_DIR}}|${BASE_DIR}|g"
  local sed_expr_etc_dir="s|{{ETC_DIR}}|${ETC_DIR}|g"
  local sed_expr_symlink_exec="s|{{SYMLINK_EXECUTABLE_PATH}}|${SYMLINK_EXECUTABLE_PATH}|g"
  local sed_expr_source_data="s|{{SOURCE_DATA_DIR}}|${SOURCE_DATA_DIR}|g"
  local sed_expr_csv_data="s|{{CSV_DATA_DIR}}|${CSV_DATA_DIR}|g"

  if [[ "$DRY_RUN" == true ]]; then
    info "[DRY-RUN] Would process wrapper template '$WRAPPER_TEMPLATE_PATH' into '$temp_wrapper_file' using sed with expressions."
    # Could log all expressions if needed for deep debug, but usually type of action is enough.
  else
    sed \
      -e "$sed_expr_app_name" \
      -e "$sed_expr_app_user" \
      -e "$sed_expr_base_dir" \
      -e "$sed_expr_etc_dir" \
      -e "$sed_expr_symlink_exec" \
      -e "$sed_expr_source_data" \
      -e "$sed_expr_csv_data" \
      "$WRAPPER_TEMPLATE_PATH" > "$temp_wrapper_file" \
      || error_exit "Failed to process wrapper script template '$WRAPPER_TEMPLATE_PATH'." "$EXIT_CODE_FILE_ERROR"
  fi

  install_file_to_dest "$temp_wrapper_file" "$INSTALLED_WRAPPER_SCRIPT_PATH" "$APP_USER" "$APP_GROUP" "0750"
  debug "Wrapper script deployed."
}

deploy_systemd_units() {
  debug "Deploying systemd units to '$SYSTEMD_DIR'"
  ensure_directory "$SYSTEMD_DIR" "root" "root" "0755"

  local sed_expressions_systemd=(
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
    -e "s#{{REMOTE_HOST_URL}}#${REMOTE_HOST_URL}#g"
  )

  for template_file in "${systemd_template_files[@]}"; do
    local unit_name; unit_name=$(basename "${template_file%.template}")
    local output_file="${SYSTEMD_DIR}/${unit_name}"
    local temp_unit_file # Variable for this loop iteration

    if [[ "$DRY_RUN" == true ]]; then
        temp_unit_file="${SCRIPT_DIR}/${unit_name}.tmp.DRYRUN"
        info "[DRY-RUN] Would use temporary systemd unit file: $temp_unit_file"
        touch "$temp_unit_file" || warn "[DRY-RUN] Failed to touch placeholder '$temp_unit_file'."
        info "[DRY-RUN] Would process systemd template '$template_file' into '$temp_unit_file'."
    else
        temp_unit_file=$(mktemp "/tmp/${unit_name}.tmp.XXXXXX")
    fi
    # This trap is for the CURRENT $temp_unit_file in this loop iteration.
    # It will be redefined in the next iteration for the next temp_unit_file.
    trap 'rm -f "$temp_unit_file" &>/dev/null' RETURN # <<< THIS LINE MUST USE $temp_unit_file

    debug "  Processing systemd template '$template_file' -> '$output_file' (via '$temp_unit_file')"

    if [[ "$DRY_RUN" != true ]]; then
      sed "${sed_expressions_systemd[@]}" "$template_file" > "$temp_unit_file" \
        || error_exit "Failed to process systemd template '$template_file'." "$EXIT_CODE_FILE_ERROR"
    fi

    install_file_to_dest "$temp_unit_file" "$output_file" "root" "root" "0644"
    # rm -f "$temp_unit_file" is handled by the trap set above for this iteration on RETURN
  done
  # Clear any lingering per-iteration trap by setting a general one or unsetting
  trap - RETURN # Or set to a general cleanup if needed outside the loop

  debug "Reloading systemd daemon..."
  if ! run systemctl daemon-reload; then error_exit "Failed to reload systemd daemon." "$EXIT_CODE_ACTION_FAILED"; fi
  debug "Systemd units deployed."
}

deploy_application_configs() {
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
    local temp_bitmover_cfg

    if [[ "$DRY_RUN" == true ]]; then
        temp_bitmover_cfg="${SCRIPT_DIR}/config.ini.tmp.DRYRUN"
        info "[DRY-RUN] Would use temporary bitmover config file: $temp_bitmover_cfg"
        touch "$temp_bitmover_cfg" || warn "[DRY-RUN] Failed to touch placeholder '$temp_bitmover_cfg'."
        info "[DRY-RUN] Would process bitmover template '$bitmover_template_path' into '$temp_bitmover_cfg'."
    else
        temp_bitmover_cfg=$(mktemp "/tmp/bitmover_cfg.tmp.XXXXXX")
    fi
    trap 'rm -f '"$temp_bitmover_cfg"' &>/dev/null' RETURN

    local sed_expr_base_dir_bm="s|{{BASE_DIR}}|${BASE_DIR}|g"
    local sed_expr_log_dir_bm="s|{{BITMOVER_LOG_DIR}}|${BITMOVER_LOG_DIR}|g"
    local sed_expr_remote_url_bm="s#{{REMOTE_HOST_URL}}#${REMOTE_HOST_URL}#g"

    if [[ "$DRY_RUN" != true ]]; then
      sed \
        -e "$sed_expr_base_dir_bm" \
        -e "$sed_expr_log_dir_bm" \
        -e "$sed_expr_remote_url_bm" \
        "$bitmover_template_path" > "$temp_bitmover_cfg" \
        || error_exit "Failed to generate '$BITMOVER_CONFIG_FILE' from template." "$EXIT_CODE_FILE_ERROR"
    fi

    install_file_to_dest "$temp_bitmover_cfg" "$BITMOVER_CONFIG_FILE" "$APP_USER" "$APP_GROUP" "0640"
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

  if [[ "$DRY_RUN" == true ]]; then
    info "[DRY-RUN] Would ensure directory $(dirname "$BASE_VARS_FILE")"
    info "[DRY-RUN] Would write content to '$BASE_VARS_FILE' (content omitted from log for brevity if long, see debug for full if needed)."
    debug "[DRY-RUN] Content for $BASE_VARS_FILE:\n$file_content"
    info "[DRY-RUN] Would chmod 0644 \"$BASE_VARS_FILE\""
  else
    ensure_directory "$(dirname "$BASE_VARS_FILE")" "root" "root" "0755"
    printf "%s\n" "$file_content" > "$BASE_VARS_FILE" || error_exit "Failed to write to '$BASE_VARS_FILE'" "$EXIT_CODE_FILE_ERROR"
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
    warn "Source management script '$source_manage_services_path' not found. Skipping its installation."
    return 0
  fi

  ensure_directory "$app_bin_dir" "root" "$APP_GROUP" "0755"
  install_file_to_dest "$source_manage_services_path" "$installed_manage_services_path" "root" "$APP_GROUP" "0755"

  debug "Attempting to create symlink: '${symlink_full_path}' -> '${installed_manage_services_path}'."
  if [[ "$DRY_RUN" == true ]]; then
    info "[DRY-RUN] Would ensure directory \"$symlink_standard_dir\" exists."
    info "[DRY-RUN] Would execute: ln -snf \"$installed_manage_services_path\" \"$symlink_full_path\""
  else
    mkdir -p "$symlink_standard_dir" || {
        warn "Failed to ensure standard symlink directory '$symlink_standard_dir' exists. Skipping symlink creation for '${symlink_command_name}'.";
        ((FAIL_COUNT++)) # Count as a non-fatal error
        return 0;
    }
    if ln -snf "$installed_manage_services_path" "$symlink_full_path"; then
      info "Symlink created: ${symlink_full_path} -> ${installed_manage_services_path}"
      info "Command '${symlink_command_name}' should be available in PATH."
    else
      warn "Failed to create symlink '$symlink_full_path'. Management script is available at '$installed_manage_services_path'."
      ((FAIL_COUNT++))
    fi
  fi
  debug "Management script and symlink processing complete."
}

# --- Main ---
main() {
  local main_action_verb="Installation/Update" # Default for standalone or unknown
  if [[ "$OPERATION_TYPE_CONTEXT" == "install" ]]; then
    main_action_verb="Installation"
  elif [[ "$OPERATION_TYPE_CONTEXT" == "update" ]]; then
    main_action_verb="Update"
  fi
  info "Starting ${main_action_verb,,} of '${APP_NAME}' application suite (v${VERSION_INSTALL_BASE})..." # Lowercase verb

  create_group_if_not_exists "$APP_GROUP"
  create_user_if_not_exists "$APP_USER" "$APP_GROUP" "$BASE_DIR"

  ensure_directory "/var/log/${APP_NAME}"     "root"      "root"       "0755"
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
    info "[DRY-RUN] Would change to directory \"${BASE_DIR}/bin\""
    info "[DRY-RUN] Would execute: ln -snf \"$VERSIONED_APP_BINARY_FILENAME\" \"$APP_NAME\""
    info "[DRY-RUN] Would change back to original directory"
  else
    current_dir_before_pushd=$(pwd)
    if ! pushd "${BASE_DIR}/bin" >/dev/null; then error_exit "Failed to change directory to ${BASE_DIR}/bin" "$EXIT_CODE_FILE_ERROR"; fi
    if ! ln -snf "$VERSIONED_APP_BINARY_FILENAME" "$APP_NAME"; then
        # popd before error_exit to restore directory
        popd >/dev/null || warn "Failed to popd from ${BASE_DIR}/bin after symlink failure." # Log popd failure but proceed to error_exit
        error_exit "Failed to create symlink for $APP_NAME in ${BASE_DIR}/bin" "$EXIT_CODE_FILE_ERROR"
    fi
    if ! popd >/dev/null; then error_exit "Failed to popd from ${BASE_DIR}/bin" "$EXIT_CODE_FILE_ERROR"; fi
    debug "Returned to directory: $(pwd) (was: $current_dir_before_pushd)"
  fi
  debug "Application binary symlink processed."

  deploy_wrapper_script
  setup_python_venv "$PYTHON_VENV_PATH" "$VERSIONED_DATAMOVER_WHEEL_FILENAME" "$APP_USER" "$APP_GROUP"
  deploy_systemd_units
  deploy_application_configs
  save_environment_variables_file
  install_management_script_and_symlink

  info "${main_action_verb^} of '${APP_NAME}' application suite processing complete." # Capitalize first letter of verb
  info "  Main binary: '$VERSIONED_APP_BINARY_FILENAME' -> '$DEST_VERSIONED_APP_BINARY_PATH' (linked via '$SYMLINK_EXECUTABLE_PATH')"
  info "  Wrapper script for instances: '$INSTALLED_WRAPPER_SCRIPT_PATH'"
  info "  Datamover wheel: '$VERSIONED_DATAMOVER_WHEEL_FILENAME' in '$PYTHON_VENV_PATH'"
  info "  Management script: '${BASE_DIR}/bin/manage_services.sh' (symlinked as 'exportcli-manage' in /usr/local/bin if symlink was successful)"
  info "  Default instance EXPORT_TIMEOUT (from $CONFIG_FILE_NAME_ARG): '${EXPORT_TIMEOUT_CONFIG}' seconds (stored in '$BASE_VARS_FILE')"

  if [[ "$DRY_RUN" != true ]]; then
    # Only show restart advice if not an 'install' operation called by orchestrator,
    # or if run standalone (OPERATION_TYPE_CONTEXT is empty).
    if [[ "$OPERATION_TYPE_CONTEXT" == "update" || -z "$OPERATION_TYPE_CONTEXT" ]]; then
      info "To apply changes, services might need to be (re)started."
      info "Use the 'exportcli-manage' command (if symlink creation was successful) or the full path:"
      info "  '${BASE_DIR}/bin/manage_services.sh'"
      info "For example:"
      info "  sudo exportcli-manage --restart                            # To restart the main bitmover service"
      info "  sudo exportcli-manage -i your_instance_name --restart      # To restart a specific application instance"
    elif [[ "$OPERATION_TYPE_CONTEXT" == "install" ]]; then
      debug "Restart advice suppressed: Orchestrator handles initial start/enable during an install."
    fi
  fi
  SCRIPT_SUCCESSFUL=true
}

# --- Execute Main ---
main "$@"