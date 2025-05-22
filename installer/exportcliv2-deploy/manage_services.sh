#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# --- Version ---
VERSION="1.2.6"

# --- Exit Codes ---
readonly EXIT_CODE_SUCCESS=0
readonly EXIT_CODE_GENERAL_ERROR=1
readonly EXIT_CODE_USAGE_ERROR=2
readonly EXIT_CODE_CONFIG_ERROR=3
readonly EXIT_CODE_PREREQUISITE_ERROR=4
readonly EXIT_CODE_ACTION_FAILED=6

# --- Logging Helpers ---
_ts() { date -u +'%Y-%m-%dT%H:%M:%SZ'; }
info() { echo >&2 "$(_ts) [INFO]  $*"; }
warn() { echo >&2 "$(_ts) [WARN]  $*"; }
error_exit() {
  local message="$1"
  local exit_code="${2:-$EXIT_CODE_GENERAL_ERROR}"
  # SCRIPT_SUCCESSFUL is false by default or set false by ERR trap before error_exit might be called
  # No need to set SCRIPT_SUCCESSFUL=false here as exit is immediate.
  echo >&2 "$(_ts) [ERROR] $message"
  exit "$exit_code"
}

SCRIPT_SUCCESSFUL=false
HELP_OR_VERSION_EXIT=false
INFORMATIONAL_ACTION_PERFORMED=false # New flag

# --- Cleanup Traps ---
# shellcheck disable=SC2317
cleanup_on_error() {
  local exit_code="${1:-$?}"
  local line_num="${2:-UNKNOWN_LINE}"
  local failed_command="${3:-UNKNOWN_COMMAND}"
  # This trap is for 'set -e' exits or unhandled errors.
  # error_exit calls 'exit' directly, so its message is the primary one.
  if [[ $exit_code -ne $EXIT_CODE_SUCCESS && $failed_command != error_exit* ]]; then
    warn "Script FAILED on line ${line_num} with command: ${failed_command} (exit code: ${exit_code})."
  fi
  SCRIPT_SUCCESSFUL=false # Ensure this is false if ERR trap is hit
}

# shellcheck disable=SC2317
cleanup_on_exit() {
  local exit_code="${1:-$?}" # Actual exit code of the script
  if [[ "$HELP_OR_VERSION_EXIT" == true ]]; then
    : # No summary message for --help or --version exits
  elif [[ "$INFORMATIONAL_ACTION_PERFORMED" == true && "$SCRIPT_SUCCESSFUL" == true && $exit_code -eq $EXIT_CODE_SUCCESS ]]; then
    : # No summary message for successful informational actions (status, logs)
  elif [[ "$SCRIPT_SUCCESSFUL" == true && $exit_code -eq $EXIT_CODE_SUCCESS ]]; then
    info "-------------------- OPERATION COMPLETED SUCCESSFULLY --------------------"
  elif [[ $exit_code -ne $EXIT_CODE_SUCCESS ]]; then # Any non-zero exit code means failure
    # SCRIPT_SUCCESSFUL should be false if we got here with a non-zero exit.
    # The specific error message should have already been printed.
    info "-------------------- OPERATION FAILED (EXIT CODE: $exit_code) --------------------"
  # else
    # This case (exit_code == 0 BUT SCRIPT_SUCCESSFUL == false) implies an issue
    # in script logic, e.g., an error was caught but script still exited 0.
    # Or HELP_OR_VERSION_EXIT was false and INFORMATIONAL_ACTION_PERFORMED was false,
    # and SCRIPT_SUCCESSFUL was false, but we exited 0. This shouldn't happen.
    # warn "Script exited with code 0 but was not marked as fully successful. Review logic."
  fi
}

trap 'cleanup_on_error "$?" "$LINENO" "$BASH_COMMAND"' ERR
trap 'cleanup_on_exit $?' EXIT # Catches all exits, including those from error_exit
trap 'error_exit "Script interrupted by signal." "$EXIT_CODE_GENERAL_ERROR"' INT TERM


# --- Helpers ---
enforce_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    error_exit "This action requires root or sudo." "$EXIT_CODE_PREREQUISITE_ERROR"
  fi
}

run() {
  local cmd_for_display # Variable to hold the command string for display

  # Construct a string representation of the command for logging.
  # "$*" normally joins arguments with the first character of IFS.
  # To display them on one line separated by spaces for the log,
  # we temporarily change IFS just for this string construction.
  if ((${#@})); then # Check if there are any arguments to the run function
      local OLD_IFS="$IFS"
      IFS=' ' # Set IFS to a single space for joining arguments
      cmd_for_display="$*" # Now $* expands with arguments separated by spaces
      IFS="$OLD_IFS" # Restore original IFS
  else
      cmd_for_display="" # Handle cases where run might be called with no args (though unlikely here)
  fi

  if [[ "${DRY_RUN:-false}" == true ]]; then
    # Use the space-joined string for dry-run output as well
    printf "%s [DRY-RUN] Would execute: %s\n" "$(_ts)" "$cmd_for_display" >&2
    return 0 # Assume success for dry run to allow script to continue
  fi

  # Use the space-joined string for info log
  info "Executing: $cmd_for_display"

  set +e # Temporarily disable exit on error to capture exit code
  "$@"   # Execute the actual command with original argument separation preserved
  local ec=$? # Capture exit code of the command
  set -e # Re-enable exit on error

  if [[ $ec -ne 0 ]]; then
    # Check if the command was 'systemctl status ...'
    if [[ "$1" == "systemctl" && "$2" == "status" ]]; then
      local unit_name="$3" # In this script, the unit name is reliably the 3rd argument

      case "$ec" in
        3)
          info "Service '$unit_name' is inactive/dead (systemctl exit code: $ec). This is often a normal state."
          ;;
        4)
          warn "Service '$unit_name' not found (systemctl exit code: $ec). Command: $cmd_for_display"
          ;;
        *)
          warn "Status check for '$unit_name' reported an issue (systemctl exit code: $ec). Command: $cmd_for_display"
          ;;
      esac
    else
      # Generic warning for all other commands that exit non-zero
      # Also use the nicely formatted cmd_for_display here
      warn "Command exited with code $ec: $cmd_for_display"
    fi
  fi
  return $ec
}

# --- Constants & Defaults ---
readonly BITMOVER_SERVICE_NAME="bitmover.service"
readonly APP_NAME_FOR_BASE_VARS_LOOKUP="exportcliv2"
readonly BASE_VARS_FILE="/etc/default/${APP_NAME_FOR_BASE_VARS_LOOKUP}_base_vars"

# --- State Variables ---
INSTANCE_NAME=""
MODE="bitmover"
ACTION_FLAG=""
DRY_RUN=false
SINCE_ARG=""

# --- Usage ---
usage() {
  local code="${1:-$EXIT_CODE_USAGE_ERROR}" # Default to usage error
  # If called for -h, code will be EXIT_CODE_SUCCESS
  if [[ "$code" -eq "$EXIT_CODE_SUCCESS" ]]; then
    HELP_OR_VERSION_EXIT=true # Signal that this is a clean help/version exit
  fi
  cat <<EOF
Usage: $(basename "$0") [OPTIONS] ACTION_FLAG

Manage '$BITMOVER_SERVICE_NAME' (default) or an '$APP_NAME_FOR_BASE_VARS_LOOKUP' instance.

Options:
  -i, --instance NAME   Switch to instance mode for NAME.
  --since <time>        Show logs since <time> (e.g., "1 hour ago", "YYYY-MM-DD HH:MM:SS").
  -n, --dry-run         Print commands without executing.
  --version             Show version and exit.
  -h, --help            Show this help and exit.

Actions (one only):
  --start               Start service(s).
  --stop                Stop service(s).
  --restart             Restart main service.
  --status, --check     Show status.
  --logs                Show logs (default lines or since).
  --logs-follow         Follow logs (can combine --since).
  --enable              Enable at boot.
  --disable             Disable at boot.
  --reset-failed        Reset failed state for service(s).

Examples:
  sudo $(basename "$0") --start
  sudo $(basename "$0") --logs-follow --since "30 minutes ago"
  sudo $(basename "$0") -i site_alpha --enable
EOF
  exit "$code"
}

# --- Early help/version scan ---
for arg_scan in "$@"; do # Iterate through all arguments
  case "$arg_scan" in
    --version)
      echo "$(basename "$0") v$VERSION"
      HELP_OR_VERSION_EXIT=true # Signal for exit trap
      exit $EXIT_CODE_SUCCESS
      ;;
    -h|--help)
      # HELP_OR_VERSION_EXIT will be set inside usage()
      usage $EXIT_CODE_SUCCESS
      ;;
  esac
done

# --- Parse Args ---
TEMP_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -i|--instance)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then error_exit "Option $1 requires a NAME argument." $EXIT_CODE_USAGE_ERROR; fi
      INSTANCE_NAME="$2"; MODE="instance"; shift 2;;
    --since)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then error_exit "Option --since requires a time argument." $EXIT_CODE_USAGE_ERROR; fi
      SINCE_ARG="$2"; shift 2;;
    -n|--dry-run)
      DRY_RUN=true; shift;;
    --start|--stop|--restart|--logs|--logs-follow|--enable|--disable|--reset-failed)
      if [[ -n "$ACTION_FLAG" ]]; then error_exit "Multiple actions ('$ACTION_FLAG' and '${1#--}') not allowed." $EXIT_CODE_USAGE_ERROR; fi
      ACTION_FLAG="${1#--}"; shift;;
    --status|--check)
      if [[ -n "$ACTION_FLAG" ]]; then error_exit "Multiple actions ('$ACTION_FLAG' and 'status') not allowed." $EXIT_CODE_USAGE_ERROR; fi
      ACTION_FLAG="status"; shift;;
    *)
      TEMP_ARGS+=("$1"); shift;; # Collect unrecognized arguments
  esac
done

if [[ ${#TEMP_ARGS[@]} -gt 0 ]]; then
  error_exit "Unknown/misplaced argument(s): ${TEMP_ARGS[*]}. Use --help." $EXIT_CODE_USAGE_ERROR
fi

if [[ -z "$ACTION_FLAG" ]]; then
  error_exit "No action specified. Use --help." $EXIT_CODE_USAGE_ERROR
fi

# --- Enforce root for privileged actions ---
if [[ "$DRY_RUN" != true ]]; then
  case "$ACTION_FLAG" in
    start|stop|restart|enable|disable|reset-failed)
      enforce_root;;
  esac
fi

# --- Load base vars ---
if [[ ! -f "$BASE_VARS_FILE" ]]; then
  error_exit "Base vars file not found: $BASE_VARS_FILE." $EXIT_CODE_CONFIG_ERROR
fi
info "Sourcing $BASE_VARS_FILE..."
# shellcheck source=/dev/null
source "$BASE_VARS_FILE"
: "${APP_NAME:?APP_NAME missing in $BASE_VARS_FILE.}" $EXIT_CODE_CONFIG_ERROR
# Other vars like BASE_DIR are not strictly required by this service manager script,
# but they don't hurt to be present in the environment.

# --- Determine service names ---
MAIN_SERVICE=""
PATH_SERVICE=""
RESTART_SERVICE=""
TARGET_DESC=""

if [[ "$MODE" == "instance" ]]; then
  if [[ ! "$INSTANCE_NAME" =~ ^[A-Za-z0-9._-]+$ ]]; then
    error_exit "Invalid instance name: '$INSTANCE_NAME'." $EXIT_CODE_USAGE_ERROR
  fi
  MAIN_SERVICE="${APP_NAME}@${INSTANCE_NAME}.service"
  PATH_SERVICE="${APP_NAME}-restart@${INSTANCE_NAME}.path"
  RESTART_SERVICE="${APP_NAME}-restart@${INSTANCE_NAME}.service"
  TARGET_DESC="${APP_NAME} instance '$INSTANCE_NAME'"
  info "Mode: Instance '$INSTANCE_NAME'"
else
  MAIN_SERVICE="$BITMOVER_SERVICE_NAME"
  TARGET_DESC="Bitmover service ($MAIN_SERVICE)"
  info "Mode: Bitmover"
fi

# --- Prepare journalctl options ---
journalctl_since_opts=()
if [[ -n "$SINCE_ARG" ]]; then
  journalctl_since_opts=(--since "$SINCE_ARG")
fi

info "Performing '$ACTION_FLAG' on $TARGET_DESC (Dry-run: $DRY_RUN)"

# --- Dispatch Actions ---
case "$ACTION_FLAG" in
  start)
    run systemctl start "$MAIN_SERVICE" || error_exit "Failed to start $MAIN_SERVICE" $EXIT_CODE_ACTION_FAILED
    if [[ -n "$PATH_SERVICE" ]]; then
      run systemctl start "$PATH_SERVICE" # Path units usually start if their .service is started/enabled
    fi
    ;;
  stop)
    run systemctl stop "$MAIN_SERVICE" || error_exit "Failed to stop $MAIN_SERVICE" $EXIT_CODE_ACTION_FAILED
    if [[ -n "$PATH_SERVICE" ]]; then
      run systemctl stop "$PATH_SERVICE"
    fi
    ;;
  restart)
    run systemctl restart "$MAIN_SERVICE" || error_exit "Failed to restart $MAIN_SERVICE" $EXIT_CODE_ACTION_FAILED
    if [[ -n "$PATH_SERVICE" ]]; then
      info "Note: Associated path unit ($PATH_SERVICE) is event-driven and not directly restarted."
    fi
    ;;
  status)
    INFORMATIONAL_ACTION_PERFORMED=true # Signal for exit trap
    echo "--- Status for $MAIN_SERVICE ---"
    run systemctl status "$MAIN_SERVICE" --no-pager || true # Allow non-zero exit (e.g. service failed)
    if [[ -n "$PATH_SERVICE" ]]; then
      echo; echo "--- Status for $PATH_SERVICE ---"
      run systemctl status "$PATH_SERVICE" --no-pager || true
    fi
    if [[ -n "$RESTART_SERVICE" ]]; then
      echo; echo "--- Status for related service $RESTART_SERVICE ---"
      run systemctl status "$RESTART_SERVICE" --no-pager || true
    fi
    ;;
  logs)
    INFORMATIONAL_ACTION_PERFORMED=true # Signal for exit trap
    info "Displaying logs for $MAIN_SERVICE ${SINCE_ARG:+(since $SINCE_ARG)}"
    cmd_logs=(journalctl -u "$MAIN_SERVICE" --no-pager)
    cmd_logs+=("${journalctl_since_opts[@]}")
    [[ ${#journalctl_since_opts[@]} -eq 0 ]] && cmd_logs+=("-n" "50")
    run "${cmd_logs[@]}" || true # Allow non-zero exit (e.g. no logs found)

    if [[ -n "$RESTART_SERVICE" ]]; then
      echo >&2
      info "Displaying logs for related $RESTART_SERVICE ${SINCE_ARG:+(since $SINCE_ARG)}"
      cmd_logs_restart=(journalctl -u "$RESTART_SERVICE" --no-pager)
      cmd_logs_restart+=("${journalctl_since_opts[@]}")
      [[ ${#journalctl_since_opts[@]} -eq 0 ]] && cmd_logs_restart+=("-n" "20")
      run "${cmd_logs_restart[@]}" || true
    fi
    ;;
  logs-follow)
    INFORMATIONAL_ACTION_PERFORMED=true # Signal for exit trap
    units_to_follow=( -u "$MAIN_SERVICE" )
    [[ -n "$PATH_SERVICE" ]]     && units_to_follow+=( -u "$PATH_SERVICE" )
    [[ -n "$RESTART_SERVICE" ]]  && units_to_follow+=( -u "$RESTART_SERVICE" )

    info "Following logs for services: ${units_to_follow[*]} ${SINCE_ARG:+(since $SINCE_ARG)}"
    cmd_follow=(journalctl -f "${units_to_follow[@]}") # Use array quoting
    cmd_follow+=("${journalctl_since_opts[@]}")

    if [[ "$DRY_RUN" == true ]]; then
      printf "%s [DRY-RUN] Would execute: %s\n" "$(_ts)" "${cmd_follow[*]}" >&2
    else
      # Run directly. Ctrl-C should exit journalctl, not necessarily error script.
      "${cmd_follow[@]}" || {
        # This block executes if journalctl -f exits non-zero
        jc_exit_code=$?
        # SIGINT (Ctrl-C) typically results in exit code 130
        if [[ $jc_exit_code -eq 130 ]]; then
          info "Journal follow interrupted by user (Ctrl-C)."
          # This is a clean interruption, so don't call error_exit.
          # SCRIPT_SUCCESSFUL will be set to true at the end of script.
        else
          # Other non-zero exit from journalctl -f is an actual error.
          error_exit "journalctl -f command failed or was interrupted unexpectedly (exit code: $jc_exit_code)." $EXIT_CODE_ACTION_FAILED
        fi
      }
    fi
    ;;
  enable)
    run systemctl enable "$MAIN_SERVICE" || error_exit "Failed to enable $MAIN_SERVICE" $EXIT_CODE_ACTION_FAILED
    if [[ -n "$PATH_SERVICE" ]]; then
      run systemctl enable "$PATH_SERVICE" || error_exit "Failed to enable $PATH_SERVICE" $EXIT_CODE_ACTION_FAILED
    fi
    info "$TARGET_DESC service(s) enabled."
    ;;
  disable)
    run systemctl disable "$MAIN_SERVICE" || error_exit "Failed to disable $MAIN_SERVICE" $EXIT_CODE_ACTION_FAILED
    if [[ -n "$PATH_SERVICE" ]]; then
      run systemctl disable "$PATH_SERVICE" || error_exit "Failed to disable $PATH_SERVICE" $EXIT_CODE_ACTION_FAILED
    fi
    info "$TARGET_DESC service(s) disabled."
    ;;
  reset-failed)
    info "Resetting failed state for $MAIN_SERVICE..."
    run systemctl reset-failed "$MAIN_SERVICE" || error_exit "Failed to reset-failed state for $MAIN_SERVICE" $EXIT_CODE_ACTION_FAILED
    if [[ -n "$PATH_SERVICE" ]]; then
      # Resetting failed on a path unit can clear issues if it failed to load/watch.
      run systemctl reset-failed "$PATH_SERVICE" || error_exit "Failed to reset-failed state for $PATH_SERVICE" $EXIT_CODE_ACTION_FAILED
    fi
    info "$TARGET_DESC service(s) failed state reset."
    ;;
  *)
    # This case should ideally not be reached due to the ACTION_FLAG check after parsing.
    error_exit "Unhandled action: '$ACTION_FLAG'. Internal error." $EXIT_CODE_GENERAL_ERROR
    ;;
esac

SCRIPT_SUCCESSFUL=true # If we reach here, the action was dispatched and handled as intended.
# The EXIT trap will now print the success message unless it was an informational action or help/version.
exit $EXIT_CODE_SUCCESS