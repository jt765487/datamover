#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# -----------------------------------------------------------------------------
# Simple Instance Configurator for exportcliv2
# -----------------------------------------------------------------------------
# - Creates or copies /etc/exportcliv2/<instance>.conf
# - Prints exactly which systemctl/journalctl commands to run next
# - Enforces root execution. Includes error trap.
# - Guards against overwrites without --force.
# - Validates instance name.
# -----------------------------------------------------------------------------

# --- Logging Helpers ---
_ts()   { date -u +'%Y-%m-%dT%H:%M:%SZ'; }
info()  { echo "$(_ts) [INFO]  $*"; }
warn()  { echo "$(_ts) [WARN]  $*"; }
error_exit() { echo "$(_ts) [ERROR] $*" >&2; exit 1; }

# --- Cleanup function for ERR trap ---
# First argument is the exit code
# Second argument is the line number
# Third argument is the command that failed
# shellcheck disable=SC2317
cleanup_on_error() {

  local exit_code="${1:-1}" # Default to 1 if not provided
  local line_num="${2:-UNKNOWN_LINE}"
  local failed_command="${3:-UNKNOWN_COMMAND}"

  warn "Instance configuration FAILED on line ${line_num} with command: ${failed_command} (exit code: ${exit_code})."
  warn "The system might be in an inconsistent state."
  warn "Please review logs and manually clean up if necessary."
  # No explicit exit here; the script will exit due to 'set -e' after the trap finishes
}
trap 'cleanup_on_error "$?" "$LINENO" "$BASH_COMMAND"' ERR

# --- Enforce Root Execution ---
if [[ "$(id -u)" -ne 0 ]]; then
  error_exit "This script must be run as root or with sudo."
fi

# --- Defaults & CLI State ---
DRY_RUN=""
INSTANCE=""
CONFIG_SRC=""
FORCE_OVERWRITE="" # New flag for --force

# Base‐vars lookup
APP_NAME_FOR_BASE_VARS_LOOKUP="exportcliv2"
BASE_VARS_FILE="/etc/default/${APP_NAME_FOR_BASE_VARS_LOOKUP}_base_vars"

# Defaults for generated configs
DEFAULT_EXPORT_TIMEOUT="60"
DEFAULT_EXPORT_IP="10.0.0.1"
DEFAULT_EXPORT_PORTID="1"
DEFAULT_EXPORT_START_DATE="today"
DEFAULT_EXPORT_START_TIME="00:00"
DEFAULT_EXPORT_END_DATE="today"
DEFAULT_EXPORT_END_TIME="23:59"

usage() {
  cat <<EOF
Usage: $(basename "$0") -i INSTANCE_NAME [--config-source-file PATH] [--force] [-n] [-h]

Configures a new instance for the '${APP_NAME_FOR_BASE_VARS_LOOKUP}' application.
This script MUST be run as root or with sudo.

Options:
  -i, --instance NAME       REQUIRED: This instance’s name (e.g. "lab1", "prod_main").
                              Allowed characters: A-Z, a-z, 0-9, dot (.), underscore (_), dash (-).
  --config-source-file PATH Optional: Path to a pre-existing configuration file to copy.
                              If not provided, a default configuration will be generated.
  --force                   Optional: Overwrite an existing instance configuration file.
                              Without this, the script will exit if the target config exists.
  -n, --dry-run             Print actions that would be taken, but do not execute them.
  -h, --help                Show this help message and exit.
EOF
  exit 1
}

# --- Parse args ---
while [[ $# -gt 0 ]]; do
  case $1 in
    -i|--instance)
      INSTANCE="$2"; shift 2 ;;
    --config-source-file)
      CONFIG_SRC="$2"; shift 2 ;;
    --force)
      FORCE_OVERWRITE="true"; shift ;;
    -n|--dry-run)
      DRY_RUN="echo"; shift ;;
    -h|--help)
      usage ;;
    *)
      error_exit "Unknown option: \"$1\". Use -h for help.";;
  esac
done

# Validate mandatory instance name
[[ -n "$INSTANCE" ]] || { warn "Instance name is required."; usage; }

# Validate instance name format
if ! [[ "$INSTANCE" =~ ^[A-Za-z0-9._-]+$ ]]; then
  error_exit "Invalid instance name: \"${INSTANCE}\". Only A-Z, a-z, 0-9, dot (.), underscore (_), and dash (-) are allowed."
fi
info "Validated instance name: \"${INSTANCE}\""

# --- Pre-flight check for required commands ---
declare -a required_commands=("getent" "install" "date" "id" "basename")
info "Checking for required commands..."
for cmd in "${required_commands[@]}"; do
  command -v "$cmd" &>/dev/null || error_exit "Required command \"${cmd}\" is not installed or not in PATH."
done
info "All required commands are available."

# --- Load Base Vars ---
info "Attempting to load base variables from \"${BASE_VARS_FILE}\"..."
if [[ ! -f "$BASE_VARS_FILE" ]]; then
  error_exit "Base variables file \"${BASE_VARS_FILE}\" not found. Ensure the base installer (e.g., install_base_exportcliv2.sh) was run successfully."
fi
# shellcheck source=/dev/null
source "$BASE_VARS_FILE"
info "Successfully sourced base variables from \"${BASE_VARS_FILE}\"."

# Validate what we got from base-vars
: "${APP_NAME:?ERROR: APP_NAME not set in base-vars file (\"${BASE_VARS_FILE}\")}"
: "${ETC_DIR:?ERROR: ETC_DIR not set in base-vars file (\"${BASE_VARS_FILE}\")}"
: "${APP_GROUP:?ERROR: APP_GROUP not set in base-vars file (\"${BASE_VARS_FILE}\")}"
info "Using APP_NAME from base vars: \"${APP_NAME}\" (for service names, etc.)"
info "Using ETC_DIR from base vars: \"${ETC_DIR}\""
info "Using APP_GROUP from base vars: \"${APP_GROUP}\" (for config file group ownership)"

TARGET_CONF_DIR="$ETC_DIR"
TARGET_CONF_FILE="${TARGET_CONF_DIR}/${INSTANCE}.conf"

# --- Guard against accidental overwrites ---
if [[ -e "$TARGET_CONF_FILE" && -z "$FORCE_OVERWRITE" && -z "$DRY_RUN" ]]; then
  error_exit "Instance configuration file \"${TARGET_CONF_FILE}\" already exists. Use --force to overwrite, or choose a different instance name."
elif [[ -e "$TARGET_CONF_FILE" && -n "$FORCE_OVERWRITE" && -z "$DRY_RUN" ]]; then
  warn "Instance configuration file \"${TARGET_CONF_FILE}\" already exists. --force specified, proceeding with overwrite."
elif [[ -e "$TARGET_CONF_FILE" && -z "$FORCE_OVERWRITE" && -n "$DRY_RUN" ]]; then
  info "[DRY_RUN] Instance configuration file \"${TARGET_CONF_FILE}\" exists. If not in dry-run, --force would be required to overwrite."
fi


# --- Ensure config dir exists ---
info "Ensuring target configuration directory exists: \"${TARGET_CONF_DIR}\""
$DRY_RUN install -d -o root -g root -m0755 "$TARGET_CONF_DIR" \
  || error_exit "Failed to create or set permissions for directory \"${TARGET_CONF_DIR}\"."

# --- Deploy or Generate Instance Configuration File ---
if [[ -n "$CONFIG_SRC" ]]; then
  info "Using user-provided configuration source file: \"${CONFIG_SRC}\""
  if [[ ! -f "$CONFIG_SRC" ]]; then
    error_exit "Specified configuration source file \"${CONFIG_SRC}\" not found."
  fi
  info "Copying \"${CONFIG_SRC}\" to \"${TARGET_CONF_FILE}\"..."
  $DRY_RUN install -T -o root -g "$APP_GROUP" -m0640 "$CONFIG_SRC" "$TARGET_CONF_FILE" \
    || error_exit "Failed to copy \"${CONFIG_SRC}\" to \"${TARGET_CONF_FILE}\"."
  info "Successfully copied configuration to \"${TARGET_CONF_FILE}\"."
else
  info "Generating default configuration file at \"${TARGET_CONF_FILE}\" for instance \"${INSTANCE}\"..."
  current_date_resolved_for_config=$(date +%Y-%m-%d)
  start_date_for_config=${DEFAULT_EXPORT_START_DATE//today/$current_date_resolved_for_config}
  end_date_for_config=${DEFAULT_EXPORT_END_DATE//today/$current_date_resolved_for_config}
  script_basename=$(basename "$0")

  generated_content=$(cat <<EOF
# ${APP_NAME} instance "${INSTANCE}" configuration
# Generated by ${script_basename} on $(_ts)

EXPORT_TIMEOUT="${DEFAULT_EXPORT_TIMEOUT}"
EXPORT_SOURCE="${INSTANCE}"

# Optional: Review and adjust these default values as needed.
# For example, EXPORT_IP, EXPORT_PORTID, and date/time ranges.
# If authentication is required by your exportcliv2 setup, add:
# EXPORT_AUTH_TOKEN_U="your_username_token"
# EXPORT_AUTH_TOKEN_P="your_password_token"

EXPORT_IP="${DEFAULT_EXPORT_IP}"
EXPORT_PORTID="${DEFAULT_EXPORT_PORTID}"
EXPORT_STARTTIME="${start_date_for_config}/${DEFAULT_EXPORT_START_TIME}"
EXPORT_ENDTIME="${end_date_for_config}/${DEFAULT_EXPORT_END_TIME}"
EOF
) # End of generated_content assignment

  if [[ -n "$DRY_RUN" ]]; then
    info "[DRY_RUN] Would write the following content to \"${TARGET_CONF_FILE}\":"
    echo "--- BEGIN GENERATED CONFIG ---"
    echo "$generated_content"
    echo "--- END GENERATED CONFIG ---"
    info "[DRY_RUN] Would set permissions to 0640 and ownership to root:${APP_GROUP} for \"${TARGET_CONF_FILE}\"."
  else
    info "Writing generated configuration to \"${TARGET_CONF_FILE}\"..."
    printf "%s\n" "$generated_content" > "$TARGET_CONF_FILE" \
      || error_exit "Failed to write generated configuration to \"${TARGET_CONF_FILE}\"."
    info "Setting permissions (0640) on \"${TARGET_CONF_FILE}\"..."
    chmod 0640 "$TARGET_CONF_FILE" \
      || error_exit "Failed to set permissions on \"${TARGET_CONF_FILE}\"."
    info "Setting ownership (root:${APP_GROUP}) on \"${TARGET_CONF_FILE}\"..."
    chown "root:$APP_GROUP" "$TARGET_CONF_FILE" \
      || error_exit "Failed to set ownership on \"${TARGET_CONF_FILE}\"."
    info "Successfully generated and saved default configuration to \"${TARGET_CONF_FILE}\"."
  fi
fi

# --- Next Steps Information ---
info "Instance configuration for \"${INSTANCE}\" is ready at: \"${TARGET_CONF_FILE}\""
info "If you generated a default configuration, please review and edit it as needed."

main_service_name="${APP_NAME}@${INSTANCE}.service"
path_service_name="${APP_NAME}-restart@${INSTANCE}.path"

cat <<EOF

-----------------------------------------------------------------------------
Instance '${INSTANCE}' of '${APP_NAME}' is configured.
Configuration file: ${TARGET_CONF_FILE}
-----------------------------------------------------------------------------

Next Steps: Manage this instance with systemd:

1. Enable services to start at boot:
   sudo systemctl enable ${main_service_name}
   sudo systemctl enable ${path_service_name}

2. Start services now:
   sudo systemctl start ${main_service_name}
   # The .path unit usually starts automatically if its corresponding .service is active
   # or can be started explicitly if needed:
   # sudo systemctl start ${path_service_name}

3. Check status:
   sudo systemctl status ${main_service_name}
   sudo systemctl status ${path_service_name}

4. View logs:
   sudo journalctl -u ${main_service_name} -n50 --no-pager
   sudo journalctl -u ${main_service_name} -f

5. Stop services:
   sudo systemctl stop ${main_service_name}
   # Stopping the .path unit might also be desired if you want to stop monitoring:
   # sudo systemctl stop ${path_service_name}

6. Restart main service:
   sudo systemctl restart ${main_service_name}

-----------------------------------------------------------------------------
Remember to review/edit '${TARGET_CONF_FILE}' if defaults were generated.
-----------------------------------------------------------------------------
EOF

exit 0
