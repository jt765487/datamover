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
VERSION="1.0.0"

# --- Logging Helpers ---
_ts()        { date -u +'%Y-%m-%dT%H:%M:%SZ'; }
info()       { echo >&2 "$(_ts) [INFO]  $*"; }
warn()       { echo >&2 "$(_ts) [WARN]  $*"; }
error_exit() { echo >&2 "$(_ts) [ERROR] $*"; exit 1; }

# --- Defaults (can be overridden by CLI) ---
ARCHIVE_NAME="app-install.tar.gz"
BASE_INSTALL_CONFIG_FILE="install-app.conf"
INSTANCE_NAMES=(AAA BBB CCC)
SCRIPTS_TO_CHMOD=(install_base_exportcliv2.sh configure_instance.sh manage_services.sh)

DRY_RUN=false
VERBOSE_TAR=false

# --- Preflight: ensure commands exist ---
preflight() {
  local cmds=(tar bash chmod pushd popd)
  for c in "${cmds[@]}"; do
    command -v "$c" &>/dev/null \
      || error_exit "Required command '$c' not found in PATH"
  done
  info "Preflight checks passed."
}

# --- Run or echo (for dry-run) ---
run() {
  if [[ "$DRY_RUN" == true ]]; then
    echo >&2 "$(_ts) [DRY-RUN] $*"
    return 0
  fi
  info "Executing: $*"
  set +e
  "$@"
  local ec=$?
  set -e
  if (( ec != 0 )); then
    warn "Command exited $ec: $*"
  fi
  return $ec
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
  local dirs=(*/)
  if (( ${#dirs[@]} == 1 )); then
    echo "${dirs[0]%/}"
  else
    return 1
  fi
}

# --- Usage ---
usage() {
  cat <<EOF
Usage: $(basename "$0") [OPTIONS]

Options:
  -a, --archive FILE       Archive to extract (default: $ARCHIVE_NAME)
  -c, --config FILE        Base install config (default: $BASE_INSTALL_CONFIG_FILE)
  -i, --instances LIST     Comma-separated instance names (default: ${INSTANCE_NAMES[*]})
  -n, --dry-run            Show commands instead of executing
  -v, --verbose            Enable verbose tar output
  -h, --help               Show this help and exit
EOF
  exit 1
}

# --- Parse CLI ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    -a|--archive)   ARCHIVE_NAME="$2"; shift 2 ;;
    -c|--config)    BASE_INSTALL_CONFIG_FILE="$2"; shift 2 ;;
    -i|--instances) IFS=, read -r -a INSTANCE_NAMES <<< "$2"; shift 2 ;;
    -n|--dry-run)   DRY_RUN=true; shift ;;
    -v|--verbose)   VERBOSE_TAR=true; shift ;;
    -h|--help)      usage ;;
    *)              error_exit "Unknown option: $1" ;;
  esac
done

main() {
  info "▶ deploy_all.sh v$VERSION starting…"

  # Root check
  (( EUID == 0 )) || error_exit "Please run as root or via sudo"

  preflight

  # Archive check
  [[ -f "$ARCHIVE_NAME" ]] \
    || error_exit "Archive '$ARCHIVE_NAME' not found in $(pwd)"

  # Extract
  local topdir
  topdir=$(infer_dir "$ARCHIVE_NAME")
  local tar_opts="xf"
  $VERBOSE_TAR && tar_opts="v${tar_opts}"
  if [[ "$ARCHIVE_NAME" == *.gz || "$ARCHIVE_NAME" == *.tgz ]]; then
    tar_opts="z${tar_opts}"
  fi

  info "Extracting '$ARCHIVE_NAME' → expect '$topdir/' (tar options: $tar_opts)…"
  run tar "$tar_opts" "$ARCHIVE_NAME"

  # Determine where to cd
  if [[ -d "$topdir" ]]; then
    :
  elif dir=$(find_single_dir); then
    topdir="$dir"
    info "Inferred extracted directory '$topdir/'"
  else
    error_exit "Could not find a single top-level directory after extraction"
  fi

  pushd "$topdir" > /dev/null
  info "➤ CWD now $(pwd)"

  # chmod scripts
  info "Setting +x on: ${SCRIPTS_TO_CHMOD[*]}"
  run chmod +x "${SCRIPTS_TO_CHMOD[@]}"

  # verify base config
  [[ -f "$BASE_INSTALL_CONFIG_FILE" ]] \
    || error_exit "Config '$BASE_INSTALL_CONFIG_FILE' missing in $(pwd)"

  # base install
  info "▶ Running base installer"
  run ./install_base_exportcliv2.sh -c "$BASE_INSTALL_CONFIG_FILE"

  # instances
  info "▶ Configuring instances: ${INSTANCE_NAMES[*]}"
  for inst in "${INSTANCE_NAMES[@]}"; do
    info " • $inst"
    run ./configure_instance.sh -i "$inst" --force
  done

  # bitmover
  info "▶ Managing bitmover.service"
  run ./manage_services.sh --enable
  run ./manage_services.sh --start
  run ./manage_services.sh --status

  # exportcliv2 instances
  info "▶ Managing exportcliv2 instances"
  for inst in "${INSTANCE_NAMES[@]}"; do
    info " • $inst"
    run ./manage_services.sh -i "$inst" --enable
    run ./manage_services.sh -i "$inst" --start
    run ./manage_services.sh -i "$inst" --status
  done

  popd > /dev/null
  info "✅ Deployment complete. Review logs above for any [WARN] or [ERROR]."
}

main "$@"
