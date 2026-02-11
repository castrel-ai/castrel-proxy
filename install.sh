#!/bin/bash
#
# One-liner install script for Castrel Proxy
# Usage: curl -fsSL https://raw.githubusercontent.com/stallone-ss/castrel-proxy/develop/install.sh | bash
#
# User install (no sudo): curl -fsSL ... | CASTREL_INSTALL_DIR=~/.local/bin bash
# Ensure ~/.local/bin is in your PATH.
#
# Supports: Ubuntu 20+, Debian 10+, CentOS 7+, macOS
#

set -e

REPO="castrel-ai/castrel-proxy"
BASE_URL="https://github.com/${REPO}"
INSTALL_DIR="${CASTREL_INSTALL_DIR:-/usr/local/bin}"
# Expand ~ to $HOME for user install (e.g. CASTREL_INSTALL_DIR=~/.local/bin)
INSTALL_DIR="${INSTALL_DIR/#\~/$HOME}"
BINARY_NAME="castrel-proxy"

# Colors for output (strip if not a terminal)
if [ -t 1 ]; then
  RED='\033[0;31m'
  GREEN='\033[0;32m'
  YELLOW='\033[1;33m'
  NC='\033[0m'
else
  RED='' GREEN='' YELLOW='' NC=''
fi

die() {
  echo -e "${RED}Error: $1${NC}" >&2
  exit 1
}

log() {
  echo -e "${GREEN}$1${NC}"
}

warn() {
  echo -e "${YELLOW}$1${NC}"
}

# Detect download tool (curl preferred, wget fallback)
need_download() {
  if command -v curl >/dev/null 2>&1; then
    echo "curl"
  elif command -v wget >/dev/null 2>&1; then
    echo "wget"
  else
    die "Neither curl nor wget found. Please install one of them."
  fi
}

# Download file (handles redirects)
download() {
  local url="$1"
  local output="$2"
  local dl_tool="$3"

  if [ "$dl_tool" = "curl" ]; then
    curl -fsSL -o "$output" "$url" || die "Failed to download $url"
  else
    wget -q -O "$output" "$url" || die "Failed to download $url"
  fi
}

# Compute SHA256 (try sha256sum, then shasum, then openssl)
compute_sha256() {
  local file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{print $1}'
  elif command -v openssl >/dev/null 2>&1; then
    openssl dgst -sha256 "$file" | awk '{print $NF}'
  else
    die "No SHA256 tool found (sha256sum, shasum, or openssl required)."
  fi
}

# Detect OS and architecture
detect_platform() {
  local os
  local arch

  case "$(uname -s)" in
    Darwin)
      os="macos"
      ;;
    Linux)
      os="linux"
      ;;
    *)
      die "Unsupported OS: $(uname -s)"
      ;;
  esac

  case "$(uname -m)" in
    x86_64|amd64)
      arch="x86_64"
      ;;
    aarch64|arm64)
      arch="arm64"
      ;;
    *)
      die "Unsupported architecture: $(uname -m)"
      ;;
  esac

  echo "${os}-${arch}"
}

# Get latest release info from GitHub API
get_latest_release() {
  local api_url="https://api.github.com/repos/${REPO}/releases/latest"
  local dl_tool="$1"

  if [ "$dl_tool" = "curl" ]; then
    curl -fsSL "$api_url" 2>/dev/null || die "Failed to fetch release info. Check network and https://github.com/${REPO}/releases"
  else
    wget -q -O - "$api_url" 2>/dev/null || die "Failed to fetch release info. Check network and https://github.com/${REPO}/releases"
  fi
}

# Parse JSON (minimal, no jq required) - get tag_name
parse_tag() {
  grep -o '"tag_name"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"\(v[^"]*\)"$/\1/'
}

main() {
  log "Castrel Proxy - One-click installer"
  echo ""

  local dl_tool
  dl_tool=$(need_download)

  local platform
  platform=$(detect_platform)
  log "Detected platform: $platform"

  local pkg_name="castrel-proxy-${platform}"
  local pkg_url="${BASE_URL}/releases/download/UNKNOWN/${pkg_name}"
  local sha_url="${pkg_url}.sha256"

  # Fetch latest release
  log "Fetching latest release..."
  local release_json
  release_json=$(get_latest_release "$dl_tool")
  local tag
  tag=$(echo "$release_json" | parse_tag)
  [ -z "$tag" ] && die "Could not determine latest release tag."

  log "Latest version: $tag"

  pkg_url="${BASE_URL}/releases/download/${tag}/${pkg_name}"
  sha_url="${pkg_url}.sha256"

  # Create temp dir
  local tmpdir
  tmpdir=$(mktemp -d 2>/dev/null || mktemp -d -t castrel-proxy)
  trap "rm -rf $tmpdir" EXIT

  # Download binary and checksum
  log "Downloading ${pkg_name}..."
  download "$pkg_url" "${tmpdir}/${pkg_name}" "$dl_tool"
  download "$sha_url" "${tmpdir}/${pkg_name}.sha256" "$dl_tool"

  # Verify checksum
  local expected_hash
  expected_hash=$(awk '{print $1}' "${tmpdir}/${pkg_name}.sha256")
  local actual_hash
  actual_hash=$(compute_sha256 "${tmpdir}/${pkg_name}")

  if [ "$expected_hash" != "$actual_hash" ]; then
    die "SHA256 verification failed. Expected: $expected_hash, got: $actual_hash"
  fi
  log "SHA256 checksum verified."

  # Install to target directory (create if needed for user install)
  local target_path="${INSTALL_DIR}/${BINARY_NAME}"
  if [ ! -d "$INSTALL_DIR" ]; then
    if mkdir -p "$INSTALL_DIR" 2>/dev/null; then
      :
    elif command -v sudo >/dev/null 2>&1; then
      sudo mkdir -p "$INSTALL_DIR" || die "Cannot create ${INSTALL_DIR}"
    else
      die "Directory ${INSTALL_DIR} does not exist and cannot be created."
    fi
  fi

  if [ -w "$INSTALL_DIR" ] 2>/dev/null; then
    mv "${tmpdir}/${pkg_name}" "$target_path"
  else
    warn "Need sudo to install to ${INSTALL_DIR}"
    if command -v sudo >/dev/null 2>&1; then
      sudo mv "${tmpdir}/${pkg_name}" "$target_path"
    else
      die "Cannot write to ${INSTALL_DIR} and sudo is not available."
    fi
  fi

  chmod +x "$target_path" 2>/dev/null || sudo chmod +x "$target_path"

  log "Installed successfully to $target_path"
  echo ""
  echo "Run: castrel-proxy --help"
  echo ""
}

main "$@"
