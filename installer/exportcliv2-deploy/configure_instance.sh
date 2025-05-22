#!/usr/bin/env bash
# shellcheck disable=SC1090,SC2154 # SC1090 for source, SC2154 for sourced variables
set -euo pipefail
IFS=$'\n\t'

# -----------------------------------------------------------------------------
# Instance Configurator for exportcliv2 (Refined)
# -----------------------------------------------------------------------------
# - Creates <instance>.conf (environment variables for wrapper script).
# - Creates <instance>_app.conf (config file for exportcliv2 binary -c arg).
# - Uses defaults from base installer via /etc/default/${APP_NAME}_base_vars.
# - CLI simplified based on recent installer script review.
# -----------------------------------------------------------------------------

# --- Logging & Globals ---
_ts()  { date -u +'%Y-%m-%dT%H:%M:%SZ'; }
info() { echo "$(_ts) [INFO]  $*"; }
warn() { echo "$(_ts) [WARN]  $*"; }
error_exit() { echo "$(_ts) [ERROR] $*" >&2; exit 1; }

cleanup_on_error() { # Renamed from 'cleanup' to avoid conflict if sourced
  local exit_code="${1:-$?}"
  local line_num="${2:-UNKNOWN_LINE}"
  local failed_command="${3:-UNKNOWN_COMMAND}" # $BASH_COMMAND might be more accurate if available
  warn "Instance configuration FAILED on line ${line_num} with command: ${failed_command} (exit code: ${exit_code})."
  warn "System may be in an inconsistent state. Review logs and manually clean up if necessary."
}
trap 'cleanup_on_error "$?" "$LINENO" "$BASH_COMMAND"' ERR
# No EXIT trap needed for this script as it doesn't manage temp files that need guaranteed cleanup on success.

readonly APP_NAME_FOR_BASE_VARS_LOOKUP="exportcliv2" # Used to find the _base_vars file
readonly BASE_VARS_FILE="/etc/default/${APP_NAME_FOR_BASE_VARS_LOOKUP}_base_vars"

# --- Argument Parsing ---
INSTANCE=""
CONFIG_SRC_ENV_FILE="" # Optional source for the <instance>.conf file
FORCE_OVERWRITE=""
DRY_RUN=""

usage() {
  # ETC_DIR_FOR_USAGE will be determined after sourcing BASE_VARS_FILE if possible,
  # otherwise, a sensible default is shown.
  local determined_etc_dir="${ETC_DIR:-/etc/${APP_NAME_FOR_BASE_VARS_LOOKUP}}"
  cat <<EOF
Usage: $(basename "$0") -i INSTANCE_NAME [--config-source-env-file PATH] [--force] [-n] [-h]

Configures a new instance for the '${APP_NAME_FOR_BASE_VARS_LOOKUP}' application.
This script MUST be run as root or with sudo.

It creates two configuration files per instance in '${determined_etc_dir}':
  1. <INSTANCE_NAME>.conf: Environment variables for the wrapper script.
  2. <INSTANCE_NAME>_app.conf: Config file passed via -c to the main binary.

Options:
  -i INSTANCE_NAME        REQUIRED: Name for this instance (e.g., "lab1", "prod_main").
                            Allowed characters: A-Z, a-z, 0-9, dot (.), underscore (_), dash (-).
  --config-source-env-file PATH
                            Optional: Path to a pre-existing environment configuration file
                            (<INSTANCE_NAME>.conf) to copy. The <INSTANCE_NAME>_app.conf
                            will still be generated with defaults unless --force is used
                            and it already exists.
  --force                   Optional: Overwrite existing instance configuration file(s).
  -n                        Dry-run mode (print commands, no execution).
  -h                        Show this help message and exit.
EOF
  exit 0 # Help is a clean exit
}

# Simpler getopts string, consistent with reviewed installer
while getopts ":nhi:" o; do # Added --config-source-env-file and --force as long options later
  case $o in
    i) INSTANCE="$OPTARG" ;;
    n) DRY_RUN="echo" ;;
    h) usage ;;
    \?) error_exit "Invalid short option: -$OPTARG. Use -h for help." ;;
    :) error_exit "Short option -$OPTARG requires an argument. Use -h for help." ;;
  esac
done
shift $((OPTIND -1))

# Manual parsing for long options (--config-source-env-file, --force)
# This is a common way to handle long options if not using getopts on systems where it supports them well.
while [[ $# -gt 0 ]]; do
    case "$1" in
        --config-source-env-file)
            CONFIG_SRC_ENV_FILE="$2"
            shift 2
            ;;
        --force)
            FORCE_OVERWRITE="true"
            shift
            ;;
        *)
            # If -i was not provided via short opt, try to catch it as a positional for simple cases,
            # but relying on -i is better. This is just a fallback.
            if [[ -z "$INSTANCE" && $# -eq 1 && ! "$1" =~ ^- ]]; then
                warn "Instance name provided positionally. Prefer using '-i INSTANCE_NAME'."
                INSTANCE="$1"
                shift
            else
                error_exit "Unknown option or argument: \"$1\". Use -h for help."
            fi
            ;;
    esac
done


# --- Root Execution Check ---
if [[ "$(id -u)" -ne 0 ]]; then
  error_exit "This script must be run as root or with sudo."
fi

# --- Validate Mandatory Instance Name (must be set after all parsing) ---
if [[ -z "$INSTANCE" ]]; then
  warn "Instance name (-i) is required."
  usage # This will call usage and exit
fi

# Validate instance name format
if ! [[ "$INSTANCE" =~ ^[A-Za-z0-9._-]+$ ]]; then
  error_exit "Invalid instance name: \"${INSTANCE}\". Only A-Z, a-z, 0-9, dot (.), underscore (_), and dash (-) are allowed."
fi
info "Validated instance name: \"${INSTANCE}\""

# --- Pre-flight check for required commands ---
# Consistent with reviewed installer, minimal set
required_commands=(getent install date id basename chmod chown printf mkdir)
info "Checking for required commands..."
for cmd in "${required_commands[@]}"; do
  command -v "$cmd" &>/dev/null || error_exit "Required command \"${cmd}\" is not installed or not in PATH."
done
info "All required commands are available."

# --- Load Base Vars (sourced from file created by main installer) ---
info "Attempting to load base variables from \"${BASE_VARS_FILE}\"..."
if [[ ! -f "$BASE_VARS_FILE" ]]; then
  error_exit "Base variables file \"${BASE_VARS_FILE}\" not found. Ensure the base installer (e.g., install_base_exportcliv2.sh) was run successfully."
fi
source "$BASE_VARS_FILE" # SC1090
info "Successfully sourced base variables from \"${BASE_VARS_FILE}\"."

# Validate crucial variables from BASE_VARS_FILE
: "${APP_NAME:?APP_NAME not set in ${BASE_VARS_FILE}. Base install may be incomplete.}"
: "${ETC_DIR:?ETC_DIR not set in ${BASE_VARS_FILE}. Base install may be incomplete.}"
: "${APP_GROUP:?APP_GROUP not set in ${BASE_VARS_FILE}. Base install may be incomplete.}"
: "${DEFAULT_CONFIGURE_INSTANCE_EXPORT_TIMEOUT:?DEFAULT_CONFIGURE_INSTANCE_EXPORT_TIMEOUT not set in ${BASE_VARS_FILE}. Base install may be incomplete or install-app.conf is missing EXPORT_TIMEOUT_CONFIG.}"

info "Using APP_NAME from base vars: \"${APP_NAME}\" (for service names, etc.)"
info "Using ETC_DIR from base vars: \"${ETC_DIR}\""
info "Using APP_GROUP from base vars: \"${APP_GROUP}\" (for config file group ownership)"
info "Using default instance EXPORT_TIMEOUT from base vars: \"${DEFAULT_CONFIGURE_INSTANCE_EXPORT_TIMEOUT}\" seconds"

# --- Define Target Paths ---
readonly TARGET_CONF_DIR="$ETC_DIR"
readonly TARGET_ENV_CONF_FILE="${TARGET_CONF_DIR}/${INSTANCE}.conf"
readonly APP_SPECIFIC_CONFIG_FILENAME="${INSTANCE}_app.conf"
readonly TARGET_APP_SPECIFIC_CONFIG_FILE="${TARGET_CONF_DIR}/${APP_SPECIFIC_CONFIG_FILENAME}"

# --- Define Defaults for Generated Configs (if not using a source file) ---
# These are used if CONFIG_SRC_ENV_FILE is not provided.
# DEFAULT_CONFIGURE_INSTANCE_EXPORT_TIMEOUT is already sourced.
readonly DEFAULT_EXPORT_IP="10.0.0.1"
readonly DEFAULT_EXPORT_PORTID="1"
readonly DEFAULT_EXPORT_STARTTIME_OFFSET_SPEC="3 minutes ago"
readonly DEFAULT_EXPORT_ENDTIME_VALUE="-1" # Fixed value for this app version
readonly DEFAULT_APP_CONFIG_CONTENT="mining_delta_sec=120"

# --- Guard against accidental overwrites ---
files_to_check_for_overwrite=()
if [[ -e "$TARGET_ENV_CONF_FILE" ]]; then
    files_to_check_for_overwrite+=("$TARGET_ENV_CONF_FILE")
fi
# If not sourcing an env file, and the app_specific_config target exists, it's also a candidate for overwrite check
if [[ -z "$CONFIG_SRC_ENV_FILE" && -e "$TARGET_APP_SPECIFIC_CONFIG_FILE" ]]; then
    files_to_check_for_overwrite+=("$TARGET_APP_SPECIFIC_CONFIG_FILE")
fi
# If sourcing an env file, but the app_specific_config *still* exists, it needs --force to be overwritten.
if [[ -n "$CONFIG_SRC_ENV_FILE" && -e "$TARGET_APP_SPECIFIC_CONFIG_FILE" ]]; then
    files_to_check_for_overwrite+=("$TARGET_APP_SPECIFIC_CONFIG_FILE")
fi

if (( ${#files_to_check_for_overwrite[@]} > 0 )) && [[ -z "$FORCE_OVERWRITE" ]]; then
  if [[ -z "$DRY_RUN" ]]; then
    error_exit "One or more target configuration files exist: (${files_to_check_for_overwrite[*]}). Use --force to overwrite."
  else
    info "[DRY_RUN] One or more target configuration files exist: (${files_to_check_for_overwrite[*]}). If not in dry-run, --force would be required to overwrite."
  fi
elif (( ${#files_to_check_for_overwrite[@]} > 0 )) && [[ -n "$FORCE_OVERWRITE" ]]; then
   if [[ -z "$DRY_RUN" ]]; then
    warn "One or more target configuration files exist: (${files_to_check_for_overwrite[*]}). --force specified, proceeding with overwrite."
   else
    info "[DRY_RUN] One or more target configuration files exist: (${files_to_check_for_overwrite[*]}). --force specified, would proceed with overwrite."
   fi
fi

# --- Ensure target config directory exists ---
info "Ensuring target configuration directory exists: \"${TARGET_CONF_DIR}\""
# Not using $DRY_RUN here for mkdir, similar to log dir creation. It's a prerequisite.
# Using install -d as it's concise for this purpose and sets ownership/perms.
if [[ -n "$DRY_RUN" ]]; then
    echo "$DRY_RUN install -d -o root -g root -m0755 \"$TARGET_CONF_DIR\""
else
    install -d -o root -g root -m0755 "$TARGET_CONF_DIR" \
        || error_exit "Failed to create or set permissions for directory \"${TARGET_CONF_DIR}\"."
fi


# --- Deploy or Generate Instance Environment Configuration File (e.g., ZZZ.conf) ---
if [[ -n "$CONFIG_SRC_ENV_FILE" ]]; then
  info "Using user-provided environment configuration source file: \"${CONFIG_SRC_ENV_FILE}\""
  if [[ ! -f "$CONFIG_SRC_ENV_FILE" ]]; then
    error_exit "Specified environment configuration source file \"${CONFIG_SRC_ENV_FILE}\" not found."
  fi
  info "Copying \"${CONFIG_SRC_ENV_FILE}\" to \"${TARGET_ENV_CONF_FILE}\"..."
  if [[ -n "$DRY_RUN" ]]; then
    echo "$DRY_RUN install -T -o root -g \"$APP_GROUP\" -m0640 \"$CONFIG_SRC_ENV_FILE\" \"$TARGET_ENV_CONF_FILE\""
  else
    install -T -o root -g "$APP_GROUP" -m0640 "$CONFIG_SRC_ENV_FILE" "$TARGET_ENV_CONF_FILE" \
        || error_exit "Failed to copy \"${CONFIG_SRC_ENV_FILE}\" to \"${TARGET_ENV_CONF_FILE}\"."
  fi
  info "Environment configuration file processed from source: \"${TARGET_ENV_CONF_FILE}\"."
else
  info "Generating default environment configuration file: \"${TARGET_ENV_CONF_FILE}\" for instance \"${INSTANCE}\"..."
  script_basename=$(basename "$0")
  generated_env_content=$(cat <<EOF
# ${APP_NAME} instance "${INSTANCE}" environment configuration for wrapper script
# Generated by ${script_basename} on $(_ts)

EXPORT_TIMEOUT="${DEFAULT_CONFIGURE_INSTANCE_EXPORT_TIMEOUT}" # From base_vars, ultimately install-app.conf
EXPORT_SOURCE="${INSTANCE}" # Used by wrapper to construct part of the -o path

# --- Time Configuration ---
EXPORT_STARTTIME_OFFSET_SPEC="${DEFAULT_EXPORT_STARTTIME_OFFSET_SPEC}"
EXPORT_ENDTIME="${DEFAULT_EXPORT_ENDTIME_VALUE}"

# --- Network and Other Parameters ---
EXPORT_IP="${DEFAULT_EXPORT_IP}"
EXPORT_PORTID="${DEFAULT_EXPORT_PORTID}"

# --- Path to Per-Instance Application Specific Config File ---
EXPORT_APP_CONFIG_FILE_PATH="${TARGET_APP_SPECIFIC_CONFIG_FILE}"
EOF
)
  if [[ -n "$DRY_RUN" ]]; then
    info "[DRY_RUN] Would write the following content to \"${TARGET_ENV_CONF_FILE}\":"
    echo "--- BEGIN GENERATED ENV CONFIG (${TARGET_ENV_CONF_FILE}) ---"
    echo "$generated_env_content"
    echo "--- END GENERATED ENV CONFIG ---"
    echo "$DRY_RUN chmod 0640 \"$TARGET_ENV_CONF_FILE\""
    echo "$DRY_RUN chown \"root:$APP_GROUP\" \"$TARGET_ENV_CONF_FILE\""
  else
    info "Writing generated environment configuration to \"${TARGET_ENV_CONF_FILE}\"..."
    printf "%s\n" "$generated_env_content" > "$TARGET_ENV_CONF_FILE" \
      || error_exit "Failed to write env config to \"${TARGET_ENV_CONF_FILE}\"."
    chmod 0640 "$TARGET_ENV_CONF_FILE"
    chown "root:$APP_GROUP" "$TARGET_ENV_CONF_FILE"
    info "Successfully generated and saved environment configuration to \"${TARGET_ENV_CONF_FILE}\"."
  fi
fi

# --- Always Generate/Update Application-Specific Config File (e.g., ZZZ_app.conf) ---
# This file is simple and has fixed default content.
# It's created if it doesn't exist, or if it exists AND --force is given.
generate_app_specific_conf=true
if [[ -e "$TARGET_APP_SPECIFIC_CONFIG_FILE" && -z "$FORCE_OVERWRITE" ]]; then
    # If file exists and --force is NOT given, don't generate unless in dry run.
    # This check is particularly for the case where --config-source-env-file was used,
    # as the main overwrite guard might not have covered TARGET_APP_SPECIFIC_CONFIG_FILE.
    if [[ -z "$DRY_RUN" ]]; then
        info "Application-specific config \"${TARGET_APP_SPECIFIC_CONFIG_FILE}\" already exists. Not overwriting (use --force if needed)."
        generate_app_specific_conf=false
    else
        info "[DRY_RUN] Application-specific config \"${TARGET_APP_SPECIFIC_CONFIG_FILE}\" exists. Would not overwrite without --force."
        # For dry run, still show what would be written if it were to proceed
    fi
fi

if [[ "$generate_app_specific_conf" == true || -n "$DRY_RUN" ]]; then
    if [[ -n "$DRY_RUN" ]]; then
        info "[DRY_RUN] Would ensure application-specific config file \"${TARGET_APP_SPECIFIC_CONFIG_FILE}\" contains:"
        echo "--- BEGIN APP CONFIG (${TARGET_APP_SPECIFIC_CONFIG_FILE}) ---"
        echo "${DEFAULT_APP_CONFIG_CONTENT}"
        echo "--- END APP CONFIG ---"
        echo "$DRY_RUN chmod 0640 \"$TARGET_APP_SPECIFIC_CONFIG_FILE\""
        echo "$DRY_RUN chown \"root:$APP_GROUP\" \"$TARGET_APP_SPECIFIC_CONFIG_FILE\""
    else # Not a dry run, and we should generate/overwrite
        info "Writing/Updating application-specific configuration to \"${TARGET_APP_SPECIFIC_CONFIG_FILE}\"..."
        printf "%s\n" "${DEFAULT_APP_CONFIG_CONTENT}" > "$TARGET_APP_SPECIFIC_CONFIG_FILE" \
        || error_exit "Failed to write app-specific config to \"${TARGET_APP_SPECIFIC_CONFIG_FILE}\"."
        chmod 0640 "$TARGET_APP_SPECIFIC_CONFIG_FILE"
        chown "root:$APP_GROUP" "$TARGET_APP_SPECIFIC_CONFIG_FILE"
        info "Successfully wrote/updated application-specific configuration to \"${TARGET_APP_SPECIFIC_CONFIG_FILE}\"."
    fi
fi


# --- Next Steps Information ---
info "Instance configuration for \"${INSTANCE}\" processed."
info "  Environment config (for wrapper): \"${TARGET_ENV_CONF_FILE}\""
info "  Application config (for -c arg):  \"${TARGET_APP_SPECIFIC_CONFIG_FILE}\""
if [[ -z "$CONFIG_SRC_ENV_FILE" ]]; then # Only prompt to edit if defaults were generated for env_conf
    info "If default configurations were generated, please review and edit them as needed, especially:"
    info "  - ${TARGET_ENV_CONF_FILE} for EXPORT_IP, EXPORT_PORTID, EXPORT_STARTTIME_OFFSET_SPEC, etc."
fi
# Always mention the app_specific_conf for review as its content is simple/fixed by default
info "  - Review ${TARGET_APP_SPECIFIC_CONFIG_FILE} if '${DEFAULT_APP_CONFIG_CONTENT%%=*}' needs adjustment."


readonly main_service_name="${APP_NAME}@${INSTANCE}.service"
readonly path_service_name="${APP_NAME}-restart@${INSTANCE}.path" # Consistent naming

cat <<EOF

-----------------------------------------------------------------------------
Instance '${INSTANCE}' of '${APP_NAME}' configuration processed.
  Env Config: ${TARGET_ENV_CONF_FILE}
  App Config: ${TARGET_APP_SPECIFIC_CONFIG_FILE}
-----------------------------------------------------------------------------

Next Steps: Manage this instance with systemd:

1. Enable services to start at boot (if not already enabled):
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
Remember to review/edit config files if defaults were generated or sourced.
-----------------------------------------------------------------------------
EOF

exit 0