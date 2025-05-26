#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# -----------------------------------------------------------------------------
# v2.4.6 Deployment Orchestrator
# - DEFAULT_INSTANCES now loaded from install-app.conf (DEFAULT_INSTANCES_CONFIG)
#   and is mandatory if -i is not used with --install.
# - --list-default-instances now reads from the effective config file.
# - Removed -r/--restart-services option for --update mode.
# -----------------------------------------------------------------------------
VERSION="2.4.6" # DEFAULT_INSTANCES from config, mandatory for default install

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
# DEFAULT_INSTANCES=(AAA BBB CCC) # Removed hardcoding
EFFECTIVE_DEFAULT_INSTANCES_ARRAY=() # Will be populated from config
INSTANCE_NAMES_STRING=""
PARSED_INSTANCE_NAMES=()
DRY_RUN=false
VERBOSE_MODE=false
OPERATION_MODE=""
USE_FORCE_FLAG=false

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
LIST_DEFAULTS_REQUESTED=false # Flag for --list-default-instances

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
  local cmds_to_check=(flock date chmod dirname basename readlink realpath mktemp cp sed touch)
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
  # Master exit trap is now set *after* config sourcing if --list-defaults is not used,
  # or within list_defaults if it exits early.
  # For now, set it here, and list_defaults will also call _master_exit_trap manually if it exits.
  # Simpler: let _master_exit_trap handle HELP_OR_VERSION_EXIT.
  trap _master_exit_trap EXIT
}

# --- Master Exit Trap ---
_master_exit_trap() {
    local final_exit_code=$?
    if [[ "$MAIN_PUSHED_DIR" == true ]]; then # Should only be true if main() was entered
        if popd >/dev/null 2>&1; then
            debug "Trap: Returned from source directory. Original PWD: $(pwd)"
        else
            warn "Trap: Failed to popd from source directory. Current PWD: $(pwd)"
        fi
        MAIN_PUSHED_DIR=false
    fi

    if [[ -n "$ABSOLUTE_TEMP_CONFIG_FOR_UPDATE" && -e "$ABSOLUTE_TEMP_CONFIG_FOR_UPDATE" ]]; then
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
    # _final_summary_message needs to be called unless we exited due to help/version/list_defaults flags already handled.
    if [[ "$HELP_OR_VERSION_EXIT" != true ]] ; then
      _final_summary_message "$final_exit_code"
    fi
}

# --- _final_summary_message ---
_final_summary_message() {
    local exit_code="$1"
    # This check is now in _master_exit_trap
    # if [[ "$HELP_OR_VERSION_EXIT" == true ]]; then return; fi
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
    # No explicit exit here; let the EXIT trap handle the final summary if set -e causes exit.
    # Or, if we want ERR to be the primary exit point for errors:
    exit "${exit_code:-$EXIT_CODE_FATAL_ERROR}"
}
trap 'cleanup_on_error "$?" "$LINENO" "$BASH_COMMAND"' ERR

# --- Helpers (run, _stage_component) ---
run() {
  local cmd_array=("$@"); local cmd_display; printf -v cmd_display '%q ' "${cmd_array[@]}";
  debug "Executing: $cmd_display"
  if [[ "$DRY_RUN" == true ]]; then info "[DRY-RUN] Would execute: $cmd_display"; return "$EXIT_CODE_SUCCESS"; fi
  "${cmd_array[@]}"; local ec=$?;
  if [[ $ec -ne 0 ]]; then _log_msg "WARN" "Command failed with exit code $ec: $cmd_display"; ((FAIL_COUNT++)); return $ec; fi
  return "$EXIT_CODE_SUCCESS"
}
_stage_component() {
    local src_path_var_name="$1"; local config_key_name="$2"; local -n staged_filename_ref="$3"; local -n abs_staged_path_ref="$4";
    local src_path="${!src_path_var_name}";
    if [[ -z "$src_path" ]]; then debug "No source path provided via '$src_path_var_name' for '$config_key_name', skipping."; return 0; fi
    staged_filename_ref=$(basename "$src_path"); local target_staged_relative_path="${DEPLOY_SUBDIR_NAME}/${staged_filename_ref}";
    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] Would copy '$src_path' to '$target_staged_relative_path'.";
        touch "$target_staged_relative_path" || warn "[DRY-RUN] Failed to touch placeholder '$target_staged_relative_path'.";
    else
        cp "$src_path" "$target_staged_relative_path" || error_exit "Failed to copy '$src_path' to '$target_staged_relative_path'." "$EXIT_CODE_FILE_ERROR";
    fi
    if [[ -e "$target_staged_relative_path" ]]; then abs_staged_path_ref="$(realpath "$target_staged_relative_path")";
    else abs_staged_path_ref="${SOURCE_DIR}/${target_staged_relative_path}"; # Assuming SOURCE_DIR is absolute here
         if [[ "$DRY_RUN" != true ]]; then warn "Could not find staged file '$target_staged_relative_path' for realpath.";
         else debug "[DRY-RUN] Placeholder '$target_staged_relative_path' not found for realpath."; fi; fi
    debug "Staged '$src_path' as '$target_staged_relative_path' (abs for trap: '$abs_staged_path_ref')"
    local sed_expression="s|^(\\s*${config_key_name}\\s*=\\s*).*|\\1\"${staged_filename_ref}\"|";
    if [[ "$DRY_RUN" == true ]]; then info "[DRY-RUN] Would update '$config_key_name' in '$TEMP_CONFIG_FOR_UPDATE' to '$staged_filename_ref'.";
    else sed -i -E "$sed_expression" "$TEMP_CONFIG_FOR_UPDATE" || error_exit "Failed to update '$config_key_name' in '$TEMP_CONFIG_FOR_UPDATE'." "$EXIT_CODE_FILE_ERROR"; fi
    debug "Updated '$config_key_name' in '$TEMP_CONFIG_FOR_UPDATE' to '$staged_filename_ref'"; return 0
}

# --- Usage ---
usage() {
  local exit_code="${1:-$EXIT_CODE_USAGE_ERROR}"
  if [[ "$exit_code" -eq "$EXIT_CODE_SUCCESS" ]]; then HELP_OR_VERSION_EXIT=true; fi
  local script_basename; script_basename=$(basename "$0")
  local current_dir_display; current_dir_display=$(pwd) # Current dir at time of usage call

  cat <<EOF
Usage: $script_basename [OPTIONS] --install|--update

Description:
  Orchestrates the installation or update of the ExportCLIv2 suite.
  This script is typically run from the root of an unpacked suite bundle.
  Service status checking is handled by '${DEPLOY_SUBDIR_NAME}/manage_services.sh'.

Modes (one is required):
  --install                 Performs a fresh installation or adds/reconfigures instances.
                            If '-i' is not used, default instances are taken from
                            'DEFAULT_INSTANCES_CONFIG' in '${BASE_CONFIG_FILENAME}', which is mandatory.
                            Use '--force' to overwrite existing instance configurations or to
                            auto-confirm in non-interactive (non-TTY) environments.
  --update                  Updates core application components (e.g., main binary, datamover wheel).
                            Default: Uses components from the current '--source-dir'.
                            Surgical Updates: Use with --new-binary or --new-wheel.
                            Use '--force' to auto-confirm in non-interactive (non-TTY) environments.
                            NOTE: After an update, services must be restarted manually using 'exportcli-manage'.

General Options:
  -s, --source-dir DIR      Path to the unpacked source tree. Default: '$current_dir_display'.
  -c, --config FILE         Base install config filename (in 'source-dir/${DEPLOY_SUBDIR_NAME}/').
                            Default: '${BASE_CONFIG_FILENAME}'.
                            This file also defines 'DEFAULT_INSTANCES_CONFIG'.
  -i, --instances "LIST"    Comma-separated list of instance names (e.g., "inst1,inst2").
                            Overrides 'DEFAULT_INSTANCES_CONFIG' from config file for --install.
  --new-binary ABS_PATH     (With --update) Absolute path to a new application binary.
  --new-wheel ABS_PATH      (With --update) Absolute path to a new datamover wheel.
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
  sudo $script_basename --install

  # Install specific instances, forcing overwrite if they exist:
  sudo $script_basename --install -i "instance_A,instance_B" --force

  # Update using components from a new bundle (run from new bundle dir):
  sudo $script_basename --update
  # Then manually restart services as needed.

  # List default instances from config file in current source dir:
  $script_basename --list-default-instances

  # List default instances from config file in a specific source dir:
  $script_basename --list-default-instances -s /path/to/bundle -c custom.conf

Exit codes: (0:Success, 1:Fatal, 2:Partial, 3:Usage, 4:Config, 5:Prereq, 6:FileOp)
EOF
  exit "$exit_code"
}

# --- Argument Parsing ---
for arg_pre_scan in "$@"; do # Quick pre-scan for immediate exits
  case "$arg_pre_scan" in
    --version) echo "$(basename "$0") v$VERSION"; HELP_OR_VERSION_EXIT=true; exit "$EXIT_CODE_SUCCESS";;
    -h|--help) usage "$EXIT_CODE_SUCCESS";;
    # --list-default-instances is handled after full arg parsing to get correct config file
  esac
done

TEMP_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --install) OPERATION_MODE="install"; shift ;;
    --update) OPERATION_MODE="update"; shift ;;
    -s|--source-dir) if [[ -z "${2:-}" ]]; then error_exit "$1 requires an argument." $EXIT_CODE_USAGE_ERROR; fi; SOURCE_DIR="$2"; shift 2 ;;
    -c|--config) if [[ -z "${2:-}" ]]; then error_exit "$1 requires an argument." $EXIT_CODE_USAGE_ERROR; fi; BASE_CONFIG_FILENAME="$2"; shift 2 ;;
    -i|--instances) if [[ -z "${2:-}" ]]; then error_exit "$1 requires an argument." $EXIT_CODE_USAGE_ERROR; fi; INSTANCE_NAMES_STRING="$2"; shift 2 ;;
    --new-binary) if [[ -z "${2:-}" || "$2" == -* ]]; then error_exit "$1 abs path arg." $EXIT_CODE_USAGE_ERROR; fi; if [[ "$2" != /* ]]; then error_exit "$1 path must be abs: $2" $EXIT_CODE_USAGE_ERROR; fi; NEW_BINARY_PATH_ARG="$2"; shift 2 ;;
    --new-wheel) if [[ -z "${2:-}" || "$2" == -* ]]; then error_exit "$1 abs path arg." $EXIT_CODE_USAGE_ERROR; fi; if [[ "$2" != /* ]]; then error_exit "$1 path must be abs: $2" $EXIT_CODE_USAGE_ERROR; fi; NEW_WHEEL_PATH_ARG="$2"; shift 2 ;;
    --force) USE_FORCE_FLAG=true; shift ;;
    -n|--dry-run) DRY_RUN=true; shift ;;
    -v|--verbose) VERBOSE_MODE=true; shift ;;
    --list-default-instances) LIST_DEFAULTS_REQUESTED=true; shift;; # Set flag
    *) TEMP_ARGS+=("$1"); shift ;;
  esac
done

if (( ${#TEMP_ARGS[@]} > 0 )); then error_exit "Unknown option specified: ${TEMP_ARGS[0]}" $EXIT_CODE_USAGE_ERROR; fi
# OPERATION_MODE check deferred until after list-defaults might exit

# --- Resolve Paths and Source Configuration (needed for --list-default-instances and main operation) ---
# Ensure SOURCE_DIR is absolute for reliable operations
SOURCE_DIR_ABS_RESOLVED="$(realpath -m "$SOURCE_DIR")" || error_exit "Failed to resolve source directory path: '$SOURCE_DIR'" "$EXIT_CODE_FILE_ERROR"
if [[ ! -d "$SOURCE_DIR_ABS_RESOLVED" ]]; then error_exit "Source directory not found: '$SOURCE_DIR_ABS_RESOLVED' (from '$SOURCE_DIR')." "$EXIT_CODE_FILE_ERROR"; fi
# Use the resolved absolute path henceforth for sourcing config
INSTALL_APP_CONF_FULL_PATH="${SOURCE_DIR_ABS_RESOLVED}/${DEPLOY_SUBDIR_NAME}/${BASE_CONFIG_FILENAME}"

if [[ ! -f "$INSTALL_APP_CONF_FULL_PATH" ]]; then
    error_exit "Base configuration file '$BASE_CONFIG_FILENAME' not found at '$INSTALL_APP_CONF_FULL_PATH'." "$EXIT_CODE_CONFIG_ERROR"
fi

debug "Sourcing application configuration from: $INSTALL_APP_CONF_FULL_PATH"
# Clear potentially conflicting variables before sourcing
unset DEFAULT_INSTANCES_CONFIG
# shellcheck source=/dev/null
source "$INSTALL_APP_CONF_FULL_PATH" || error_exit "Failed to source configuration file: '$INSTALL_APP_CONF_FULL_PATH'." "$EXIT_CODE_CONFIG_ERROR"

# Populate EFFECTIVE_DEFAULT_INSTANCES_ARRAY from sourced config
if [[ -n "${DEFAULT_INSTANCES_CONFIG:-}" ]]; then
    IFS=' ' read -r -a EFFECTIVE_DEFAULT_INSTANCES_ARRAY <<< "$DEFAULT_INSTANCES_CONFIG"
    # Validate default instance names
    for inst_name in "${EFFECTIVE_DEFAULT_INSTANCES_ARRAY[@]}"; do
        if ! [[ "$inst_name" =~ ^[A-Za-z0-9._-]+$ ]]; then
            error_exit "Invalid default instance name format in DEFAULT_INSTANCES_CONFIG ('$inst_name') from '$INSTALL_APP_CONF_FULL_PATH'." "$EXIT_CODE_CONFIG_ERROR"
        fi
    done
fi
# If DEFAULT_INSTANCES_CONFIG was empty string, array will be empty. If unset, array will be empty.

# Handle --list-default-instances now that config is sourced
if [[ "$LIST_DEFAULTS_REQUESTED" == true ]]; then
  echo "Default instances configured in '${INSTALL_APP_CONF_FULL_PATH}' (via DEFAULT_INSTANCES_CONFIG):"
  if ((${#EFFECTIVE_DEFAULT_INSTANCES_ARRAY[@]} > 0)); then
    echo "  $(IFS=' '; echo "${EFFECTIVE_DEFAULT_INSTANCES_ARRAY[*]}")"
  else
    echo "  (None specified or list is empty)"
    # Note: This being empty will be an error later if --install is used without -i
  fi
  HELP_OR_VERSION_EXIT=true; exit "$EXIT_CODE_SUCCESS"
fi

# Now validate operation mode after list-defaults has had a chance to exit
if [[ -z "$OPERATION_MODE" ]]; then error_exit "Operation mode --install or --update is required." $EXIT_CODE_USAGE_ERROR; fi
info "Operation Mode: $OPERATION_MODE"
# Update effective SOURCE_DIR to absolute path for main logic
SOURCE_DIR="$SOURCE_DIR_ABS_RESOLVED"


# Further argument validation and instance name processing
if [[ -n "$NEW_BINARY_PATH_ARG" || -n "$NEW_WHEEL_PATH_ARG" ]]; then
  if [[ "$OPERATION_MODE" != "update" ]]; then error_exit "--new-binary/--new-wheel can only be used with --update mode." $EXIT_CODE_USAGE_ERROR; fi
  if [[ -n "$NEW_BINARY_PATH_ARG" && ! -f "$NEW_BINARY_PATH_ARG" ]]; then error_exit "New binary file not found: $NEW_BINARY_PATH_ARG" $EXIT_CODE_FILE_ERROR; fi
  if [[ -n "$NEW_WHEEL_PATH_ARG" && ! -f "$NEW_WHEEL_PATH_ARG" ]]; then error_exit "New wheel file not found: $NEW_WHEEL_PATH_ARG" $EXIT_CODE_FILE_ERROR; fi
  info "Surgical update with external components requested."
fi
if [[ "$VERBOSE_MODE" == true ]]; then info "Verbose mode enabled."; set -x; fi # set -x here after all initial setup and sourcing

# Populate PARSED_INSTANCE_NAMES based on -i or defaults from config
if [[ -n "$INSTANCE_NAMES_STRING" ]]; then # -i was used
    IFS=',' read -r -a temp_instance_array <<< "$INSTANCE_NAMES_STRING"
    PARSED_INSTANCE_NAMES=() # Reset
    trimmed_inst=""
    for i in "${!temp_instance_array[@]}"; do
        trimmed_inst="${temp_instance_array[$i]#${temp_instance_array[$i]%%[![:space:]]*}}" # Trim leading whitespace
        trimmed_inst="${trimmed_inst%${trimmed_inst##*[![:space:]]}}" # Trim trailing whitespace
        if [[ -n "$trimmed_inst" ]]; then
            if ! [[ "$trimmed_inst" =~ ^[A-Za-z0-9._-]+$ ]]; then error_exit "Invalid instance name format in -i list: '$trimmed_inst'." $EXIT_CODE_USAGE_ERROR; fi
            PARSED_INSTANCE_NAMES+=("$trimmed_inst")
        elif [[ "${#temp_instance_array[@]}" -gt 1 || -n "${temp_instance_array[$i]}" ]]; then
             error_exit "Empty instance name detected in -i list: '$INSTANCE_NAMES_STRING'" $EXIT_CODE_USAGE_ERROR
        fi
    done
    if ((${#PARSED_INSTANCE_NAMES[@]} > 0)); then info "Operating on specified instances from -i: $(IFS=' '; echo "${PARSED_INSTANCE_NAMES[*]}")";
    elif [[ -n "$INSTANCE_NAMES_STRING" ]]; then error_exit "Instance list '$INSTANCE_NAMES_STRING' from -i yielded no valid names." $EXIT_CODE_USAGE_ERROR; fi
elif [[ "$OPERATION_MODE" == "install" ]]; then # No -i, and it's an install op
    if ((${#EFFECTIVE_DEFAULT_INSTANCES_ARRAY[@]} > 0)); then
        PARSED_INSTANCE_NAMES=("${EFFECTIVE_DEFAULT_INSTANCES_ARRAY[@]}")
        info "Using default instances from config file for --install: $(IFS=' '; echo "${PARSED_INSTANCE_NAMES[*]}")"
    else
        # DEFAULT_INSTANCES_CONFIG is mandatory if -i is not used with --install
        error_exit "DEFAULT_INSTANCES_CONFIG in '$INSTALL_APP_CONF_FULL_PATH' is mandatory and must not be empty when using --install without the -i flag." "$EXIT_CODE_CONFIG_ERROR"
    fi
fi


dependency_check
acquire_lock # This sets the main EXIT trap
trap 'error_exit "Script interrupted by SIGINT/SIGTERM." "$EXIT_CODE_FATAL_ERROR"' INT TERM


# --- Confirmation Prompt ---
# (Logic for confirmation prompt remains largely the same, uses PARSED_INSTANCE_NAMES)
if [[ "$DRY_RUN" != true ]]; then
  confirm_prompt="Proceed with $OPERATION_MODE"
  if ((${#PARSED_INSTANCE_NAMES[@]} > 0)); then confirm_prompt+=" for instances: ($(IFS=','; echo "${PARSED_INSTANCE_NAMES[*]}"))";
  elif [[ "$OPERATION_MODE" == "install" ]]; then confirm_prompt+=" (base components only - implies no default instances were configured, which should have been an error)"; fi # This case should be rare now

  if [[ "$OPERATION_MODE" == "update" ]]; then
    if [[ -n "$NEW_BINARY_PATH_ARG" || -n "$NEW_WHEEL_PATH_ARG" ]]; then confirm_prompt+=" (surgical update)"; else confirm_prompt+=" (bundle update)"; fi
  fi

  if [[ "$USE_FORCE_FLAG" == true && "$OPERATION_MODE" == "install" ]]; then
    confirm_prompt+=" (forcing instance configuration overwrite)"
  fi

  if [ -t 0 ]; then # Check if running in a TTY for prompt
    read -r -p "${C_WARN}${confirm_prompt} using source '${SOURCE_DIR}'? [y/N] ${C_RESET}" yn
    case "$yn" in
      [Yy]*) info "User confirmed. Proceeding.";;
      *) info "User aborted operation."; USER_ABORTED=true; SCRIPT_SUCCESSFUL=false; exit "$EXIT_CODE_SUCCESS";; # Exit trap will not show standard summary
    esac
  else # Non-interactive
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
  # SOURCE_DIR is already absolute
  if ! pushd "$SOURCE_DIR" >/dev/null; then error_exit "Failed to change directory to '$SOURCE_DIR'." "$EXIT_CODE_FILE_ERROR" ; fi
  MAIN_PUSHED_DIR=true; debug "Working directory: $(pwd)"

  # effective_config_filename_for_base_install is relative to SCRIPT_DIR of install_base_exportcliv2.sh
  # which is ${DEPLOY_SUBDIR_NAME} inside the current SOURCE_DIR
  local effective_config_filename_for_base_install_rel_to_subscript_dir="$BASE_CONFIG_FILENAME"

  if [[ "$OPERATION_MODE" == "update" && (-n "$NEW_BINARY_PATH_ARG" || -n "$NEW_WHEEL_PATH_ARG") ]]; then
    info "Preparing for surgical update with externally provided files..."
    # original_config_path_in_bundle is relative to current SOURCE_DIR
    local original_config_path_in_bundle="${DEPLOY_SUBDIR_NAME}/${BASE_CONFIG_FILENAME}"

    if [[ ! -f "$original_config_path_in_bundle" ]]; then error_exit "Original base config '$original_config_path_in_bundle' not found. Cannot proceed." "$EXIT_CODE_CONFIG_ERROR"; fi
    if [[ ! -d "$DEPLOY_SUBDIR_NAME" ]]; then error_exit "Deployment subdirectory '$DEPLOY_SUBDIR_NAME' not found." "$EXIT_CODE_FILE_ERROR"; fi

    if [[ "$DRY_RUN" == true ]]; then
        TEMP_CONFIG_FOR_UPDATE="${DEPLOY_SUBDIR_NAME}/install-app.conf.tmp.DRYRUN"
        info "[DRY-RUN] Would use temporary config for update: $TEMP_CONFIG_FOR_UPDATE"
        info "[DRY_RUN] Would copy '$original_config_path_in_bundle' to '$TEMP_CONFIG_FOR_UPDATE'"
        touch "$TEMP_CONFIG_FOR_UPDATE" || warn "[DRY-RUN] Failed to touch placeholder '$TEMP_CONFIG_FOR_UPDATE'."
        if [[ -e "$TEMP_CONFIG_FOR_UPDATE" ]]; then ABSOLUTE_TEMP_CONFIG_FOR_UPDATE="$(realpath "$TEMP_CONFIG_FOR_UPDATE")"; else ABSOLUTE_TEMP_CONFIG_FOR_UPDATE="${SOURCE_DIR}/${TEMP_CONFIG_FOR_UPDATE}"; fi
    else
        TEMP_CONFIG_FOR_UPDATE="$(mktemp "./${DEPLOY_SUBDIR_NAME}/install-app.conf.tmp.XXXXXX")" || error_exit "Failed to create temporary config file in ./${DEPLOY_SUBDIR_NAME}." "$EXIT_CODE_FILE_ERROR"
        ABSOLUTE_TEMP_CONFIG_FOR_UPDATE="$(realpath "$TEMP_CONFIG_FOR_UPDATE")"
        cp "$original_config_path_in_bundle" "$TEMP_CONFIG_FOR_UPDATE" || error_exit "Failed to copy '$original_config_path_in_bundle' to '$TEMP_CONFIG_FOR_UPDATE'." "$EXIT_CODE_FILE_ERROR"
    fi
    debug "Effective temp config for update: $TEMP_CONFIG_FOR_UPDATE (abs for trap: $ABSOLUTE_TEMP_CONFIG_FOR_UPDATE)"

    _stage_component "NEW_BINARY_PATH_ARG" "VERSIONED_APP_BINARY_FILENAME" STAGED_NEW_BINARY_FILENAME ABSOLUTE_STAGED_NEW_BINARY_PATH
    _stage_component "NEW_WHEEL_PATH_ARG" "VERSIONED_DATAMOVER_WHEEL_FILENAME" STAGED_NEW_WHEEL_FILENAME ABSOLUTE_STAGED_NEW_WHEEL_PATH
    effective_config_filename_for_base_install_rel_to_subscript_dir="$(basename "$TEMP_CONFIG_FOR_UPDATE")"
    debug "Using effective config for base install (relative to sub-script dir): $effective_config_filename_for_base_install_rel_to_subscript_dir"
  fi

  debug "Verifying required files..."
  local file_to_check_main
  for file_to_check_main in "${SCRIPTS_TO_CHECK[@]}"; do
      [[ -f "$file_to_check_main" ]] || error_exit "Missing required script: $(pwd)/$file_to_check_main" "$EXIT_CODE_FILE_ERROR"
  done
  # Check for the config file that install_base_exportcliv2.sh will use
  local base_install_config_to_check="${DEPLOY_SUBDIR_NAME}/${effective_config_filename_for_base_install_rel_to_subscript_dir}"
  if [[ "$DRY_RUN" == true && "$OPERATION_MODE" == "update" && (-n "$NEW_BINARY_PATH_ARG" || -n "$NEW_WHEEL_PATH_ARG") ]]; then
    [[ -e "$base_install_config_to_check" ]] || warn "[DRY-RUN] Placeholder for effective base config not found: $base_install_config_to_check"
  else
    [[ -f "$base_install_config_to_check" ]] || error_exit "Effective base configuration file not found: $base_install_config_to_check" "$EXIT_CODE_CONFIG_ERROR"
  fi
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
  base_install_cmd_array_main+=("-c" "$effective_config_filename_for_base_install_rel_to_subscript_dir") # Pass relative name
  if [[ "$DRY_RUN" == true ]]; then base_install_cmd_array_main+=("-n"); fi
  if [[ "$VERBOSE_MODE" == true ]]; then base_install_cmd_array_main+=("-v"); fi
  base_install_cmd_array_main+=("--operation-type" "$OPERATION_MODE")

  if ! run "${base_install_cmd_array_main[@]}"; then
    error_exit "Base installer script '${DEPLOY_SUBDIR_NAME}/install_base_exportcliv2.sh' failed." "$EXIT_CODE_FATAL_ERROR"
  fi

  if [[ "$OPERATION_MODE" == "update" && (-n "$NEW_BINARY_PATH_ARG" || -n "$NEW_WHEEL_PATH_ARG") ]]; then
    # Cleanup of staged files (placeholders in dry-run)
    if [[ -n "$STAGED_NEW_BINARY_FILENAME" && -e "${DEPLOY_SUBDIR_NAME}/${STAGED_NEW_BINARY_FILENAME}" ]]; then
        local staged_bin_path_to_remove="${DEPLOY_SUBDIR_NAME}/${STAGED_NEW_BINARY_FILENAME}"
        if [[ "$DRY_RUN" == true ]]; then info "[DRY-RUN] Would remove staged binary placeholder: $staged_bin_path_to_remove";
        else debug "Main: Removing staged binary after use: $staged_bin_path_to_remove"; rm -f "$staged_bin_path_to_remove"; fi
    fi
    if [[ -n "$STAGED_NEW_WHEEL_FILENAME" && -e "${DEPLOY_SUBDIR_NAME}/${STAGED_NEW_WHEEL_FILENAME}" ]]; then
        local staged_wheel_path_to_remove="${DEPLOY_SUBDIR_NAME}/${STAGED_NEW_WHEEL_FILENAME}"
        if [[ "$DRY_RUN" == true ]]; then info "[DRY-RUN] Would remove staged wheel placeholder: $staged_wheel_path_to_remove";
        else debug "Main: Removing staged wheel after use: $staged_wheel_path_to_remove"; rm -f "$staged_wheel_path_to_remove"; fi
    fi
    # TEMP_CONFIG_FOR_UPDATE (placeholder in dry-run) is removed by the EXIT trap.
  fi

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
      info "No specific instances to configure (should not happen if DEFAULT_INSTANCES_CONFIG is mandatory and used)."
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
        info "Instance service status: ./${DEPLOY_SUBDIR_NAME}/manage_services.sh -i \"INSTANCE_NAME\" --status"
    fi
    info "Service setup attempts complete."

  elif [[ "$OPERATION_MODE" == "update" ]]; then
    info "▶ Base update processing complete."
    echo; info "--------------------------------------------------------------------------------";
    info "IMPORTANT: Update complete. Services must be restarted manually for changes to take effect.";
    info "--------------------------------------------------------------------------------";
    info "Use 'sudo exportcli-manage' or 'sudo ./exportcliv2-deploy/manage_services.sh' to manage services.";
    info ""; info "Recommended restart actions based on this update:";
    local wheel_updated_flag=false; local binary_updated_flag=false;
    if [[ -n "$NEW_WHEEL_PATH_ARG" ]]; then wheel_updated_flag=true; fi
    if [[ -n "$NEW_BINARY_PATH_ARG" ]]; then binary_updated_flag=true; fi
    if [[ -z "$NEW_BINARY_PATH_ARG" && -z "$NEW_WHEEL_PATH_ARG" ]]; then # General bundle update
        info "  This was a general bundle update. It's recommended to restart both the main Bitmover service";
        info "  and all active exportcliv2 instances.";
        info "  Examples:";
        info "    sudo exportcli-manage --restart                # For the main Bitmover service";
        info "    sudo exportcli-manage -i <INSTANCE_NAME> --restart # For each exportcliv2 instance";
    else
        if [[ "$wheel_updated_flag" == true ]]; then
            info "  The Datamover wheel was updated. Restart the main Bitmover service:";
            info "    sudo exportcli-manage --restart";
        fi
        if [[ "$binary_updated_flag" == true ]]; then
            info "  The exportcliv2 binary was updated. Restart all affected exportcliv2 instances:";
            info "    sudo exportcli-manage -i <INSTANCE_NAME> --restart";
            info "    (Repeat for each installed instance, e.g., $(IFS=' '; echo "${EFFECTIVE_DEFAULT_INSTANCES_ARRAY[*]}") if they use the updated binary).";
        fi
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
# Call main function only if not exited by help/version/list-defaults
if [[ "$HELP_OR_VERSION_EXIT" != true ]]; then
    main "$@" # Pass original args for potential future use, though current main doesn't use them
fi


if [[ "$DRY_RUN" == true && "$HELP_OR_VERSION_EXIT" != true ]]; then # Don't show if already shown by list_defaults or help
    info "[DRY-RUN] Orchestration dry run scan completed."
fi

# Final exit code determined by _master_exit_trap calling _final_summary_message
# If SCRIPT_SUCCESSFUL is true at the end of main, and FAIL_COUNT is 0, exit 0.
# If FAIL_COUNT > 0, exit partial success.
# If SCRIPT_SUCCESSFUL is false (e.g. user abort or other non-ERR exit), exit 1 (or specific user abort code).
# ERR trap handles immediate fatal errors.
# The explicit exit calls in the script for usage, version etc. are fine.
# The _master_exit_trap will still run.

# Let the EXIT trap handle the final decision on exit code if we reach here
if [[ "$HELP_OR_VERSION_EXIT" != true ]] ; then # Avoid double exit or overriding specific exit codes
    if [[ "$SCRIPT_SUCCESSFUL" == true ]]; then
        if (( FAIL_COUNT > 0 )); then
            exit "$EXIT_CODE_PARTIAL_SUCCESS"
        fi
        # If help/version exited successfully, this point isn't reached with SCRIPT_SUCCESSFUL=true
        # unless it was from list_defaults.
        # If list_defaults set HELP_OR_VERSION_EXIT=true and exited 0, that's fine.
        # If we fall through here, it means main() completed.
        exit "$EXIT_CODE_SUCCESS"
    elif [[ "$USER_ABORTED" == true ]]; then # This should have already exited, but as a fallback
        exit "$EXIT_CODE_SUCCESS" # User abort is considered a "successful" termination of intent
    fi
    # If SCRIPT_SUCCESSFUL is false and not user_aborted, something went wrong before ERR trap.
    # The EXIT trap's _final_summary_message will reflect based on $?
fi