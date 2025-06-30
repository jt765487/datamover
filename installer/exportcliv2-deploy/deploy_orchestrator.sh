#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# -----------------------------------------------------------------------------
# v2.4.8 Deployment Orchestrator
# - Removed --new-binary and --new-wheel options (surgical update).
#   Use 'install_patch.sh' to prepare a bundle with patches first.
# - --update mode now always performs a full bundle update based on the
#   install-app.conf in the source directory.
# - Removed -i|--instances command-line option. Instances for install are
#   now always taken from DEFAULT_INSTANCES_CONFIG in install-app.conf.
# -----------------------------------------------------------------------------
VERSION="2.4.8" # Simplified --update, removed surgical patch options

# --- Colorized Logging & Exit Codes ---
CSI=$'\033['
C_RESET="${CSI}0m"
C_INFO="${CSI}32m"  # Green
C_WARN="${CSI}33m"  # Yellow
C_ERROR="${CSI}31m" # Red
C_DEBUG="${CSI}36m" # Cyan for debug messages

readonly EXIT_CODE_SUCCESS=0
readonly EXIT_CODE_FATAL_ERROR=1
readonly EXIT_CODE_PARTIAL_SUCCESS=2
readonly EXIT_CODE_USAGE_ERROR=3
readonly EXIT_CODE_CONFIG_ERROR=4
readonly EXIT_CODE_PREREQUISITE_ERROR=5
readonly EXIT_CODE_FILE_ERROR=6

# --- Logging ---
_ts() { date -u +'%Y-%m-%dT%H:%M:%SZ'; }
_log_msg() {
    local log_level_name="$1"; local color_var_name="C_${log_level_name}"; local color_code="${!color_var_name}"; shift;
    echo -e "${color_code}$(_ts) [${log_level_name^^}] $*${C_RESET}" >&2;
}
info()       { _log_msg "INFO" "$*"; }
warn()       { _log_msg "WARN" "$*"; }
debug() { if [[ "${VERBOSE_MODE:-false}" == true ]]; then _log_msg "DEBUG" "$*"; fi; }
error_exit() { local message="$1"; local exit_code="${2:-$EXIT_CODE_FATAL_ERROR}"; _log_msg "ERROR" "$message"; exit "$exit_code"; }

# --- Configuration & Globals ---
readonly DEPLOY_SUBDIR_NAME="exportcliv2-deploy"
SOURCE_DIR="." # Default source directory
BASE_CONFIG_FILENAME="install-app.conf" # Default config file name
EFFECTIVE_DEFAULT_INSTANCES_ARRAY=() # Will be populated from config
PARSED_INSTANCE_NAMES=() # Will be populated from EFFECTIVE_DEFAULT_INSTANCES_ARRAY
DRY_RUN=false
VERBOSE_MODE=false
OPERATION_MODE=""
USE_FORCE_FLAG=false

# Removed globals related to surgical updates:
# NEW_BINARY_PATH_ARG, NEW_WHEEL_PATH_ARG, TEMP_CONFIG_FOR_UPDATE,
# STAGED_NEW_BINARY_FILENAME, STAGED_NEW_WHEEL_FILENAME,
# ABSOLUTE_TEMP_CONFIG_FOR_UPDATE, ABSOLUTE_STAGED_NEW_BINARY_PATH, ABSOLUTE_STAGED_NEW_WHEEL_PATH

FAIL_COUNT=0
SCRIPT_SUCCESSFUL=false
USER_ABORTED=false
SCRIPT_RUNNING_LOCK=false
HELP_OR_VERSION_EXIT=false
LIST_DEFAULTS_REQUESTED=false

SCRIPTS_TO_CHECK=(
  "${DEPLOY_SUBDIR_NAME}/install_base_exportcliv2.sh"
  "${DEPLOY_SUBDIR_NAME}/configure_instance.sh"
  "${DEPLOY_SUBDIR_NAME}/manage_services.sh"
)
LOCKFILE_DIR="/tmp"
LOCKFILE="${LOCKFILE_DIR}/$(basename "$0" ".sh").lock"
MAIN_PUSHED_DIR=false
SOURCE_DIR_ABS_RESOLVED="" # Will hold absolute path to source_dir

# --- Dependency checks ---
dependency_check() {
  local cmds_to_check=(flock date chmod dirname basename readlink realpath mktemp cp sed touch) # mktemp might not be needed if no temp files
  debug "Checking for core orchestrator commands: ${cmds_to_check[*]}"
  for cmd_to_check in "${cmds_to_check[@]}"; do
    if ! command -v "$cmd_to_check" &>/dev/null; then
      error_exit "Required command '$cmd_to_check' not found in PATH." "$EXIT_CODE_PREREQUISITE_ERROR"
    fi
  done
  debug "Core orchestrator commands found."
}

# --- Locking with flock ---
acquire_lock() {
  debug "Attempting to acquire execution lock: $LOCKFILE"
  mkdir -p "$LOCKFILE_DIR" || error_exit "Failed to create lock directory $LOCKFILE_DIR" "$EXIT_CODE_FILE_ERROR"
  exec 200>"$LOCKFILE"
  if ! flock -n 200; then
    local locker_pid
    locker_pid=$(head -n 1 "$LOCKFILE" 2>/dev/null || echo "unknown PID")
    error_exit "Another instance is running (lockfile: ${LOCKFILE}, reported locker PID: ${locker_pid})." "$EXIT_CODE_FATAL_ERROR"
  fi
  echo "$$" >&200
  SCRIPT_RUNNING_LOCK=true
  debug "Execution lock acquired (PID: $$)."
  trap _master_exit_trap EXIT
}

# --- Master Exit Trap ---
_master_exit_trap() {
    local final_exit_code=$?
    if [[ "$MAIN_PUSHED_DIR" == true ]]; then
        if popd >/dev/null 2>&1; then
            debug "Trap: Returned from source directory. Original PWD: $(pwd)"
        else
            warn "Trap: Failed to popd from source directory. Current PWD: $(pwd)"
        fi
        MAIN_PUSHED_DIR=false
    fi

    # Removed cleanup for temporary config and staged surgical patch files

    if [[ "$SCRIPT_RUNNING_LOCK" == true ]]; then
        if rm -f "$LOCKFILE"; then
          debug "Trap: Execution lock released: $LOCKFILE"
        else
          warn "Trap: Failed to remove lockfile: $LOCKFILE. Manual cleanup may be needed."
        fi
        SCRIPT_RUNNING_LOCK=false
    fi
    if [[ "$HELP_OR_VERSION_EXIT" != true ]] ; then
      _final_summary_message "$final_exit_code"
    fi
}

# --- _final_summary_message ---
_final_summary_message() {
    local exit_code="$1"
    if [[ "$USER_ABORTED" == true ]]; then
        echo; info "▶ Orchestrator aborted by user."
        return
    fi
    echo
    if [[ "$exit_code" -eq "$EXIT_CODE_SUCCESS" && "$SCRIPT_SUCCESSFUL" == true && "$FAIL_COUNT" -eq 0 ]]; then
        info "▶ Orchestrator finished successfully."
    elif [[ "$exit_code" -eq "$EXIT_CODE_PARTIAL_SUCCESS" || ("$FAIL_COUNT" -gt 0 && "$SCRIPT_SUCCESSFUL" == true) ]]; then
        warn "▶ Orchestrator finished with $FAIL_COUNT non-fatal error(s). Review output."
    elif [[ "$exit_code" -ne "$EXIT_CODE_SUCCESS" ]]; then
        echo -e "${C_ERROR}$(_ts) [ERROR] ▶ Orchestrator FAILED. Review error messages above.${C_RESET}" >&2
    else
        warn "▶ Orchestrator finished. Status unclear (exit code $exit_code, SCRIPT_SUCCESSFUL=$SCRIPT_SUCCESSFUL, FAIL_COUNT=$FAIL_COUNT, USER_ABORTED=$USER_ABORTED). Review output."
    fi
}

# --- ERR Trap ---
cleanup_on_error() {
    local exit_code="$1"; local line_no="$2"; local failed_command="$3"; echo;
    if [[ ! "$failed_command" =~ error_exit ]]; then
        warn "-------------------- ORCHESTRATOR UNHANDLED ERROR DETECTED --------------------"
        local error_message_detail="Error on or near line ${line_no}: command '${failed_command}' returned exit code ${exit_code}."
        local hint=$'\n'"Hint: An unexpected error occurred. Check script logic or dependencies."
        _log_msg "ERROR" "${error_message_detail}${hint}"
    fi
    exit "${exit_code:-$EXIT_CODE_FATAL_ERROR}"
}
trap 'cleanup_on_error "$?" "$LINENO" "$BASH_COMMAND"' ERR

# --- Helper (run) ---
run() {
  local cmd_array=("$@"); local cmd_display; printf -v cmd_display '%q ' "${cmd_array[@]}";
  debug "Executing: $cmd_display"
  if [[ "$DRY_RUN" == true ]]; then info "[DRY-RUN] Would execute: $cmd_display"; return "$EXIT_CODE_SUCCESS"; fi
  "${cmd_array[@]}"; local ec=$?;
  if [[ $ec -ne 0 ]]; then _log_msg "WARN" "Command failed with exit code $ec: $cmd_display"; ((FAIL_COUNT++)); return $ec; fi
  return "$EXIT_CODE_SUCCESS"
}

# Removed _stage_component helper function

# --- Usage ---
usage() {
  local exit_code="${1:-$EXIT_CODE_USAGE_ERROR}"
  if [[ "$exit_code" -eq "$EXIT_CODE_SUCCESS" ]]; then HELP_OR_VERSION_EXIT=true; fi
  local script_basename; script_basename=$(basename "$0")
  local current_dir_display; current_dir_display=$(pwd)

  cat <<EOF
Usage: $script_basename [OPTIONS] --install|--update

Description:
  Orchestrates the installation or update of the ExportCLIv2 suite.
  This script is typically run from the root of an unpacked suite bundle.
  Service management is handled by '${DEPLOY_SUBDIR_NAME}/manage_services.sh'.

Modes (one is required):
  --install                 Performs a fresh installation.
                            Instances to install are taken from 'DEFAULT_INSTANCES_CONFIG'
                            in '${BASE_CONFIG_FILENAME}', which is mandatory for this mode.
                            Use '--force' to overwrite existing instance configurations or to
                            auto-confirm in non-interactive (non-TTY) environments.
  --update                  Updates core application components using the current bundle.
                            The components specified in './${DEPLOY_SUBDIR_NAME}/${BASE_CONFIG_FILENAME}'
                            will be deployed. To apply specific patches (new binary/wheel)
                            to a bundle before updating, use the 'install_patch.sh' script first.
                            Use '--force' to auto-confirm in non-interactive (non-TTY) environments.
                            NOTE: After an update, services must be restarted manually using 'exportcli-manage'.

General Options:
  -s, --source-dir DIR      Path to the unpacked source tree (bundle root). Default: '$current_dir_display'.
  -c, --config FILE         Base install config filename (in 'source-dir/${DEPLOY_SUBDIR_NAME}/').
                            Default: '${BASE_CONFIG_FILENAME}'.
                            This file also defines 'DEFAULT_INSTANCES_CONFIG'.
  --force                   Used with --install to overwrite existing instance configurations.
                            For all modes, if running in a non-interactive (non-TTY) environment,
                            this flag assumes 'yes' to the main confirmation prompt.
  -n, --dry-run             Show commands and simulate file operations without actual changes.
  -v, --verbose             Enable verbose shell tracing (set -x) and detailed debug messages.
  --list-default-instances  Show default instance names from the effective config file and exit.
  -h, --help                Show this help message and exit.
  --version                 Show script version and exit.

EXAMPLES:
  # Fresh install using default instances from install-app.conf:
  cd /path/to/exportcliv2-suite-vX.Y.Z/
  sudo ./$script_basename --install

  # Update using components from the current bundle:
  cd /path/to/exportcliv2-suite-vX.Y.Z/ # (This bundle might have been patched by install_patch.sh)
  sudo ./$script_basename --update
  # Then manually restart services as needed.

  # List default instances from config file in current source dir:
  ./$script_basename --list-default-instances

Exit codes: (0:Success, 1:Fatal, 2:Partial, 3:Usage, 4:Config, 5:Prereq, 6:FileOp)
EOF
  exit "$exit_code"
}

# --- Argument Parsing ---
for arg_pre_scan in "$@"; do
  case "$arg_pre_scan" in
    --version) echo "$(basename "$0") v$VERSION"; HELP_OR_VERSION_EXIT=true; exit "$EXIT_CODE_SUCCESS";;
    -h|--help) usage "$EXIT_CODE_SUCCESS";;
  esac
done

TEMP_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --install) OPERATION_MODE="install"; shift ;;
    --update) OPERATION_MODE="update"; shift ;;
    -s|--source-dir) if [[ -z "${2:-}" ]]; then error_exit "$1 requires an argument." $EXIT_CODE_USAGE_ERROR; fi; SOURCE_DIR="$2"; shift 2 ;;
    -c|--config) if [[ -z "${2:-}" ]]; then error_exit "$1 requires an argument." $EXIT_CODE_USAGE_ERROR; fi; BASE_CONFIG_FILENAME="$2"; shift 2 ;;
    # Removed --new-binary and --new-wheel cases
    --force) USE_FORCE_FLAG=true; shift ;;
    -n|--dry-run) DRY_RUN=true; shift ;;
    -v|--verbose) VERBOSE_MODE=true; shift ;;
    --list-default-instances) LIST_DEFAULTS_REQUESTED=true; shift;;
    *) TEMP_ARGS+=("$1"); shift ;;
  esac
done

if (( ${#TEMP_ARGS[@]} > 0 )); then error_exit "Unknown option specified: ${TEMP_ARGS[0]}" $EXIT_CODE_USAGE_ERROR; fi

# --- Resolve Paths and Source Configuration ---
SOURCE_DIR_ABS_RESOLVED="$(realpath -m "$SOURCE_DIR")" || error_exit "Failed to resolve source directory path: '$SOURCE_DIR'" "$EXIT_CODE_FILE_ERROR"
if [[ ! -d "$SOURCE_DIR_ABS_RESOLVED" ]]; then error_exit "Source directory not found: '$SOURCE_DIR_ABS_RESOLVED' (from '$SOURCE_DIR')." "$EXIT_CODE_FILE_ERROR"; fi
INSTALL_APP_CONF_FULL_PATH="${SOURCE_DIR_ABS_RESOLVED}/${DEPLOY_SUBDIR_NAME}/${BASE_CONFIG_FILENAME}"

if [[ ! -f "$INSTALL_APP_CONF_FULL_PATH" ]]; then
    error_exit "Base configuration file '$BASE_CONFIG_FILENAME' not found at '$INSTALL_APP_CONF_FULL_PATH'." "$EXIT_CODE_CONFIG_ERROR"
fi

debug "Sourcing application configuration from: $INSTALL_APP_CONF_FULL_PATH"
unset DEFAULT_INSTANCES_CONFIG
# shellcheck source=/dev/null
source "$INSTALL_APP_CONF_FULL_PATH" || error_exit "Failed to source configuration file: '$INSTALL_APP_CONF_FULL_PATH'." "$EXIT_CODE_CONFIG_ERROR"

if [[ -n "${DEFAULT_INSTANCES_CONFIG:-}" ]]; then
    IFS=' ' read -r -a EFFECTIVE_DEFAULT_INSTANCES_ARRAY <<< "$DEFAULT_INSTANCES_CONFIG"
    for inst_name in "${EFFECTIVE_DEFAULT_INSTANCES_ARRAY[@]}"; do
        if ! [[ "$inst_name" =~ ^[A-Za-z0-9._-]+$ ]]; then
            error_exit "Invalid default instance name format in DEFAULT_INSTANCES_CONFIG ('$inst_name') from '$INSTALL_APP_CONF_FULL_PATH'." "$EXIT_CODE_CONFIG_ERROR"
        fi
    done
fi

if [[ "$LIST_DEFAULTS_REQUESTED" == true ]]; then
  echo "Default instances configured in '${INSTALL_APP_CONF_FULL_PATH}' (via DEFAULT_INSTANCES_CONFIG):"
  if ((${#EFFECTIVE_DEFAULT_INSTANCES_ARRAY[@]} > 0)); then
    echo "  $(IFS=' '; echo "${EFFECTIVE_DEFAULT_INSTANCES_ARRAY[*]}")"
  else
    echo "  (None specified or list is empty)"
  fi
  HELP_OR_VERSION_EXIT=true; exit "$EXIT_CODE_SUCCESS"
fi

if [[ -z "$OPERATION_MODE" ]]; then error_exit "Operation mode --install or --update is required." $EXIT_CODE_USAGE_ERROR; fi
info "Operation Mode: $OPERATION_MODE"
SOURCE_DIR="$SOURCE_DIR_ABS_RESOLVED" # Use absolute path henceforth

# Removed further argument validation related to --new-binary/--new-wheel

if [[ "$VERBOSE_MODE" == true ]]; then info "Verbose mode enabled."; set -x; fi

if [[ "$OPERATION_MODE" == "install" ]]; then
    if ((${#EFFECTIVE_DEFAULT_INSTANCES_ARRAY[@]} > 0)); then
        PARSED_INSTANCE_NAMES=("${EFFECTIVE_DEFAULT_INSTANCES_ARRAY[@]}")
        info "Using default instances from config file for --install: $(IFS=' '; echo "${PARSED_INSTANCE_NAMES[*]}")"
    else
        error_exit "DEFAULT_INSTANCES_CONFIG in '$INSTALL_APP_CONF_FULL_PATH' is mandatory and must not be empty when using --install." "$EXIT_CODE_CONFIG_ERROR"
    fi
elif [[ "$OPERATION_MODE" == "update" ]]; then
    if ((${#EFFECTIVE_DEFAULT_INSTANCES_ARRAY[@]} > 0)); then
        PARSED_INSTANCE_NAMES=("${EFFECTIVE_DEFAULT_INSTANCES_ARRAY[@]}")
        debug "Default instances from config (for informational messages during update): $(IFS=' '; echo "${PARSED_INSTANCE_NAMES[*]}")"
    else
        debug "No default instances found in config for update mode, or DEFAULT_INSTANCES_CONFIG is empty."
    fi
fi

dependency_check
acquire_lock
trap 'error_exit "Script interrupted by SIGINT/SIGTERM." "$EXIT_CODE_FATAL_ERROR"' INT TERM

# --- Confirmation Prompt ---
if [[ "$DRY_RUN" != true ]]; then
  confirm_prompt="Proceed with $OPERATION_MODE"
  if [[ "$OPERATION_MODE" == "install" && ((${#PARSED_INSTANCE_NAMES[@]} > 0)) ]]; then
    confirm_prompt+=" for instances: ($(IFS=','; echo "${PARSED_INSTANCE_NAMES[*]}"))"
  elif [[ "$OPERATION_MODE" == "install" ]]; then
    confirm_prompt+=" (base components only - WARNING: no instances defined in config for install!)"
  fi

  if [[ "$OPERATION_MODE" == "update" ]]; then
    # Update is now always a bundle update
    confirm_prompt+=" (bundle update)"
  fi

  if [[ "$USE_FORCE_FLAG" == true && "$OPERATION_MODE" == "install" ]]; then
    confirm_prompt+=" (forcing instance configuration overwrite)"
  fi

  if [ -t 0 ]; then
    read -r -p "${C_WARN}${confirm_prompt} using source '${SOURCE_DIR}'? [y/N] ${C_RESET}" yn
    case "$yn" in
      [Yy]*) info "User confirmed. Proceeding.";;
      *) info "User aborted operation."; USER_ABORTED=true; SCRIPT_SUCCESSFUL=false; exit "$EXIT_CODE_SUCCESS";;
    esac
  else
    if [[ "$USE_FORCE_FLAG" == true ]]; then
      info "Non-interactive mode (no TTY): Proceeding with operation due to --force flag."
    else
      error_exit "Non-interactive mode (no TTY): Confirmation required. Run interactively or use --force." "$EXIT_CODE_USAGE_ERROR"
    fi
  fi
fi

# --- Main Logic Call ---
main() {
  info "▶ Orchestrator v$VERSION starting (Mode: $OPERATION_MODE)"
  if ! pushd "$SOURCE_DIR" >/dev/null; then error_exit "Failed to change directory to '$SOURCE_DIR'." "$EXIT_CODE_FILE_ERROR" ; fi
  MAIN_PUSHED_DIR=true; debug "Working directory: $(pwd)"

  # effective_config_filename_for_base_install is always the one from the bundle
  local effective_config_filename_for_base_install_rel_to_subscript_dir="$BASE_CONFIG_FILENAME"

  # Removed logic for surgical update (temp config, staging components)

  debug "Verifying required files..."
  local file_to_check_main
  for file_to_check_main in "${SCRIPTS_TO_CHECK[@]}"; do
      [[ -f "$file_to_check_main" ]] || error_exit "Missing required script: $(pwd)/$file_to_check_main" "$EXIT_CODE_FILE_ERROR"
  done
  # Check for the config file that install_base_exportcliv2.sh will use
  local base_install_config_to_check="${DEPLOY_SUBDIR_NAME}/${effective_config_filename_for_base_install_rel_to_subscript_dir}"
  [[ -f "$base_install_config_to_check" ]] || error_exit "Effective base configuration file not found: $base_install_config_to_check" "$EXIT_CODE_CONFIG_ERROR"
  debug "Required files check complete."

  debug "Ensuring sub-scripts are executable..."
  for script_to_make_exec_main in "${SCRIPTS_TO_CHECK[@]}"; do
    if ! run chmod +x "$script_to_make_exec_main"; then
        error_exit "Failed to make sub-script '$script_to_make_exec_main' executable." "$EXIT_CODE_FILE_ERROR"
    fi
  done

  info "▶ Running base installer/updater (${DEPLOY_SUBDIR_NAME}/install_base_exportcliv2.sh)..."
  local base_install_cmd_array_main=()
  base_install_cmd_array_main+=("./${DEPLOY_SUBDIR_NAME}/install_base_exportcliv2.sh")
  base_install_cmd_array_main+=("-c" "$effective_config_filename_for_base_install_rel_to_subscript_dir")
  if [[ "$DRY_RUN" == true ]]; then base_install_cmd_array_main+=("-n"); fi
  if [[ "$VERBOSE_MODE" == true ]]; then base_install_cmd_array_main+=("-v"); fi
  base_install_cmd_array_main+=("--operation-type" "$OPERATION_MODE")

  if ! run "${base_install_cmd_array_main[@]}"; then
    error_exit "Base installer script '${DEPLOY_SUBDIR_NAME}/install_base_exportcliv2.sh' failed." "$EXIT_CODE_FATAL_ERROR"
  fi

  # Removed cleanup of staged files for surgical update

  if [[ "$OPERATION_MODE" == "install" ]]; then
    if ((${#PARSED_INSTANCE_NAMES[@]} > 0)); then
      info "▶ Configuring instances..."
      for instance_name in "${PARSED_INSTANCE_NAMES[@]}"; do
        info "--- Configuring instance: $instance_name ---"
        local config_cmd_array=(); config_cmd_array+=("./${DEPLOY_SUBDIR_NAME}/configure_instance.sh");
        config_cmd_array+=("-i" "$instance_name");
        if [[ "$DRY_RUN" == true ]]; then config_cmd_array+=("-n"); fi
        if [[ "$VERBOSE_MODE" == true ]]; then config_cmd_array+=("-v"); fi
        if [[ "$USE_FORCE_FLAG" == true ]]; then config_cmd_array+=("--force"); fi
        if ! run "${config_cmd_array[@]}"; then info "Instance '$instance_name' configuration failed. Continuing..."; fi
      done
    else
      warn "No instances found to configure. This should not happen if DEFAULT_INSTANCES_CONFIG is correctly set and mandatory."
    fi

    info "▶ Setting up services for initial install..."
    local manage_opts_install=()
    if [[ "$DRY_RUN" == true ]]; then manage_opts_install+=("-n"); fi
    if [[ "$VERBOSE_MODE" == true ]]; then manage_opts_install+=("-v"); fi

    info "--- Enabling main Bitmover service ---"
    if ! run "./${DEPLOY_SUBDIR_NAME}/manage_services.sh" "${manage_opts_install[@]}" --enable; then info "Failed to enable main Bitmover service. Check logs."; fi
    info "--- Starting main Bitmover service ---"
    if ! run "./${DEPLOY_SUBDIR_NAME}/manage_services.sh" "${manage_opts_install[@]}" --start; then info "Failed to start main Bitmover service. Check logs."; fi
    info "Main service status: ./${DEPLOY_SUBDIR_NAME}/manage_services.sh --status"

    if ((${#PARSED_INSTANCE_NAMES[@]} > 0)); then
        info "--- Additionally setting up services for instances: ${PARSED_INSTANCE_NAMES[*]} ---"
        for instance_name in "${PARSED_INSTANCE_NAMES[@]}"; do
            info "--- Enabling services for instance: $instance_name ---"
            if ! run "./${DEPLOY_SUBDIR_NAME}/manage_services.sh" "${manage_opts_install[@]}" -i "$instance_name" --enable; then info "Failed to enable services for instance '$instance_name'."; fi
            info "--- Starting services for instance: $instance_name ---"
            if ! run "./${DEPLOY_SUBDIR_NAME}/manage_services.sh" "${manage_opts_install[@]}" -i "$instance_name" --start; then info "Failed to start services for instance '$instance_name'."; fi
        done

        info "--- Enabling automated health checks for instances ---"
        # The base_vars file must have APP_NAME defined for this to work.
        local app_name_from_base_vars
                app_name_from_base_vars=$(grep -oP '(?<=^export APP_NAME=")[^"]+' "/etc/default/exportcliv2_base_vars" || echo "")
        if [[ -z "$app_name_from_base_vars" ]]; then
            warn "Could not determine APP_NAME to enable health check timers. Skipping."
        else
            for instance_name in "${PARSED_INSTANCE_NAMES[@]}"; do
                # Only enable the timer if the configured interval is greater than 0
                local health_check_interval_from_config="${HEALTH_CHECK_INTERVAL_MINS_CONFIG:-5}"
                if (( health_check_interval_from_config > 0 )); then
                    info "--- Enabling health check timer for instance: $instance_name ---"
                    if ! run systemctl enable "${app_name_from_base_vars}-healthcheck@${instance_name}.timer"; then info "Failed to enable health check timer for '$instance_name'."; fi
                    if ! run systemctl start "${app_name_from_base_vars}-healthcheck@${instance_name}.timer"; then info "Failed to start health check timer for '$instance_name'."; fi
                else
                    info "--- Skipping health check for instance '$instance_name' as interval is set to 0 ---"
                fi
            done
        fi
    fi
    info "Service setup attempts complete."

  elif [[ "$OPERATION_MODE" == "update" ]]; then
    info "▶ Bundle update processing complete." # Message simplified
    echo; info "--------------------------------------------------------------------------------";
    info "IMPORTANT: Update complete. Services must be restarted manually for changes to take effect.";
    info "--------------------------------------------------------------------------------";
    info "Use 'sudo exportcli-manage' or 'sudo ./exportcliv2-deploy/manage_services.sh' to manage services.";
    info ""; info "Recommended restart actions based on this update:";
    # Simplified restart message as it's always a general bundle update now
    info "  This was a bundle update. Depending on what changed in the bundle (binary, wheel, configs),";
    info "  you may need to restart the main Bitmover service and/or relevant exportcliv2 instances.";
    info "  Consult the release notes for the bundle to determine specific restart needs.";
    info "  General Examples:";
    info "    sudo exportcli-manage --restart                # For the main Bitmover service (if wheel/common configs changed)";
    info "    sudo exportcli-manage -i <INSTANCE_NAME> --restart # For each exportcliv2 instance (if binary/instance configs changed)";
    if ((${#PARSED_INSTANCE_NAMES[@]} > 0)); then
        info "    (e.g., for instances like: $(IFS=' '; echo "${PARSED_INSTANCE_NAMES[*]}"))";
    fi
    info ""; info "You can also check status or view logs using 'exportcli-manage':";
    info "    sudo exportcli-manage --status";
    info "    sudo exportcli-manage -i <INSTANCE_NAME> --status";
    info "    sudo exportcli-manage --logs-follow --since \"10m\"";
    info "    sudo exportcli-manage -i <INSTANCE_NAME> --logs-follow"; echo;
  fi
  SCRIPT_SUCCESSFUL=true
}

# --- Script Entry Point & Final Exit Logic ---
if [[ "$HELP_OR_VERSION_EXIT" != true ]]; then
    main "$@"
fi

if [[ "$DRY_RUN" == true && "$HELP_OR_VERSION_EXIT" != true ]]; then
    info "[DRY-RUN] Orchestration dry run scan completed."
fi

if [[ "$HELP_OR_VERSION_EXIT" != true ]] ; then
    if [[ "$SCRIPT_SUCCESSFUL" == true ]]; then
        if (( FAIL_COUNT > 0 )); then
            exit "$EXIT_CODE_PARTIAL_SUCCESS"
        fi
        exit "$EXIT_CODE_SUCCESS"
    elif [[ "$USER_ABORTED" == true ]]; then
        exit "$EXIT_CODE_SUCCESS"
    fi
fi