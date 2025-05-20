#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# -----------------------------------------------------------------------------
# Full Deployment & Instance Setup Orchestrator
# -----------------------------------------------------------------------------
# Supports:
#   • Custom archive names (.tar, .tar.gz, .tgz)
#   • Dry-run mode (--dry-run)
#   • Verbose extraction (--verbose)
#   • Dynamic instance lists (via CLI)
#   • Preflight checks for required commands
#   • Automatic fallback if the extracted dir isn’t named after the archive
# -----------------------------------------------------------------------------

# --- Metadata ---
VERSION="1.0.1" # Incremented for help text fix

# --- Logging Helpers ---
_ts()        { date -u +'%Y-%m-%dT%H:%M:%SZ'; }
info()       { echo >&2 "$(_ts) [INFO]  $*"; }
warn()       { echo >&2 "$(_ts) [WARN]  $*"; }
error_exit() { echo >&2 "$(_ts) [ERROR] $*"; exit 1; }

# --- Defaults (can be overridden by CLI) ---
ARCHIVE_NAME="app-install.tar.gz"
BASE_INSTALL_CONFIG_FILE="install-app.conf"
# Define default instances as an array
DEFAULT_INSTANCE_NAMES_ARRAY=(AAA BBB CCC)
# Create a comma-separated string from the array for the help message
IFS_ORIGINAL="$IFS" # Save original IFS
IFS=, # Set IFS to comma for joining
DEFAULT_INSTANCES_STRING="${DEFAULT_INSTANCE_NAMES_ARRAY[*]}" # Join with comma
IFS="$IFS_ORIGINAL" # Restore original IFS

INSTANCE_NAMES=("${DEFAULT_INSTANCE_NAMES_ARRAY[@]}") # Initialize INSTANCE_NAMES with the default array

SCRIPTS_TO_CHMOD=(install_base_exportcliv2.sh configure_instance.sh manage_services.sh)

DRY_RUN=false
VERBOSE_TAR=false

# --- Preflight: ensure commands exist ---
preflight() {
  local cmds=(tar bash chmod pushd popd) # These are for the orchestrator itself
  # Sub-scripts (install_base, configure_instance, manage_services) have their own preflight checks
  for c in "${cmds[@]}"; do
    command -v "$c" &>/dev/null \
      || error_exit "Required command '$c' for orchestrator not found in PATH"
  done
  info "Orchestrator preflight checks passed."
}

# --- Run or echo (for dry-run) ---
run() {
  if [[ "$DRY_RUN" == true ]]; then
    echo >&2 "$(_ts) [DRY-RUN] $*"
    return 0
  fi
  info "Executing: $*"
  # Temporarily disable exit on error for the command itself to capture its status
  set +e
  "$@"
  local ec=$? # Capture exit code
  set -e # Re-enable exit on error

  if (( ec != 0 )); then
    # Warn if the command failed, but don't exit here;
    # let the caller decide if it's a fatal error (e.g. using || error_exit)
    warn "Command exited with status $ec: $*"
  fi
  return $ec # Return the original exit code
}

# --- Infer directory from archive name ---
infer_dir() {
  local base
  base=$(basename "$1")
  base="${base%.tar.gz}"
  base="${base%.tgz}"
  base="${base%.tar}"
  echo "$base"
}

# --- Locate extracted top‐level directory if infer fails ---
find_single_dir() {
  # This function attempts to find if there's exactly one directory
  # in the current location. Used as a fallback if infer_dir's guess is wrong.
  local dirs_found=()
  local item
  for item in */; do # Iterate over directories in current path
    # Check if item is a directory and not a symlink to a directory (optional, but safer)
    # For simplicity, this just lists all directory-like entries.
    [[ -d "$item" ]] && dirs_found+=("$item")
  done

  if (( ${#dirs_found[@]} == 1 )); then
    echo "${dirs_found[0]%/}" # Return the single directory name, stripping trailing slash
  else
    return 1 # Indicate failure (more than one dir, or no dirs)
  fi
}

# --- Usage ---
usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Automates the full deployment and setup of the application suite,
including base installation and configuration of specified instances.

Options:
  -a, --archive FILE       Archive file to extract (e.g., app-install.tar.gz).
                           Default: ${ARCHIVE_NAME}
  -c, --config FILE        Configuration file for the base installer, expected inside the archive.
                           Default: ${BASE_INSTALL_CONFIG_FILE}
  -i, --instances LIST     Comma-separated list of instance names to create and manage.
                           Example: "T1,T2,PROD_SITE_A"
                           Default: ${DEFAULT_INSTANCES_STRING}
  -n, --dry-run            Show commands that would be executed, without actually running them.
                           Useful for verifying actions before applying system changes.
  -v, --verbose            Enable verbose output during tar extraction.
  -h, --help               Show this help message and exit.
  --version                Show script version and exit.
EOF
  exit 1 # Default exit for usage error, help exits with 0
}

# --- Parse CLI ---
# Handle --version and --help first
for arg in "$@"; do
  if [[ "$arg" == "--version" ]]; then
    echo "$(basename "$0") version $VERSION"; exit 0;
  elif [[ "$arg" == "-h" || "$arg" == "--help" ]]; then
    usage; exit 0; # Call usage then exit 0 for help
  fi
done

while [[ $# -gt 0 ]]; do
  case "$1" in
    -a|--archive)   ARCHIVE_NAME="$2"; shift 2 ;;
    -c|--config)    BASE_INSTALL_CONFIG_FILE="$2"; shift 2 ;;
    -i|--instances)
      if [[ -z "${2:-}" ]]; then error_exit "Missing argument for $1"; fi
      IFS=',' read -r -a raw <<< "$2"
      INSTANCE_NAMES=()
      for inst in "${raw[@]}"; do
        # trim spaces
        inst="${inst#"${inst%%[![:space:]]*}"}"
        inst="${inst%"${inst##*[![:space:]]}"}"
        [[ -n "$inst" ]] && INSTANCE_NAMES+=("$inst")
      done
      shift 2
      ;;
    -n|--dry-run)   DRY_RUN=true; shift ;;
    -v|--verbose)   VERBOSE_TAR=true; shift ;;
    # Help and version already handled, just shift if encountered again
    -h|--help|--version) shift ;;
    *)              error_exit "Unknown option: '$1'. Use -h for help." ;;
  esac
done

main() {
  info "▶ $(basename "$0") v$VERSION starting full deployment..."

  # Root check
  (( EUID == 0 )) || error_exit "This script must be run as root or via sudo."
  info "Root privileges confirmed."

  preflight # Check for tar, chmod, pushd, popd

  # Archive check
  [[ -f "$ARCHIVE_NAME" ]] \
    || error_exit "Deployment archive '$ARCHIVE_NAME' not found in current directory ('$(pwd)')."
  info "Deployment archive '$ARCHIVE_NAME' found."

  # Extract
  local top_level_extracted_dir
  top_level_extracted_dir=$(infer_dir "$ARCHIVE_NAME")
  local tar_extraction_options="xf" # x=extract, f=file
  $VERBOSE_TAR && tar_extraction_options="v${tar_extraction_options}" # v=verbose

  if [[ "$ARCHIVE_NAME" == *.gz || "$ARCHIVE_NAME" == *.tgz ]]; then
    tar_extraction_options="z${tar_extraction_options}" # z=gzip
  fi

  info "Extracting '$ARCHIVE_NAME' (using options: $tar_extraction_options), expecting content in a directory like '$top_level_extracted_dir/'..."
  # Run the tar command; if it fails, error_exit due to set -e or explicit check
  run tar "$tar_extraction_options" "$ARCHIVE_NAME" \
    || error_exit "Failed to extract archive '$ARCHIVE_NAME'."
  info "Archive extraction completed."

  # Determine where to cd: use inferred name or fallback to finding a single directory
  if [[ ! -d "$top_level_extracted_dir" ]]; then
    warn "Inferred directory '$top_level_extracted_dir' not found. Attempting to find a single extracted directory..."
    local found_dir
    found_dir=$(find_single_dir) \
      || error_exit "Could not uniquely determine the extracted top-level directory. Found multiple or no directories at the extraction root."
    top_level_extracted_dir="$found_dir"
    info "Automatically detected extracted directory as '$top_level_extracted_dir/'."
  fi

  pushd "$top_level_extracted_dir" > /dev/null # Suppress pushd output
  info "➤ Changed current directory to '$(pwd)' (inside extracted archive)."

  # Set execute permissions on deployment scripts
  info "Setting +x on deployment scripts: ${SCRIPTS_TO_CHMOD[*]}"
  run chmod +x "${SCRIPTS_TO_CHMOD[@]}" \
    || error_exit "Failed to set execute permissions on one or more scripts: ${SCRIPTS_TO_CHMOD[*]}"

  # Verify base installation config file exists inside the extracted directory
  [[ -f "$BASE_INSTALL_CONFIG_FILE" ]] \
    || error_exit "Base installation configuration file '$BASE_INSTALL_CONFIG_FILE' not found in '$(pwd)'."
  info "Base installation configuration file '$BASE_INSTALL_CONFIG_FILE' found."

  # Run base installer
  info "▶ Running base installer ('./install_base_exportcliv2.sh')..."
  run ./install_base_exportcliv2.sh -c "$BASE_INSTALL_CONFIG_FILE" \
    || error_exit "The base installation script (install_base_exportcliv2.sh) failed."
  info "Base installation completed."

  # Configure instances
  if (( ${#INSTANCE_NAMES[@]} > 0 )); then
    info "▶ Configuring exportcliv2 instances: ${INSTANCE_NAMES[*]}"
    local inst_name # Declare loop variable
    for inst_name in "${INSTANCE_NAMES[@]}"; do
      info "  • Configuring instance '$inst_name'..."
      run ./configure_instance.sh -i "$inst_name" --force \
        || error_exit "Configuration script (configure_instance.sh) failed for instance '$inst_name'."
      info "  • Instance '$inst_name' configured."
    done
    info "All specified exportcliv2 instances configured."
  else
    warn "No instance names provided via -i or defaults; skipping instance configuration."
  fi

  # Manage Bitmover Service
  info "▶ Managing 'bitmover.service' (enable, start, status)..."
  run ./manage_services.sh --enable || warn "Attempt to enable 'bitmover.service' reported an issue."
  run ./manage_services.sh --start  || warn "Attempt to start 'bitmover.service' reported an issue."
  run ./manage_services.sh --status || warn "Attempt to get status for 'bitmover.service' reported an issue."
  info "Bitmover service management actions attempted."

  # Manage exportcliv2 Instances
  if (( ${#INSTANCE_NAMES[@]} > 0 )); then
    info "▶ Managing exportcliv2 instances (enable, start, status)..."
    for inst_name in "${INSTANCE_NAMES[@]}"; do
      info "  • Managing instance '$inst_name'..."
      run ./manage_services.sh -i "$inst_name" --enable || warn "Enable reported an issue for instance '$inst_name'."
      run ./manage_services.sh -i "$inst_name" --start  || warn "Start reported an issue for instance '$inst_name'."
      run ./manage_services.sh -i "$inst_name" --status || warn "Status reported an issue for instance '$inst_name'."
      info "  • Management actions attempted for instance '$inst_name'."
    done
    info "All specified exportcliv2 instances have had management actions attempted."
  else
    info "No instances to manage for exportcliv2."
  fi

  popd > /dev/null # Return to original directory
  info "Returned to original directory '$(pwd)'."

  info "✅ Deployment orchestrator finished."
  info "Review the output above for any [WARN] or [ERROR] messages."
  info "Use './${top_level_extracted_dir}/manage_services.sh' for further service management."
}

# --- Script Entry Point ---
main "$@" # Pass all script arguments to main, though main doesn't currently use them directly