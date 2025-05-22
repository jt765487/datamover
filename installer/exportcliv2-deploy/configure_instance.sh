#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# -----------------------------------------------------------------------------
# Instance Configurator for exportcliv2
# -----------------------------------------------------------------------------
# - Creates or copies /etc/exportcliv2/<instance>.conf (environment variables for wrapper)
# - Creates /etc/exportcliv2/<instance>_app.conf (config file for exportcliv2 binary -c arg)
# - Prints systemctl/journalctl commands for next steps.
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
# shellcheck disable=SC2317
cleanup_on_error() {
  local exit_code="${1:-1}"
  local line_num="${2:-UNKNOWN_LINE}"
  local failed_command="${3:-UNKNOWN_COMMAND}"
  warn "Instance configuration FAILED on line ${line_num} with command: ${failed_command} (exit code: ${exit_code})."
  warn "The system might be in an inconsistent state."
  warn "Please review logs and manually clean up if necessary."
}
trap 'cleanup_on_error "$?" "$LINENO" "$BASH_COMMAND"' ERR

# --- Enforce Root Execution ---
if [[ "$(id -u)" -ne 0 ]]; then
  error_exit "This script must be run as root or with sudo."
fi

# --- Defaults & CLI State ---
DRY_RUN=""
INSTANCE=""
CONFIG_SRC_ENV_FILE="" # For sourcing an existing <instance>.conf (environment vars)
FORCE_OVERWRITE=""

APP_NAME_FOR_BASE_VARS_LOOKUP="exportcliv2"
BASE_VARS_FILE="/etc/default/${APP_NAME_FOR_BASE_VARS_LOOKUP}_base_vars"

# Defaults for generated configs
DEFAULT_EXPORT_IP="10.0.0.1"
DEFAULT_EXPORT_PORTID="1"
DEFAULT_EXPORT_STARTTIME_OFFSET_SPEC="3 minutes ago" # For wrapper script
DEFAULT_EXPORT_ENDTIME_VALUE="-1"                    # For exportcliv2 binary (passed by wrapper)
DEFAULT_APP_CONFIG_CONTENT="mining_delta_sec=120"    # Content for the -c config file

usage() {
  cat <<EOF
Usage: $(basename "$0") -i INSTANCE_NAME [--config-source-env-file PATH] [--force] [-n] [-h]

Configures a new instance for the '${APP_NAME_FOR_BASE_VARS_LOOKUP}' application.
This script MUST be run as root or with sudo.
It creates two configuration files per instance in ${ETC_DIR:-/etc/${APP_NAME_FOR_BASE_VARS_LOOKUP}}:
  1. <INSTANCE_NAME>.conf: Environment variables for the wrapper script.
  2. <INSTANCE_NAME>_app.conf: Config file passed via -c to the main binary.

Options:
  -i, --instance NAME       REQUIRED: This instance’s name (e.g. "lab1", "prod_main").
                              Allowed characters: A-Z, a-z, 0-9, dot (.), underscore (_), dash (-).
  --config-source-env-file PATH Optional: Path to a pre-existing environment configuration file
                              (<INSTANCE_NAME>.conf) to copy. If provided, the corresponding
                              _app.conf file will still be generated with default content
                              unless it also already exists at the target location.
  --force                   Optional: Overwrite existing instance configuration files.
                              Without this, the script will exit if target files exist.
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
    --config-source-env-file) # Changed from --config-source-file for clarity
      CONFIG_SRC_ENV_FILE="$2"; shift 2 ;;
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
declare -a required_commands=("getent" "install" "date" "id" "basename" "chmod" "chown" "printf")
info "Checking for required commands..."
for cmd in "${required_commands[@]}"; do
  command -v "$cmd" &>/dev/null || error_exit "Required command \"${cmd}\" is not installed or not in PATH."
done
info "All required commands are available."

# --- Load Base Vars ---
info "Attempting to load base variables from \"${BASE_VARS_FILE}\"..."
if [[ ! -f "$BASE_VARS_FILE" ]]; then
  error_exit "Base variables file \"${BASE_VARS_FILE}\" not found. Ensure install_base_exportcliv2.sh was run."
fi
# shellcheck source=/dev/null
source "$BASE_VARS_FILE"
info "Successfully sourced base variables from \"${BASE_VARS_FILE}\"."

: "${APP_NAME:?ERROR: APP_NAME not set in ${BASE_VARS_FILE}}"
: "${ETC_DIR:?ERROR: ETC_DIR not set in ${BASE_VARS_FILE}}"
: "${APP_GROUP:?ERROR: APP_GROUP not set in ${BASE_VARS_FILE}}"
info "Using APP_NAME from base vars: \"${APP_NAME}\" (for service names, etc.)"
info "Using ETC_DIR from base vars: \"${ETC_DIR}\""
info "Using APP_GROUP from base vars: \"${APP_GROUP}\" (for config file group ownership)"

TARGET_CONF_DIR="$ETC_DIR"
# Path for the environment variable file (e.g., ZZZ.conf)
TARGET_ENV_CONF_FILE="${TARGET_CONF_DIR}/${INSTANCE}.conf"
# Path for the application-specific config file passed via -c (e.g., ZZZ_app.conf)
APP_SPECIFIC_CONFIG_FILENAME="${INSTANCE}_app.conf"
TARGET_APP_SPECIFIC_CONFIG_FILE="${TARGET_CONF_DIR}/${APP_SPECIFIC_CONFIG_FILENAME}"

# --- Guard against accidental overwrites ---
# Check both files if we are not using a source file (i.e., generating defaults)
# If using a source env file, we only strictly need to check the env file for overwrite.
# The _app.conf will be generated if it doesn't exist, or overwritten if --force is used and it exists.
files_to_check_for_overwrite=("$TARGET_ENV_CONF_FILE")
if [[ -z "$CONFIG_SRC_ENV_FILE" ]]; then # If generating defaults, also check _app.conf target
    files_to_check_for_overwrite+=("$TARGET_APP_SPECIFIC_CONFIG_FILE")
fi

for file_to_check in "${files_to_check_for_overwrite[@]}"; do
    if [[ -e "$file_to_check" && -z "$FORCE_OVERWRITE" && -z "$DRY_RUN" ]]; then
    error_exit "Instance configuration file \"${file_to_check}\" already exists. Use --force to overwrite, or choose a different instance name."
    elif [[ -e "$file_to_check" && -n "$FORCE_OVERWRITE" && -z "$DRY_RUN" ]]; then
    warn "Instance configuration file \"${file_to_check}\" already exists. --force specified, proceeding with overwrite."
    elif [[ -e "$file_to_check" && -z "$FORCE_OVERWRITE" && -n "$DRY_RUN" ]]; then
    info "[DRY_RUN] Instance configuration file \"${file_to_check}\" exists. If not in dry-run, --force would be required to overwrite."
    fi
done


# --- Ensure config dir exists ---
info "Ensuring target configuration directory exists: \"${TARGET_CONF_DIR}\""
$DRY_RUN install -d -o root -g root -m0755 "$TARGET_CONF_DIR" \
  || error_exit "Failed to create or set permissions for directory \"${TARGET_CONF_DIR}\"."

# --- Deploy or Generate Instance Environment Configuration File (e.g., ZZZ.conf) ---
if [[ -n "$CONFIG_SRC_ENV_FILE" ]]; then
  info "Using user-provided environment configuration source file: \"${CONFIG_SRC_ENV_FILE}\""
  if [[ ! -f "$CONFIG_SRC_ENV_FILE" ]]; then
    error_exit "Specified environment configuration source file \"${CONFIG_SRC_ENV_FILE}\" not found."
  fi
  info "Copying \"${CONFIG_SRC_ENV_FILE}\" to \"${TARGET_ENV_CONF_FILE}\"..."
  $DRY_RUN install -T -o root -g "$APP_GROUP" -m0640 "$CONFIG_SRC_ENV_FILE" "$TARGET_ENV_CONF_FILE" \
    || error_exit "Failed to copy \"${CONFIG_SRC_ENV_FILE}\" to \"${TARGET_ENV_CONF_FILE}\"."
  info "Successfully copied environment configuration to \"${TARGET_ENV_CONF_FILE}\"."
  # Note: User is responsible for ensuring the copied file contains EXPORT_APP_CONFIG_FILE_PATH
  # and EXPORT_STARTTIME_OFFSET_SPEC if they differ from what would be generated.
  # We will still attempt to generate the _app.conf file with defaults if it doesn't exist
  # or if --force is given.
else
  info "Generating default environment configuration file at \"${TARGET_ENV_CONF_FILE}\" for instance \"${INSTANCE}\"..."
  script_basename=$(basename "$0")

  generated_env_content=$(cat <<EOF
# ${APP_NAME} instance "${INSTANCE}" environment configuration for wrapper script
# Generated by ${script_basename} on $(_ts)

EXPORT_TIMEOUT="${DEFAULT_EXPORT_TIMEOUT}"
EXPORT_SOURCE="${INSTANCE}" # Used by wrapper to construct part of the -o path

# --- Time Configuration ---
# EXPORT_STARTTIME_OFFSET_SPEC is used by the wrapper script to calculate the dynamic start time.
# Examples: "3 minutes ago", "1 hour ago", "2 days ago 00:00"
EXPORT_STARTTIME_OFFSET_SPEC="${DEFAULT_EXPORT_STARTTIME_OFFSET_SPEC}"

# EXPORT_ENDTIME is passed by the wrapper directly to the ${APP_NAME} binary.
# For this version, it is typically fixed to ${DEFAULT_EXPORT_ENDTIME_VALUE}
EXPORT_ENDTIME="${DEFAULT_EXPORT_ENDTIME_VALUE}"

# --- Network and Other Parameters ---
# These are passed by the wrapper directly to the ${APP_NAME} binary.
EXPORT_IP="${DEFAULT_EXPORT_IP}"
EXPORT_PORTID="${DEFAULT_EXPORT_PORTID}"

# --- Path to Per-Instance Application Specific Config File ---
# This file is referenced by the -c argument passed by the wrapper to the ${APP_NAME} binary.
# It is also generated by ${script_basename} in ${TARGET_CONF_DIR}/
EXPORT_APP_CONFIG_FILE_PATH="${TARGET_APP_SPECIFIC_CONFIG_FILE}"
EOF
) # End of generated_env_content

  if [[ -n "$DRY_RUN" ]]; then
    info "[DRY_RUN] Would write the following content to \"${TARGET_ENV_CONF_FILE}\":"
    echo "--- BEGIN GENERATED ENV CONFIG (${TARGET_ENV_CONF_FILE}) ---"
    echo "$generated_env_content"
    echo "--- END GENERATED ENV CONFIG ---"
    info "[DRY_RUN] Would set permissions to 0640 and ownership to root:${APP_GROUP} for \"${TARGET_ENV_CONF_FILE}\"."
  else
    info "Writing generated environment configuration to \"${TARGET_ENV_CONF_FILE}\"..."
    printf "%s\n" "$generated_env_content" > "$TARGET_ENV_CONF_FILE" \
      || error_exit "Failed to write generated environment configuration to \"${TARGET_ENV_CONF_FILE}\"."
    chmod 0640 "$TARGET_ENV_CONF_FILE"
    chown "root:$APP_GROUP" "$TARGET_ENV_CONF_FILE"
    info "Successfully generated and saved environment configuration to \"${TARGET_ENV_CONF_FILE}\"."
  fi
fi

# --- Always Generate/Update Application-Specific Config File (e.g., ZZZ_app.conf) ---
# This file is simple and contains fixed content for now.
# We generate it unless it exists and --force is not given.
if [[ -e "$TARGET_APP_SPECIFIC_CONFIG_FILE" && -z "$FORCE_OVERWRITE" && -z "$DRY_RUN" && -n "$CONFIG_SRC_ENV_FILE" ]]; then
    info "Application-specific config file \"${TARGET_APP_SPECIFIC_CONFIG_FILE}\" already exists. Not overwriting as --force was not specified for this scenario."
elif [[ -n "$DRY_RUN" ]]; then
    info "[DRY_RUN] Would ensure application-specific config file \"${TARGET_APP_SPECIFIC_CONFIG_FILE}\" contains:"
    echo "--- BEGIN APP CONFIG (${TARGET_APP_SPECIFIC_CONFIG_FILE}) ---"
    echo "${DEFAULT_APP_CONFIG_CONTENT}"
    echo "--- END APP CONFIG ---"
    info "[DRY_RUN] Would set permissions to 0640 and ownership to root:${APP_GROUP} for \"${TARGET_APP_SPECIFIC_CONFIG_FILE}\"."
else
    info "Writing/Updating application-specific configuration to \"${TARGET_APP_SPECIFIC_CONFIG_FILE}\"..."
    printf "%s\n" "${DEFAULT_APP_CONFIG_CONTENT}" > "$TARGET_APP_SPECIFIC_CONFIG_FILE" \
      || error_exit "Failed to write application-specific configuration to \"${TARGET_APP_SPECIFIC_CONFIG_FILE}\"."
    chmod 0640 "$TARGET_APP_SPECIFIC_CONFIG_FILE"
    chown "root:$APP_GROUP" "$TARGET_APP_SPECIFIC_CONFIG_FILE"
    info "Successfully wrote/updated application-specific configuration to \"${TARGET_APP_SPECIFIC_CONFIG_FILE}\"."
fi


# --- Next Steps Information ---
info "Instance configuration for \"${INSTANCE}\" is ready."
info "  Environment config (for wrapper): \"${TARGET_ENV_CONF_FILE}\""
info "  Application config (for -c arg): \"${TARGET_APP_SPECIFIC_CONFIG_FILE}\""
info "If default configurations were generated, please review and edit them as needed, especially:"
info "  - ${TARGET_ENV_CONF_FILE} for EXPORT_IP, EXPORT_PORTID, EXPORT_STARTTIME_OFFSET_SPEC, etc."
info "  - ${TARGET_APP_SPECIFIC_CONFIG_FILE} if 'mining_delta_sec' needs adjustment."

main_service_name="${APP_NAME}@${INSTANCE}.service"
path_service_name="${APP_NAME}-restart@${INSTANCE}.path" # Assuming this naming convention

cat <<EOF

-----------------------------------------------------------------------------
Instance '${INSTANCE}' of '${APP_NAME}' is configured.
  Env Config: ${TARGET_ENV_CONF_FILE}
  App Config: ${TARGET_APP_SPECIFIC_CONFIG_FILE}
-----------------------------------------------------------------------------

Next Steps: Manage this instance with systemd:

1. Enable services to start at boot:
   sudo systemctl enable ${main_service_name}
   sudo systemctl enable ${path_service_name}

2. Start services now:
   sudo systemctl start ${main_service_name}

3. Check status:
   sudo systemctl status ${main_service_name}
   sudo systemctl status ${path_service_name}

4. View logs:
   sudo journalctl -u ${main_service_name} -f

-----------------------------------------------------------------------------
Remember to review/edit config files if defaults were generated.
-----------------------------------------------------------------------------
EOF

exit 0