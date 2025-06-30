#!/usr/bin/env bash
#
# uninstall_exportcliv2_suite.sh
# Uninstalls the ExportCLIv2 application suite.
# WARNING: This script performs destructive operations. Review carefully.
# Version: 1.0.3 (Refined instance discovery, bin dir cleanup)

# --- Colorized Logging ---
CSI=$'\033['
C_RESET="${CSI}0m"
C_INFO="${CSI}32m"  # Green
C_WARN="${CSI}33m"  # Yellow
C_ERROR="${CSI}31m" # Red

_ts() { date -u +'%Y-%m-%dT%H:%M:%SZ'; }
_log_msg() {
    local log_level_name="$1"; local color_var_name="C_${log_level_name}"; local color_code="${!color_var_name}"; shift;
    echo -e "${color_code}$(_ts) [${log_level_name^^}] $*${C_RESET}" >&2;
}
info()       { _log_msg "INFO" "$*"; }
warn()       { _log_msg "WARN" "$*"; }
error_msg()  { _log_msg "ERROR" "$*"; } # Just logs, doesn't exit

# --- Globals ---
APP_NAME_FOR_BASE_VARS_LOOKUP="exportcliv2" # Default, might be overridden by sourced vars
BASE_VARS_FILE="/etc/default/${APP_NAME_FOR_BASE_VARS_LOOKUP}_base_vars"
APP_NAME="" # Will be sourced
ETC_DIR=""
BASE_DIR=""
# These will be sourced, declare them to avoid unbound variable errors if set -u is active elsewhere
APP_USER=""
APP_GROUP=""
PYTHON_VENV_PATH=""
SYMLINK_EXECUTABLE_PATH=""
DEST_VERSIONED_APP_BINARY_PATH=""
INSTALLED_WRAPPER_SCRIPT_PATH=""
SOURCE_DATA_DIR=""
CSV_DATA_DIR=""
WORKER_DATA_DIR=""
UPLOADED_DATA_DIR=""
DEAD_LETTER_DATA_DIR=""

BITMOVER_SERVICE_NAME="bitmover.service" # Usually fixed
ORCHESTRATOR_LOCK_FILE="/tmp/deploy_orchestrator.lock" # As per deploy_orchestrator.sh

REMOVE_DATA_DIRS=false
REMOVE_LOG_DIRS=false

# --- Helper to run a command and log warning on failure, but not exit ---
run_and_warn() {
    local cmd_display
    printf -v cmd_display '%q ' "$@"
    info "Attempting: $cmd_display"
    "$@"
    local ec=$?
    if [[ $ec -ne 0 ]]; then
        warn "Command failed with exit code $ec: $cmd_display"
    fi
    return $ec
}

# --- Main Script Logic ---
main() {
    info "Starting ExportCLIv2 Application Suite Uninstallation (v1.1.0)..."

    if [[ "$(id -u)" -ne 0 ]]; then
        error_msg "This script must be run as root or with sudo."
        exit 1
    fi

    # --- Load Base Variables ---
    if [[ -f "$BASE_VARS_FILE" ]]; then
        info "Loading installation variables from $BASE_VARS_FILE..."
        # shellcheck source=/dev/null
        source "$BASE_VARS_FILE"
        # Update APP_NAME_FOR_BASE_VARS_LOOKUP if APP_NAME is defined in the file
        APP_NAME_FOR_BASE_VARS_LOOKUP="${APP_NAME:-$APP_NAME_FOR_BASE_VARS_LOOKUP}"
        info "Using APP_NAME: ${APP_NAME:-<not set, using default for some paths>}"
        info "Using BASE_DIR: ${BASE_DIR:-<not set, cleanup may be incomplete>}"
        info "Using ETC_DIR:  ${ETC_DIR:-<not set, cleanup may be incomplete>}"
    else
        error_msg "CRITICAL: Base variables file '$BASE_VARS_FILE' not found!"
        error_msg "Cannot automatically determine installation paths. Aborting."
        exit 1
    fi

    # Check essential variables
    if [[ -z "$APP_NAME" || -z "$BASE_DIR" || -z "$ETC_DIR" ]]; then
        error_msg "CRITICAL: One or more essential variables (APP_NAME, BASE_DIR, ETC_DIR) are not set from $BASE_VARS_FILE."
        error_msg "Aborting to prevent damage."
        exit 1
    fi

    # --- User Confirmation ---
    echo
    warn "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! WARNING !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    warn "This script will attempt to uninstall the '${APP_NAME}' application suite."
    warn "This involves stopping services, removing files, and systemd units."
    warn "Base application directory: $BASE_DIR"
    warn "Configuration directory:    $ETC_DIR"
    warn "Log directory (base):       /var/log/$APP_NAME"
    warn "The application user ('${APP_USER:-unknown}') and group ('${APP_GROUP:-unknown}') will NOT be removed."
    warn "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
    echo
    read -r -p "Are you absolutely sure you want to proceed? (yes/NO): " confirmation
    if [[ "$confirmation" != "yes" ]]; then
        info "Uninstallation aborted by user."
        exit 0
    fi

    echo
    read -r -p "Do you want to remove application DATA directories (e.g., PCAPs, CSVs in $BASE_DIR/{source,csv,worker,uploaded,dead_letter})? (yes/NO): " confirm_data
    if [[ "$confirm_data" == "yes" ]]; then
        REMOVE_DATA_DIRS=true
        warn "User confirmed: Application DATA WILL BE REMOVED."
    else
        info "Application data directories will be preserved (if they exist)."
    fi

    echo
    read -r -p "Do you want to remove application LOG directories (in /var/log/$APP_NAME)? (yes/NO): " confirm_logs
    if [[ "$confirm_logs" == "yes" ]]; then
        REMOVE_LOG_DIRS=true
        warn "User confirmed: Application LOGS WILL BE REMOVED."
    else
        info "Application log directories will be preserved (if they exist)."
    fi
    echo

    # --- 1. Stop and Disable Systemd Services ---
    info "--- Stopping and Disabling Systemd Services ---"
    local instance_conf_files
    if [[ -d "$ETC_DIR" ]]; then
        # Refined find: exclude common.auth.conf, config.ini, and *_app.conf
        instance_conf_files=$(find "$ETC_DIR" -maxdepth 1 -type f -name "*.conf" \
                                ! -name "common.auth.conf" \
                                ! -name "config.ini" \
                                ! -name "*_app.conf" -print)
    else
        instance_conf_files=""
        warn "Configuration directory $ETC_DIR not found, cannot identify instances for service stop/disable."
    fi

    for conf_file in $instance_conf_files; do
        local instance_name
        instance_name=$(basename "$conf_file" .conf)
        if [[ -z "$instance_name" ]]; then
            warn "Could not derive instance name from '$conf_file', skipping."
            continue
        fi
        info "Processing instance: $instance_name"
        run_and_warn systemctl stop "${APP_NAME}@${instance_name}.service"
        run_and_warn systemctl disable "${APP_NAME}@${instance_name}.service"
        run_and_warn systemctl stop "${APP_NAME}-restart@${instance_name}.path"
        run_and_warn systemctl disable "${APP_NAME}-restart@${instance_name}.path"
        run_and_warn systemctl disable "${APP_NAME}-restart@${instance_name}.service"

        # --- ADD THESE THREE LINES ---
        info "Stopping and disabling health check timer for instance: $instance_name"
        run_and_warn systemctl stop "${APP_NAME}-healthcheck@${instance_name}.timer"
        run_and_warn systemctl disable "${APP_NAME}-healthcheck@${instance_name}.timer"
        # ---------------------------
    done

    info "Processing main Bitmover service: $BITMOVER_SERVICE_NAME"
    run_and_warn systemctl stop "$BITMOVER_SERVICE_NAME"
    run_and_warn systemctl disable "$BITMOVER_SERVICE_NAME"

    # --- 2. Remove Systemd Unit Files ---
    info "--- Removing Systemd Unit Files ---"
    run_and_warn rm -f "/etc/systemd/system/$BITMOVER_SERVICE_NAME"
    run_and_warn rm -f "/etc/systemd/system/${APP_NAME}@.service"
    run_and_warn rm -f "/etc/systemd/system/${APP_NAME}-restart@.path"
    run_and_warn rm -f "/etc/systemd/system/${APP_NAME}-restart@.service"

    info "Removing health check systemd units..."
    run_and_warn rm -f "/etc/systemd/system/${APP_NAME}-healthcheck@.service"
    run_and_warn rm -f "/etc/systemd/system/${APP_NAME}-healthcheck@.timer"

    info "Reloading systemd daemon..."
    run_and_warn systemctl daemon-reload

    # --- 3. Remove Application Filesystem Components ---
    info "--- Removing Application Filesystem Components ---"
    info "Removing management symlink: /usr/local/bin/exportcli-manage"
    run_and_warn rm -f "/usr/local/bin/exportcli-manage"

    info "Removing base variables file: $BASE_VARS_FILE"
    run_and_warn rm -f "$BASE_VARS_FILE"

    if [[ -n "$ETC_DIR" && "$ETC_DIR" != "/" ]]; then # Safety check
        info "Removing configuration directory: $ETC_DIR"
        run_and_warn rm -rf "$ETC_DIR"
    else
        warn "ETC_DIR variable is not set or is '/', skipping removal of config directory."
    fi

    # Files/dirs within BASE_DIR
    if [[ -n "$BASE_DIR" && "$BASE_DIR" != "/" ]]; then # Safety check
        info "Cleaning up base application directory: $BASE_DIR"

        # If removing data, the whole BASE_DIR will be removed later, so specific file removals
        # inside BASE_DIR become somewhat redundant but harmless.
        # If NOT removing data, we need to be more surgical.

        if [[ "$REMOVE_DATA_DIRS" == true ]]; then
            warn "REMOVING ENTIRE BASE DIRECTORY (including data, logs, bin, venv) as requested by user: $BASE_DIR"
            run_and_warn rm -rf "$BASE_DIR"
        else
            info "Preserving data directories. Removing only specific application components from $BASE_DIR."
            if [[ -n "$PYTHON_VENV_PATH" && -d "$PYTHON_VENV_PATH" ]]; then
                info "Removing Python virtual environment: $PYTHON_VENV_PATH"
                run_and_warn rm -rf "$PYTHON_VENV_PATH"
            fi
            if [[ -d "${BASE_DIR}/bin" ]]; then
                info "Removing application binaries and scripts from ${BASE_DIR}/bin/"
                if [[ -n "$DEST_VERSIONED_APP_BINARY_PATH" && -f "$DEST_VERSIONED_APP_BINARY_PATH" ]]; then
                     run_and_warn rm -f "$DEST_VERSIONED_APP_BINARY_PATH"
                fi
                # Also attempt to remove what the symlink points to, if different or if base_vars was stale
                if [[ -n "$SYMLINK_EXECUTABLE_PATH" && -L "$SYMLINK_EXECUTABLE_PATH" ]]; then
                    local actual_binary_target
                    actual_binary_target=$(readlink "$SYMLINK_EXECUTABLE_PATH")
                    if [[ -n "$actual_binary_target" && -f "${BASE_DIR}/bin/${actual_binary_target}" ]]; then
                        if [[ "${BASE_DIR}/bin/${actual_binary_target}" != "$DEST_VERSIONED_APP_BINARY_PATH" ]]; then
                            info "Removing actual symlink target: ${BASE_DIR}/bin/${actual_binary_target}"
                            run_and_warn rm -f "${BASE_DIR}/bin/${actual_binary_target}"
                        fi
                    fi
                fi
                if [[ -n "$SYMLINK_EXECUTABLE_PATH" ]]; then
                    run_and_warn rm -f "$SYMLINK_EXECUTABLE_PATH"
                fi
                if [[ -n "$INSTALLED_WRAPPER_SCRIPT_PATH" ]]; then
                    run_and_warn rm -f "$INSTALLED_WRAPPER_SCRIPT_PATH"
                fi
                run_and_warn rm -f "${BASE_DIR}/bin/manage_services.sh"

                # Attempt to remove bin dir if empty
                rmdir "${BASE_DIR}/bin" 2>/dev/null || \
                    info "Directory ${BASE_DIR}/bin not empty or error removing. This is okay if data/other files are preserved."
            fi
            info "Base application directory $BASE_DIR has had components removed. Data subdirectories (source, csv, etc.) are preserved."
            info "You may need to manually remove $BASE_DIR if it's no longer needed and contains only preserved data."
        fi
    else
        warn "BASE_DIR variable is not set or is '/', skipping removal of base application directory."
    fi

    # Log directory
    local log_dir_base="/var/log/$APP_NAME"
    if [[ "$REMOVE_LOG_DIRS" == true ]]; then
        warn "REMOVING LOG DIRECTORIES as requested by user: $log_dir_base"
        if [[ -d "$log_dir_base" && "$log_dir_base" != "/" && "$log_dir_base" != "/var/log" ]]; then # Safety
            run_and_warn rm -rf "$log_dir_base"
        else
            warn "Log directory '$log_dir_base' not found or is a system path, skipping removal."
        fi
    else
        info "Preserving log directory (if it exists): $log_dir_base."
    fi

    # --- 4. Miscellaneous Cleanup ---
    info "--- Miscellaneous Cleanup ---"
    if [[ -f "$ORCHESTRATOR_LOCK_FILE" ]]; then
        info "Removing orchestrator lock file: $ORCHESTRATOR_LOCK_FILE"
        run_and_warn rm -f "$ORCHESTRATOR_LOCK_FILE"
    fi

    echo
    info "Uninstallation attempt complete."
    info "Please review the output above for any warnings or errors."
    info "If data or log directories were preserved, you may need to remove them manually if desired."
    info "The application user ('${APP_USER:-unknown}') and group ('${APP_GROUP:-unknown}') have NOT been removed."
}

# --- Script Entry ---
main "$@"

exit 0 # Exit cleanly, user reviews logs for step failures.