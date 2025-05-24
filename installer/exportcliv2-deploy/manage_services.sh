#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# -----------------------------------------------------------------------------
# Service Manager for exportcliv2 suite
# Standardized logging, dry-run, error handling, exit codes.
# -----------------------------------------------------------------------------
VERSION="1.3.0" # Script version

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
    local exit_code="$1"; local line_no="$2"; local command="$3"; echo;
    warn "--- SERVICE MANAGER ERROR DETECTED ---"
    error_exit "Error on or near line ${line_no} in $(basename "${BASH_SOURCE[0]}"): command '${command}' returned exit code ${exit_code}." "${exit_code:-$EXIT_CODE_FATAL_ERROR}"
}
# shellcheck disable=SC2317
_cleanup_on_exit_manage() {
    local exit_code=$?
    if [[ "$HELP_OR_VERSION_EXIT" == true ]]; then return; fi
    echo
    if [[ "$exit_code" -eq "$EXIT_CODE_SUCCESS" && "$SCRIPT_SUCCESSFUL" == true ]]; then
        info "▶ Service Management Script ($(basename "${BASH_SOURCE[0]}")) finished successfully."
    elif [[ "$exit_code" -eq "$EXIT_CODE_PARTIAL_SUCCESS" || ("$exit_code" -eq "$EXIT_CODE_SUCCESS" && "$FAIL_COUNT" -gt 0 && "$SCRIPT_SUCCESSFUL" == true) ]]; then
        warn "▶ Service Management Script ($(basename "${BASH_SOURCE[0]}")) finished with $FAIL_COUNT non-fatal error(s)."
    elif [[ "$exit_code" -ne "$EXIT_CODE_SUCCESS" ]]; then
        echo -e "${C_ERROR}$(_ts) [ERROR] ▶ Service Management Script ($(basename "${BASH_SOURCE[0]}")) failed. Review messages.${C_RESET}" >&2
    else
        warn "▶ Service Management Script ($(basename "${BASH_SOURCE[0]}")) finished. Status unclear."
    fi
}
trap '_cleanup_on_error_manage "$?" "$LINENO" "$BASH_COMMAND"' ERR
trap '_cleanup_on_exit_manage' EXIT
trap 'error_exit "Script $(basename "${BASH_SOURCE[0]}") interrupted by signal." "$EXIT_CODE_FATAL_ERROR"' INT TERM


# --- Standardized run Helper ---
run() {
  local cmd_array=("$@")
  local cmd_display
  printf -v cmd_display '%q ' "${cmd_array[@]}"
  debug "Executing: $cmd_display"
  if [[ "$DRY_RUN" == true ]]; then
    info "[DRY-RUN] Would execute: $cmd_display"
    # For systemctl status in dry run, we can't know the real status, so indicate it's a dry run.
    if [[ "${cmd_array[0]}" == "systemctl" && "${cmd_array[1]}" == "status" ]]; then
        info "[DRY-RUN] Status check for '${cmd_array[2]}' skipped."
        return "$EXIT_CODE_SUCCESS" # Return success for dry-run status checks
    fi
    return "$EXIT_CODE_SUCCESS"
  fi

  # Special handling for systemctl status to not fail script on inactive/not-found
  if [[ "${cmd_array[0]}" == "systemctl" && "${cmd_array[1]}" == "status" ]]; then
    "${cmd_array[@]}"
    local ec=$?
    local unit_name="${cmd_array[2]}" # Assumes unit name is the 3rd arg to systemctl status
    if [[ "$unit_name" == "--no-pager" && ${#cmd_array[@]} -gt 3 ]]; then # Handle --no-pager correctly
        unit_name="${cmd_array[3]}"
    elif [[ "$unit_name" == "--no-pager" ]]; then # If status is called without unit
        unit_name="<global status>"
    fi

    case "$ec" in
      0) # Active
        return "$EXIT_CODE_SUCCESS" ;;
      3) # Inactive/dead
        info "Service '$unit_name' is inactive/dead (systemctl exit code: $ec)."
        return "$EXIT_CODE_SUCCESS" # Treat as success for status check purposes
        ;;
      4) # Not found
        warn "Service '$unit_name' not found (systemctl exit code: $ec)."
        ((FAIL_COUNT++))
        return $ec # Propagate error for "not found" as it's a config issue
        ;;
      *) # Other errors
        warn "Status check for '$unit_name' reported an issue (systemctl exit code: $ec)."
        ((FAIL_COUNT++))
        return $ec
        ;;
    esac
  else # For commands other than systemctl status
    "${cmd_array[@]}"
    local ec=$?
    if [[ $ec -ne 0 ]]; then
      warn "Command failed with exit code $ec: $cmd_display"
      ((FAIL_COUNT++))
      return $ec
    fi
  fi
  return "$EXIT_CODE_SUCCESS"
}


# --- Helpers ---
enforce_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    error_exit "This action requires root or sudo." "$EXIT_CODE_PREREQUISITE_ERROR"
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
    # Action flags
    --start|--stop|--restart|--logs|--logs-follow|--enable|--disable|--reset-failed)
      if [[ -n "$ACTION_FLAG" ]]; then error_exit "Multiple actions ('$ACTION_FLAG' and '${1#--}') not allowed." "$EXIT_CODE_USAGE_ERROR"; fi
      ACTION_FLAG="${1#--}"; shift;;
    --status|--check) # Alias for status
      if [[ -n "$ACTION_FLAG" ]]; then error_exit "Multiple actions ('$ACTION_FLAG' and 'status') not allowed." "$EXIT_CODE_USAGE_ERROR"; fi
      ACTION_FLAG="status"; shift;;
    *)
      TEMP_ARGS+=("$1"); shift;; # Collect unknown options
  esac
done

if (( ${#TEMP_ARGS[@]} > 0 )); then
  error_exit "Unknown option or argument: ${TEMP_ARGS[0]}. Use --help for usage." "$EXIT_CODE_USAGE_ERROR"
fi
if [[ -z "$ACTION_FLAG" ]]; then
  error_exit "No action specified (e.g., --start, --status). Use --help for usage." "$EXIT_CODE_USAGE_ERROR"
fi

if [[ "$VERBOSE_MODE" == true ]]; then
  info "Verbose mode enabled (command tracing 'set -x' activated)."
  set -x
fi

# --- Enforce root for privileged actions ---
if [[ "$DRY_RUN" != true ]]; then # No root check needed for dry-run or non-modifying actions
  case "$ACTION_FLAG" in
    start|stop|restart|enable|disable|reset-failed)
      enforce_root;;
    logs|logs-follow|status)
      # These actions might not strictly need root but often provide more info with it.
      # For now, let them run without explicit root check if not modifying state.
      debug "Action '$ACTION_FLAG' does not require root, but may show more with it."
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
: "${APP_NAME:?APP_NAME not set in ${BASE_VARS_FILE}. Base install may be incomplete.}" "$EXIT_CODE_CONFIG_ERROR"
debug "Successfully sourced APP_NAME='${APP_NAME}' from base variables."

# --- Determine service names ---
MAIN_SERVICE_UNIT=""    # The primary .service file (bitmover.service or app@instance.service)
PATH_SERVICE_UNITS=()   # Array for related .path units, if any
RELATED_SERVICE_UNITS=() # Array for other related .service units (like restart helpers)
TARGET_DESC=""          # Description for logging

if [[ "$MODE" == "instance" ]]; then
  if [[ -z "$INSTANCE_NAME" ]]; then # Should have been caught by arg parsing if -i used without value
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
else # bitmover mode (default)
  MAIN_SERVICE_UNIT="$BITMOVER_SERVICE_NAME"
  # Global bitmover service might not have related path/restart units, or they might be named differently.
  # For this example, assume no standard related units for global bitmover.
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
  start)
    run systemctl start "$MAIN_SERVICE_UNIT"
    for unit in "${PATH_SERVICE_UNITS[@]}"; do run systemctl start "$unit"; done
    ;;
  stop)
    run systemctl stop "$MAIN_SERVICE_UNIT"
    for unit in "${PATH_SERVICE_UNITS[@]}"; do run systemctl stop "$unit"; done
    # Stopping related services might be too aggressive or handled by dependencies.
    # for unit in "${RELATED_SERVICE_UNITS[@]}"; do run systemctl stop "$unit"; done
    ;;
  restart)
    run systemctl restart "$MAIN_SERVICE_UNIT"
    # Path units are event-driven, restarting them directly isn't usually done.
    # Restarting related services might be needed if they don't pick up changes automatically.
    # For now, focusing on restarting the main service unit.
    if ((${#PATH_SERVICE_UNITS[@]} > 0)); then
      info "Note: Associated path unit(s) (${PATH_SERVICE_UNITS[*]}) are event-driven and not directly restarted."
    fi
    ;;
  status)
    SCRIPT_SUCCESSFUL=true # Status is informational, set success true if command runs
    echo "--- Status for $MAIN_SERVICE_UNIT ---"
    run systemctl status "$MAIN_SERVICE_UNIT" --no-pager
    for unit in "${PATH_SERVICE_UNITS[@]}"; do
      echo; echo "--- Status for $unit ---"
      run systemctl status "$unit" --no-pager
    done
    for unit in "${RELATED_SERVICE_UNITS[@]}"; do
      echo; echo "--- Status for $unit ---"
      run systemctl status "$unit" --no-pager
    done
    ;;
  logs)
    SCRIPT_SUCCESSFUL=true
    info "Displaying logs for $MAIN_SERVICE_UNIT ${SINCE_ARG:+(since $SINCE_ARG)}"
    # CORRECTED: Removed 'local'
    cmd_logs_main=("journalctl" "-u" "$MAIN_SERVICE_UNIT" "--no-pager")
    cmd_logs_main+=("${journalctl_opts_array[@]}")
    if [[ -z "$SINCE_ARG" ]]; then cmd_logs_main+=("-n" "50"); fi
    run "${cmd_logs_main[@]}"

    for unit in "${RELATED_SERVICE_UNITS[@]}"; do
      echo >&2; info "Displaying logs for related $unit ${SINCE_ARG:+(since $SINCE_ARG)}"
      # CORRECTED: Removed 'local'
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
      "${cmd_follow_array[@]}" || { # Direct execution, not via 'run' for interactive follow
        jc_exit_code=$?
        if [[ $jc_exit_code -eq 130 ]]; then # SIGINT (Ctrl-C)
          info "Journal follow interrupted by user (Ctrl-C)."
        else # Other errors from journalctl -f
          error_exit "journalctl -f command failed or was interrupted (exit code: $jc_exit_code)." "$EXIT_CODE_ACTION_FAILED"
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
  *) # Should not be reached due to ACTION_FLAG validation earlier
    error_exit "Unhandled action: '$ACTION_FLAG'. Internal error." "$EXIT_CODE_FATAL_ERROR"
    ;;
esac

# If we reached here for non-informational actions, and no 'run' command failed fatally (due to ERR trap calling error_exit)
# then the sequence of operations is considered successful at this script's level.
# FAIL_COUNT handles partial success reporting by the EXIT trap.
SCRIPT_SUCCESSFUL=true
# EXIT trap handles final summary messages