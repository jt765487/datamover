#!/usr/bin/env bash
# shellcheck disable=SC1090,SC2154 # SC1090 for source, SC2154 for sourced variables
set -euo pipefail
IFS=$'\n\t'

# -----------------------------------------------------------------------------
# Instance Configurator for exportcliv2 (v4 - Verbose Mode)
# -----------------------------------------------------------------------------
# - Creates <instance>.conf (environment variables for wrapper script).
# - Creates <instance>_app.conf (config file for exportcliv2 binary -c arg).
# - Uses defaults from base installer via /etc/default/${APP_NAME}_base_vars.
# - Added verbose mode (-v, --verbose).
# -----------------------------------------------------------------------------

# --- Exit Codes ---
readonly EXIT_CODE_SUCCESS=0
readonly EXIT_CODE_GENERAL_ERROR=1
readonly EXIT_CODE_USAGE_ERROR=2
readonly EXIT_CODE_CONFIG_ERROR=3
readonly EXIT_CODE_PREREQUISITE_ERROR=4
readonly EXIT_CODE_FILE_ERROR=5

# --- Logging & Globals ---
_ts()  { date -u +'%Y-%m-%dT%H:%M:%SZ'; }
info() { echo "$(_ts) [INFO]  $*"; } # Always shown
warn() { echo "$(_ts) [WARN]  $*"; } # Always shown

VERBOSE_MODE_CONFIGURE_INSTANCE=false # Global for verbose state

debug() {
  if [[ "$VERBOSE_MODE_CONFIGURE_INSTANCE" == true ]]; then
    echo "$(_ts) [DEBUG] $*";
  fi
}

error_exit() {
  local message="$1"
  local exit_code="${2:-$EXIT_CODE_GENERAL_ERROR}"
  echo "$(_ts) [ERROR]  $message" >&2
  exit "$exit_code"
}

SCRIPT_SUCCESSFUL=false

# shellcheck disable=SC2317
cleanup_on_error() {
  local exit_code="${1:-$?}"
  local line_num="${2:-UNKNOWN_LINE}"
  local failed_command="${3:-UNKNOWN_COMMAND}"
  if [[ "$exit_code" -ne "$EXIT_CODE_SUCCESS" && "$failed_command" != "error_exit"* ]]; then
    warn "Instance configuration FAILED on line ${line_num} with command: ${failed_command} (exit code: ${exit_code})."
    warn "System may be in an inconsistent state. Review logs and manually clean up if necessary."
  fi
  SCRIPT_SUCCESSFUL=false
}

# shellcheck disable=SC2317
cleanup_on_exit() {
    local exit_code="${1:-$?}"
    if [[ "$SCRIPT_SUCCESSFUL" == true && "$exit_code" -eq "$EXIT_CODE_SUCCESS" ]]; then
        info "-------------------- INSTANCE CONFIGURATION COMPLETED SUCCESSFULLY --------------------"
    elif [[ "$exit_code" -ne "$EXIT_CODE_SUCCESS" && "$SCRIPT_SUCCESSFUL" == false ]]; then
        if [[ "$exit_code" -ne "$EXIT_CODE_SUCCESS" || ($exit_code -eq "$EXIT_CODE_SUCCESS" && "$SCRIPT_SUCCESSFUL" == false) ]]; then
             info "-------------------- INSTANCE CONFIGURATION FAILED OR EXITED PREMATURELY --------------------"
        fi
    fi
}

trap 'cleanup_on_error "$?" "$LINENO" "$BASH_COMMAND"' ERR
trap 'cleanup_on_exit $?' EXIT


readonly APP_NAME_FOR_BASE_VARS_LOOKUP="exportcliv2"
readonly BASE_VARS_FILE="/etc/default/${APP_NAME_FOR_BASE_VARS_LOOKUP}_base_vars"

# --- Argument Parsing ---
INSTANCE=""
CONFIG_SRC_ENV_FILE=""
FORCE_OVERWRITE=""
DRY_RUN=""

usage() {
  local determined_etc_dir_desc="the application's etc directory (typically /etc/${APP_NAME_FOR_BASE_VARS_LOOKUP})"
  cat <<EOF
Usage: $(basename "$0") -i INSTANCE_NAME [--config-source-env-file PATH] [--force] [-v|--verbose] [-n] [-h]

Configures a new instance for the '${APP_NAME_FOR_BASE_VARS_LOOKUP}' application.
This script MUST be run as root or with sudo.

It creates two configuration files per instance in ${determined_etc_dir_desc}:
  1. <INSTANCE_NAME>.conf: Environment variables for the wrapper script.
  2. <INSTANCE_NAME>_app.conf: Config file passed via -c to the main binary.

Options:
  -i INSTANCE_NAME          REQUIRED: Name for this instance (e.g., "lab1", "prod_main").
                            Allowed characters: A-Z, a-z, 0-9, dot (.), underscore (_), dash (-).
  --config-source-env-file PATH
                            Optional: Path to a pre-existing environment configuration file
                            (<INSTANCE_NAME>.conf) to copy. The <INSTANCE_NAME>_app.conf
                            will still be generated with defaults.
  --force                   Optional: Overwrite existing instance configuration file(s)
                            (both <INSTANCE_NAME>.conf and <INSTANCE_NAME>_app.conf if they exist).
  -v, --verbose             Optional: Enable verbose output.
  -n                        Dry-run mode (print commands, no execution).
  -h                        Show this help message and exit.
EOF
  exit "${1:-$EXIT_CODE_USAGE_ERROR}"
}

while getopts ":nvi:" o; do # Added 'v'
  case $o in
    i) INSTANCE="$OPTARG" ;;
    n) DRY_RUN="echo" ;;
    v) VERBOSE_MODE_CONFIGURE_INSTANCE=true ;; # Set verbose mode
    h) usage "$EXIT_CODE_SUCCESS" ;;
    \?)
        if [[ "${!OPTIND:-}" == --* ]]; then
            break
        else
            error_exit "Invalid short option: -$OPTARG. Use -h for help." "$EXIT_CODE_USAGE_ERROR"
        fi
        ;;
    :) error_exit "Short option -$OPTARG requires an argument. Use -h for help." "$EXIT_CODE_USAGE_ERROR" ;;
  esac
done
shift $((OPTIND -1))

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config-source-env-file)
            if [[ -z "${2:-}" || "${2}" == -* ]]; then
                error_exit "Option --config-source-env-file requires an argument." "$EXIT_CODE_USAGE_ERROR";
            fi
            CONFIG_SRC_ENV_FILE="$2"
            shift 2
            ;;
        --force)
            FORCE_OVERWRITE="true"
            shift
            ;;
        --verbose) # Added long option for verbose
            VERBOSE_MODE_CONFIGURE_INSTANCE=true
            shift
            ;;
        *)
            error_exit "Unknown option or argument: \"$1\". Use -h for help." "$EXIT_CODE_USAGE_ERROR"
            ;;
    esac
done


# --- Root Execution Check ---
if [[ "$(id -u)" -ne 0 ]]; then
  error_exit "This script must be run as root or with sudo." "$EXIT_CODE_PREREQUISITE_ERROR"
fi

if [[ -z "$INSTANCE" ]]; then
  error_exit "Instance name (-i) is required. Use -h for help." "$EXIT_CODE_USAGE_ERROR"
fi

if ! [[ "$INSTANCE" =~ ^[A-Za-z0-9._-]+$ ]]; then
  error_exit "Invalid instance name: \"${INSTANCE}\". Only A-Z, a-z, 0-9, dot (.), underscore (_), and dash (-) are allowed." "$EXIT_CODE_USAGE_ERROR"
fi
debug "Validated instance name: \"${INSTANCE}\"" # Changed to debug

# --- Pre-flight check for required commands ---
required_commands=(getent install date id basename chmod chown printf mkdir)
debug "Checking for required commands..." # Changed to debug
for cmd in "${required_commands[@]}"; do
  command -v "$cmd" &>/dev/null || error_exit "Required command \"${cmd}\" is not installed or not in PATH." "$EXIT_CODE_PREREQUISITE_ERROR"
done
debug "All required commands are available." # Changed to debug

# --- Load Base Vars ---
debug "Attempting to load base variables from \"${BASE_VARS_FILE}\"..." # Changed to debug
if [[ ! -f "$BASE_VARS_FILE" ]]; then
  error_exit "Base variables file \"${BASE_VARS_FILE}\" not found. Ensure the base installer was run successfully." "$EXIT_CODE_CONFIG_ERROR"
fi
source "$BASE_VARS_FILE"
debug "Successfully sourced base variables from \"${BASE_VARS_FILE}\"." # Changed to debug

: "${APP_NAME:?APP_NAME not set in ${BASE_VARS_FILE}. Base install may be incomplete.}" "$EXIT_CODE_CONFIG_ERROR"
: "${ETC_DIR:?ETC_DIR not set in ${BASE_VARS_FILE}. Base install may be incomplete.}" "$EXIT_CODE_CONFIG_ERROR"
: "${APP_GROUP:?APP_GROUP not set in ${BASE_VARS_FILE}. Base install may be incomplete.}" "$EXIT_CODE_CONFIG_ERROR"
: "${DEFAULT_CONFIGURE_INSTANCE_EXPORT_TIMEOUT:?DEFAULT_CONFIGURE_INSTANCE_EXPORT_TIMEOUT not set in ${BASE_VARS_FILE}. Base install may be incomplete or install-app.conf is missing EXPORT_TIMEOUT_CONFIG.}" "$EXIT_CODE_CONFIG_ERROR"

debug "Using APP_NAME from base vars: \"${APP_NAME}\" (for service names, etc.)" # Changed to debug
debug "Using ETC_DIR from base vars: \"${ETC_DIR}\"" # Changed to debug
debug "Using APP_GROUP from base vars: \"${APP_GROUP}\" (for config file group ownership)" # Changed to debug
debug "Using default instance EXPORT_TIMEOUT from base vars: \"${DEFAULT_CONFIGURE_INSTANCE_EXPORT_TIMEOUT}\" seconds" # Changed to debug

# --- Define Target Paths ---
readonly TARGET_CONF_DIR="$ETC_DIR"
readonly TARGET_ENV_CONF_FILE="${TARGET_CONF_DIR}/${INSTANCE}.conf"
readonly APP_SPECIFIC_CONFIG_FILENAME="${INSTANCE}_app.conf"
readonly TARGET_APP_SPECIFIC_CONFIG_FILE="${TARGET_CONF_DIR}/${APP_SPECIFIC_CONFIG_FILENAME}"

# --- Define Defaults for Generated Configs ---
readonly DEFAULT_EXPORT_IP="10.0.0.1"
readonly DEFAULT_EXPORT_PORTID="1"
readonly DEFAULT_EXPORT_STARTTIME_OFFSET_SPEC="3 minutes ago"
readonly DEFAULT_EXPORT_ENDTIME_VALUE="-1"
readonly DEFAULT_APP_CONFIG_CONTENT="mining_delta_sec=120"


# --- Helper Functions for File Operations ---
_manage_file_permissions() {
    local dest_file="$1"; local owner="$2"; local group="$3"; local perms="$4"
    $DRY_RUN chown "$owner:$group" "$dest_file" \
        || error_exit "Failed to set ownership on '$dest_file'." "$EXIT_CODE_FILE_ERROR"
    $DRY_RUN chmod "$perms" "$dest_file" \
        || error_exit "Failed to set permissions on '$dest_file'." "$EXIT_CODE_FILE_ERROR"
}

ensure_config_directory() {
    local dir_path="$1"
    debug "Ensuring target configuration directory: \"${dir_path}\"" # Changed to debug
    # The actual command execution will be visible in dry-run because of $DRY_RUN prefix
    $DRY_RUN install -d -o root -g "${APP_GROUP}" -m0755 "${dir_path}" \
        || error_exit "Failed to create or set permissions for directory \"${dir_path}\"." "$EXIT_CODE_FILE_ERROR"
}

copy_source_env_file() {
    local src_file="$1"; local dest_file="$2"; local owner="$3"; local group="$4"; local perms="$5"
    debug "Copying \"${src_file}\" to \"${dest_file}\"..." # Changed to debug
    if [[ ! -f "$src_file" ]]; then
        error_exit "Specified environment configuration source file \"${src_file}\" not found." "$EXIT_CODE_CONFIG_ERROR"
    fi
    $DRY_RUN install -T "$src_file" "$dest_file" \
        || error_exit "Failed to copy \"${src_file}\" to \"${dest_file}\"." "$EXIT_CODE_FILE_ERROR"
    _manage_file_permissions "$dest_file" "$owner" "$group" "$perms"
    debug "Environment configuration file processed from source: \"${dest_file}\"." # Changed to debug
}

write_generated_file_content() {
    local content="$1"; local output_path="$2"; local owner="$3"; local group="$4"; local perms="$5"; local file_description="$6"

    debug "Writing generated ${file_description} to \"${output_path}\"..." # Changed to debug
    if [[ -n "$DRY_RUN" ]]; then
        # This info is specific to dry-run and should remain
        info "[DRY_RUN] Would write the following content to \"${output_path}\":"
        cat <<DRYRUNEOF
--- BEGIN GENERATED ${file_description^^} (${output_path}) ---
$content
--- END GENERATED ${file_description^^} ---
DRYRUNEOF
        echo "$DRY_RUN chown \"$owner:$group\" \"$output_path\""
        echo "$DRY_RUN chmod \"$perms\" \"$output_path\""
    else
        printf "%s\n" "$content" > "$output_path" \
            || error_exit "Failed to write ${file_description} to \"${output_path}\"." "$EXIT_CODE_FILE_ERROR"
        _manage_file_permissions "$output_path" "$owner" "$group" "$perms"
        debug "Successfully generated and saved ${file_description} to \"${output_path}\"." # Changed to debug
    fi
}

# --- Main Logic ---

if [[ -n "$DRY_RUN" ]]; then
    warn "DRY RUN MODE ENABLED: No changes will be made to the system."
elif [[ "$VERBOSE_MODE_CONFIGURE_INSTANCE" == true ]]; then
    info "Verbose mode enabled for instance configurator."
fi


target_files_exist=false
existing_files_msg=""
if [[ -e "$TARGET_ENV_CONF_FILE" ]]; then
    target_files_exist=true
    existing_files_msg+="'${TARGET_ENV_CONF_FILE}' "
fi
if [[ -e "$TARGET_APP_SPECIFIC_CONFIG_FILE" ]]; then
    target_files_exist=true
    existing_files_msg+="'${TARGET_APP_SPECIFIC_CONFIG_FILE}'"
fi
existing_files_msg="${existing_files_msg%" "}"


if [[ "$target_files_exist" == true && -z "$FORCE_OVERWRITE" ]]; then
  if [[ -z "$DRY_RUN" ]]; then
    error_exit "One or more target configuration files exist: (${existing_files_msg}). Use --force to overwrite both." "$EXIT_CODE_FILE_ERROR"
  else
    # This info is specific to dry-run and should remain
    info "[DRY_RUN] One or more target configuration files exist: (${existing_files_msg}). If not in dry-run, --force would be required to overwrite."
  fi
elif [[ "$target_files_exist" == true && -n "$FORCE_OVERWRITE" ]]; then
   if [[ -z "$DRY_RUN" ]]; then
    warn "One or more target configuration files exist: (${existing_files_msg}). --force specified, proceeding with overwrite."
   else
    # This info is specific to dry-run and should remain
    info "[DRY_RUN] One or more target configuration files exist: (${existing_files_msg}). --force specified, would proceed with overwrite."
   fi
fi

ensure_config_directory "$TARGET_CONF_DIR" # Uses debug internally

if [[ -n "$CONFIG_SRC_ENV_FILE" ]]; then
  copy_source_env_file "$CONFIG_SRC_ENV_FILE" "$TARGET_ENV_CONF_FILE" "root" "$APP_GROUP" "0640" # Uses debug internally
else
  script_basename=$(basename "$0")
  generated_env_content=$(cat <<EOF
# ${APP_NAME} instance "${INSTANCE}" environment configuration for wrapper script
# Generated by ${script_basename} on $(_ts)
EXPORT_TIMEOUT="${DEFAULT_CONFIGURE_INSTANCE_EXPORT_TIMEOUT}"
EXPORT_SOURCE="${INSTANCE}"
EXPORT_STARTTIME_OFFSET_SPEC="${DEFAULT_EXPORT_STARTTIME_OFFSET_SPEC}"
EXPORT_ENDTIME="${DEFAULT_EXPORT_ENDTIME_VALUE}"
EXPORT_IP="${DEFAULT_EXPORT_IP}"
EXPORT_PORTID="${DEFAULT_EXPORT_PORTID}"
EXPORT_APP_CONFIG_FILE_PATH="${TARGET_APP_SPECIFIC_CONFIG_FILE}"
EOF
)
  write_generated_file_content "$generated_env_content" "$TARGET_ENV_CONF_FILE" "root" "$APP_GROUP" "0640" "environment configuration" # Uses debug internally
fi

write_generated_file_content "$DEFAULT_APP_CONFIG_CONTENT" "$TARGET_APP_SPECIFIC_CONFIG_FILE" "root" "$APP_GROUP" "0640" "application-specific configuration" # Uses debug internally


# --- Next Steps Information --- Keep these as info
info "Instance configuration for \"${INSTANCE}\" processing complete."
info "  Environment config (for wrapper): \"${TARGET_ENV_CONF_FILE}\""
info "  Application config (for -c arg):  \"${TARGET_APP_SPECIFIC_CONFIG_FILE}\""
if [[ -z "$CONFIG_SRC_ENV_FILE" ]]; then
  info "If default configurations were generated, please review and edit them as needed, especially:"
  info "    - ${TARGET_ENV_CONF_FILE} for EXPORT_IP, EXPORT_PORTID, EXPORT_STARTTIME_OFFSET_SPEC, etc."
fi
info "    - Review ${TARGET_APP_SPECIFIC_CONFIG_FILE} if '${DEFAULT_APP_CONFIG_CONTENT%%=*}' needs adjustment."


readonly main_service_name="${APP_NAME}@${INSTANCE}.service"
readonly path_service_name="${APP_NAME}-restart@${INSTANCE}.path"

# This heredoc is important user output, should always be displayed
cat <<EOF

-----------------------------------------------------------------------------
Instance '${INSTANCE}' of '${APP_NAME}' configuration files processed:
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

SCRIPT_SUCCESSFUL=true
exit "$EXIT_CODE_SUCCESS"