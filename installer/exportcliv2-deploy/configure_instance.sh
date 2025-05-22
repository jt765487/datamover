#!/usr/bin/env bash
# shellcheck disable=SC1090,SC2154 # SC1090 for source, SC2154 for sourced variables
set -euo pipefail
IFS=$'\n\t'

# -----------------------------------------------------------------------------
# Instance Configurator for exportcliv2 (v3 - Further Refined)
# -----------------------------------------------------------------------------
# - Creates <instance>.conf (environment variables for wrapper script).
# - Creates <instance>_app.conf (config file for exportcliv2 binary -c arg).
# - Uses defaults from base installer via /etc/default/${APP_NAME}_base_vars.
# - Incorporates feedback on exit codes, helper functions, --force documentation,
#   dry-run consistency, success messaging, and usage error handling.
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
info() { echo "$(_ts) [INFO]  $*"; }
warn() { echo "$(_ts) [WARN]  $*"; }
error_exit() {
  local message="$1"
  local exit_code="${2:-$EXIT_CODE_GENERAL_ERROR}"
  echo "$(_ts) [ERROR] $message" >&2
  exit "$exit_code"
}

SCRIPT_SUCCESSFUL=false # Flag to indicate successful completion for EXIT trap

# shellcheck disable=SC2317
cleanup_on_error() {
  local exit_code="${1:-$?}"
  local line_num="${2:-UNKNOWN_LINE}"
  local failed_command="${3:-UNKNOWN_COMMAND}"

  # This ERR trap runs if a command fails due to set -e, or if error_exit is called.
  # If error_exit was called, SCRIPT_SUCCESSFUL will be false.
  # If set -e triggered this, SCRIPT_SUCCESSFUL will also be false.
  # We only want to print detailed error if error_exit hasn't already handled it.
  if [[ "$exit_code" -ne "$EXIT_CODE_SUCCESS" && "$failed_command" != "error_exit"* ]]; then
    warn "Instance configuration FAILED on line ${line_num} with command: ${failed_command} (exit code: ${exit_code})."
    warn "System may be in an inconsistent state. Review logs and manually clean up if necessary."
  fi
  SCRIPT_SUCCESSFUL=false # Ensure it's false on any error
}
# shellcheck disable=SC2317
cleanup_on_exit() {
    local exit_code="${1:-$?}"
    if [[ "$SCRIPT_SUCCESSFUL" == true && "$exit_code" -eq "$EXIT_CODE_SUCCESS" ]]; then
        info "-------------------- INSTANCE CONFIGURATION COMPLETED SUCCESSFULLY --------------------"
    elif [[ "$exit_code" -ne "$EXIT_CODE_SUCCESS" && "$SCRIPT_SUCCESSFUL" == false ]]; then
        # Error message would have been printed by error_exit or cleanup_on_error
        info "-------------------- INSTANCE CONFIGURATION FAILED --------------------"
    fi
}

trap 'cleanup_on_error "$?" "$LINENO" "$BASH_COMMAND"' ERR
trap 'cleanup_on_exit $?' EXIT


readonly APP_NAME_FOR_BASE_VARS_LOOKUP="exportcliv2" # Used to find the _base_vars file
readonly BASE_VARS_FILE="/etc/default/${APP_NAME_FOR_BASE_VARS_LOOKUP}_base_vars"

# --- Argument Parsing ---
INSTANCE=""
CONFIG_SRC_ENV_FILE=""
FORCE_OVERWRITE=""
DRY_RUN=""

usage() {
  local determined_etc_dir_desc="the application's etc directory (typically /etc/${APP_NAME_FOR_BASE_VARS_LOOKUP})"
  cat <<EOF
Usage: $(basename "$0") -i INSTANCE_NAME [--config-source-env-file PATH] [--force] [-n] [-h]

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
  -n                        Dry-run mode (print commands, no execution).
  -h                        Show this help message and exit.
EOF
  # If usage is called directly (e.g. -h), exit with 0. If called due to error, caller should use error_exit.
  # However, for consistency with error_exit, we'll make it exit with USAGE_ERROR.
  # The caller can decide if it's a "clean help exit" or an error.
  # For -h, the script exits before SCRIPT_SUCCESSFUL is set to true.
  exit "${1:-$EXIT_CODE_USAGE_ERROR}"
}

while getopts ":nhi:" o; do
  case $o in
    i) INSTANCE="$OPTARG" ;;
    n) DRY_RUN="echo" ;;
    h) usage "$EXIT_CODE_SUCCESS" ;; # Explicit success exit for -h
    \?) error_exit "Invalid short option: -$OPTARG. Use -h for help." "$EXIT_CODE_USAGE_ERROR" ;;
    :) error_exit "Short option -$OPTARG requires an argument. Use -h for help." "$EXIT_CODE_USAGE_ERROR" ;;
  esac
done
shift $((OPTIND -1))

# Manual parsing for long options
while [[ $# -gt 0 ]]; do
    case "$1" in
        --config-source-env-file)
            if [[ -z "${2:-}" ]]; then error_exit "Option --config-source-env-file requires an argument." "$EXIT_CODE_USAGE_ERROR"; fi
            CONFIG_SRC_ENV_FILE="$2"
            shift 2
            ;;
        --force)
            FORCE_OVERWRITE="true"
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

# --- Validate Mandatory Instance Name (must be set after all parsing) ---
if [[ -z "$INSTANCE" ]]; then
  error_exit "Instance name (-i) is required. Use -h for help." "$EXIT_CODE_USAGE_ERROR"
fi

# Validate instance name format
if ! [[ "$INSTANCE" =~ ^[A-Za-z0-9._-]+$ ]]; then
  error_exit "Invalid instance name: \"${INSTANCE}\". Only A-Z, a-z, 0-9, dot (.), underscore (_), and dash (-) are allowed." "$EXIT_CODE_USAGE_ERROR"
fi
info "Validated instance name: \"${INSTANCE}\""

# --- Pre-flight check for required commands ---
required_commands=(getent install date id basename chmod chown printf mkdir)
info "Checking for required commands..."
for cmd in "${required_commands[@]}"; do
  command -v "$cmd" &>/dev/null || error_exit "Required command \"${cmd}\" is not installed or not in PATH." "$EXIT_CODE_PREREQUISITE_ERROR"
done
info "All required commands are available."

# --- Load Base Vars (sourced from file created by main installer) ---
info "Attempting to load base variables from \"${BASE_VARS_FILE}\"..."
if [[ ! -f "$BASE_VARS_FILE" ]]; then
  error_exit "Base variables file \"${BASE_VARS_FILE}\" not found. Ensure the base installer was run successfully." "$EXIT_CODE_CONFIG_ERROR"
fi
source "$BASE_VARS_FILE" # SC1090
info "Successfully sourced base variables from \"${BASE_VARS_FILE}\"."

: "${APP_NAME:?APP_NAME not set in ${BASE_VARS_FILE}. Base install may be incomplete.}" "$EXIT_CODE_CONFIG_ERROR"
: "${ETC_DIR:?ETC_DIR not set in ${BASE_VARS_FILE}. Base install may be incomplete.}" "$EXIT_CODE_CONFIG_ERROR"
: "${APP_GROUP:?APP_GROUP not set in ${BASE_VARS_FILE}. Base install may be incomplete.}" "$EXIT_CODE_CONFIG_ERROR"
: "${DEFAULT_CONFIGURE_INSTANCE_EXPORT_TIMEOUT:?DEFAULT_CONFIGURE_INSTANCE_EXPORT_TIMEOUT not set in ${BASE_VARS_FILE}. Base install may be incomplete or install-app.conf is missing EXPORT_TIMEOUT_CONFIG.}" "$EXIT_CODE_CONFIG_ERROR"

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
readonly DEFAULT_EXPORT_IP="10.0.0.1"
readonly DEFAULT_EXPORT_PORTID="1"
readonly DEFAULT_EXPORT_STARTTIME_OFFSET_SPEC="3 minutes ago"
readonly DEFAULT_EXPORT_ENDTIME_VALUE="-1" # Fixed value for this app version
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
    info "Ensuring target configuration directory (previewed in dry-run): \"${dir_path}\""
    # Using install -d as it's concise for this purpose and sets ownership/perms.
    # Group is APP_GROUP to allow service to read if needed, root owns.
    $DRY_RUN install -d -o root -g "${APP_GROUP}" -m0755 "${dir_path}" \
        || error_exit "Failed to create or set permissions for directory \"${dir_path}\"." "$EXIT_CODE_FILE_ERROR"
}

copy_source_env_file() {
    local src_file="$1"; local dest_file="$2"; local owner="$3"; local group="$4"; local perms="$5"
    info "Copying \"${src_file}\" to \"${dest_file}\"..."
    if [[ ! -f "$src_file" ]]; then
        error_exit "Specified environment configuration source file \"${src_file}\" not found." "$EXIT_CODE_CONFIG_ERROR"
    fi
    $DRY_RUN install -T "$src_file" "$dest_file" \
        || error_exit "Failed to copy \"${src_file}\" to \"${dest_file}\"." "$EXIT_CODE_FILE_ERROR"
    _manage_file_permissions "$dest_file" "$owner" "$group" "$perms"
    info "Environment configuration file processed from source: \"${dest_file}\"."
}

write_generated_file_content() {
    local content="$1"; local output_path="$2"; local owner="$3"; local group="$4"; local perms="$5"; local file_description="$6"

    info "Writing generated ${file_description} to \"${output_path}\"..."
    if [[ -n "$DRY_RUN" ]]; then
        info "[DRY_RUN] Would write the following content to \"${output_path}\":"
        # Using cat with heredoc for clear dry-run output of content
        cat <<DRYRUNEOF
--- BEGIN GENERATED ${file_description^^} (${output_path}) ---
$content
--- END GENERATED ${file_description^^} ---
DRYRUNEOF
        # Also show what chown/chmod would do
        echo "$DRY_RUN chown \"$owner:$group\" \"$output_path\""
        echo "$DRY_RUN chmod \"$perms\" \"$output_path\""
    else
        printf "%s\n" "$content" > "$output_path" \
            || error_exit "Failed to write ${file_description} to \"${output_path}\"." "$EXIT_CODE_FILE_ERROR"
        _manage_file_permissions "$output_path" "$owner" "$group" "$perms" # Call helper for actual chown/chmod
        info "Successfully generated and saved ${file_description} to \"${output_path}\"."
    fi
}

# --- Main Logic ---

[[ -n "$DRY_RUN" ]] && warn "DRY RUN MODE ENABLED: No changes will be made to the system."

# Guard against accidental overwrites
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

if [[ "$target_files_exist" == true && -z "$FORCE_OVERWRITE" ]]; then
  if [[ -z "$DRY_RUN" ]]; then
    error_exit "One or more target configuration files exist: (${existing_files_msg}). Use --force to overwrite both." "$EXIT_CODE_FILE_ERROR"
  else
    info "[DRY_RUN] One or more target configuration files exist: (${existing_files_msg}). If not in dry-run, --force would be required to overwrite."
  fi
elif [[ "$target_files_exist" == true && -n "$FORCE_OVERWRITE" ]]; then
   if [[ -z "$DRY_RUN" ]]; then
    warn "One or more target configuration files exist: (${existing_files_msg}). --force specified, proceeding with overwrite."
   else
    info "[DRY_RUN] One or more target configuration files exist: (${existing_files_msg}). --force specified, would proceed with overwrite."
   fi
fi

ensure_config_directory "$TARGET_CONF_DIR"

# Deploy or Generate Instance Environment Configuration File (e.g., ZZZ.conf)
if [[ -n "$CONFIG_SRC_ENV_FILE" ]]; then
  copy_source_env_file "$CONFIG_SRC_ENV_FILE" "$TARGET_ENV_CONF_FILE" "root" "$APP_GROUP" "0640"
else
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
  write_generated_file_content "$generated_env_content" "$TARGET_ENV_CONF_FILE" "root" "$APP_GROUP" "0640" "environment configuration"
fi

# Always Generate/Update Application-Specific Config File (e.g., ZZZ_app.conf)
# This file is simple and has fixed default content.
# The main overwrite guard already handled the "exists without --force" scenario.
# So, if we are here, either the file doesn't exist, or --force was given.
write_generated_file_content "$DEFAULT_APP_CONFIG_CONTENT" "$TARGET_APP_SPECIFIC_CONFIG_FILE" "root" "$APP_GROUP" "0640" "application-specific configuration"


# --- Next Steps Information ---
info "Instance configuration for \"${INSTANCE}\" processing complete." # "processing complete" to avoid "successful" before final exit trap
info "  Environment config (for wrapper): \"${TARGET_ENV_CONF_FILE}\""
info "  Application config (for -c arg):  \"${TARGET_APP_SPECIFIC_CONFIG_FILE}\""
if [[ -z "$CONFIG_SRC_ENV_FILE" ]]; then
  info "If default configurations were generated, please review and edit them as needed, especially:"
  info "    - ${TARGET_ENV_CONF_FILE} for EXPORT_IP, EXPORT_PORTID, EXPORT_STARTTIME_OFFSET_SPEC, etc."
fi
info "    - Review ${TARGET_APP_SPECIFIC_CONFIG_FILE} if '${DEFAULT_APP_CONFIG_CONTENT%%=*}' needs adjustment."


readonly main_service_name="${APP_NAME}@${INSTANCE}.service"
readonly path_service_name="${APP_NAME}-restart@${INSTANCE}.path" # Assuming this naming from previous context

# Final guidance printed to stdout, not via info/warn
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

SCRIPT_SUCCESSFUL=true # Set flag for successful completion
# Normal exit will trigger cleanup_on_exit
exit "$EXIT_CODE_SUCCESS"
