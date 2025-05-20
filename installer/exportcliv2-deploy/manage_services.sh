#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# --- Version ---
VERSION="1.1.3"  # Bumped for logs-follow fix

# --- Trap Signals ---
_ts() { date -u +'%Y-%m-%dT%H:%M:%SZ'; }
error_exit() { echo >&2 "$(_ts) [ERROR] $*"; exit 1; }
trap 'error_exit "Script interrupted by signal (INT or TERM)."' INT TERM

# --- Logging Helpers ---
info() { echo >&2 "$(_ts) [INFO]  $*"; }
warn() { echo >&2 "$(_ts) [WARN]  $*"; }

enforce_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    error_exit "This action requires root privileges. Please run with sudo."
  fi
}

# --- Constants & Defaults ---
BITMOVER_SERVICE_NAME="bitmover.service"
APP_NAME_FOR_BASE_VARS_LOOKUP="exportcliv2"
BASE_VARS_FILE="/etc/default/${APP_NAME_FOR_BASE_VARS_LOOKUP}_base_vars"

# --- State variables ---
INSTANCE_NAME=""
MODE="bitmover"
ACTION_FLAG=""
DRY_RUN=false
SINCE_ARG=""

usage() {
  local exit_code="${1:-1}"
  local me; me=$(basename "$0")
  cat <<EOF
Usage: $me [OPTIONS] ACTION_FLAG

Manage '$BITMOVER_SERVICE_NAME' (default) or an '$APP_NAME_FOR_BASE_VARS_LOOKUP' instance.

Options:
  -i, --instance NAME   Switch to instance mode for NAME.
  --since <time>        For logs: show entries since <time>.
  --dry-run, -n         Print commands without executing.
  --version             Show version and exit.
  -h, --help            Show this help and exit.

Actions (one only):
  --start               Start service(s).
  --stop                Stop service(s).
  --restart             Restart main service.
  --status, --check     Show status.
  --logs                Show recent logs (50 lines or since <time>).
  --logs-follow         Follow logs (can combine --since).
  --enable              Enable at boot.
  --disable             Disable at boot.

Examples:
  sudo $me --start
  sudo $me --logs-follow --since "30 minutes ago"
  sudo $me -i site_alpha --enable
EOF
  exit "$exit_code"
}

run() {
  if [[ "$DRY_RUN" == true ]]; then
    echo >&2 "$(_ts) [DRY-RUN] Would execute: $*"
    return 0
  fi
  info "Executing: $*"
  set +e
  "$@"
  local ec=$?
  set -e
  if [[ $ec -ne 0 ]]; then
    warn "Command exited $ec: $*"
  fi
  return $ec
}

# Handle version/help
for arg; do
  case $arg in
    --version) echo "$(basename "$0") v$VERSION"; exit 0 ;;
    -h|--help) usage 0 ;;
  esac
done

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    -i|--instance)
      INSTANCE_NAME="$2"; MODE="instance"; shift 2 ;;
    --since)
      SINCE_ARG="$2"; shift 2 ;;
    --dry-run|-n)
      DRY_RUN=true; shift ;;
    --start|--stop|--restart|--logs|--logs-follow|--enable|--disable)
      [[ -z "$ACTION_FLAG" ]] || error_exit "Multiple actions ('$ACTION_FLAG' and '${1#--}')"
      ACTION_FLAG="${1#--}"; shift ;;
    --status|--check)
      [[ -z "$ACTION_FLAG" ]] || error_exit "Multiple actions ('$ACTION_FLAG' and 'status')"
      ACTION_FLAG="status"; shift ;;
    -h|--help|--version)
      shift ;;
    *)
      error_exit "Unknown option/action: $1" ;;
  esac
done

# Enforce root for mutating actions
if [[ "$DRY_RUN" != true ]]; then
  case "$ACTION_FLAG" in
    start|stop|restart|enable|disable) enforce_root ;;
  esac
fi

[[ -n "$ACTION_FLAG" ]] || error_exit "No action specified. Use --help."

# Determine target services
MAIN_SERVICE=""
PATH_SERVICE=""
TARGET_DESC=""
APP_NAME=""

if [[ "$MODE" == "instance" ]]; then
  [[ -n "$INSTANCE_NAME" ]] || error_exit "Instance name required."
  [[ "$INSTANCE_NAME" =~ ^[A-Za-z0-9._-]+$ ]] || error_exit "Invalid instance name '$INSTANCE_NAME'."
  info "Instance mode for '$INSTANCE_NAME'"
  [[ -f "$BASE_VARS_FILE" ]] || error_exit "Missing $BASE_VARS_FILE"
  # shellcheck source=/dev/null
  source "$BASE_VARS_FILE"
  [[ -n "${APP_NAME:-}" ]] || error_exit "APP_NAME undefined in base vars."
  MAIN_SERVICE="${APP_NAME}@${INSTANCE_NAME}.service"
  PATH_SERVICE="${APP_NAME}-restart@${INSTANCE_NAME}.path"
  TARGET_DESC="${APP_NAME} instance '${INSTANCE_NAME}'"
else
  MAIN_SERVICE="$BITMOVER_SERVICE_NAME"
  TARGET_DESC="Bitmover service ($MAIN_SERVICE)"
  info "Bitmover mode"
fi

# Prepare journalctl --since options
journalctl_since_opts_array=()
if [[ -n "$SINCE_ARG" ]]; then
  journalctl_since_opts_array=(--since "$SINCE_ARG")
fi

info "About to '$ACTION_FLAG' on $TARGET_DESC (dry-run=$DRY_RUN)"

# Execute action
case "$ACTION_FLAG" in
  start)
    run systemctl start "$MAIN_SERVICE"
    [[ -n "$PATH_SERVICE" ]] && run systemctl start "$PATH_SERVICE"
    ;;

  stop)
    run systemctl stop "$MAIN_SERVICE"
    [[ -n "$PATH_SERVICE" ]] && run systemctl stop "$PATH_SERVICE"
    ;;

  restart)
    run systemctl restart "$MAIN_SERVICE"
    info "Path unit '$PATH_SERVICE' unaffected by restart.";;

  status)
    run systemctl status "$MAIN_SERVICE" --no-pager
    if [[ -n "$PATH_SERVICE" ]]; then
      echo >&2
      info "Status for path unit $PATH_SERVICE:"
      run systemctl status "$PATH_SERVICE" --no-pager
    fi
    ;;

  logs)
    info "Logs for $MAIN_SERVICE"
    main_log=(journalctl -u "$MAIN_SERVICE" --no-pager "${journalctl_since_opts_array[@]}")
    [[ ${#journalctl_since_opts_array[@]} -eq 0 ]] && main_log+=(-n50)
    run "${main_log[@]}"

    if [[ -n "$PATH_SERVICE" ]]; then
      echo >&2
      restart_unit="${APP_NAME}-restart@${INSTANCE_NAME}.service"
      info "Logs for $restart_unit"
      rlog=(journalctl -u "$restart_unit" --no-pager "${journalctl_since_opts_array[@]}")
      [[ ${#journalctl_since_opts_array[@]} -eq 0 ]] && rlog+=(-n20)
      run "${rlog[@]}"
    fi
    ;;

  logs-follow)
    info "Following logs for $MAIN_SERVICE${PATH_SERVICE:+ and $PATH_SERVICE}"
    follow_cmd=(journalctl -f -u "$MAIN_SERVICE")
    if [[ -n "$PATH_SERVICE" ]]; then
      follow_cmd+=("-u" "$PATH_SERVICE")
    fi
    follow_cmd+=("${journalctl_since_opts_array[@]}")
    run "${follow_cmd[@]}"
    ;;

  enable)
    run systemctl enable "$MAIN_SERVICE"
    [[ -n "$PATH_SERVICE" ]] && run systemctl enable "$PATH_SERVICE"
    info "Enabled at boot; consider 'systemctl daemon-reload'.";;

  disable)
    run systemctl disable "$MAIN_SERVICE"
    [[ -n "$PATH_SERVICE" ]] && run systemctl disable "$PATH_SERVICE"
    info "Disabled at boot; consider 'systemctl daemon-reload'.";;

  *)
    error_exit "Unhandled action: '$ACTION_FLAG'";;

esac

[[ "$DRY_RUN" == false ]] && info "Completed '$ACTION_FLAG' on $TARGET_DESC."
exit 0
