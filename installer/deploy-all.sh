#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# -----------------------------------------------------------------------------
# v2 Deployment Orchestrator (with Update Capability)
# -----------------------------------------------------------------------------
VERSION="2.1.0" # Version bump for update feature

# --- Logging ---
_ts()        { date -u +'%Y-%m-%dT%H:%M:%SZ'; }
info()       { echo >&2 "$(_ts) [INFO]  $*"; }
warn()       { echo >&2 "$(_ts) [WARN]  $*"; }
error_exit() { echo >&2 "$(_ts) [ERROR] $*"; exit 1; }

# --- Defaults ---
SOURCE_DIR="."
BASE_CONFIG="install-app.conf"
DEFAULT_INSTANCES=(AAA BBB CCC) # Example default instances
INSTANCE_NAMES_STRING="" # Will hold comma-separated string from CLI
PARSED_INSTANCE_NAMES=() # Array of parsed instance names
DRY_RUN=false
VERBOSE=false # Still present, can be implemented later
OPERATION_MODE="install" # "install" or "update"
FORCE_INSTANCE_CONFIG=false # For --force-reconfigure option

SCRIPTS_TO_CHECK=(install_base_exportcliv2.sh configure_instance.sh manage_services.sh)

# --- Helpers ---
run() {
  if [[ "$DRY_RUN" == true ]]; then
    # Use printf for better quoting of arguments in dry run
    printf "%s [DRY-RUN] Would execute: " "$(_ts)" >&2
    printf "'%s' " "$@" >&2
    printf "\n" >&2
    return 0
  fi
  info "Running: $*"
  set +e
  "$@"
  local ec=$?
  set -e
  if (( ec != 0 )); then
    warn "Command failed (exit code $ec): $*"
    # For critical steps, the caller should use '|| error_exit'
  fi
  return "$ec"
}

# --- Usage ---
usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS] [--install | --update]

Orchestrates the deployment or update of the v2 application suite.
Must be run from the unpacked source tree directory.

Modes (one is required):
  --install                Perform a fresh installation or add/reconfigure instances.
  --update                 Perform an update of application binaries/wheels.
                           (Assumes new artifacts are in source-dir and $BASE_CONFIG is updated).

General Options:
  -s, --source-dir DIR     Path to the unpacked source tree (default: current directory).
                           This script should usually be run from within this directory.
  -c, --config FILE        Base install config filename (inside source-dir).
                           Default: ${BASE_CONFIG}
  -i, --instances LIST     Comma-separated instance names to configure/manage.
                           Default for --install (if not empty): ${DEFAULT_INSTANCES[*]}
                           For --update, instances are not reconfigured by default.
  --force-reconfigure      During --install, force overwrite of existing instance configs.
                           (Passes --force to configure_instance.sh).
  -n, --dry-run            Show commands without executing.
  -v, --verbose            Enable verbose logging (currently a placeholder).
  -h, --help               Show this help and exit.
  --version                Show version and exit.
EOF
  exit 1
}

# --- Parse CLI ---
# Handle --version and --help first
for arg_scan in "$@"; do
  case "$arg_scan" in
    --version) echo "$(basename "$0") v$VERSION"; exit 0 ;;
    -h|--help) usage ;;
  esac
done

# Initialize PARSED_INSTANCE_NAMES with defaults if mode becomes install and -i is not given
# This will be refined after mode is determined.

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install)
      [[ -n "$OPERATION_MODE" && "$OPERATION_MODE" != "install" ]] && error_exit "Cannot specify both --install and --update."
      OPERATION_MODE="install"; shift ;;
    --update)
      [[ -n "$OPERATION_MODE" && "$OPERATION_MODE" != "update" ]] && error_exit "Cannot specify both --install and --update."
      OPERATION_MODE="update"; shift ;;
    -s|--source-dir)
      SOURCE_DIR="$2"; shift 2 ;;
    -c|--config)
      BASE_CONFIG="$2";  shift 2 ;;
    -i|--instances)
      INSTANCE_NAMES_STRING="$2" # Store the string, parse later
      shift 2 ;;
    --force-reconfigure)
      FORCE_INSTANCE_CONFIG=true; shift ;;
    -n|--dry-run)
      DRY_RUN=true; shift ;;
    -v|--verbose)
      VERBOSE=true; shift ;; # Placeholder for verbose
    *)
      error_exit "Unknown option '$1'. Use --help." ;;
  esac
done

# --- Validate Operation Mode ---
if [[ "$OPERATION_MODE" != "install" && "$OPERATION_MODE" != "update" ]]; then
    # This case should not be hit if logic above is correct, but as a safeguard:
    error_exit "An operation mode (--install or --update) must be specified. Use --help."
fi
info "Operation Mode: $OPERATION_MODE"

# --- Parse Instance Names ---
if [[ -n "$INSTANCE_NAMES_STRING" ]]; then
    IFS=',' read -r -a temp_arr <<< "$INSTANCE_NAMES_STRING"
    PARSED_INSTANCE_NAMES=() # Reset
    for x_inst in "${temp_arr[@]}"; do
        x_inst="${x_inst#"${x_inst%%[![:space:]]*}"}" # Trim leading whitespace
        x_inst="${x_inst%"${x_inst##*[![:space:]]}"}"  # Trim trailing whitespace
        if [[ -n "$x_inst" ]]; then
            if ! [[ "$x_inst" =~ ^[A-Za-z0-9._-]+$ ]]; then # Validate format early
                error_exit "Invalid instance name format in list: '$x_inst'"
            fi
            PARSED_INSTANCE_NAMES+=("$x_inst")
        fi
    done
else
    # If -i not given AND mode is "install", use defaults. For "update", empty is fine.
    if [[ "$OPERATION_MODE" == "install" ]]; then
        PARSED_INSTANCE_NAMES=("${DEFAULT_INSTANCES[@]}")
        info "No instances specified with -i, using defaults for --install: ${PARSED_INSTANCE_NAMES[*]}"
    fi
fi


main() {
  info "▶ Starting v2 deployment orchestrator v$VERSION (Mode: $OPERATION_MODE)"
  [[ "$DRY_RUN" == true ]] && warn "DRY RUN MODE ENABLED"

  # Check source directory and cd into it
  if [[ ! -d "$SOURCE_DIR" ]]; then
    error_exit "Source directory '$SOURCE_DIR' not found."
  fi
  info "Operating within source directory: $(cd "$SOURCE_DIR" && pwd)" # Show absolute path
  pushd "$SOURCE_DIR" > /dev/null

  # Ensure sub-scripts & config exist in the current directory (which is now SOURCE_DIR)
  for script_to_check in "${SCRIPTS_TO_CHECK[@]}"; do
    [[ -f "$script_to_check" ]] \
      || error_exit "Missing required file in '$SOURCE_DIR': $script_to_check"
  done
  if [[ ! -f "$BASE_CONFIG" ]]; then
      error_exit "Missing base config file in '$SOURCE_DIR': $BASE_CONFIG"
  fi
  info "All required scripts and base config file present."

  # Make scripts executable
  info "Ensuring deployment scripts are executable..."
  # Use a loop for better error message if one fails
  for script_to_chmod in "${SCRIPTS_TO_CHECK[@]}"; do
      run chmod +x "$script_to_chmod" \
        || error_exit "Failed to chmod script: $script_to_chmod"
  done

  # --- Perform Base Installation or Update ---
  if [[ "$OPERATION_MODE" == "install" || "$OPERATION_MODE" == "update" ]]; then
    info "▶ Running base installer/updater (install_base_exportcliv2.sh)..."
    run ./install_base_exportcliv2.sh -c "$BASE_CONFIG" ${DRY_RUN:+-n} \
      || error_exit "Base installer/updater (install_base_exportcliv2.sh) failed."
    info "Base installer/updater finished."
  fi

  # --- Configure Instances (only for --install mode) ---
  if [[ "$OPERATION_MODE" == "install" ]]; then
    if (( ${#PARSED_INSTANCE_NAMES[@]} > 0 )); then
      info "▶ Configuring instances: ${PARSED_INSTANCE_NAMES[*]}"
      local configure_opts=("-i") # Start with -i
      [[ "$DRY_RUN" == true ]] && configure_opts+=("-n")
      [[ "$FORCE_INSTANCE_CONFIG" == true ]] && configure_opts+=("--force")

      for inst_name in "${PARSED_INSTANCE_NAMES[@]}"; do
        info " • Configuring instance: $inst_name"
        # Run configure_instance.sh with dynamic options
        run ./configure_instance.sh "${configure_opts[@]}" "$inst_name" \
          || error_exit "configure_instance.sh failed for instance: $inst_name"
      done
      info "Instance configuration finished."
    else
      warn "No instances specified or defaulted for --install mode; skipping instance configuration."
    fi
  fi

  # --- Manage Services (Enable/Start for --install, Advise Restart for --update) ---
  if [[ "$OPERATION_MODE" == "install" ]]; then
    info "▶ Setting up services for configured instances..."
    # Bitmover
    info " • Setting up Bitmover service"
    run ./manage_services.sh ${DRY_RUN:+-n} --enable || warn "Enable bitmover.service failed"
    run ./manage_services.sh ${DRY_RUN:+-n} --start  || warn "Start bitmover.service failed"
    run ./manage_services.sh ${DRY_RUN:+-n} --status || warn "Status bitmover.service failed"
    # Instances
    if (( ${#PARSED_INSTANCE_NAMES[@]} > 0 )); then
        for inst_name in "${PARSED_INSTANCE_NAMES[@]}"; do
            info " • Setting up services for exportcliv2 instance '$inst_name'"
            run ./manage_services.sh ${DRY_RUN:+-n} -i "$inst_name" --enable || warn "Enable services for $inst_name failed"
            run ./manage_services.sh ${DRY_RUN:+-n} -i "$inst_name" --start  || warn "Start services for $inst_name failed"
            run ./manage_services.sh ${DRY_RUN:+-n} -i "$inst_name" --status || warn "Status check for $inst_name failed"
        done
    fi
    info "Service setup finished."
  elif [[ "$OPERATION_MODE" == "update" ]]; then
    info "▶ Update performed. Services may need restarting."
    info "  To restart Bitmover: sudo ./manage_services.sh ${DRY_RUN:+-n} --restart"
    info "  To restart an instance: sudo ./manage_services.sh ${DRY_RUN:+-n} -i <INSTANCE_NAME> --restart"
    info "  Consider running status checks: sudo ./manage_services.sh ${DRY_RUN:+-n} --status (for bitmover)"
    info "                                sudo ./manage_services.sh ${DRY_RUN:+-n} -i <INSTANCE_NAME> --status"
  fi

  popd > /dev/null # Return to original directory
  info "✅ Orchestration Mode '$OPERATION_MODE' complete."
}

main "$@"