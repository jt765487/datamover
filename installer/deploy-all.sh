#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# -----------------------------------------------------------------------------
# v2 Deployment Orchestrator (Further Polished)
# -----------------------------------------------------------------------------
VERSION="2.2.3" # Minor polishes based on review

# --- Colorized Logging ---
CSI="\033["
C_RESET="${CSI}0m"
C_INFO="${CSI}32m"  # Green
C_WARN="${CSI}33m"  # Yellow
C_ERROR="${CSI}31m" # Red

# --- Exit Codes ---
readonly EXIT_CODE_SUCCESS=0
readonly EXIT_CODE_FATAL_ERROR=1
readonly EXIT_CODE_PARTIAL_SUCCESS=2
readonly EXIT_CODE_USAGE_ERROR=3
readonly EXIT_CODE_CONFIG_ERROR=4
readonly EXIT_CODE_PREREQUISITE_ERROR=5
readonly EXIT_CODE_FILE_ERROR=6

# --- Logging ---
_ts()        { date -u +'%Y-%m-%dT%H:%M:%SZ'; }
info()       { echo -e "${C_INFO}$(_ts) [INFO]  $*${C_RESET}" >&2; }
warn()       { echo -e "${C_WARN}$(_ts) [WARN]  $*${C_RESET}" >&2; }
error_exit() {
  local message="$1"
  local exit_code="${2:-$EXIT_CODE_FATAL_ERROR}"
  echo -e "${C_ERROR}$(_ts) [ERROR] $message${C_RESET}" >&2
  exit "$exit_code"
}

# --- Globals ---
SOURCE_DIR="."
BASE_CONFIG="install-app.conf"
DEFAULT_INSTANCES=(AAA BBB CCC)
INSTANCE_NAMES_STRING=""
PARSED_INSTANCE_NAMES=()
DRY_RUN=false
VERBOSE_MODE=false
OPERATION_MODE="" # "install", "update", or "status-only"
FORCE_INSTANCE_CONFIG=false
RESTART_SERVICES_ON_UPDATE=false
# STATUS_ONLY_MODE removed; will use OPERATION_MODE directly

FAIL_COUNT=0
SCRIPT_SUCCESSFUL=false
SCRIPT_RUNNING_LOCK=false
HELP_OR_VERSION_EXIT=false

SCRIPTS_TO_CHECK=(install_base_exportcliv2.sh configure_instance.sh manage_services.sh)

LOCKFILE_DIR="/tmp"
LOCKFILE="${LOCKFILE_DIR}/$(basename "$0" ".sh").lock"

MAIN_PUSHED_DIR=false # Global flag for EXIT trap to manage popd

# --- Dependency checks ---
dependency_check() {
  local cmds_to_check=(flock date chmod dirname basename readlink realpath)
  info "Checking for core orchestrator commands: ${cmds_to_check[*]}"
  for cmd_to_check in "${cmds_to_check[@]}"; do
    if ! command -v "$cmd_to_check" &>/dev/null; then
      error_exit "Required command '$cmd_to_check' not found in PATH." "$EXIT_CODE_PREREQUISITE_ERROR"
    fi
  done
  info "Core orchestrator commands found."
}

# --- Locking with flock ---
acquire_lock() {
  info "Attempting to acquire execution lock: $LOCKFILE"
  mkdir -p "$LOCKFILE_DIR" || error_exit "Failed to create lock directory $LOCKFILE_DIR" "$EXIT_CODE_FATAL_ERROR"
  exec 200>"$LOCKFILE"
  if ! flock -n 200; then
    local locker_pid
    locker_pid=$(head -n 1 "$LOCKFILE" 2>/dev/null || echo "unknown")
    error_exit "Another instance is running (reported PID: ${locker_pid}, lockfile: $LOCKFILE)." "$EXIT_CODE_FATAL_ERROR"
  fi
  echo "$$" >&200
  SCRIPT_RUNNING_LOCK=true
  info "Execution lock acquired (PID: $$)."
  trap _master_exit_trap EXIT
}

# --- Master Exit Trap ---
# shellcheck disable=SC2317
_master_exit_trap() {
    local final_exit_code=$?
    if [[ "$MAIN_PUSHED_DIR" == true ]]; then # Check before lock, in case lock acquisition failed after pushd (unlikely)
        if popd >/dev/null; then
             info "Returned from source directory."
        else
            warn "Failed to popd from source directory. Current directory: $(pwd)"
        fi
        MAIN_PUSHED_DIR=false
    fi
    if [[ "$SCRIPT_RUNNING_LOCK" == true ]]; then
        if rm -f "$LOCKFILE"; then
          info "Execution lock released: $LOCKFILE"
        else
          warn "Failed to remove lockfile: $LOCKFILE. Manual cleanup may be needed."
        fi
        SCRIPT_RUNNING_LOCK=false
        # flock -u 200; exec 200>&- # Optional explicit release/close
    fi
    _final_summary_message "$final_exit_code"
}

# shellcheck disable=SC2317
_final_summary_message() {
    local exit_code="$1"
    if [[ "$HELP_OR_VERSION_EXIT" == true ]]; then :
    elif [[ "$OPERATION_MODE" == "status-only" && "$SCRIPT_SUCCESSFUL" == true && "$exit_code" -eq "$EXIT_CODE_SUCCESS" ]]; then : # CORRECTED: Use OPERATION_MODE
    elif [[ "$SCRIPT_SUCCESSFUL" == true && "$exit_code" -eq "$EXIT_CODE_SUCCESS" ]]; then
        info "-------------------- ORCHESTRATION COMPLETED SUCCESSFULLY --------------------"
    elif [[ "$exit_code" -eq "$EXIT_CODE_PARTIAL_SUCCESS" && "$SCRIPT_SUCCESSFUL" == true ]]; then
        warn "-------------------- ORCHESTRATION COMPLETED WITH NON-FATAL ERRORS (EXIT CODE: $exit_code) --------------------"
    elif [[ "$exit_code" -ne "$EXIT_CODE_SUCCESS" ]]; then
        info "-------------------- ORCHESTRATION FAILED (EXIT CODE: $exit_code) --------------------"
    fi
}

# --- ERR Trap ---
# shellcheck disable=SC2317
cleanup_on_error() {
  local exit_code="${1:-$?}"
  local line_num="${2:-UNKNOWN_LINE}"
  local failed_command="${3:-UNKNOWN_COMMAND}"
  SCRIPT_SUCCESSFUL=false
  if [[ $exit_code -ne $EXIT_CODE_SUCCESS && $failed_command != error_exit* && $failed_command != exit* ]]; then
    warn "Orchestrator FAILED on line ${line_num} with command: ${failed_command} (exit code: ${exit_code})."
  fi
}
trap 'cleanup_on_error "$?" "$LINENO" "$BASH_COMMAND"' ERR
trap 'error_exit "Script interrupted by signal." "$EXIT_CODE_FATAL_ERROR"' INT TERM

# --- Helpers ---
run() {
  local cmd_display_str
  if (($# > 0)); then
    local arg_idx
    cmd_display_str=""
    for ((arg_idx=1; arg_idx<=$#; arg_idx++)); do
        local current_arg="${!arg_idx}"
        if [[ "$current_arg" == *" "* ]]; then
            cmd_display_str+="'$current_arg' "
        else
            cmd_display_str+="$current_arg "
        fi
    done
    cmd_display_str="${cmd_display_str% }"
  else
    cmd_display_str="(no command specified to run)"
  fi

  if [[ "$DRY_RUN" == true ]]; then
    echo -e "${C_INFO}$(_ts) [DRY-RUN] Would execute: $cmd_display_str${C_RESET}" >&2
    return 0
  fi

  info "Running: $cmd_display_str"
  set +e
  "$@"
  local ec=$?
  set -e
  if (( ec != 0 )); then
    warn "Command failed (exit code $ec): $cmd_display_str"
    ((FAIL_COUNT++))
  fi
  return "$ec"
}

# --- Usage & List Defaults ---
usage() {
  local exit_code="${1:-$EXIT_CODE_USAGE_ERROR}"
  if [[ "$exit_code" -eq "$EXIT_CODE_SUCCESS" ]]; then
      HELP_OR_VERSION_EXIT=true
  fi
  cat <<EOF
Usage: $(basename "$0") [OPTIONS] --install|--update|--status-only

Modes (one is required):
  --install                 Fresh install or add/reconfigure instances.
  --update                  Update application binaries/wheels from current source-dir.
  --status-only             Only run service status checks for specified/default instances.

General Options:
  -s, --source-dir DIR      Path to the unpacked source tree (default: current directory).
                            This script should usually be run from within this directory.
  -c, --config FILE         Base install config filename (inside source-dir).
                            Default: $BASE_CONFIG
  -i, --instances LIST      Comma-separated instance names to configure/manage.
                            Default for --install or --status-only: ${DEFAULT_INSTANCES[*]}
  --force-reconfigure       During --install, force overwrite of existing instance configs.
  -n, --dry-run             Show commands without executing.
  -v, --verbose             Enable verbose shell tracing (set -x).
  -r, --restart-services    (For --update mode only) Restart services after update.
  --list-default-instances  Show default instance names and exit.
  -h, --help                Show this help and exit.
  --version                 Show version and exit.

Exit codes:
  0   Success
  1   Fatal error (usage, prereq, lock, unexpected)
  2   Completed with non-fatal errors during operations
  3   Usage error (specific for parsing)
  4   Configuration error (missing files, bad values)
  5   Prerequisite error (missing commands)
  6   File operation error (chmod, copy, etc.)
EOF
  exit "$exit_code"
}

list_defaults() {
  echo "Default instances configured in this script: ${DEFAULT_INSTANCES[*]}"
  HELP_OR_VERSION_EXIT=true
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
      if [[ -n "$OPERATION_MODE" ]]; then error_exit "Cannot specify more than one operation mode." "$EXIT_CODE_USAGE_ERROR"; fi
      OPERATION_MODE="install"; shift;;
    --update)
      if [[ -n "$OPERATION_MODE" ]]; then error_exit "Cannot specify more than one operation mode." "$EXIT_CODE_USAGE_ERROR"; fi
      OPERATION_MODE="update"; shift;;
    --status-only)
      if [[ -n "$OPERATION_MODE" ]]; then error_exit "Cannot specify more than one operation mode." "$EXIT_CODE_USAGE_ERROR"; fi
      OPERATION_MODE="status-only"; shift;; # No need for STATUS_ONLY_MODE=true
    -s|--source-dir)
      if [[ -z "${2:-}" ]]; then error_exit "Option $1 requires a DIR argument." "$EXIT_CODE_USAGE_ERROR"; fi
      SOURCE_DIR="$2"; shift 2;;
    -c|--config)
      if [[ -z "${2:-}" ]]; then error_exit "Option $1 requires a FILE argument." "$EXIT_CODE_USAGE_ERROR"; fi
      BASE_CONFIG="$2"; shift 2;;
    -i|--instances)
      if [[ -z "${2:-}" ]]; then error_exit "Option $1 requires a LIST argument." "$EXIT_CODE_USAGE_ERROR"; fi
      INSTANCE_NAMES_STRING="$2"; shift 2;;
    --force-reconfigure)
      FORCE_INSTANCE_CONFIG=true; shift;;
    -n|--dry-run)
      DRY_RUN=true; shift;;
    -v|--verbose)
      VERBOSE_MODE=true; shift;;
    -r|--restart-services)
      RESTART_SERVICES_ON_UPDATE=true; shift;;
    *)
      TEMP_ARGS+=("$1"); shift;;
  esac
done

if (( ${#TEMP_ARGS[@]} > 0 )); then
  error_exit "Unknown option or argument: ${TEMP_ARGS[0]}" "$EXIT_CODE_USAGE_ERROR"
fi

if [[ -z "$OPERATION_MODE" ]]; then
  error_exit "An operation mode (--install, --update, or --status-only) must be specified." "$EXIT_CODE_USAGE_ERROR"
fi
info "Operation Mode: $OPERATION_MODE"

if [[ "$VERBOSE_MODE" == true ]]; then
  info "Verbose mode enabled (set -x is active for subsequent commands)."
  set -x
fi

if [[ -n "$INSTANCE_NAMES_STRING" ]]; then
  IFS=',' read -r -a temp_instance_array <<< "$INSTANCE_NAMES_STRING"
  PARSED_INSTANCE_NAMES=()
  for inst_val in "${temp_instance_array[@]}"; do
    trimmed_inst="${inst_val#"${inst_val%%[![:space:]]*}"}"
    trimmed_inst="${trimmed_inst%"${trimmed_inst##*[![:space:]]}"}"
    if [[ -n "$trimmed_inst" ]]; then
      if ! [[ "$trimmed_inst" =~ ^[A-Za-z0-9._-]+$ ]]; then
        error_exit "Invalid instance name format in list: '$trimmed_inst' (from '$inst_val')." "$EXIT_CODE_USAGE_ERROR"
      fi
      PARSED_INSTANCE_NAMES+=("$trimmed_inst")
    fi
  done
elif [[ "$OPERATION_MODE" == "install" || "$OPERATION_MODE" == "status-only" ]]; then # CORRECTED: Use OPERATION_MODE
  if (( ${#DEFAULT_INSTANCES[@]} > 0 )); then
    PARSED_INSTANCE_NAMES=("${DEFAULT_INSTANCES[@]}")
    info "No instances specified with -i; using default instances for $OPERATION_MODE: ${PARSED_INSTANCE_NAMES[*]}"
  else
    info "No instances specified with -i and no defaults defined for $OPERATION_MODE."
  fi
fi

dependency_check
acquire_lock

if [[ "$DRY_RUN" != true && "$OPERATION_MODE" != "status-only" ]]; then # CORRECTED: Use OPERATION_MODE
  confirm_prompt="Proceed with $OPERATION_MODE"
  if (( ${#PARSED_INSTANCE_NAMES[@]} > 0 )); then
    confirm_prompt+=" on instances: ${PARSED_INSTANCE_NAMES[*]}"
  elif [[ "$OPERATION_MODE" == "install" || "$OPERATION_MODE" == "update" ]]; then
     confirm_prompt+=" (base service operations primarily)"
  fi
  # Ensure prompt uses color reset if C_WARN is used
  read -r -p "${C_WARN}${confirm_prompt}? [y/N] ${C_RESET}" yn
  case "$yn" in
    [Yy]*) info "Proceeding based on user confirmation." ;;
    *) info "Aborted by user."; exit "$EXIT_CODE_SUCCESS";;
  esac
fi

# --- Main Application Logic ---
main() {
  info "▶ Orchestrator v$VERSION starting (Mode: $OPERATION_MODE)"

  if ! pushd "$SOURCE_DIR" >/dev/null; then
    # EXIT trap (_master_exit_trap) will call cleanup_lock
    error_exit "Failed to change directory to '$SOURCE_DIR'." "$EXIT_CODE_FATAL_ERROR"
  fi
  MAIN_PUSHED_DIR=true # Signal for EXIT trap to popd

  info "Working directory: $(pwd)"

  if [[ "$OPERATION_MODE" == "status-only" ]]; then # CORRECTED: Use OPERATION_MODE
    info "▶ Performing service status checks only..."
    local checked_something_status=false
    info "--- Bitmover Service Status ---"
    run ./manage_services.sh ${DRY_RUN:+-n} --status
    checked_something_status=true

    if (( ${#PARSED_INSTANCE_NAMES[@]} > 0 )); then
      info "--- Instance Service Status (${#PARSED_INSTANCE_NAMES[@]}) ---"
      for inst_name_status_check in "${PARSED_INSTANCE_NAMES[@]}"; do
        run ./manage_services.sh ${DRY_RUN:+-n} -i "$inst_name_status_check" --status
      done
    elif [[ "$checked_something_status" != true ]]; then # This condition is unlikely to be met
        info "No specific instances provided via -i and no defaults available for status check."
    fi
    # SCRIPT_SUCCESSFUL is set after main() call for this path
    return # from main, skip further processing in main
  fi

  # --- For Install or Update modes ---
  info "Verifying required files in current directory ($(pwd))..."
  for file_to_check_main in "${SCRIPTS_TO_CHECK[@]}"; do
      [[ -f "$file_to_check_main" ]] || error_exit "Missing required script: $file_to_check_main" "$EXIT_CODE_CONFIG_ERROR"
  done
  [[ -f "$BASE_CONFIG" ]] || error_exit "Missing base config file: $BASE_CONFIG" "$EXIT_CODE_CONFIG_ERROR"
  info "All required sub-scripts and base config file present."

  info "Ensuring sub-scripts are executable..."
  for script_to_make_exec_main in "${SCRIPTS_TO_CHECK[@]}"; do
    run chmod +x "$script_to_make_exec_main" || error_exit "Failed to chmod $script_to_make_exec_main" "$EXIT_CODE_FILE_ERROR"
  done

  info "▶ Running base installer/updater (install_base_exportcliv2.sh)..."
  local base_install_cmd_array_main=(./install_base_exportcliv2.sh -c "$BASE_CONFIG")
  if [[ "$DRY_RUN" == true ]]; then base_install_cmd_array_main+=("-n"); fi
  run "${base_install_cmd_array_main[@]}" || error_exit "Base installer/updater script failed." "$EXIT_CODE_FATAL_ERROR"

  if [[ "$OPERATION_MODE" == "install" ]]; then
    if (( ${#PARSED_INSTANCE_NAMES[@]} > 0 )); then
      info "▶ Configuring instances: ${PARSED_INSTANCE_NAMES[*]}"
      local configure_base_cmd_array_main=("./configure_instance.sh")
      if [[ "$DRY_RUN" == true ]]; then configure_base_cmd_array_main+=("-n"); fi

      for inst_name_config_main in "${PARSED_INSTANCE_NAMES[@]}"; do
        info " • Configuring instance: $inst_name_config_main"
        # Corrected call to configure_instance.sh
        local current_configure_cmd_array_main=("${configure_base_cmd_array_main[@]}" -i "$inst_name_config_main")
        if [[ "$FORCE_INSTANCE_CONFIG" == true ]]; then current_configure_cmd_array_main+=("--force"); fi

        run "${current_configure_cmd_array_main[@]}" \
          || error_exit "configure_instance.sh failed for instance: $inst_name_config_main" "$EXIT_CODE_FATAL_ERROR"
      done
      info "Instance configuration finished."
    else
      info "No instances specified or defaulted for --install mode; skipping instance configuration."
    fi
  fi

  local manage_service_base_opts_array_main=()
  if [[ "$DRY_RUN" == true ]]; then manage_service_base_opts_array_main+=("-n"); fi

  if [[ "$OPERATION_MODE" == "install" ]]; then
    info "▶ Setting up services (enable, start, status)..."
    info " • Managing Bitmover service"
    run ./manage_services.sh "${manage_service_base_opts_array_main[@]}" --enable
    run ./manage_services.sh "${manage_service_base_opts_array_main[@]}" --start
    run ./manage_services.sh "${manage_service_base_opts_array_main[@]}" --status

    if (( ${#PARSED_INSTANCE_NAMES[@]} > 0 )); then
      for inst_name_manage_main in "${PARSED_INSTANCE_NAMES[@]}"; do
        info " • Managing services for exportcliv2 instance '$inst_name_manage_main'"
        run ./manage_services.sh "${manage_service_base_opts_array_main[@]}" -i "$inst_name_manage_main" --enable
        run ./manage_services.sh "${manage_service_base_opts_array_main[@]}" -i "$inst_name_manage_main" --start
        run ./manage_services.sh "${manage_service_base_opts_array_main[@]}" -i "$inst_name_manage_main" --status
      done
    fi
    info "Service setup finished."

  elif [[ "$OPERATION_MODE" == "update" ]]; then
    info "▶ Update processing complete by install_base_exportcliv2.sh."
    if [[ "$RESTART_SERVICES_ON_UPDATE" == true ]]; then
      info "▶ Restarting services as requested by --restart-services..."
      info " • Restarting Bitmover service"
      run ./manage_services.sh "${manage_service_base_opts_array_main[@]}" --restart

      if (( ${#PARSED_INSTANCE_NAMES[@]} > 0 )); then
        info " • Restarting specified exportcliv2 instances: ${PARSED_INSTANCE_NAMES[*]}"
        for inst_name_restart_main in "${PARSED_INSTANCE_NAMES[@]}"; do
          run ./manage_services.sh "${manage_service_base_opts_array_main[@]}" -i "$inst_name_restart_main" --restart
        done
      else
          info "No specific instances provided via -i for restart after update. Only Bitmover was targeted for restart (if applicable)."
      fi
    else
      info "Services not automatically restarted. Use --restart-services with --update, or restart manually using manage_services.sh."
    fi
  fi
}

# --- Script Execution Starts Here ---
main "$@"
SCRIPT_SUCCESSFUL=true # If main completes (or returns early for status-only) without error_exit

# --- Summary & Final Exit based on FAIL_COUNT ---
if [[ "$DRY_RUN" == true ]]; then
    if (( FAIL_COUNT > 0 )); then
        warn "[DRY-RUN] Orchestration dry run indicated $FAIL_COUNT potential non-fatal issues from sub-commands."
    else
        # Only print generic dry run complete if not a status-only mode, which has its own conclusion.
        if [[ "$OPERATION_MODE" != "status-only" ]]; then
             info "[DRY-RUN] Orchestration dry run completed."
        fi
    fi
fi

if (( FAIL_COUNT > 0 )); then
  # SCRIPT_SUCCESSFUL is true because the orchestrator itself didn't fatally error.
  # The _final_summary_message in the EXIT trap will use this combination.
  exit "$EXIT_CODE_PARTIAL_SUCCESS"
fi

# If SCRIPT_SUCCESSFUL is true and FAIL_COUNT is 0, the EXIT trap's _final_summary_message
# will print "ORCHESTRATION COMPLETED SUCCESSFULLY" (unless help/version/status-only).
exit "$EXIT_CODE_SUCCESS"