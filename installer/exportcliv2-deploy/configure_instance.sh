#!/usr/bin/env bash
# shellcheck disable=SC1090,SC2154 # SC1090 for source, SC2154 for sourced variables
set -euo pipefail
IFS=$'\n\t'

# -----------------------------------------------------------------------------
# Instance Configurator for exportcliv2
# Standardized argument parsing, logging, dry-run, error handling.
# Aligned with orchestrator's --force flag.
# v4.2.0: Use app.conf.template instead of hardcoded app config.
# -----------------------------------------------------------------------------
VERSION_CONFIGURE_INSTANCE="4.2.0" # Script version

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
# EXIT_CODE_ACTION_FAILED (7) might not be used here unless specific actions fail

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
FAIL_COUNT=0 # For run helper, though direct calls more common here

readonly APP_NAME_FOR_BASE_VARS_LOOKUP="exportcliv2" # Used to find /etc/default/...
readonly BASE_VARS_FILE="/etc/default/${APP_NAME_FOR_BASE_VARS_LOOKUP}_base_vars"

INSTANCE=""
CONFIG_SRC_ENV_FILE="" # Path to an optional source for <INSTANCE>.conf
USE_FORCE_FLAG=false   # Renamed from FORCE_OVERWRITE for consistency

# --- Trap Handling (Standardized) ---
# shellcheck disable=SC2317
_cleanup_on_error_configure() {
    local exit_code="$1"; local line_no="$2"; local command="$3"; echo;
    warn "--- INSTANCE CONFIGURATOR ERROR DETECTED ---"
    error_exit "Error on or near line ${line_no} in $(basename "${BASH_SOURCE[0]}"): command '${command}' returned exit code ${exit_code}." "${exit_code:-$EXIT_CODE_FATAL_ERROR}"
}
# shellcheck disable=SC2317
_cleanup_on_exit_configure() {
    local exit_code=$?
    if [[ "$HELP_OR_VERSION_EXIT" == true ]]; then return; fi
    echo
    if [[ "$exit_code" -eq "$EXIT_CODE_SUCCESS" && "$SCRIPT_SUCCESSFUL" == true ]]; then
        info "▶ Instance Configuration Script ($(basename "${BASH_SOURCE[0]}")) finished successfully."
    elif [[ "$exit_code" -eq "$EXIT_CODE_PARTIAL_SUCCESS" || ("$exit_code" -eq "$EXIT_CODE_SUCCESS" && "$FAIL_COUNT" -gt 0 && "$SCRIPT_SUCCESSFUL" == true) ]]; then
        warn "▶ Instance Configuration Script ($(basename "${BASH_SOURCE[0]}")) finished with $FAIL_COUNT non-fatal error(s)."
    elif [[ "$exit_code" -ne "$EXIT_CODE_SUCCESS" ]]; then
        echo -e "${C_ERROR}$(_ts) [ERROR] ▶ Instance Configuration Script ($(basename "${BASH_SOURCE[0]}")) failed. Review messages.${C_RESET}" >&2
    else
        warn "▶ Instance Configuration Script ($(basename "${BASH_SOURCE[0]}")) finished. Status unclear."
    fi
}
trap '_cleanup_on_error_configure "$?" "$LINENO" "$BASH_COMMAND"' ERR
trap '_cleanup_on_exit_configure' EXIT
trap 'error_exit "Script $(basename "${BASH_SOURCE[0]}") interrupted by signal." "$EXIT_CODE_FATAL_ERROR"' INT TERM

# --- Standardized run Helper (even if less used, good for consistency) ---
run() {
  local cmd_array=("$@"); local cmd_display; printf -v cmd_display '%q ' "${cmd_array[@]}";
  debug "Executing: $cmd_display"
  if [[ "$DRY_RUN" == true ]]; then info "[DRY-RUN] Would execute: $cmd_display"; return "$EXIT_CODE_SUCCESS"; fi
  "${cmd_array[@]}"; local ec=$?;
  if [[ $ec -ne 0 ]]; then warn "Command failed with $ec: $cmd_display"; ((FAIL_COUNT++)); return $ec; fi
  return "$EXIT_CODE_SUCCESS"
}

# --- Argument Parsing (Standardized to while/case) ---
usage() {
  HELP_OR_VERSION_EXIT=true
  local script_name; script_name=$(basename "$0")
  local determined_etc_dir_desc="the application's etc directory (e.g., /etc/${APP_NAME_FOR_BASE_VARS_LOOKUP} - determined from base install)"

  cat <<EOF
Usage: $script_name -i INSTANCE_NAME [OPTIONS]

Configures a new instance for the '${APP_NAME_FOR_BASE_VARS_LOOKUP}' application.
This script MUST be run as root or with sudo.

It creates two configuration files per instance in ${determined_etc_dir_desc}:
  1. <INSTANCE_NAME>.conf: Environment variables for the wrapper script.
  2. <INSTANCE_NAME>_app.conf: Config file passed via -c to the main binary. This file
                             is now copied from 'config_files/app.conf.template'.

Required:
  -i, --instance NAME       Name for this instance (e.g., "lab1", "prod_main").
                            Allowed characters: A-Z, a-z, 0-9, dot (.), underscore (_), dash (-).
Options:
  --config-source-env-file PATH
                            Optional: Path to a pre-existing environment configuration file
                            (<INSTANCE_NAME>.conf) to copy.
  --force                   Optional: Overwrite existing instance configuration file(s)
                            (both <INSTANCE_NAME>.conf and <INSTANCE_NAME>_app.conf).
  -n, --dry-run             Dry-run mode (print commands instead of executing).
  -v, --verbose             Verbose mode (enables debug messages and command tracing 'set -x').
  -h, --help                Show this help message and exit.
  --version                 Show script version and exit.
EOF
  exit "${1:-$EXIT_CODE_SUCCESS}"
}

# Pre-scan for help/version
for arg_pre_scan in "$@"; do
  case "$arg_pre_scan" in
    --version) echo "$(basename "$0") v${VERSION_CONFIGURE_INSTANCE}"; HELP_OR_VERSION_EXIT=true; exit "$EXIT_CODE_SUCCESS";;
    -h|--help) usage "$EXIT_CODE_SUCCESS";;
  esac
done

TEMP_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -i|--instance)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then error_exit "Option $1 requires a NAME argument." "$EXIT_CODE_USAGE_ERROR"; fi
      INSTANCE="$2"; shift 2;;
    --config-source-env-file)
      if [[ -z "${2:-}" || "${2}" == -* ]]; then error_exit "Option $1 requires a PATH argument." "$EXIT_CODE_USAGE_ERROR"; fi
      CONFIG_SRC_ENV_FILE="$2"; shift 2;;
    --force)
      USE_FORCE_FLAG=true; shift;;
    -n|--dry-run)
      DRY_RUN=true; shift;;
    -v|--verbose)
      VERBOSE_MODE=true; shift;;
    *)
      TEMP_ARGS+=("$1"); shift;; # Collect unknown options
  esac
done

if (( ${#TEMP_ARGS[@]} > 0 )); then
  error_exit "Unknown option or argument: ${TEMP_ARGS[0]}. Use --help for usage." "$EXIT_CODE_USAGE_ERROR"
fi

if [[ -z "$INSTANCE" ]]; then
  error_exit "Instance name (-i, --instance) is required. Use --help for usage." "$EXIT_CODE_USAGE_ERROR"
fi

if ! [[ "$INSTANCE" =~ ^[A-Za-z0-9._-]+$ ]]; then
  error_exit "Invalid instance name: \"${INSTANCE}\". Only A-Z, a-z, 0-9, '.', '_', '-' allowed." "$EXIT_CODE_USAGE_ERROR"
fi
debug "Validated instance name: \"${INSTANCE}\""

if [[ "$VERBOSE_MODE" == true ]]; then
  info "Verbose mode enabled (command tracing 'set -x' activated)."
  set -x
fi

# --- Root Execution Check ---
if [[ "$(id -u)" -ne 0 ]]; then
  error_exit "This script must be run as root or with sudo." "$EXIT_CODE_PREREQUISITE_ERROR"
fi

# <<< ADDED >>> Determine script directory to find templates
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
debug "Script directory determined as: $SCRIPT_DIR"

# --- Pre-flight check for required commands ---
required_commands=(getent install date id basename chmod chown printf mkdir realpath)
debug "Checking for required commands: ${required_commands[*]}"
for cmd in "${required_commands[@]}"; do
  command -v "$cmd" &>/dev/null || error_exit "Required command \"${cmd}\" not found." "$EXIT_CODE_PREREQUISITE_ERROR"
done
debug "All required commands are available."

# --- Load Base Vars ---
debug "Attempting to load base variables from \"${BASE_VARS_FILE}\"..."
if [[ ! -f "$BASE_VARS_FILE" ]]; then
  error_exit "Base variables file \"${BASE_VARS_FILE}\" not found. Ensure base installer ran." "$EXIT_CODE_CONFIG_ERROR"
fi
# shellcheck source=/dev/null
source "$BASE_VARS_FILE"
debug "Successfully sourced base variables from \"${BASE_VARS_FILE}\"."

# Validate essential variables from BASE_VARS_FILE
: "${APP_NAME:?APP_NAME not set in ${BASE_VARS_FILE}.}" "$EXIT_CODE_CONFIG_ERROR"
: "${ETC_DIR:?ETC_DIR not set in ${BASE_VARS_FILE}.}" "$EXIT_CODE_CONFIG_ERROR"
: "${APP_GROUP:?APP_GROUP not set in ${BASE_VARS_FILE}.}" "$EXIT_CODE_CONFIG_ERROR"
: "${DEFAULT_CONFIGURE_INSTANCE_EXPORT_TIMEOUT:?DEFAULT_CONFIGURE_INSTANCE_EXPORT_TIMEOUT not set in ${BASE_VARS_FILE}.}" "$EXIT_CODE_CONFIG_ERROR"

debug "Using APP_NAME: \"${APP_NAME}\", ETC_DIR: \"${ETC_DIR}\", APP_GROUP: \"${APP_GROUP}\"."
debug "Using default EXPORT_TIMEOUT: \"${DEFAULT_CONFIGURE_INSTANCE_EXPORT_TIMEOUT}\" seconds."

# --- Define Target Paths ---
readonly TARGET_CONF_DIR="$ETC_DIR" # e.g. /etc/exportcliv2
readonly TARGET_ENV_CONF_FILE="${TARGET_CONF_DIR}/${INSTANCE}.conf"
readonly APP_SPECIFIC_CONFIG_FILENAME="${INSTANCE}_app.conf"
readonly TARGET_APP_SPECIFIC_CONFIG_FILE="${TARGET_CONF_DIR}/${APP_SPECIFIC_CONFIG_FILENAME}"
# <<< ADDED >>> Define path to the new template file
readonly APP_CONFIG_TEMPLATE_PATH="${SCRIPT_DIR}/config_files/app.conf.template"

# <<< ADDED >>> Pre-flight check for the new template file
if [[ ! -f "$APP_CONFIG_TEMPLATE_PATH" ]]; then
    error_exit "Application config template not found at: '${APP_CONFIG_TEMPLATE_PATH}'" "$EXIT_CODE_CONFIG_ERROR"
fi
debug "Found application config template: '${APP_CONFIG_TEMPLATE_PATH}'"


# --- Define Defaults for Generated Configs ---
readonly DEFAULT_EXPORT_IP="10.0.0.1" # Example
readonly DEFAULT_EXPORT_PORTID="1"    # Example
readonly DEFAULT_EXPORT_STARTTIME_OFFSET_SPEC="3 minutes ago"
readonly DEFAULT_EXPORT_ENDTIME_VALUE="-1"
# <<< REMOVED >>> The hardcoded config content is no longer needed.
# readonly DEFAULT_APP_CONFIG_CONTENT="mining_delta_sec=120" # Example content

# --- Helper Functions for File Operations (Simplified to use 'run') ---
_manage_file_permissions() {
    local dest_file="$1"; local owner="$2"; local group="$3"; local perms="$4"
    run chown "$owner:$group" "$dest_file" \
        || error_exit "Failed to set ownership on '$dest_file'." "$EXIT_CODE_FILE_ERROR"
    run chmod "$perms" "$dest_file" \
        || error_exit "Failed to set permissions on '$dest_file'." "$EXIT_CODE_FILE_ERROR"
}

ensure_config_directory() {
    local dir_path="$1"
    debug "Ensuring target configuration directory: \"${dir_path}\""
    run install -d -o root -g "${APP_GROUP}" -m0755 "${dir_path}" \
        || error_exit "Failed to create/set perms for directory \"${dir_path}\"." "$EXIT_CODE_FILE_ERROR"
}

# <<< ADDED >>> New helper function specifically for installing template files
install_template_file() {
    local src_template="$1"; local dest_file="$2"; local owner="$3"; local group="$4"; local perms="$5"; local file_description="$6"
    debug "Installing ${file_description} from template '${src_template}' to '${dest_file}'"
    run install -T -o "$owner" -g "$group" -m "$perms" "$src_template" "$dest_file" \
        || error_exit "Failed to install ${file_description} from template '${src_template}' to '${dest_file}'." "$EXIT_CODE_FILE_ERROR"
    debug "Successfully installed ${file_description} to '${dest_file}'."
}


copy_source_env_file() {
    local src_file="$1"; local dest_file="$2"; local owner="$3"; local group="$4"; local perms="$5"
    debug "Copying \"${src_file}\" to \"${dest_file}\"..."
    if [[ ! -f "$src_file" ]]; then # src_file is user input, check before 'run'
        error_exit "Specified --config-source-env-file \"${src_file}\" not found." "$EXIT_CODE_CONFIG_ERROR"
    fi
    run install -T "$src_file" "$dest_file" \
        || error_exit "Failed to copy \"${src_file}\" to \"${dest_file}\"." "$EXIT_CODE_FILE_ERROR"
    _manage_file_permissions "$dest_file" "$owner" "$group" "$perms"
    debug "Environment configuration file processed from source: \"${dest_file}\"."
}

write_generated_file_content() {
    local content="$1"; local output_path="$2"; local owner="$3"; local group="$4"; local perms="$5"; local file_description="$6"
    debug "Writing generated ${file_description} to \"${output_path}\"..."
    if [[ "$DRY_RUN" == true ]]; then
        info "[DRY-RUN] Would write to \"${output_path}\":"
        echo "--- BEGIN GENERATED ${file_description^^} (${output_path}) ---"
        echo "$content"
        echo "--- END GENERATED ${file_description^^} ---"
        info "[DRY-RUN] Would chown \"$owner:$group\" \"$output_path\""
        info "[DRY-RUN] Would chmod \"$perms\" \"$output_path\""
    else
        # Direct write for content, then use run for chown/chmod via _manage_file_permissions
        printf "%s\n" "$content" > "$output_path" \
            || error_exit "Failed to write ${file_description} to \"${output_path}\"." "$EXIT_CODE_FILE_ERROR"
        _manage_file_permissions "$output_path" "$owner" "$group" "$perms"
        debug "Successfully generated and saved ${file_description} to \"${output_path}\"."
    fi
}

# --- Main Logic ---
main() {
    info "Starting instance configuration for '${INSTANCE}' (v${VERSION_CONFIGURE_INSTANCE})..."
    # DRY_RUN/VERBOSE_MODE info handled by arg parsing section

    target_files_exist=false
    existing_files_msg=""
    if [[ -e "$TARGET_ENV_CONF_FILE" ]]; then target_files_exist=true; existing_files_msg+="'${TARGET_ENV_CONF_FILE}' "; fi
    if [[ -e "$TARGET_APP_SPECIFIC_CONFIG_FILE" ]]; then target_files_exist=true; existing_files_msg+="'${TARGET_APP_SPECIFIC_CONFIG_FILE}'"; fi
    existing_files_msg="${existing_files_msg%" "}" # Trim trailing space

    if [[ "$target_files_exist" == true && "$USE_FORCE_FLAG" != true ]]; then # Use boolean check
      # This error message is specific and helpful.
      error_exit "One or more target configuration files exist: (${existing_files_msg}). Use this script's --force option to overwrite." "$EXIT_CODE_FILE_ERROR"
    elif [[ "$target_files_exist" == true && "$USE_FORCE_FLAG" == true ]]; then
      warn "Target configuration files exist: (${existing_files_msg}). --force specified, proceeding with overwrite."
    fi

    ensure_config_directory "$TARGET_CONF_DIR"

    if [[ -n "$CONFIG_SRC_ENV_FILE" ]]; then
      copy_source_env_file "$CONFIG_SRC_ENV_FILE" "$TARGET_ENV_CONF_FILE" "root" "$APP_GROUP" "0640"
    else
      local script_basename; script_basename=$(basename "$0") # basename is safe
      # Using local variable for content to avoid very long lines in heredoc assignment
      local generated_env_content
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
      write_generated_file_content "$generated_env_content" "$TARGET_ENV_CONF_FILE" "root" "$APP_GROUP" "0640" "environment configuration"
    fi

    # <<< MODIFIED >>> Use the new function to copy the template
    install_template_file "$APP_CONFIG_TEMPLATE_PATH" "$TARGET_APP_SPECIFIC_CONFIG_FILE" "root" "$APP_GROUP" "0640" "application-specific configuration"

    info "Instance configuration for \"${INSTANCE}\" processing complete."
    info "  Environment config (for wrapper): \"${TARGET_ENV_CONF_FILE}\""
    info "  Application config (for -c arg):  \"${TARGET_APP_SPECIFIC_CONFIG_FILE}\" (copied from template)"
    if [[ -z "$CONFIG_SRC_ENV_FILE" ]]; then
      info "Default configurations were generated. Please review and edit them as needed:"
      info "    - ${TARGET_ENV_CONF_FILE} (especially EXPORT_IP, EXPORT_PORTID)"
    fi
    # <<< MODIFIED >>> Updated info message
    info "    - Review ${TARGET_APP_SPECIFIC_CONFIG_FILE} if its templated content needs instance-specific adjustment."

    # Final heredoc summary
    local main_service_name="${APP_NAME}@${INSTANCE}.service" # Moved into main, as APP_NAME comes from sourced file
    local path_service_name="${APP_NAME}-restart@${INSTANCE}.path"
cat <<EOF

-----------------------------------------------------------------------------
Instance '${INSTANCE}' of '${APP_NAME}' configuration files processed:
  Env Config: ${TARGET_ENV_CONF_FILE}
  App Config: ${TARGET_APP_SPECIFIC_CONFIG_FILE}
-----------------------------------------------------------------------------
Next Steps:
The deployment orchestrator (if used) typically handles enabling and starting
services after configuration.

To manage this instance ('${INSTANCE}') manually, use 'exportcli-manage':
  sudo exportcli-manage -i ${INSTANCE} --status        # Check status
  sudo exportcli-manage -i ${INSTANCE} --enable         # Enable services for boot
  sudo exportcli-manage -i ${INSTANCE} --start          # Start services
  sudo exportcli-manage -i ${INSTANCE} --restart        # Restart services
  sudo exportcli-manage -i ${INSTANCE} --stop           # Stop services
  sudo exportcli-manage -i ${INSTANCE} --disable        # Disable services for boot
  sudo exportcli-manage -i ${INSTANCE} --logs           # View recent logs
  sudo exportcli-manage -i ${INSTANCE} --logs-follow    # Follow live logs
-----------------------------------------------------------------------------
Remember to review/edit the generated configuration files as needed:
  - ${TARGET_ENV_CONF_FILE} (especially EXPORT_IP, EXPORT_PORTID)
  - ${TARGET_APP_SPECIFIC_CONFIG_FILE} (which is now based on a template)
-----------------------------------------------------------------------------
EOF
    SCRIPT_SUCCESSFUL=true
}

# --- Execute Main ---
main "$@"
# EXIT trap handles final summary messages