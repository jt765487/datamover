#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# -----------------------------------------------------------------------------
# Service Manager for exportcliv2 suite
# Standardized logging, dry-run, error handling, exit codes.
# -----------------------------------------------------------------------------
VERSION="1.3.1" # Script version (Incremented)

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
_ts() { date -u +'%Y-%m-%dT%H:%M:%SZ'; } # Relies on 'date' command
_log_msg() {
    local log_level_name="$1"; local color_var_name="C_${log_level_name}"; local color_code="${!color_var_name}"; shift;
    # Fallback for timestamp if _ts fails (e.g., date command issue, though prerequisite check should catch this)
    local timestamp
    timestamp=$(_ts 2>/dev/null || echo "NO_TS")
    echo -e "${color_code}${timestamp} [${log_level_name^^}] $*${C_RESET}" >&2;
}
info()       { _log_msg "INFO" "$*"; }
warn()       { _log_msg "WARN" "$*"; }
debug() { if [[ "${VERBOSE_MODE:-false}" == true ]]; then _log_msg "DEBUG" "$*"; fi; }
error_exit() { local message="$1"; local exit_code="${2:-$EXIT_CODE_FATAL_ERROR}"; _log_msg "ERROR" "$message"; exit "$exit_code"; }

# --- Globals (Standardized where applicable) ---
VERBOSE_MODE=false
DRY_RUN=false
SCRIPT_SUCCESSFUL=false # Explicitly false until an action defines success or script completes operations
HELP_OR_VERSION_EXIT=false
FAIL_COUNT=0 # For run helper

readonly BITMOVER_SERVICE_NAME="bitmover.service" # Default global service
readonly APP_NAME_FOR_BASE_VARS_LOOKUP="exportcliv2"
readonly BASE_VARS_FILE="/etc/default/${APP_NAME_FOR_BASE_VARS_LOOKUP}_base_vars"

INSTANCE_NAME=""
MODE="bitmover" # 'bitmover' or 'instance'
ACTION_FLAG=""  # e.g., start, stop, status
SINCE_ARG=""    # For logs

# --- Trap Handling (Standardized) ---
# shellcheck disable=SC2317
_cleanup_on_error_manage() {
    local exit_code_val="$1"; local line_no="$2"; local command="$3"; echo; # Renamed exit_code to avoid conflict
    # Ensure _log_msg and _ts are minimally functional or have fallbacks if this trap is hit early
    warn "--- SERVICE MANAGER ERROR DETECTED ---"
    error_exit "Error on or near line ${line_no} in $(basename "${BASH_SOURCE[0]}"): command '${command}' returned exit code ${exit_code_val}." "${exit_code_val:-$EXIT_CODE_FATAL_ERROR}"
}
# shellcheck disable=SC2317
_cleanup_on_exit_manage() {
    local exit_code_val=$? # Renamed to avoid conflict if any function in the trap used 'exit_code'
    if [[ "$HELP_OR_VERSION_EXIT" == true ]]; then return; fi
    echo

    # The logic here determines the final message based on the script's outcome
    if [[ "$exit_code_val" -eq "$EXIT_CODE_SUCCESS" && "$SCRIPT_SUCCESSFUL" == true && "$FAIL_COUNT" -eq 0 ]]; then
        info "▶ Service Management Script ($(basename "${BASH_SOURCE[0]}")) finished successfully."
    elif [[ "$exit_code_val" -eq "$EXIT_CODE_PARTIAL_SUCCESS" ]] || \
         [[ "$exit_code_val" -eq "$EXIT_CODE_SUCCESS" && "$FAIL_COUNT" -gt 0 && "$SCRIPT_SUCCESSFUL" == true ]]; then
        warn "▶ Service Management Script ($(basename "${BASH_SOURCE[0]}")) finished with $FAIL_COUNT non-fatal error(s). Exit code: $exit_code_val."
    elif [[ "$exit_code_val" -ne "$EXIT_CODE_SUCCESS" ]]; then
        # This is the problematic message the user was seeing for 'status inactive'
        _log_msg "ERROR" "▶ Service Management Script ($(basename "${BASH_SOURCE[0]}")) failed. Exit code: $exit_code_val. Review messages."
    else # Should ideally not be reached if logic above is complete, implies exit_code_val == 0 but SCRIPT_SUCCESSFUL might be false or FAIL_COUNT > 0 not caught above
        warn "▶ Service Management Script ($(basename "${BASH_SOURCE[0]}")) finished. Status unclear (exit_code: $exit_code_val, successful_flag: $SCRIPT_SUCCESSFUL, fail_count: $FAIL_COUNT)."
    fi
}
trap '_cleanup_on_error_manage "$?" "$LINENO" "$BASH_COMMAND"' ERR
trap '_cleanup_on_exit_manage' EXIT
trap 'error_exit "Script $(basename "${BASH_SOURCE[0]}")) interrupted by signal." "$EXIT_CODE_FATAL_ERROR"' INT TERM


# --- Prerequisite Check ---
check_prerequisites() {
    if ! command -v date >/dev/null 2>&1; then
        # Minimal echo if logging itself might fail due to missing date
        echo "FATAL: 'date' command not found. It is required for script timestamps." >&2
        exit "$EXIT_CODE_PREREQUISITE_ERROR"
    fi
    debug "Prerequisite 'date' command found."

    if ! command -v systemctl >/dev/null 2>&1; then
        error_exit "'systemctl' command not found. This script requires systemd." "$EXIT_CODE_PREREQUISITE_ERROR"
    fi
    debug "Prerequisite 'systemctl' command found."
}
# Call prerequisite check early
check_prerequisites


# --- Standardized run Helper ---
run() {
  local cmd_array=("$@")
  local cmd_display
  printf -v cmd_display '%q ' "${cmd_array[@]}"
  debug "Executing: $cmd_display"
  if [[ "$DRY_RUN" == true ]]; then
    info "[DRY-RUN] Would execute: $cmd_display"
    if [[ "${cmd_array[0]}" == "systemctl" && "${cmd_array[1]}" == "status" ]]; then
        info "[DRY-RUN] Status check for '${cmd_array[*]:2}' skipped."
        return "$EXIT_CODE_SUCCESS"
    fi
    return "$EXIT_CODE_SUCCESS"
  fi

  if [[ "${cmd_array[0]}" == "systemctl" && "${cmd_array[1]}" == "status" ]]; then
    local unit_name_for_msg
    unit_name_for_msg="${cmd_array[2]}"
    if [[ "$unit_name_for_msg" == "--no-pager" ]]; then
        if [[ ${#cmd_array[@]} -gt 3 ]]; then unit_name_for_msg="${cmd_array[3]}"; else unit_name_for_msg="<unknown unit>"; fi
    elif [[ -z "$unit_name_for_msg" ]]; then
        unit_name_for_msg="<global systemd status>"
    fi
    debug "run: systemctl status called for unit identified as '$unit_name_for_msg' in message."

    local ec
    # Execute systemctl status. If it fails (returns non-zero), capture the exit code.
    # If it succeeds (returns 0), set ec to 0.
    # This structure prevents set -e from exiting the script prematurely.
    if "${cmd_array[@]}"; then  # <<< MODIFIED SECTION START
        ec=0
    else
        ec=$?
    fi                         # <<< MODIFIED SECTION END
    debug "run: systemctl status raw exit code for '$unit_name_for_msg': $ec"

    case "$ec" in
      0) # Active
        debug "run: Service '$unit_name_for_msg' is active (systemctl exit code: $ec)."
        return "$EXIT_CODE_SUCCESS" ;;
      3) # Inactive/dead
        debug "run: Service '$unit_name_for_msg' reported as inactive/dead (systemctl exit code: $ec)."
        info "Service '$unit_name_for_msg' is inactive/dead."
        return "$EXIT_CODE_SUCCESS"
        ;;
      4) # Not found / no such unit
        warn "Service '$unit_name_for_msg' not found (systemctl exit code: $ec)."
        ((FAIL_COUNT++))
        return $ec # Propagate error for "not found"
        ;;
      *) # Other errors
        warn "Status check for '$unit_name_for_msg' reported an issue (systemctl exit code: $ec)."
        ((FAIL_COUNT++))
        return $ec # Propagate other errors
        ;;
    esac
  else # For commands other than systemctl status
    "${cmd_array[@]}"
    local other_ec=$? # Renamed to avoid confusion with 'ec' above
    if [[ $other_ec -ne 0 ]]; then
      warn "Command failed with exit code $other_ec: $cmd_display"
      ((FAIL_COUNT++))
      return "$other_ec" # Return the actual error code
    fi
  fi
  return "$EXIT_CODE_SUCCESS" # Default success for the 'run' function
}


# --- Helpers ---
enforce_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    error_exit "This action requires root or sudo." "$EXIT_CODE_PREREQUISITE_ERROR"
  fi
}

_trigger_instance_restart() {
    local instance_name="$1"
    if [[ -z "$instance_name" ]]; then
        warn "_trigger_instance_restart called without an instance name."
        return 1
    fi

    # CSV_DATA_DIR is already sourced from BASE_VARS_FILE.
    if [[ -z "${CSV_DATA_DIR:-}" ]]; then
        error_exit "CSV_DATA_DIR is not defined. Cannot determine path for restart trigger file." "$EXIT_CODE_CONFIG_ERROR"
    fi

    local restart_trigger_file="${CSV_DATA_DIR%/}/${instance_name}.restart"

    if [[ -e "$restart_trigger_file" ]]; then
        info "Restart for instance '${instance_name}' has already been triggered. Skipping."
    else
        warn "Instance '${instance_name}' is unhealthy. Triggering restart via file: ${restart_trigger_file}"
        run touch "$restart_trigger_file"
    fi
}

# --- Argument Parsing (Standardized to while/case) ---
usage() {
  HELP_OR_VERSION_EXIT=true
  local script_name; script_name=$(basename "$0")
  cat <<EOF
Usage: $script_name [OPTIONS] ACTION_FLAG

Manage '$BITMOVER_SERVICE_NAME' (default) or an '${APP_NAME_FOR_BASE_VARS_LOOKUP}' instance services.
This script usually requires root/sudo for actions that modify service states.

Options:
  -i, --instance NAME   Switch to instance mode to manage services for instance NAME.
                        If not specified, actions apply to the global '$BITMOVER_SERVICE_NAME'.
  --since <time>        For '--logs' or '--logs-follow', show logs since <time>
                        (e.g., "1 hour ago", "YYYY-MM-DD HH:MM:SS").
  -n, --dry-run         Dry-run mode (print commands instead of executing).
  -v, --verbose         Verbose mode (enables debug messages and command tracing 'set -x').
  -h, --help            Show this help message and exit.
  --version             Show script version and exit.

Actions (one is required):
  --start               Start service(s).
  --stop                Stop service(s).
  --restart             Restart main service(s). For instances, restarts the main app service.
  --status, --check     Show status of relevant service(s).
  --logs                Show recent logs. Use --since for specific timeframes.
  --logs-follow         Follow logs in real-time. Use --since for history.
  --enable              Enable service(s) to start at boot.
  --disable             Disable service(s) from starting at boot.
  --reset-failed        Reset 'failed' state for service(s) in systemd.
  --run-health-check    (Internal) Run a health check for an instance. If unhealthy,
                        triggers a restart. Used by the systemd timer.

Examples:
  sudo $script_name --start                    # Starts the global $BITMOVER_SERVICE_NAME
  sudo $script_name --logs-follow --since "10m"
  sudo $script_name -i site_alpha --enable     # Enables services for instance 'site_alpha'
  sudo $script_name -i site_beta --status
EOF
  exit "${1:-$EXIT_CODE_SUCCESS}"
}

# Pre-scan for help/version
for arg_pre_scan in "$@"; do
  case "$arg_pre_scan" in
    --version) echo "$(basename "$0") v$VERSION"; HELP_OR_VERSION_EXIT=true; exit "$EXIT_CODE_SUCCESS";;
    -h|--help) usage "$EXIT_CODE_SUCCESS";;
  esac
done

TEMP_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -i|--instance)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then error_exit "Option $1 requires a NAME argument." "$EXIT_CODE_USAGE_ERROR"; fi
      INSTANCE_NAME="$2"; MODE="instance"; shift 2;;
    --since)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then error_exit "Option $1 requires a time argument." "$EXIT_CODE_USAGE_ERROR"; fi
      SINCE_ARG="$2"; shift 2;;
    -n|--dry-run)
      DRY_RUN=true; shift;;
    -v|--verbose)
      VERBOSE_MODE=true; shift;;
    --start|--stop|--restart|--logs|--logs-follow|--enable|--disable|--reset-failed)
      if [[ -n "$ACTION_FLAG" ]]; then error_exit "Multiple actions ('$ACTION_FLAG' and '${1#--}') not allowed." "$EXIT_CODE_USAGE_ERROR"; fi
      ACTION_FLAG="${1#--}"; shift;;
    --status|--check)
      if [[ -n "$ACTION_FLAG" ]]; then error_exit "Multiple actions ('$ACTION_FLAG' and 'status') not allowed." "$EXIT_CODE_USAGE_ERROR"; fi
      ACTION_FLAG="status"; shift;;
    --run-health-check)
      if [[ -n "$ACTION_FLAG" ]]; then error_exit "Multiple actions ('$ACTION_FLAG' and 'run-health-check') not allowed." "$EXIT_CODE_USAGE_ERROR"; fi
      ACTION_FLAG="run-health-check"; shift;;
    *)
      TEMP_ARGS+=("$1"); shift;;
  esac
done

if (( ${#TEMP_ARGS[@]} > 0 )); then
  # Improved error message for unknown options
  error_exit "Unknown option or argument(s): '${TEMP_ARGS[*]}'. Use --help for usage." "$EXIT_CODE_USAGE_ERROR"
fi
if [[ -z "$ACTION_FLAG" ]]; then
  error_exit "No action specified (e.g., --start, --status). Use --help for usage." "$EXIT_CODE_USAGE_ERROR"
fi

if [[ "$VERBOSE_MODE" == true ]]; then
  info "Verbose mode enabled."
  # set -x is deferred to after prerequisite checks and basic setup
  # to avoid overly noisy output if these initial steps have issues.
fi

# --- Enforce root for privileged actions ---
if [[ "$DRY_RUN" != true ]]; then
  case "$ACTION_FLAG" in
    start|stop|restart|enable|disable|reset-failed)
      enforce_root;;
    logs|logs-follow|status)
      debug "Action '$ACTION_FLAG' typically does not require root, but may show more with it."
      ;;
  esac
fi

# --- Load base vars (APP_NAME is needed to construct instance service names) ---
debug "Attempting to load base variables from \"${BASE_VARS_FILE}\"..."
if [[ ! -f "$BASE_VARS_FILE" ]]; then
  error_exit "Base variables file \"${BASE_VARS_FILE}\" not found. Ensure base installer ran." "$EXIT_CODE_CONFIG_ERROR"
fi
# shellcheck source=/dev/null
source "$BASE_VARS_FILE"
# Improved check for APP_NAME
if [[ -z "${APP_NAME:-}" ]]; then
    error_exit "APP_NAME not set or empty in ${BASE_VARS_FILE}. Base install may be incomplete." "$EXIT_CODE_CONFIG_ERROR"
fi
debug "Successfully sourced APP_NAME='${APP_NAME}' from base variables."


if [[ "$VERBOSE_MODE" == true ]]; then
  info "Command tracing ('set -x') activated due to verbose mode."
  set -x
fi

# --- Determine service names ---
MAIN_SERVICE_UNIT=""
PATH_SERVICE_UNITS=()
RELATED_SERVICE_UNITS=()
TARGET_DESC=""

if [[ "$MODE" == "instance" ]]; then
  if [[ -z "$INSTANCE_NAME" ]]; then
      error_exit "Instance mode selected but no instance name provided." "$EXIT_CODE_USAGE_ERROR"
  fi
  if ! [[ "$INSTANCE_NAME" =~ ^[A-Za-z0-9._-]+$ ]]; then
    error_exit "Invalid instance name: '$INSTANCE_NAME'. Only A-Z, a-z, 0-9, '.', '_', '-' allowed." "$EXIT_CODE_USAGE_ERROR"
  fi
  MAIN_SERVICE_UNIT="${APP_NAME}@${INSTANCE_NAME}.service"
  PATH_SERVICE_UNITS+=("${APP_NAME}-restart@${INSTANCE_NAME}.path")
  RELATED_SERVICE_UNITS+=("${APP_NAME}-restart@${INSTANCE_NAME}.service")
  TARGET_DESC="${APP_NAME} instance '$INSTANCE_NAME'"
  debug "Mode: Instance '$INSTANCE_NAME'. Main service: $MAIN_SERVICE_UNIT"
else
  MAIN_SERVICE_UNIT="$BITMOVER_SERVICE_NAME"
  TARGET_DESC="Global Bitmover service ($MAIN_SERVICE_UNIT)"
  debug "Mode: Global Bitmover. Main service: $MAIN_SERVICE_UNIT"
fi

# --- Prepare journalctl options ---
journalctl_opts_array=()
if [[ -n "$SINCE_ARG" ]]; then
  journalctl_opts_array+=(--since "$SINCE_ARG")
fi

info "Performing '$ACTION_FLAG' on $TARGET_DESC (Dry-run: $DRY_RUN)"

# --- Dispatch Actions ---
case "$ACTION_FLAG" in
run-health-check)
    SCRIPT_SUCCESSFUL=true # Assume success unless a check fails
    if [[ "$MODE" != "instance" ]]; then
        error_exit "--run-health-check requires an instance name (-i)." "$EXIT_CODE_USAGE_ERROR"
    fi

    info "Running health check for instance '${INSTANCE_NAME}'..."

    if [[ -z "${HEALTH_CHECK_INTERVAL_MINS:-}" || ! "$HEALTH_CHECK_INTERVAL_MINS" =~ ^[0-9]+$ || "$HEALTH_CHECK_INTERVAL_MINS" -le 0 ]]; then
        info "Health check is disabled or interval is invalid (HEALTH_CHECK_INTERVAL_MINS='${HEALTH_CHECK_INTERVAL_MINS:-}'). Skipping."
        exit "$EXIT_CODE_SUCCESS"
    fi

    if ! systemctl is-active --quiet "$MAIN_SERVICE_UNIT"; then
        status=$(systemctl is-active "$MAIN_SERVICE_UNIT") || true
        warn "Health check FAILED for '${INSTANCE_NAME}'. Service is not active (state: ${status})."
        _trigger_instance_restart "$INSTANCE_NAME"
        exit "$EXIT_CODE_SUCCESS"
    fi
    debug "Service '${MAIN_SERVICE_UNIT}' is active. Now checking for log activity."

    health_check_window="${HEALTH_CHECK_INTERVAL_MINS} minutes ago" # <-- FIX: 'local' removed
    info "Checking for log entries within the last ${HEALTH_CHECK_INTERVAL_MINS} minutes..."

    journal_cmd_array=(journalctl -u "$MAIN_SERVICE_UNIT" --since "$health_check_window" --no-pager --quiet --output=cat) # <-- FIX: 'local' removed

    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] Would check for logs with: ${journal_cmd_array[*]}"
        info "[DRY-RUN] Would trigger restart if no logs were found."
    elif ! "${journal_cmd_array[@]}" | grep -q .; then
        warn "Health check FAILED for '${INSTANCE_NAME}'. Service is active but has produced NO log entries since '${health_check_window}'."
        _trigger_instance_restart "$INSTANCE_NAME"
    else
        info "Health check PASSED for '${INSTANCE_NAME}'. Service is active and has recent log entries."
    fi
    ;;
  start)
    run systemctl start "$MAIN_SERVICE_UNIT"
    for unit in "${PATH_SERVICE_UNITS[@]}"; do run systemctl start "$unit"; done
    ;;
  stop)
    run systemctl stop "$MAIN_SERVICE_UNIT"
    for unit in "${PATH_SERVICE_UNITS[@]}"; do run systemctl stop "$unit"; done
    ;;
  restart)
    info "Attempting to restart $TARGET_DESC." # TARGET_DESC is already set in the script
    info "This operation involves stopping and then starting the service(s)."
    info "If a service is slow to stop, this command may appear to hang for its configured timeout (e.g., up to 90 seconds or more). Please wait for completion..."

    run systemctl restart "$MAIN_SERVICE_UNIT"

    # If 'run systemctl restart' returns successfully (i.e., systemctl itself didn't report an immediate error
    # and the ERR trap wasn't triggered), it means systemd has completed the restart sequence
    # (waited for stop, then waited for start).
    # The overall script success/failure will be handled by the EXIT trap.
    # We can add a small confirmation that the command was processed by systemd.

    # This check is a bit tricky because $? after the `if` block below would be from the `if`.
    # For now, let's rely on the main script EXIT trap for the final "success" message.
    # The crucial part is the warning message above.

    if ((${#PATH_SERVICE_UNITS[@]} > 0)); then
      info "Note: Associated path unit(s) (${PATH_SERVICE_UNITS[*]}) are event-driven and not directly restarted with this command."
    fi
    # No specific "restart action succeeded" message here; the main script's EXIT trap covers it.
    # If 'run systemctl restart' failed critically, the ERR trap would have already fired.
    ;;
  status)
    SCRIPT_SUCCESSFUL=true # Status is informational; success if command runs and reports.
    info "--- Status for $MAIN_SERVICE_UNIT ---" # Changed from echo to info for consistency
    run systemctl status "$MAIN_SERVICE_UNIT" --no-pager
    for unit in "${PATH_SERVICE_UNITS[@]}"; do
      info ""; info "--- Status for $unit ---"
      run systemctl status "$unit" --no-pager
    done
    for unit in "${RELATED_SERVICE_UNITS[@]}"; do
      info ""; info "--- Status for $unit ---"
      run systemctl status "$unit" --no-pager
    done
    ;;
  logs)
    SCRIPT_SUCCESSFUL=true
    info "Displaying logs for $MAIN_SERVICE_UNIT ${SINCE_ARG:+(since $SINCE_ARG)}"
    cmd_logs_main=("journalctl" "-u" "$MAIN_SERVICE_UNIT" "--no-pager")
    cmd_logs_main+=("${journalctl_opts_array[@]}")
    if [[ -z "$SINCE_ARG" ]]; then cmd_logs_main+=("-n" "50"); fi # Show last 50 if no --since
    run "${cmd_logs_main[@]}"

    for unit in "${RELATED_SERVICE_UNITS[@]}"; do
      info ""; info "Displaying logs for related $unit ${SINCE_ARG:+(since $SINCE_ARG)}"
      cmd_logs_related=("journalctl" "-u" "$unit" "--no-pager")
      cmd_logs_related+=("${journalctl_opts_array[@]}")
      if [[ -z "$SINCE_ARG" ]]; then cmd_logs_related+=("-n" "20"); fi
      run "${cmd_logs_related[@]}"
    done
    ;;
  logs-follow)
    SCRIPT_SUCCESSFUL=true
    units_to_follow_array=("-u" "$MAIN_SERVICE_UNIT")
    for unit in "${PATH_SERVICE_UNITS[@]}"; do units_to_follow_array+=("-u" "$unit"); done
    for unit in "${RELATED_SERVICE_UNITS[@]}"; do units_to_follow_array+=("-u" "$unit"); done

    info "Following logs for services: ${units_to_follow_array[*]} ${SINCE_ARG:+(since $SINCE_ARG)}"
    cmd_follow_array=("journalctl" "-f" "${units_to_follow_array[@]}")
    cmd_follow_array+=("${journalctl_opts_array[@]}")

    if [[ "$DRY_RUN" == true ]]; then
      info "[DRY-RUN] Would execute: $(printf '%q ' "${cmd_follow_array[@]}")"
    else
      "${cmd_follow_array[@]}" || {
        jc_exit_code=$?
        if [[ $jc_exit_code -eq 130 ]]; then # SIGINT (Ctrl-C)
          info "Journal follow interrupted by user (Ctrl-C)."
        else
          # Do not use error_exit here as it would recall EXIT trap recursively if journalctl fails early.
          _log_msg "ERROR" "journalctl -f command failed or was interrupted (exit code: $jc_exit_code)."
          exit "$jc_exit_code"
        fi
      }
    fi
    ;;
  enable)
    run systemctl enable "$MAIN_SERVICE_UNIT"
    for unit in "${PATH_SERVICE_UNITS[@]}"; do run systemctl enable "$unit"; done
    info "$TARGET_DESC service(s) enabled."
    ;;
  disable)
    run systemctl disable "$MAIN_SERVICE_UNIT"
    for unit in "${PATH_SERVICE_UNITS[@]}"; do run systemctl disable "$unit"; done
    info "$TARGET_DESC service(s) disabled."
    ;;
  reset-failed)
    run systemctl reset-failed "$MAIN_SERVICE_UNIT"
    for unit in "${PATH_SERVICE_UNITS[@]}"; do run systemctl reset-failed "$unit"; done
    for unit in "${RELATED_SERVICE_UNITS[@]}"; do run systemctl reset-failed "$unit"; done
    info "$TARGET_DESC service(s) failed state reset."
    ;;
  *)
    error_exit "Unhandled action: '$ACTION_FLAG'. Internal error." "$EXIT_CODE_FATAL_ERROR"
    ;;
esac

if [[ "$ACTION_FLAG" != "status" && "$ACTION_FLAG" != "logs" && "$ACTION_FLAG" != "logs-follow" ]]; then
    # For modifying actions
    if [[ $FAIL_COUNT -eq 0 ]]; then
        SCRIPT_SUCCESSFUL=true
    else
        # One or more operations failed for this action
        SCRIPT_SUCCESSFUL=false # More semantically correct
        if [[ $? -eq 0 ]]; then
            # If the last command in the action block succeeded, but FAIL_COUNT > 0,
            # we must explicitly exit with a partial success code.
            debug "FAIL_COUNT is $FAIL_COUNT, but last command succeeded. Overriding exit to PARTIAL_SUCCESS."
            exit "$EXIT_CODE_PARTIAL_SUCCESS"
        fi
        # If $? is already non-zero, that will be the exit code picked up by the EXIT trap.
    fi
else
    # For status/logs/logs-follow, SCRIPT_SUCCESSFUL is already set to true within their action blocks.
    # If FAIL_COUNT > 0 (e.g., a unit not found during status),
    # the run helper would have returned non-zero, and $? would reflect that,
    # or if it was not the last command, FAIL_COUNT would be > 0 and $? could be 0.
    # We need to ensure a PARTIAL_SUCCESS exit if FAIL_COUNT > 0 and $? is 0.
    if [[ $FAIL_COUNT -gt 0 && $? -eq 0 ]]; then
        debug "FAIL_COUNT is $FAIL_COUNT for info action, but last command succeeded. Overriding exit to PARTIAL_SUCCESS."
        exit "$EXIT_CODE_PARTIAL_SUCCESS"
    fi
fi
# If we reach here and $? is 0 and FAIL_COUNT is 0, it's a full success (EXIT_CODE_SUCCESS).
# If $? is non-zero, it's some other failure type, handled by the EXIT trap.