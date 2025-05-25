#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# -----------------------------------------------------------------------------
# v2.4.3 Deployment Orchestrator
# - Standardized on --force flag.
# - Simplified ERR trap hint.
# - Retains surgical update features.
# - Removed --status-only mode.
# - Fixed top-level local variable declaration.
# - Addressed set -e interaction with run() for partial success.
# - Added non-TTY check for confirmation prompt.
# - Removed unused tput dependency.
# - Improved final summary message for user abort.
# - Removed unreachable fallback exit.
# - Improved --dry-run fidelity for file operations in surgical updates.
# -----------------------------------------------------------------------------
VERSION="2.4.3" # Dry-run fidelity, removed fallback exit

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
SOURCE_DIR="."
BASE_CONFIG_FILENAME="install-app.conf"
DEFAULT_INSTANCES=(AAA BBB CCC) # Example
INSTANCE_NAMES_STRING=""
PARSED_INSTANCE_NAMES=()
DRY_RUN=false
VERBOSE_MODE=false
OPERATION_MODE=""
USE_FORCE_FLAG=false
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
USER_ABORTED=false
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

# --- Dependency checks ---
dependency_check() {
  local cmds_to_check=(flock date chmod dirname basename readlink realpath mktemp cp sed touch) # Added touch for dry-run placeholders
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
# shellcheck disable=SC2317
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

    # Cleanup for temporary/staged files, including dry-run placeholders
    if [[ -n "$ABSOLUTE_TEMP_CONFIG_FOR_UPDATE" && -e "$ABSOLUTE_TEMP_CONFIG_FOR_UPDATE" ]]; then # Check -e for dry-run placeholders
        debug "Trap: Removing temporary config file/placeholder: $ABSOLUTE_TEMP_CONFIG_FOR_UPDATE"
        rm -f "$ABSOLUTE_TEMP_CONFIG_FOR_UPDATE"
    fi
    if [[ -n "$ABSOLUTE_STAGED_NEW_BINARY_PATH" && -e "$ABSOLUTE_STAGED_NEW_BINARY_PATH" ]]; then
        debug "Trap: Removing staged binary/placeholder: $ABSOLUTE_STAGED_NEW_BINARY_PATH"
        rm -f "$ABSOLUTE_STAGED_NEW_BINARY_PATH"
    fi
    if [[ -n "$ABSOLUTE_STAGED_NEW_WHEEL_PATH" && -e "$ABSOLUTE_STAGED_NEW_WHEEL_PATH" ]]; then
        debug "Trap: Removing staged wheel/placeholder: $ABSOLUTE_STAGED_NEW_WHEEL_PATH"
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

# --- _final_summary_message ---
# shellcheck disable=SC2317
_final_summary_message() {
    local exit_code="$1"
    if [[ "$HELP_OR_VERSION_EXIT" == true ]]; then return; fi
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
# shellcheck disable=SC2317
cleanup_on_error() {
    local exit_code="$1"
    local line_no="$2"
    local failed_command="$3"
    echo
    if [[ ! "$failed_command" =~ error_exit ]]; then
        warn "-------------------- ORCHESTRATOR UNHANDLED ERROR DETECTED --------------------"
        local error_message_detail="Error on or near line ${line_no}: command '${failed_command}' returned exit code ${exit_code}."
        local hint=$'\n'"Hint: An unexpected error occurred. Check script logic or dependencies."
        _log_msg "ERROR" "${error_message_detail}${hint}"
    fi
    exit "${exit_code:-$EXIT_CODE_FATAL_ERROR}"
}
trap 'cleanup_on_error "$?" "$LINENO" "$BASH_COMMAND"' ERR

# --- Helpers (run, _stage_component) ---
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
    _log_msg "WARN" "Command failed with exit code $ec: $cmd_display"
    ((FAIL_COUNT++))
    return $ec
  fi
  return "$EXIT_CODE_SUCCESS"
}

_stage_component() {
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

    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] Would copy new component '$src_path' to staging area '$target_staged_relative_path'."
        # Touch a placeholder for realpath and trap cleanup in dry-run
        touch "$target_staged_relative_path" || warn "[DRY-RUN] Failed to touch placeholder '$target_staged_relative_path'. Subsequent dry-run steps might be affected."
    else
        cp "$src_path" "$target_staged_relative_path" || error_exit "Failed to copy new component '$src_path' to staging area '$target_staged_relative_path'." "$EXIT_CODE_FILE_ERROR"
    fi

    # Get absolute path for trap cleanup (works on placeholder in dry_run if touched)
    if [[ -e "$target_staged_relative_path" ]]; then
        abs_staged_path_ref="$(realpath "$target_staged_relative_path")"
    else
        abs_staged_path_ref="${SOURCE_DIR}/${target_staged_relative_path}" # Fallback
        if [[ "$DRY_RUN" != true ]]; then # Only warn if not dry-run and file is missing after cp
             warn "Could not find staged file '$target_staged_relative_path' after operation for realpath; using constructed absolute path '$abs_staged_path_ref' for trap cleanup."
        else # In dry-run, this means touch likely failed
             debug "[DRY-RUN] Placeholder '$target_staged_relative_path' not found for realpath (touch might have failed); using constructed path '$abs_staged_path_ref' for trap."
        fi
    fi
    debug "Staged '$src_path' as '$target_staged_relative_path' (abs path for trap: '$abs_staged_path_ref')"

    local sed_expression="s|^(\\s*${config_key_name}\\s*=\\s*).*|\\1\"${staged_filename_ref}\"|"
    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] Would update '$config_key_name' in temp config '$TEMP_CONFIG_FOR_UPDATE' to '$staged_filename_ref'."
        debug "[DRY-RUN] SED expression would be: $sed_expression"
    else
        sed -i -E "$sed_expression" "$TEMP_CONFIG_FOR_UPDATE" || error_exit "Failed to update '$config_key_name' in temp config '$TEMP_CONFIG_FOR_UPDATE'." "$EXIT_CODE_FILE_ERROR"
    fi
    debug "Updated '$config_key_name' in '$TEMP_CONFIG_FOR_UPDATE' to '$staged_filename_ref'"
    return 0
}

# --- Usage & List Defaults ---
usage() {
  local exit_code="${1:-$EXIT_CODE_USAGE_ERROR}"
  if [[ "$exit_code" -eq "$EXIT_CODE_SUCCESS" ]]; then HELP_OR_VERSION_EXIT=true; fi
  local default_instances_str; default_instances_str=$(IFS=' '; echo "${DEFAULT_INSTANCES[*]}")
  if [[ -z "$default_instances_str" ]]; then default_instances_str="(none defined)"; fi
  local script_basename; script_basename=$(basename "$0")
  local current_dir_display; current_dir_display=$(pwd)

  cat <<EOF
Usage: $script_basename [OPTIONS] --install|--update

Description:
  Orchestrates the installation or update of the ExportCLIv2 suite.
  This script is typically run from the root of an unpacked suite bundle.
  Service status checking is handled by '${DEPLOY_SUBDIR_NAME}/manage_services.sh'.

Modes (one is required):
  --install                 Performs a fresh installation or adds/reconfigures instances.
                            Use '--force' with this mode to overwrite existing instance configurations
                            or to assume 'yes' to prompts in non-interactive (non-TTY) environments.
  --update                  Updates core application components (e.g., main binary, datamover wheel).
                            Default: Uses components from the current '--source-dir'.
                            Surgical Updates: Use with --new-binary or --new-wheel to apply
                            specific external files.
                            Use '--force' to assume 'yes' to prompts in non-interactive (non-TTY) environments.


General Options:
  -s, --source-dir DIR      Path to the unpacked source tree. Default: '$current_dir_display'.
  -c, --config FILE         Base install config filename (in 'source-dir/${DEPLOY_SUBDIR_NAME}/').
                            Default: '${BASE_CONFIG_FILENAME}'.
                            NOTE: For surgical --update, this config is read but relevant filenames
                                  are overridden by --new-binary/--new-wheel.
  -i, --instances "LIST"    Comma-separated list of instance names (e.g., "inst1,inst2").
                            Default for --install: $default_instances_str
  --new-binary ABS_PATH     (With --update) Absolute path to a new application binary.
  --new-wheel ABS_PATH      (With --update) Absolute path to a new datamover wheel.
  --force                   Used with --install to overwrite existing instance configurations.
                            For all modes, if running in a non-interactive (non-TTY) environment,
                            this flag assumes 'yes' to the main confirmation prompt.
  -n, --dry-run             Show commands and simulate file operations without actual changes.
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

  # Run non-interactively (e.g., in a script), forcing install:
  sudo $script_basename --install --force

Exit codes: (0:Success, 1:Fatal, 2:Partial, 3:Usage, 4:Config, 5:Prereq, 6:FileOp)
EOF
  exit "$exit_code"
}
list_defaults() {
  HELP_OR_VERSION_EXIT=true
  echo "Default instance names that would be used if -i is not specified for --install:"
  if ((${#DEFAULT_INSTANCES[@]} > 0)); then
    echo "  $(IFS=' '; echo "${DEFAULT_INSTANCES[*]}")"
  else
    echo "  (No default instances are defined in this script)"
  fi
  exit "$EXIT_CODE_SUCCESS"
}


# --- Argument Parsing ---
for arg_pre_scan in "$@"; do
  case "$arg_pre_scan" in
    --version) echo "$(basename "$0") v$VERSION"; HELP_OR_VERSION_EXIT=true; exit "$EXIT_CODE_SUCCESS";;
    -h|--help) usage "$EXIT_CODE_SUCCESS";;
    --list-default-instances) list_defaults;;
  esac
done

TEMP_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --install)
      if [[ -n "$OPERATION_MODE" ]]; then error_exit "Multiple modes (--install/--update) specified." $EXIT_CODE_USAGE_ERROR; fi
      OPERATION_MODE="install"
      shift
      ;;
    --update)
      if [[ -n "$OPERATION_MODE" ]]; then error_exit "Multiple modes (--install/--update) specified." $EXIT_CODE_USAGE_ERROR; fi
      OPERATION_MODE="update"
      shift
      ;;
    -s|--source-dir)
      if [[ -z "${2:-}" ]]; then error_exit "$1 requires an argument." $EXIT_CODE_USAGE_ERROR; fi
      SOURCE_DIR="$2"
      shift 2
      ;;
    -c|--config)
      if [[ -z "${2:-}" ]]; then error_exit "$1 requires an argument." $EXIT_CODE_USAGE_ERROR; fi
      BASE_CONFIG_FILENAME="$2"
      shift 2
      ;;
    -i|--instances)
      if [[ -z "${2:-}" ]]; then error_exit "$1 requires an argument." $EXIT_CODE_USAGE_ERROR; fi
      INSTANCE_NAMES_STRING="$2"
      shift 2
      ;;
    --new-binary)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then error_exit "$1 requires an absolute path argument." $EXIT_CODE_USAGE_ERROR; fi
      if [[ "$2" != /* ]]; then error_exit "$1 path must be absolute: $2" $EXIT_CODE_USAGE_ERROR; fi
      NEW_BINARY_PATH_ARG="$2"
      shift 2
      ;;
    --new-wheel)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then error_exit "$1 requires an absolute path argument." $EXIT_CODE_USAGE_ERROR; fi
      if [[ "$2" != /* ]]; then error_exit "$1 path must be absolute: $2" $EXIT_CODE_USAGE_ERROR; fi
      NEW_WHEEL_PATH_ARG="$2"
      shift 2
      ;;
    --force)
      USE_FORCE_FLAG=true
      shift
      ;;
    -n|--dry-run)
      DRY_RUN=true
      shift
      ;;
    -v|--verbose)
      VERBOSE_MODE=true
      shift
      ;;
    -r|--restart-services)
      RESTART_SERVICES_ON_UPDATE=true
      shift
      ;;
    *)
      TEMP_ARGS+=("$1")
      shift
      ;;
  esac
done

if (( ${#TEMP_ARGS[@]} > 0 )); then error_exit "Unknown option specified: ${TEMP_ARGS[0]}" $EXIT_CODE_USAGE_ERROR; fi
if [[ -z "$OPERATION_MODE" ]]; then error_exit "Operation mode --install or --update is required." $EXIT_CODE_USAGE_ERROR; fi
info "Operation Mode: $OPERATION_MODE"

if [[ -n "$NEW_BINARY_PATH_ARG" || -n "$NEW_WHEEL_PATH_ARG" ]]; then
  if [[ "$OPERATION_MODE" != "update" ]]; then error_exit "--new-binary/--new-wheel can only be used with --update mode." $EXIT_CODE_USAGE_ERROR; fi
  if [[ -n "$NEW_BINARY_PATH_ARG" && ! -f "$NEW_BINARY_PATH_ARG" ]]; then error_exit "New binary file not found: $NEW_BINARY_PATH_ARG" $EXIT_CODE_FILE_ERROR; fi
  if [[ -n "$NEW_WHEEL_PATH_ARG" && ! -f "$NEW_WHEEL_PATH_ARG" ]]; then error_exit "New wheel file not found: $NEW_WHEEL_PATH_ARG" $EXIT_CODE_FILE_ERROR; fi
  info "Surgical update with external components requested."
fi
if [[ "$VERBOSE_MODE" == true ]]; then info "Verbose mode enabled."; set -x; fi

if [[ -n "$INSTANCE_NAMES_STRING" ]]; then
    IFS=',' read -r -a temp_instance_array <<< "$INSTANCE_NAMES_STRING"
    PARSED_INSTANCE_NAMES=()
    trimmed_inst=""
    for i in "${!temp_instance_array[@]}"; do
        trimmed_inst="${temp_instance_array[$i]#${temp_instance_array[$i]%%[![:space:]]*}}"
        trimmed_inst="${trimmed_inst%${trimmed_inst##*[![:space:]]}}"
        if [[ -n "$trimmed_inst" ]]; then
            if ! [[ "$trimmed_inst" =~ ^[A-Za-z0-9._-]+$ ]]; then error_exit "Invalid instance name format: '$trimmed_inst'. Allowed: A-Z a-z 0-9 . _ -" $EXIT_CODE_USAGE_ERROR; fi
            PARSED_INSTANCE_NAMES+=("$trimmed_inst")
        elif [[ "${#temp_instance_array[@]}" -gt 1 || -n "${temp_instance_array[$i]}" ]]; then
             error_exit "Empty instance name detected in list: '$INSTANCE_NAMES_STRING'" $EXIT_CODE_USAGE_ERROR
        fi
    done
    if ((${#PARSED_INSTANCE_NAMES[@]} > 0)); then info "Operating on specified instances: $(IFS=' '; echo "${PARSED_INSTANCE_NAMES[*]}")";
    elif [[ -n "$INSTANCE_NAMES_STRING" ]]; then error_exit "Instance list '$INSTANCE_NAMES_STRING' yielded no valid names after parsing." $EXIT_CODE_USAGE_ERROR; fi
elif [[ "$OPERATION_MODE" == "install" ]]; then
    if ((${#DEFAULT_INSTANCES[@]} > 0)); then
        PARSED_INSTANCE_NAMES=("${DEFAULT_INSTANCES[@]}")
        info "Using default instances for --install: $(IFS=' '; echo "${PARSED_INSTANCE_NAMES[*]}")"
    else
        debug "No instances specified via -i and no default instances are defined. For --install, this means only base components will be installed/reconfigured if applicable."
    fi
fi


dependency_check
acquire_lock
trap 'error_exit "Script interrupted by SIGINT/SIGTERM." "$EXIT_CODE_FATAL_ERROR"' INT TERM

SOURCE_DIR_ABS="$(realpath -m "$SOURCE_DIR")"
if [[ ! -d "$SOURCE_DIR_ABS" ]]; then error_exit "Source directory not found: '$SOURCE_DIR_ABS' (from '$SOURCE_DIR')." "$EXIT_CODE_FILE_ERROR"; fi
SOURCE_DIR="$SOURCE_DIR_ABS"; debug "Effective source dir: $SOURCE_DIR"
debug "Base config filename: $BASE_CONFIG_FILENAME"

if [[ "$DRY_RUN" != true ]]; then
  confirm_prompt="Proceed with $OPERATION_MODE"
  if ((${#PARSED_INSTANCE_NAMES[@]} > 0)); then confirm_prompt+=" for instances: ($(IFS=','; echo "${PARSED_INSTANCE_NAMES[*]}"))";
  elif [[ "$OPERATION_MODE" == "install" ]]; then confirm_prompt+=" (base components only)"; fi

  if [[ "$OPERATION_MODE" == "update" ]]; then
    if [[ -n "$NEW_BINARY_PATH_ARG" || -n "$NEW_WHEEL_PATH_ARG" ]]; then confirm_prompt+=" (surgical update)"; else confirm_prompt+=" (bundle update)"; fi
    if [[ "$RESTART_SERVICES_ON_UPDATE" == true ]]; then confirm_prompt+=" and restart services"; fi
  fi

  if [[ "$USE_FORCE_FLAG" == true && "$OPERATION_MODE" == "install" ]]; then
    confirm_prompt+=" (forcing instance configuration overwrite)"
  fi

  if [ -t 0 ]; then
    read -r -p "${C_WARN}${confirm_prompt} using source '${SOURCE_DIR}'? [y/N] ${C_RESET}" yn
    case "$yn" in
      [Yy]*) info "User confirmed. Proceeding.";;
      *)
        info "User aborted operation."
        USER_ABORTED=true
        SCRIPT_SUCCESSFUL=false
        exit "$EXIT_CODE_SUCCESS"
        ;;
    esac
  else
    if [[ "$USE_FORCE_FLAG" == true ]]; then
      info "Non-interactive mode (no TTY): Proceeding with operation due to --force flag."
    else
      error_exit "Non-interactive mode (no TTY): Confirmation required. Run interactively or use the --force flag to proceed automatically." "$EXIT_CODE_USAGE_ERROR"
    fi
  fi
fi


main() {
  info "▶ Orchestrator v$VERSION starting (Mode: $OPERATION_MODE)"
  if ! pushd "$SOURCE_DIR" >/dev/null; then error_exit "Failed to change directory to '$SOURCE_DIR'." "$EXIT_CODE_FILE_ERROR" ; fi
  MAIN_PUSHED_DIR=true; debug "Working directory: $(pwd)"

  local effective_config_filename_for_base_install="$BASE_CONFIG_FILENAME"

  # --- Surgical Update Staging (with improved --dry-run) ---
  if [[ "$OPERATION_MODE" == "update" && (-n "$NEW_BINARY_PATH_ARG" || -n "$NEW_WHEEL_PATH_ARG") ]]; then
    info "Preparing for surgical update with externally provided files..."
    local original_config_path_in_bundle="${DEPLOY_SUBDIR_NAME}/${BASE_CONFIG_FILENAME}"

    if [[ ! -f "$original_config_path_in_bundle" ]]; then error_exit "Original base config '$original_config_path_in_bundle' not found in '$DEPLOY_SUBDIR_NAME'. Cannot proceed." "$EXIT_CODE_CONFIG_ERROR"; fi
    if [[ ! -d "$DEPLOY_SUBDIR_NAME" ]]; then error_exit "Deployment subdirectory '$DEPLOY_SUBDIR_NAME' not found. Cannot stage files." "$EXIT_CODE_FILE_ERROR"; fi

    if [[ "$DRY_RUN" == true ]]; then
        # Simulate temp file creation for dry run
        TEMP_CONFIG_FOR_UPDATE="${DEPLOY_SUBDIR_NAME}/install-app.conf.tmp.DRYRUN" # Predictable name for dry-run
        info "[DRY-RUN] Would use temporary config for update: $TEMP_CONFIG_FOR_UPDATE"
        info "[DRY-RUN] Would copy '$original_config_path_in_bundle' to '$TEMP_CONFIG_FOR_UPDATE'"
        # Touch placeholder for sed simulation and trap cleanup
        touch "$TEMP_CONFIG_FOR_UPDATE" || warn "[DRY-RUN] Failed to touch placeholder '$TEMP_CONFIG_FOR_UPDATE'."
        # Attempt to get a real-ish absolute path for the placeholder
        if [[ -e "$TEMP_CONFIG_FOR_UPDATE" ]]; then ABSOLUTE_TEMP_CONFIG_FOR_UPDATE="$(realpath "$TEMP_CONFIG_FOR_UPDATE")"; else ABSOLUTE_TEMP_CONFIG_FOR_UPDATE="${SOURCE_DIR}/${TEMP_CONFIG_FOR_UPDATE}"; fi
    else
        TEMP_CONFIG_FOR_UPDATE="$(mktemp "${DEPLOY_SUBDIR_NAME}/install-app.conf.tmp.XXXXXX")" || error_exit "Failed to create temporary config file in ${DEPLOY_SUBDIR_NAME}." "$EXIT_CODE_FILE_ERROR"
        ABSOLUTE_TEMP_CONFIG_FOR_UPDATE="$(realpath "$TEMP_CONFIG_FOR_UPDATE")"
        cp "$original_config_path_in_bundle" "$TEMP_CONFIG_FOR_UPDATE" || error_exit "Failed to copy '$original_config_path_in_bundle' to '$TEMP_CONFIG_FOR_UPDATE'." "$EXIT_CODE_FILE_ERROR"
    fi
    debug "Effective temp config for update: $TEMP_CONFIG_FOR_UPDATE (abs for trap: $ABSOLUTE_TEMP_CONFIG_FOR_UPDATE)"

    _stage_component "NEW_BINARY_PATH_ARG" "VERSIONED_APP_BINARY_FILENAME" STAGED_NEW_BINARY_FILENAME ABSOLUTE_STAGED_NEW_BINARY_PATH
    _stage_component "NEW_WHEEL_PATH_ARG" "VERSIONED_DATAMOVER_WHEEL_FILENAME" STAGED_NEW_WHEEL_FILENAME ABSOLUTE_STAGED_NEW_WHEEL_PATH
    effective_config_filename_for_base_install="$(basename "$TEMP_CONFIG_FOR_UPDATE")" # Will be predictable in dry-run
    debug "Using effective config for base install: $effective_config_filename_for_base_install"
  fi

  debug "Verifying required files..."
  local file_to_check_main
  for file_to_check_main in "${SCRIPTS_TO_CHECK[@]}"; do
      # For dry run, the existence of sub-scripts is still important.
      [[ -f "$file_to_check_main" ]] || error_exit "Missing required script: $(pwd)/$file_to_check_main" "$EXIT_CODE_FILE_ERROR"
  done
  # For effective_config_filename_for_base_install, it would be a placeholder in dry-run surgical update.
  if [[ "$DRY_RUN" == true && "$OPERATION_MODE" == "update" && (-n "$NEW_BINARY_PATH_ARG" || -n "$NEW_WHEEL_PATH_ARG") ]]; then
    [[ -e "${DEPLOY_SUBDIR_NAME}/${effective_config_filename_for_base_install}" ]] || warn "[DRY-RUN] Placeholder for effective base config not found: ${DEPLOY_SUBDIR_NAME}/${effective_config_filename_for_base_install}"
  else
    [[ -f "${DEPLOY_SUBDIR_NAME}/${effective_config_filename_for_base_install}" ]] || error_exit "Effective base configuration file not found: ${DEPLOY_SUBDIR_NAME}/${effective_config_filename_for_base_install}" "$EXIT_CODE_CONFIG_ERROR"
  fi
  debug "Required files check complete."


  debug "Ensuring sub-scripts are executable..."
  for script_to_make_exec_main in "${SCRIPTS_TO_CHECK[@]}"; do
    if ! run chmod +x "$script_to_make_exec_main"; then
        # run() handles DRY_RUN output, increments FAIL_COUNT, and logs warning.
        # Making chmod failure fatal as sub-scripts won't run otherwise.
        error_exit "Failed to make sub-script '$script_to_make_exec_main' executable. Check permissions." "$EXIT_CODE_FILE_ERROR"
    fi
  done


  info "▶ Running base installer/updater (${DEPLOY_SUBDIR_NAME}/install_base_exportcliv2.sh)..."
  local base_install_cmd_array_main=()
  base_install_cmd_array_main+=("./${DEPLOY_SUBDIR_NAME}/install_base_exportcliv2.sh")
  base_install_cmd_array_main+=("-c" "$effective_config_filename_for_base_install")
  if [[ "$DRY_RUN" == true ]]; then base_install_cmd_array_main+=("-n"); fi
  if [[ "$VERBOSE_MODE" == true ]]; then base_install_cmd_array_main+=("-v"); fi

  if ! run "${base_install_cmd_array_main[@]}"; then
    error_exit "Base installer script '${DEPLOY_SUBDIR_NAME}/install_base_exportcliv2.sh' failed. Orchestration aborted." "$EXIT_CODE_FATAL_ERROR"
  fi


  if [[ "$OPERATION_MODE" == "update" && (-n "$NEW_BINARY_PATH_ARG" || -n "$NEW_WHEEL_PATH_ARG") ]]; then
    # Cleanup of staged files (placeholders in dry-run) is best-effort here; trap is the primary mechanism.
    if [[ -n "$STAGED_NEW_BINARY_FILENAME" && -e "${DEPLOY_SUBDIR_NAME}/${STAGED_NEW_BINARY_FILENAME}" ]]; then
        local staged_bin_path_to_remove="${DEPLOY_SUBDIR_NAME}/${STAGED_NEW_BINARY_FILENAME}"
        if [[ "$DRY_RUN" == true ]]; then
            info "[DRY-RUN] Would remove staged binary placeholder: $staged_bin_path_to_remove" # Corrected
        else
            debug "Main: Removing staged binary after use: $staged_bin_path_to_remove"
            rm -f "$staged_bin_path_to_remove"
        fi
    fi
    if [[ -n "$STAGED_NEW_WHEEL_FILENAME" && -e "${DEPLOY_SUBDIR_NAME}/${STAGED_NEW_WHEEL_FILENAME}" ]]; then
        local staged_wheel_path_to_remove="${DEPLOY_SUBDIR_NAME}/${STAGED_NEW_WHEEL_FILENAME}"
        if [[ "$DRY_RUN" == true ]]; then
            info "[DRY-RUN] Would remove staged wheel placeholder: $staged_wheel_path_to_remove" # Corrected
        else
            debug "Main: Removing staged wheel after use: $staged_wheel_path_to_remove"
            rm -f "$staged_wheel_path_to_remove"
        fi
    fi
    # TEMP_CONFIG_FOR_UPDATE (placeholder in dry-run) is removed by the EXIT trap.
  fi


  if [[ "$OPERATION_MODE" == "install" ]]; then
    if ((${#PARSED_INSTANCE_NAMES[@]} > 0)); then
      info "▶ Configuring instances..."
      for instance_name in "${PARSED_INSTANCE_NAMES[@]}"; do
        info "--- Configuring instance: $instance_name ---"
        local config_cmd_array=()
        config_cmd_array+=("./${DEPLOY_SUBDIR_NAME}/configure_instance.sh")
        config_cmd_array+=("-i" "$instance_name")
        if [[ "$DRY_RUN" == true ]]; then config_cmd_array+=("-n"); fi
        if [[ "$VERBOSE_MODE" == true ]]; then config_cmd_array+=("-v"); fi
        if [[ "$USE_FORCE_FLAG" == true ]]; then config_cmd_array+=("--force"); fi

        if ! run "${config_cmd_array[@]}"; then
            info "Instance '$instance_name' configuration failed (or would fail in dry-run). Continuing with other instances if any."
        fi
      done
    else
      info "No specific instances to configure (either none specified via -i for --install, or no defaults defined)."
    fi

    info "▶ Setting up services for initial install..."
    local manage_opts_install=()
    if [[ "$DRY_RUN" == true ]]; then manage_opts_install+=("-n"); fi
    if [[ "$VERBOSE_MODE" == true ]]; then manage_opts_install+=("-v"); fi

    if ((${#PARSED_INSTANCE_NAMES[@]} > 0)); then
        for instance_name in "${PARSED_INSTANCE_NAMES[@]}"; do
            info "--- Enabling services for instance: $instance_name ---"
            if ! run "./${DEPLOY_SUBDIR_NAME}/manage_services.sh" "${manage_opts_install[@]}" -i "$instance_name" --enable; then
                info "Failed to enable services (or would fail in dry-run) for instance '$instance_name'. Check logs. Will attempt to start."
            fi
            info "--- Starting services for instance: $instance_name ---"
            if ! run "./${DEPLOY_SUBDIR_NAME}/manage_services.sh" "${manage_opts_install[@]}" -i "$instance_name" --start; then
                info "Failed to start services (or would fail in dry-run) for instance '$instance_name'. Check logs."
            fi
        done
        info "Instance service status can be checked using: ./${DEPLOY_SUBDIR_NAME}/manage_services.sh -i \"INSTANCE_NAME\" --status"
    else
        info "--- Enabling main Bitmover service (if applicable to base install) ---"
        if ! run "./${DEPLOY_SUBDIR_NAME}/manage_services.sh" "${manage_opts_install[@]}" --enable; then
             info "Failed to enable main Bitmover service (or would fail in dry-run). Check logs. Will attempt to start."
        fi
        info "--- Starting main Bitmover service (if applicable to base install) ---"
        if ! run "./${DEPLOY_SUBDIR_NAME}/manage_services.sh" "${manage_opts_install[@]}" --start; then
             info "Failed to start main Bitmover service (or would fail in dry-run). Check logs."
        fi
        info "Main service status can be checked using: ./${DEPLOY_SUBDIR_NAME}/manage_services.sh --status"
    fi
    info "Service setup attempts complete. Review output for any failures."

  elif [[ "$OPERATION_MODE" == "update" ]]; then
    info "▶ Base update processing complete."
    if [[ "$RESTART_SERVICES_ON_UPDATE" == true ]]; then
      info "▶ Restarting services due to --restart-services flag..."
      local manage_opts_update=()
      if [[ "$DRY_RUN" == true ]]; then manage_opts_update+=("-n"); fi
      if [[ "$VERBOSE_MODE" == true ]]; then manage_opts_update+=("-v"); fi

      if ((${#PARSED_INSTANCE_NAMES[@]} > 0)); then
          for instance_name in "${PARSED_INSTANCE_NAMES[@]}"; do
              info "--- Restarting services for specified instance: $instance_name ---"
              if ! run "./${DEPLOY_SUBDIR_NAME}/manage_services.sh" "${manage_opts_update[@]}" -i "$instance_name" --restart; then
                  info "Failed to restart services (or would fail in dry-run) for instance '$instance_name'. Check logs."
              fi
          done
      else
          info "--- Restarting main Bitmover service(s) ---"
          if ! run "./${DEPLOY_SUBDIR_NAME}/manage_services.sh" "${manage_opts_update[@]}" --restart; then
              info "Failed to restart main Bitmover service(s) (or would fail in dry-run). Check logs."
          fi
          warn "Note: If only main Bitmover service was targeted for restart, application instances might need separate attention or use of '-i <instance>' with manage_services.sh."
      fi
      info "Service restart attempts complete. Review output for any failures."
    else
      info "Services not automatically restarted. Use './${DEPLOY_SUBDIR_NAME}/manage_services.sh' or the -r option with this script during update."
    fi
  fi
  SCRIPT_SUCCESSFUL=true
}

# --- Script Entry Point & Final Exit Logic ---
main "$@"

if [[ "$DRY_RUN" == true ]]; then
    info "[DRY-RUN] Orchestration dry run scan completed."
fi

if [[ "$SCRIPT_SUCCESSFUL" == true ]]; then
    if (( FAIL_COUNT > 0 )); then
        exit "$EXIT_CODE_PARTIAL_SUCCESS"
    fi
    exit "$EXIT_CODE_SUCCESS"
fi
