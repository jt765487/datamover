#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# -----------------------------------------------------------------------------
# v2 Deployment Orchestrator
# - Standardized on --force flag, passed down to sub-scripts.
# - Simplified ERR trap hint, relying on sub-scripts for specific error details.
# - Retains surgical update features.
# -----------------------------------------------------------------------------
VERSION="2.3.9" # Standardized --force, simplified ERR trap

# --- Colorized Logging & Exit Codes (No change) ---
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

# --- Logging (Using _log_msg helper - No change from 2.3.8) ---
_ts() { date -u +'%Y-%m-%dT%H:%M:%SZ'; }
_log_msg() {
    local log_level_name="$1"; local color_var_name="C_${log_level_name}"; local color_code="${!color_var_name}"; shift;
    echo -e "${color_code}$(_ts) [${log_level_name^^}] $*${C_RESET}" >&2;
}
info()       { _log_msg "INFO" "$*"; }
warn()       { _log_msg "WARN" "$*"; }
debug() { if [[ "${VERBOSE_MODE:-false}" == true ]]; then _log_msg "DEBUG" "$*"; fi; }
error_exit() { local message="$1"; local exit_code="${2:-$EXIT_CODE_FATAL_ERROR}"; _log_msg "ERROR" "$message"; exit "$exit_code"; }

# --- Configuration & Globals (No change to these core ones) ---
readonly DEPLOY_SUBDIR_NAME="exportcliv2-deploy"
SOURCE_DIR="."
BASE_CONFIG_FILENAME="install-app.conf"
DEFAULT_INSTANCES=(AAA BBB CCC) # Example
INSTANCE_NAMES_STRING=""
PARSED_INSTANCE_NAMES=()
DRY_RUN=false
VERBOSE_MODE=false
OPERATION_MODE=""
USE_FORCE_FLAG=false # <<<< RENAMED from FORCE_INSTANCE_CONFIG
RESTART_SERVICES_ON_UPDATE=false

NEW_BINARY_PATH_ARG=""
NEW_WHEEL_PATH_ARG=""
TEMP_CONFIG_FOR_UPDATE=""
STAGED_NEW_BINARY_FILENAME=""
STAGED_NEW_WHEEL_FILENAME=""
ABSOLUTE_TEMP_CONFIG_FOR_UPDATE=""
ABSOLUTE_STAGED_NEW_BINARY_PATH=""
ABSOLUTE_STAGED_NEW_WHEEL_PATH=""

FAIL_COUNT=0
SCRIPT_SUCCESSFUL=false
SCRIPT_RUNNING_LOCK=false
HELP_OR_VERSION_EXIT=false

SCRIPTS_TO_CHECK=(
  "${DEPLOY_SUBDIR_NAME}/install_base_exportcliv2.sh"
  "${DEPLOY_SUBDIR_NAME}/configure_instance.sh"
  "${DEPLOY_SUBDIR_NAME}/manage_services.sh"
)
LOCKFILE_DIR="/tmp"
LOCKFILE="${LOCKFILE_DIR}/$(basename "$0" ".sh").lock"
MAIN_PUSHED_DIR=false

# --- Dependency checks (No change) ---
dependency_check() {
  local cmds_to_check=(flock date chmod dirname basename readlink realpath mktemp cp sed)
  debug "Checking for core orchestrator commands: ${cmds_to_check[*]}"
  for cmd_to_check in "${cmds_to_check[@]}"; do
    if ! command -v "$cmd_to_check" &>/dev/null; then
      error_exit "Required command '$cmd_to_check' not found in PATH." "$EXIT_CODE_PREREQUISITE_ERROR"
    fi
  done
  debug "Core orchestrator commands found."
}

# --- Locking with flock (No change) ---
acquire_lock() { # ... same as 2.3.8 ...
  debug "Attempting to acquire execution lock: $LOCKFILE"
  mkdir -p "$LOCKFILE_DIR" || error_exit "Failed to create lock directory $LOCKFILE_DIR" "$EXIT_CODE_FATAL_ERROR"
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


# --- Master Exit Trap (No change from 2.3.8) ---
# shellcheck disable=SC2317
_master_exit_trap() { # ... same as 2.3.8 ...
    local final_exit_code=$?
    if [[ "$MAIN_PUSHED_DIR" == true ]]; then
        if popd >/dev/null 2>&1; then
            debug "Trap: Returned from source directory. Original PWD: $(pwd)"
        else
            warn "Trap: Failed to popd from source directory. Current PWD: $(pwd)"
        fi
        MAIN_PUSHED_DIR=false
    fi

    if [[ -n "$ABSOLUTE_TEMP_CONFIG_FOR_UPDATE" && -f "$ABSOLUTE_TEMP_CONFIG_FOR_UPDATE" ]]; then
        debug "Trap: Removing temporary config file: $ABSOLUTE_TEMP_CONFIG_FOR_UPDATE"
        rm -f "$ABSOLUTE_TEMP_CONFIG_FOR_UPDATE"
    fi
    if [[ -n "$ABSOLUTE_STAGED_NEW_BINARY_PATH" && -f "$ABSOLUTE_STAGED_NEW_BINARY_PATH" ]]; then
        debug "Trap: Removing staged binary: $ABSOLUTE_STAGED_NEW_BINARY_PATH"
        rm -f "$ABSOLUTE_STAGED_NEW_BINARY_PATH"
    fi
    if [[ -n "$ABSOLUTE_STAGED_NEW_WHEEL_PATH" && -f "$ABSOLUTE_STAGED_NEW_WHEEL_PATH" ]]; then
        debug "Trap: Removing staged wheel: $ABSOLUTE_STAGED_NEW_WHEEL_PATH"
        rm -f "$ABSOLUTE_STAGED_NEW_WHEEL_PATH"
    fi

    if [[ "$SCRIPT_RUNNING_LOCK" == true ]]; then
        if rm -f "$LOCKFILE"; then
          debug "Trap: Execution lock released: $LOCKFILE"
        else
          warn "Trap: Failed to remove lockfile: $LOCKFILE. Manual cleanup may be needed."
        fi
        SCRIPT_RUNNING_LOCK=false
    fi
    _final_summary_message "$final_exit_code"
}

# --- _final_summary_message (No change from 2.3.8) ---
# shellcheck disable=SC2317
_final_summary_message() { # ... same as 2.3.8 ...
    local exit_code="$1"
    if [[ "$HELP_OR_VERSION_EXIT" == true ]]; then return; fi
    echo
    if [[ "$exit_code" -eq "$EXIT_CODE_SUCCESS" && "$SCRIPT_SUCCESSFUL" == true ]]; then
        info "▶ Orchestrator finished successfully."
    elif [[ "$exit_code" -eq "$EXIT_CODE_PARTIAL_SUCCESS" || ("$exit_code" -eq "$EXIT_CODE_SUCCESS" && "$FAIL_COUNT" -gt 0 && "$SCRIPT_SUCCESSFUL" == true) ]]; then
        warn "▶ Orchestrator finished with $FAIL_COUNT non-fatal error(s). Review output."
    elif [[ "$exit_code" -ne "$EXIT_CODE_SUCCESS" ]]; then
        echo -e "${C_ERROR}$(_ts) [ERROR] ▶ Orchestrator failed. Review error messages above.${C_RESET}" >&2
    else
        warn "▶ Orchestrator finished. Status unclear (exit code 0, but not marked fully successful). Review output."
    fi
}

# --- ERR Trap (Simplified Hint) ---
# shellcheck disable=SC2317
cleanup_on_error() {
    local exit_code="$1"
    local line_no="$2"
    local failed_command="$3"
    echo
    warn "-------------------- ORCHESTRATOR ERROR DETECTED --------------------"
    local error_message_detail="Error on or near line ${line_no}: command '${failed_command}' returned exit code ${exit_code}."
    local hint=""
    if [[ "$failed_command" == run*\.*sh* ]]; then # If a sub-script called via run failed
        hint=$'\n'"Hint: A sub-script reported an error. Review its specific messages above for details and potential solutions (e.g., using this orchestrator's '--force' option if applicable)."
    fi
    error_exit "${error_message_detail}${hint}" "${exit_code:-$EXIT_CODE_FATAL_ERROR}"
}
trap 'cleanup_on_error "$?" "$LINENO" "$BASH_COMMAND"' ERR

# --- Helpers (run, _stage_component - No change from 2.3.8) ---
run() { # ... same as 2.3.8 ...
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
_stage_component() { # ... same as 2.3.8 ...
    local src_path_var_name="$1"
    local config_key_name="$2"
    local -n staged_filename_ref="$3"
    local -n abs_staged_path_ref="$4"

    local src_path="${!src_path_var_name}"

    if [[ -z "$src_path" ]]; then
        debug "No source path provided via '$src_path_var_name' for component '$config_key_name', skipping."
        return 0
    fi

    staged_filename_ref=$(basename "$src_path")
    local target_staged_relative_path="${DEPLOY_SUBDIR_NAME}/${staged_filename_ref}"

    run cp "$src_path" "$target_staged_relative_path"
    if [[ $? -ne 0 && "$DRY_RUN" != true ]]; then
         error_exit "Failed to copy new component '$src_path' to staging area '$target_staged_relative_path'." "$EXIT_CODE_FILE_ERROR"
    fi
    if [[ "$DRY_RUN" == true && ! -e "$target_staged_relative_path" ]]; then
         debug "[DRY-RUN] Touching placeholder for staged file: $target_staged_relative_path"
         touch "$target_staged_relative_path"
    fi
    if [[ -e "$target_staged_relative_path" ]]; then
        abs_staged_path_ref="$(realpath "$target_staged_relative_path")"
    else
        abs_staged_path_ref="${SOURCE_DIR}/${target_staged_relative_path}"
        warn "Could not find staged file '$target_staged_relative_path' for realpath; using constructed absolute path '$abs_staged_path_ref' for trap."
    fi
    debug "Staged '$src_path' as '$target_staged_relative_path' (abs path for trap: '$abs_staged_path_ref')"

    local sed_expression="s|^(\\s*${config_key_name}\\s*=\\s*).*|\\1\"${staged_filename_ref}\"|"
    run sed -i -E "$sed_expression" "$TEMP_CONFIG_FOR_UPDATE"
    if [[ $? -ne 0 && "$DRY_RUN" != true ]]; then
        error_exit "Failed to update '$config_key_name' in temp config '$TEMP_CONFIG_FOR_UPDATE'."
    fi
    debug "Updated '$config_key_name' in '$TEMP_CONFIG_FOR_UPDATE' to '$staged_filename_ref'"
    return 0
}

# --- Usage & List Defaults (Modified for --force) ---
usage() {
  local exit_code="${1:-$EXIT_CODE_USAGE_ERROR}"
  if [[ "$exit_code" -eq "$EXIT_CODE_SUCCESS" ]]; then HELP_OR_VERSION_EXIT=true; fi
  local default_instances_str; default_instances_str=$(IFS=' '; echo "${DEFAULT_INSTANCES[*]}")
  if [[ -z "$default_instances_str" ]]; then default_instances_str="(none defined)"; fi
  local script_basename; script_basename=$(basename "$0")
  local current_dir_display; current_dir_display=$(pwd)

  cat <<EOF
Usage: $script_basename [OPTIONS] --install|--update|--status-only

Description:
  Orchestrates the installation, update, or status checking of the ExportCLIv2 suite.
  This script is typically run from the root of an unpacked suite bundle.

Modes (one is required):
  --install                 Performs a fresh installation or adds/reconfigures instances.
                            Use '--force' with this mode to overwrite existing instance configurations.
  --update                  Updates core application components (e.g., main binary, datamover wheel).
                            Default: Uses components from the current '--source-dir'.
                            Surgical Updates: Use with --new-binary or --new-wheel to apply
                            specific external files. See EXAMPLES.
  --status-only             Only run service status checks for specified or default instances.

General Options:
  -s, --source-dir DIR      Path to the unpacked source tree. Default: '$current_dir_display'.
  -c, --config FILE         Base install config filename (in 'source-dir/${DEPLOY_SUBDIR_NAME}/').
                            Default: '${BASE_CONFIG_FILENAME}'.
                            NOTE: For surgical --update, this config is read but relevant filenames
                                  are overridden by --new-binary/--new-wheel.
  -i, --instances "LIST"    Comma-separated list of instance names (e.g., "inst1,inst2").
                            Default for --install/--status-only: $default_instances_str
  --new-binary ABS_PATH     (With --update) Absolute path to a new application binary.
  --new-wheel ABS_PATH      (With --update) Absolute path to a new datamover wheel.
  --force                   (With --install) Overwrite existing instance configurations if they exist.
                            (This flag is passed down to relevant sub-scripts).
  -n, --dry-run             Show commands without executing.
  -v, --verbose             Enable verbose shell tracing (set -x) and detailed debug messages.
  -r, --restart-services    (With --update) Restart relevant services after the update.
  --list-default-instances  Show default instance names and exit.
  -h, --help                Show this help message and exit.
  --version                 Show script version and exit.

EXAMPLES:
  # Fresh install using components from the current directory bundle:
  sudo $script_basename --install

  # Install specific instances, forcing overwrite if they exist:
  sudo $script_basename --install -i "instance_A,instance_B" --force

  # Update using components from a new bundle (run from new bundle dir):
  sudo $script_basename --update -r

  # Apply a hotfix binary (run from existing/original bundle dir):
  sudo $script_basename --update --new-binary /path/to/downloaded/new_exportcliv2.bin -r

  # Check status of all default instances:
  sudo $script_basename --status-only

Exit codes: (0:Success, 1:Fatal, 2:Partial, 3:Usage, 4:Config, 5:Prereq, 6:FileOp)
EOF
  exit "$exit_code"
}
list_defaults() { # ... same as 2.3.8 ...
  HELP_OR_VERSION_EXIT=true
  echo "Default instance names that would be used if -i is not specified for --install or --status-only:"
  if ((${#DEFAULT_INSTANCES[@]} > 0)); then
    # Print as a single, space-separated string
    echo "  $(IFS=' '; echo "${DEFAULT_INSTANCES[*]}")"
  else
    echo "  (No default instances are defined in this script)"
  fi
  exit "$EXIT_CODE_SUCCESS"
}


# --- Argument Parsing (Modified for --force) ---
for arg_pre_scan in "$@"; do
  # ... (same as 2.3.8) ...
  case "$arg_pre_scan" in
    --version) echo "$(basename "$0") v$VERSION"; HELP_OR_VERSION_EXIT=true; exit "$EXIT_CODE_SUCCESS";;
    -h|--help) usage "$EXIT_CODE_SUCCESS";;
    --list-default-instances) list_defaults;;
  esac
done

TEMP_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    # ... (install, update, status-only, -s, -c, -i, --new-binary, --new-wheel - same as 2.3.8) ...
    --install) if [[ -n "$OPERATION_MODE" ]]; then error_exit "Multiple modes."; fi; OPERATION_MODE="install"; shift;;
    --update) if [[ -n "$OPERATION_MODE" ]]; then error_exit "Multiple modes."; fi; OPERATION_MODE="update"; shift;;
    --status-only) if [[ -n "$OPERATION_MODE" ]]; then error_exit "Multiple modes."; fi; OPERATION_MODE="status-only"; shift;;
    -s|--source-dir) if [[ -z "${2:-}" ]]; then error_exit "$1 needs arg."; fi; SOURCE_DIR="$2"; shift 2;;
    -c|--config) if [[ -z "${2:-}" ]]; then error_exit "$1 needs arg."; fi; BASE_CONFIG_FILENAME="$2"; shift 2;;
    -i|--instances) if [[ -z "${2:-}" ]]; then error_exit "$1 needs arg."; fi; INSTANCE_NAMES_STRING="$2"; shift 2;;
    --new-binary) if [[ -z "${2:-}"||"${2}"==-* ]]; then error_exit "$1 needs path.";fi; if ! [[ "$2" = /* ]]; then error_exit "$1 path abs.";fi; NEW_BINARY_PATH_ARG="$2"; shift 2;;
    --new-wheel) if [[ -z "${2:-}"||"${2}"==-* ]]; then error_exit "$1 needs path.";fi; if ! [[ "$2" = /* ]]; then error_exit "$1 path abs.";fi; NEW_WHEEL_PATH_ARG="$2"; shift 2;;

    --force) # <<<< CHANGED from --force-reconfigure
      USE_FORCE_FLAG=true; shift;;
    -n|--dry-run) DRY_RUN=true; shift;;
    -v|--verbose) VERBOSE_MODE=true; shift;;
    -r|--restart-services) RESTART_SERVICES_ON_UPDATE=true; shift;;
    *) TEMP_ARGS+=("$1"); shift;;
  esac
done

# ... (validation logic - same as 2.3.8 for unknown args, op mode, new-binary/wheel usage) ...
if (( ${#TEMP_ARGS[@]} > 0 )); then error_exit "Unknown option: ${TEMP_ARGS[0]}"; fi
if [[ -z "$OPERATION_MODE" ]]; then error_exit "Operation mode required."; fi
info "Operation Mode: $OPERATION_MODE"
if [[ -n "$NEW_BINARY_PATH_ARG" || -n "$NEW_WHEEL_PATH_ARG" ]]; then
  if [[ "$OPERATION_MODE" != "update" ]]; then error_exit "--new-binary/--new-wheel only with --update."; fi
  if [[ -n "$NEW_BINARY_PATH_ARG" && ! -f "$NEW_BINARY_PATH_ARG" ]]; then error_exit "New binary not found: $NEW_BINARY_PATH_ARG"; fi
  if [[ -n "$NEW_WHEEL_PATH_ARG" && ! -f "$NEW_WHEEL_PATH_ARG" ]]; then error_exit "New wheel not found: $NEW_WHEEL_PATH_ARG"; fi
  info "Surgical update with external components requested."
fi
if [[ "$VERBOSE_MODE" == true ]]; then info "Verbose mode enabled."; set -x; fi
# ... (Instance name parsing - same as 2.3.8) ...
if [[ -n "$INSTANCE_NAMES_STRING" ]]; then
    IFS=',' read -r -a temp_instance_array <<< "$INSTANCE_NAMES_STRING"
    PARSED_INSTANCE_NAMES=()
    for i in "${!temp_instance_array[@]}"; do
        local trimmed_inst="${temp_instance_array[$i]#${temp_instance_array[$i]%%[![:space:]]*}}"
        trimmed_inst="${trimmed_inst%${trimmed_inst##*[![:space:]]}}"
        if [[ -n "$trimmed_inst" ]]; then
            if ! [[ "$trimmed_inst" =~ ^[A-Za-z0-9._-]+$ ]]; then error_exit "Invalid instance name: '$trimmed_inst'"; fi
            PARSED_INSTANCE_NAMES+=("$trimmed_inst")
        elif [[ "${#temp_instance_array[@]}" -gt 1 || -n "${temp_instance_array[$i]}" ]]; then error_exit "Empty instance name in list: '$INSTANCE_NAMES_STRING'"; fi
    done
    if ((${#PARSED_INSTANCE_NAMES[@]} > 0)); then info "Operating on specified instances: $(IFS=' '; echo "${PARSED_INSTANCE_NAMES[*]}")";
    elif [[ -n "$INSTANCE_NAMES_STRING" ]]; then error_exit "Instance list '$INSTANCE_NAMES_STRING' yielded no valid names."; fi
elif [[ "$OPERATION_MODE" == "install" || "$OPERATION_MODE" == "status-only" ]]; then
    if ((${#DEFAULT_INSTANCES[@]} > 0)); then PARSED_INSTANCE_NAMES=("${DEFAULT_INSTANCES[@]}"); info "Using default instances: $(IFS=' '; echo "${PARSED_INSTANCE_NAMES[*]}")";
    elif [[ "$OPERATION_MODE" == "install" ]]; then warn "No instances specified or defaulted for --install. Base install only."; fi
fi


dependency_check
acquire_lock
trap 'error_exit "Script interrupted by signal." "$EXIT_CODE_FATAL_ERROR"' INT TERM

# ... (SOURCE_DIR absolute path resolution - same as 2.3.8) ...
SOURCE_DIR_ABS="$(realpath -m "$SOURCE_DIR")"
if [[ ! -d "$SOURCE_DIR_ABS" ]]; then error_exit "Source dir not found: '$SOURCE_DIR_ABS' (from '$SOURCE_DIR')."; fi
SOURCE_DIR="$SOURCE_DIR_ABS"; debug "Effective source dir: $SOURCE_DIR"
debug "Base config filename: $BASE_CONFIG_FILENAME"

# ... (Confirmation prompt - modified for --force) ...
if [[ "$DRY_RUN" != true && "$OPERATION_MODE" != "status-only" ]]; then
  confirm_prompt="Proceed with $OPERATION_MODE"
  # ... (instance list for prompt - same) ...
  if ((${#PARSED_INSTANCE_NAMES[@]} > 0)); then confirm_prompt+=" for instances: ($(IFS=','; echo "${PARSED_INSTANCE_NAMES[*]}"))";
  elif [[ "$OPERATION_MODE" == "install" ]]; then confirm_prompt+=" (base components only)"; fi

  if [[ "$OPERATION_MODE" == "update" ]]; then # ... (update specific prompt - same) ...
    if [[ -n "$NEW_BINARY_PATH_ARG"||-n "$NEW_WHEEL_PATH_ARG" ]]; then confirm_prompt+=" (surgical update)"; else confirm_prompt+=" (bundle update)"; fi
    if [[ "$RESTART_SERVICES_ON_UPDATE" == true ]]; then confirm_prompt+=" and restart services"; fi
  fi
  if [[ "$USE_FORCE_FLAG" == true && "$OPERATION_MODE" == "install" ]]; then # <<<< CHANGED
    confirm_prompt+=" (forcing operation)"
  fi
  read -r -p "${C_WARN}${confirm_prompt} using source '${SOURCE_DIR}'? [y/N] ${C_RESET}" yn
  case "$yn" in [Yy]*) info "Proceeding.";; *) info "Aborted."; SCRIPT_SUCCESSFUL=false; exit "$EXIT_CODE_SUCCESS";; esac
fi


main() {
  info "▶ Orchestrator v$VERSION starting (Mode: $OPERATION_MODE)"
  if ! pushd "$SOURCE_DIR" >/dev/null; then error_exit "Failed to cd to '$SOURCE_DIR'."; fi
  MAIN_PUSHED_DIR=true; debug "Working directory: $(pwd)"

  local effective_config_filename_for_base_install="$BASE_CONFIG_FILENAME"

  # --- Surgical Update Staging (No change from 2.3.8, uses _stage_component) ---
  if [[ "$OPERATION_MODE" == "update" && (-n "$NEW_BINARY_PATH_ARG" || -n "$NEW_WHEEL_PATH_ARG") ]]; then
    # ... (same as 2.3.8, calls _stage_component) ...
    info "Preparing for surgical update with externally provided files..."
    local original_config_path_in_bundle="${DEPLOY_SUBDIR_NAME}/${BASE_CONFIG_FILENAME}"
    if [[ ! -f "$original_config_path_in_bundle" ]]; then error_exit "Original base config '$original_config_path_in_bundle' not found. Cannot proceed."; fi
    if [[ ! -d "$DEPLOY_SUBDIR_NAME" ]]; then error_exit "Deployment subdir '$DEPLOY_SUBDIR_NAME' not found."; fi
    TEMP_CONFIG_FOR_UPDATE="$(mktemp "${DEPLOY_SUBDIR_NAME}/install-app.conf.tmp.XXXXXX")"
    ABSOLUTE_TEMP_CONFIG_FOR_UPDATE="$(realpath "$TEMP_CONFIG_FOR_UPDATE")"
    debug "Temp config for update: $TEMP_CONFIG_FOR_UPDATE (abs: $ABSOLUTE_TEMP_CONFIG_FOR_UPDATE)"
    run cp "$original_config_path_in_bundle" "$TEMP_CONFIG_FOR_UPDATE"
    _stage_component "NEW_BINARY_PATH_ARG" "VERSIONED_APP_BINARY_FILENAME" STAGED_NEW_BINARY_FILENAME ABSOLUTE_STAGED_NEW_BINARY_PATH
    _stage_component "NEW_WHEEL_PATH_ARG" "VERSIONED_DATAMOVER_WHEEL_FILENAME" STAGED_NEW_WHEEL_FILENAME ABSOLUTE_STAGED_NEW_WHEEL_PATH
    effective_config_filename_for_base_install="$(basename "$TEMP_CONFIG_FOR_UPDATE")"
    debug "Using temporary config for base install: $effective_config_filename_for_base_install"
  fi

  # --- Status-only mode (No change from 2.3.8) ---
  if [[ "$OPERATION_MODE" == "status-only" ]]; then # ... same as 2.3.8 ...
    info "▶ Performing status check for instances..."
    local base_manage_cmd=("./${DEPLOY_SUBDIR_NAME}/manage_services.sh")
    if [[ "$DRY_RUN" == true ]]; then base_manage_cmd+=("-n"); fi
    if [[ "$VERBOSE_MODE" == true ]]; then base_manage_cmd+=("-v"); fi
    if ((${#PARSED_INSTANCE_NAMES[@]} == 0)); then
        warn "No instances specified or defaulted. Checking main Bitmover service status only."
        run "${base_manage_cmd[@]}" --status
    else
        for instance_name in "${PARSED_INSTANCE_NAMES[@]}"; do
            info "--- Checking status for instance: $instance_name ---"
            run "${base_manage_cmd[@]}" -i "$instance_name" --status
        done
    fi
    SCRIPT_SUCCESSFUL=true
    return
  fi


  # --- File Verification & Permissions (No change from 2.3.8) ---
  debug "Verifying required files..." # ... same as 2.3.8 ...
  local file_to_check_main
  for file_to_check_main in "${SCRIPTS_TO_CHECK[@]}"; do
      [[ -f "$file_to_check_main" ]] || error_exit "Missing script: $(pwd)/$file_to_check_main"
  done
  if [[ ! -f "${DEPLOY_SUBDIR_NAME}/${effective_config_filename_for_base_install}" ]]; then
    error_exit "Effective base config not found: ${DEPLOY_SUBDIR_NAME}/${effective_config_filename_for_base_install}"
  fi
  debug "Required files present."
  debug "Ensuring sub-scripts executable..."
  for script_to_make_exec_main in "${SCRIPTS_TO_CHECK[@]}"; do
    run chmod +x "$script_to_make_exec_main"
  done
  if [[ "$FAIL_COUNT" -gt 0 && "$DRY_RUN" != true ]]; then error_exit "Failed to make sub-scripts executable."; fi


  # --- Base Install/Update (No change from 2.3.8) ---
  info "▶ Running base installer/updater (${DEPLOY_SUBDIR_NAME}/install_base_exportcliv2.sh)..."
  # ... (same base_install_cmd_array_main build and run call as 2.3.8) ...
  local base_install_cmd_array_main=()
  base_install_cmd_array_main+=("./${DEPLOY_SUBDIR_NAME}/install_base_exportcliv2.sh")
  base_install_cmd_array_main+=("-c" "$effective_config_filename_for_base_install")
  if [[ "$DRY_RUN" == true ]]; then base_install_cmd_array_main+=("-n"); fi
  if [[ "$VERBOSE_MODE" == true ]]; then base_install_cmd_array_main+=("-v"); fi
  run "${base_install_cmd_array_main[@]}"
  local base_install_ec=$?


  # --- Surgical Update Cleanup (No change from 2.3.8) ---
  if [[ "$OPERATION_MODE" == "update" && (-n "$NEW_BINARY_PATH_ARG" || -n "$NEW_WHEEL_PATH_ARG") ]]; then
    # ... (same as 2.3.8) ...
    if [[ -n "$STAGED_NEW_BINARY_FILENAME" && -f "${DEPLOY_SUBDIR_NAME}/${STAGED_NEW_BINARY_FILENAME}" ]]; then
        local staged_bin_path_to_remove="${DEPLOY_SUBDIR_NAME}/${STAGED_NEW_BINARY_FILENAME}"
        debug "Main: Removing staged binary: $staged_bin_path_to_remove"
        if [[ "$DRY_RUN" == true ]]; then info "[DRY-RUN] Would remove '$staged_bin_path_to_remove'"; else rm -f "$staged_bin_path_to_remove"; fi
    fi
    if [[ -n "$STAGED_NEW_WHEEL_FILENAME" && -f "${DEPLOY_SUBDIR_NAME}/${STAGED_NEW_WHEEL_FILENAME}" ]]; then
        local staged_wheel_path_to_remove="${DEPLOY_SUBDIR_NAME}/${STAGED_NEW_WHEEL_FILENAME}"
        debug "Main: Removing staged wheel: $staged_wheel_path_to_remove"
        if [[ "$DRY_RUN" == true ]]; then info "[DRY-RUN] Would remove '$staged_wheel_path_to_remove'"; else rm -f "$staged_wheel_path_to_remove"; fi
    fi
  fi

  if [[ $base_install_ec -ne 0 ]]; then
      error_exit "Base installer script '${DEPLOY_SUBDIR_NAME}/install_base_exportcliv2.sh' failed." "$EXIT_CODE_FATAL_ERROR"
  fi

# --- Instance Configuration (Modified to pass --force) ---
  if [[ "$OPERATION_MODE" == "install" ]]; then
    if ((${#PARSED_INSTANCE_NAMES[@]} > 0)); then
      info "▶ Configuring instances..."
      for instance_name in "${PARSED_INSTANCE_NAMES[@]}"; do
        info "--- Configuring instance: $instance_name ---"
        local config_cmd_array=() # Initialize as an empty array for each iteration
        config_cmd_array+=("./${DEPLOY_SUBDIR_NAME}/configure_instance.sh")
        config_cmd_array+=("-i" "$instance_name")
        # -c option is not used by configure_instance.sh, so it's omitted here.

        if [[ "$DRY_RUN" == true ]]; then
          config_cmd_array+=("-n")
        fi
        if [[ "$VERBOSE_MODE" == true ]]; then
          config_cmd_array+=("-v")
        fi
        if [[ "$USE_FORCE_FLAG" == true ]]; then # This is the flag from orchestrator's args
          config_cmd_array+=("--force") # Pass --force to configure_instance.sh
        fi

        run "${config_cmd_array[@]}" # run helper increments FAIL_COUNT on error
        # The ERR trap will handle fatal exit if run returns non-zero
      done
    else
      info "No specific instances to configure."
    fi

    # --- Service Setup for Install ---
    info "▶ Setting up services for initial install..."
    local manage_opts_install=()
    if [[ "$DRY_RUN" == true ]]; then manage_opts_install+=("-n"); fi
    if [[ "$VERBOSE_MODE" == true ]]; then manage_opts_install+=("-v"); fi
    # NOTE: The orchestrator's --force flag is typically for file/config overwrites,
    # not usually passed to service management enable/start actions.
    # So, USE_FORCE_FLAG is NOT passed to manage_services.sh here.

    if ((${#PARSED_INSTANCE_NAMES[@]} > 0)); then
        for instance_name in "${PARSED_INSTANCE_NAMES[@]}"; do
            info "--- Enabling and starting services for instance: $instance_name ---"
            run "./${DEPLOY_SUBDIR_NAME}/manage_services.sh" "${manage_opts_install[@]}" -i "$instance_name" --enable
            run "./${DEPLOY_SUBDIR_NAME}/manage_services.sh" "${manage_opts_install[@]}" -i "$instance_name" --start
        done
        info "Check status with: $0 --status-only -i \"$(IFS=','; echo "${PARSED_INSTANCE_NAMES[*]}")\""
    else
        info "--- Enabling and starting main Bitmover service ---"
        run "./${DEPLOY_SUBDIR_NAME}/manage_services.sh" "${manage_opts_install[@]}" --enable
        run "./${DEPLOY_SUBDIR_NAME}/manage_services.sh" "${manage_opts_install[@]}" --start
        info "Check status with: $0 --status-only (for main services)"
    fi
    info "Service setup attempts complete."

  # --- Update Mode Service Restart (No change from 2.3.8 logic) ---
  elif [[ "$OPERATION_MODE" == "update" ]]; then
    # ... (existing update mode logic) ...
    info "▶ Update processing complete by ${DEPLOY_SUBDIR_NAME}/install_base_exportcliv2.sh."
    if [[ "$RESTART_SERVICES_ON_UPDATE" == true ]]; then
      info "▶ Restarting services due to --restart-services flag..."
      local manage_opts_update=()
      if [[ "$DRY_RUN" == true ]]; then manage_opts_update+=("-n"); fi
      if [[ "$VERBOSE_MODE" == true ]]; then manage_opts_update+=("-v"); fi
      # Orchestrator's --force is NOT passed to service restart.
      if ((${#PARSED_INSTANCE_NAMES[@]} > 0)); then
          for instance_name in "${PARSED_INSTANCE_NAMES[@]}"; do
              info "--- Restarting services for specified instance: $instance_name ---"
              run "./${DEPLOY_SUBDIR_NAME}/manage_services.sh" "${manage_opts_update[@]}" -i "$instance_name" --restart
          done
      else
          info "--- Restarting main Bitmover service ---"
          run "./${DEPLOY_SUBDIR_NAME}/manage_services.sh" "${manage_opts_update[@]}" --restart
          warn "Note: If only main Bitmover service was restarted, application instances might need manual restart or use '-i'."
      fi
      info "Attempted to restart relevant services. Check status if needed."
    else
      info "Services not automatically restarted. Use 'exportcli-manage' or -r option."
    fi
  fi
  SCRIPT_SUCCESSFUL=true
}
# --- Script Entry Point & Final Exit Logic (No change from 2.3.8) ---
main "$@"
if [[ "$DRY_RUN" == true && "$OPERATION_MODE" != "status-only" ]]; then
    info "[DRY-RUN] Orchestration dry run scan completed."
fi
if [[ "$SCRIPT_SUCCESSFUL" == true ]]; then
    if (( FAIL_COUNT > 0 )); then exit "$EXIT_CODE_PARTIAL_SUCCESS"; fi
    exit "$EXIT_CODE_SUCCESS"
fi