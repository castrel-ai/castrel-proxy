#!/usr/bin/env bash
set -euo pipefail

# Build castrel-proxy single-file binary with PyInstaller.
#
# Modes:
# - local: build in manylinux2014 container using host architecture (docker-only)
# - manylinux-x86_64: build in manylinux2014 x86_64 container (glibc 2.17 baseline)
# - manylinux-arm64: build in manylinux2014 aarch64 container (glibc 2.17 baseline)
# - macos-arm64 / macos-x86_64: not supported in Docker

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist"
WORK_DIR="${ROOT_DIR}/build"
ENTRY_FILE="${ROOT_DIR}/entry_point.py"
BINARY_NAME="castrel-proxy"
MODE="local"
CACHE_ROOT="${ROOT_DIR}/.cache/package_binary"
USE_CACHE="1"
CLEAN_CACHE="0"
PYTHON_VERSION="3.11.9"

usage() {
  cat <<'EOF'
Usage:
  scripts/package_binary.sh [--mode MODE] [--cache-dir DIR] [--no-cache] [--clean-cache]

Options:
  --mode MODE         Build mode:
                      local | manylinux-x86_64 | manylinux-arm64 | macos-arm64 | macos-x86_64
                      Default: local
  --cache-dir DIR     Cache root dir for docker build caches
                      Default: .cache/package_binary
  --no-cache          Disable pip/PyInstaller cache mounts
  --clean-cache       Remove cache dir before build
  --python-version V  CPython version used in manylinux builds (default: 3.11.9)
  -h, --help          Show this help message

Examples:
  scripts/package_binary.sh
  scripts/package_binary.sh --mode local
  scripts/package_binary.sh --mode local --cache-dir .cache/package_binary
  scripts/package_binary.sh --mode local --clean-cache
  scripts/package_binary.sh --mode manylinux-x86_64 --python-version 3.11.9
  scripts/package_binary.sh --mode manylinux-x86_64
EOF
}

log() {
  printf '[package] %s\n' "$1"
}

die() {
  printf '[package] ERROR: %s\n' "$1" >&2
  exit 1
}

ensure_command() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || die "Missing command: ${cmd}"
}

create_entry_file() {
  cat >"${ENTRY_FILE}" <<'EOF'
#!/usr/bin/env python
"""Entry point for PyInstaller - uses absolute imports."""
import os
import sys

if getattr(sys, "frozen", False):
    import certifi

    os.environ["SSL_CERT_FILE"] = certifi.where()
    os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()

from castrel_proxy.cli.commands import run

if __name__ == "__main__":
    run()
EOF
}

resolve_local_mode() {
  local arch
  arch="$(uname -m)"

  case "$arch" in
  x86_64 | amd64)
    echo "manylinux-x86_64"
    ;;
  arm64 | aarch64)
    echo "manylinux-arm64"
    ;;
  *)
    die "Unsupported host architecture for local docker mode: ${arch}"
    ;;
  esac
}

build_manylinux() {
  local image="$1"
  local cache_key="$2"
  ensure_command docker

  create_entry_file

  local shared_python_target="/tmp/python-shared"
  local shared_python_host="${WORK_DIR}/python-shared/${cache_key}/cpython-${PYTHON_VERSION}"

  mkdir -p "$shared_python_host"
  local shared_python_mount_arg=( -v "${shared_python_host}:${shared_python_target}" )

  local docker_cache_args=( )

  if [[ "$USE_CACHE" == "1" ]]; then
    local pip_cache="${CACHE_ROOT}/${cache_key}/pip"
    local pyinstaller_cache="${CACHE_ROOT}/${cache_key}/pyinstaller"
    mkdir -p "$pip_cache" "$pyinstaller_cache"
    docker_cache_args=(
      -e "PIP_CACHE_DIR=/tmp/pip-cache"
      -e "PYINSTALLER_CONFIG_DIR=/tmp/pyinstaller-cache"
      -v "${pip_cache}:/tmp/pip-cache"
      -v "${pyinstaller_cache}:/tmp/pyinstaller-cache"
    )
  fi

  log "Building in container: ${image}"
  docker run --rm \
    -e "HOST_UID=$(id -u)" \
    -e "HOST_GID=$(id -g)" \
    ${docker_cache_args+"${docker_cache_args[@]}"} \
    "${shared_python_mount_arg[@]}" \
    -v "${ROOT_DIR}:/work" \
    -w /work \
    "${image}" \
    bash -lc "
      set -euo pipefail

      SHARED_ROOT='${shared_python_target}'
      SHARED_PY=\"\$SHARED_ROOT/bin/python3\"
      SHARED_PIP=\"\$SHARED_ROOT/bin/pip3\"
      PY_VER='${PYTHON_VERSION}'
      OPENSSL_VER='1.1.1w'
      OPENSSL_ROOT=\"\$SHARED_ROOT/openssl-\$OPENSSL_VER\"
      YUM_OPTS='--setopt=timeout=15 --setopt=retries=2'

      if ls /etc/yum.repos.d/*epel*.repo >/dev/null 2>&1; then
        YUM_OPTS=\"\$YUM_OPTS --disablerepo=epel --disablerepo=epel*\"
      fi

      configure_aliyun_yum() {
        if [[ -f /etc/yum.repos.d/CentOS-Base.repo ]]; then
          sed -i 's|^mirrorlist=|#mirrorlist=|g' /etc/yum.repos.d/CentOS-Base.repo || true
          sed -i 's|^#baseurl=http://mirror.centos.org|baseurl=http://mirrors.aliyun.com|g' /etc/yum.repos.d/CentOS-Base.repo || true
          sed -i 's|^#baseurl=https://mirror.centos.org|baseurl=https://mirrors.aliyun.com|g' /etc/yum.repos.d/CentOS-Base.repo || true
          sed -i 's|^baseurl=http://mirror.centos.org|baseurl=http://mirrors.aliyun.com|g' /etc/yum.repos.d/CentOS-Base.repo || true
          sed -i 's|^baseurl=https://mirror.centos.org|baseurl=https://mirrors.aliyun.com|g' /etc/yum.repos.d/CentOS-Base.repo || true
        fi

        if [[ -f /etc/yum.repos.d/CentOS-Vault.repo ]]; then
          sed -i 's|^mirrorlist=|#mirrorlist=|g' /etc/yum.repos.d/CentOS-Vault.repo || true
          sed -i 's|^#baseurl=http://vault.centos.org|baseurl=http://mirrors.aliyun.com/centos-vault|g' /etc/yum.repos.d/CentOS-Vault.repo || true
          sed -i 's|^#baseurl=https://vault.centos.org|baseurl=https://mirrors.aliyun.com/centos-vault|g' /etc/yum.repos.d/CentOS-Vault.repo || true
        fi
      }

      download_with_fallback() {
        local output=\"\$1\"
        shift

        local url
        for url in \"\$@\"; do
          if curl -fL --connect-timeout 10 --retry 2 --retry-delay 1 -o \"\$output\" \"\$url\"; then
            return 0
          fi
        done

        return 1
      }

      configure_aliyun_yum

      if [[ ! -f \"\$OPENSSL_ROOT/lib/libssl.so\" ]]; then
        echo '[package] Building OpenSSL for shared CPython...'
        yum \$YUM_OPTS install -y gcc make perl-core tar >/dev/null

        TMP_OSSL=\"/tmp/openssl-build-\$RANDOM\"
        mkdir -p \"\$TMP_OSSL\"
        cd \"\$TMP_OSSL\"
        download_with_fallback \"openssl-\$OPENSSL_VER.tar.gz\" \
          "https://mirrors.cloud.tencent.com/openssl/source/openssl-\$OPENSSL_VER.tar.gz" \
          "https://www.openssl.org/source/openssl-\$OPENSSL_VER.tar.gz" \
          \"https://github.com/openssl/openssl/releases/download/OpenSSL_1_1_1w/openssl-\$OPENSSL_VER.tar.gz\" || {
          echo '[package] ERROR: failed to download OpenSSL source tarball' >&2
          exit 1
        }
        tar -xf \"openssl-\$OPENSSL_VER.tar.gz\"
        cd \"openssl-\$OPENSSL_VER\"
        ./config --prefix=\"\$OPENSSL_ROOT\" --openssldir=\"\$OPENSSL_ROOT\" shared zlib >/dev/null
        make -j\"\$(nproc)\" >/dev/null
        make install_sw >/dev/null
      fi

      SHARED_OK=0
      if [[ -x \"\$SHARED_PY\" ]]; then
        SHARED_OK=\"\$(LD_LIBRARY_PATH=\"\$SHARED_ROOT/lib:\$OPENSSL_ROOT/lib:\${LD_LIBRARY_PATH:-}\" \\
          \"\$SHARED_PY\" - <<'PY' 2>/dev/null || echo 0
import sysconfig
import importlib.util

is_shared = str(sysconfig.get_config_var('Py_ENABLE_SHARED')) == '1'
has_ssl = importlib.util.find_spec('_ssl') is not None
print('1' if is_shared and has_ssl else '0')
PY
)\"
      fi

      if [[ \"\$SHARED_OK\" != \"1\" ]]; then
        echo '[package] Building shared CPython in manylinux container...'
        yum \$YUM_OPTS install -y gcc make tar xz bzip2-devel libffi-devel zlib-devel >/dev/null

        # Remove partial/broken Python cache before rebuild.
        rm -rf \"\$SHARED_ROOT/bin\" \"\$SHARED_ROOT/include\" \"\$SHARED_ROOT/lib\" || true

        TMP_BUILD=\"/tmp/cpython-build-\$RANDOM\"
        mkdir -p \"\$TMP_BUILD\"
        cd \"\$TMP_BUILD\"
        download_with_fallback \"Python-\$PY_VER.tgz\" \
          \"https://mirrors.aliyun.com/python-release/source/Python-\$PY_VER.tgz\" \
          "https://mirrors.huaweicloud.com/python/\$PY_VER/Python-\$PY_VER.tgz" \
          \"https://www.python.org/ftp/python/\$PY_VER/Python-\$PY_VER.tgz\" || {
          echo '[package] ERROR: failed to download Python source tarball' >&2
          exit 1
        }
        tar -xf \"Python-\$PY_VER.tgz\"
        cd \"Python-\$PY_VER\"
        CPPFLAGS=\"-I\$OPENSSL_ROOT/include\" \
        LDFLAGS=\"-L\$OPENSSL_ROOT/lib\" \
        PKG_CONFIG_PATH=\"\$OPENSSL_ROOT/lib/pkgconfig\" \
        ./configure \
          --prefix=\"\$SHARED_ROOT\" \
          --enable-shared \
          --with-ensurepip=install \
          --with-openssl=\"\$OPENSSL_ROOT\" \
          --with-openssl-rpath=auto >/dev/null
        make -j\"\$(nproc)\" >/dev/null
        make install >/dev/null
      fi

      export LD_LIBRARY_PATH=\"\$OPENSSL_ROOT/lib:\$SHARED_ROOT/lib:\${LD_LIBRARY_PATH:-}\"

      \"\$SHARED_PY\" - <<'PY'
import ssl
print(ssl.OPENSSL_VERSION)
PY

      \"\$SHARED_PY\" -V
      cd /work
      echo '[package] Installing project dependencies from /work...'
      \"\$SHARED_PIP\" install --upgrade pip
      \"\$SHARED_PIP\" install . pyinstaller
      \"\$SHARED_ROOT/bin/pyinstaller\" \
        --onefile \
        --name castrel-proxy \
        --paths src \
        --hidden-import castrel_proxy.data \
        --hidden-import castrel_proxy.cli.commands \
        --hidden-import typer \
        --hidden-import aiohttp \
        --hidden-import mcp \
        --hidden-import langchain_mcp_adapters \
        --hidden-import file_read_backwards \
        --hidden-import certifi \
        --collect-all castrel_proxy \
        --copy-metadata castrel-proxy \
        --collect-data certifi \
        --console \
        /work/entry_point.py
      chown -R "\${HOST_UID}:\${HOST_GID}" /work/dist /work/build || true
      "
}

while [[ $# -gt 0 ]]; do
  case "$1" in
  --mode)
    MODE="$2"
    shift 2
    ;;
  --cache-dir)
    CACHE_ROOT="$2"
    shift 2
    ;;
  --no-cache)
    USE_CACHE="0"
    shift
    ;;
  --clean-cache)
    CLEAN_CACHE="1"
    shift
    ;;
  --python-version)
    PYTHON_VERSION="$2"
    shift 2
    ;;
  -h | --help)
    usage
    exit 0
    ;;
  *)
    die "Unknown argument: $1"
    ;;
  esac
done

cd "${ROOT_DIR}"
mkdir -p "${DIST_DIR}" "${WORK_DIR}"
rm -f "${ENTRY_FILE}"

if [[ "$CLEAN_CACHE" == "1" ]]; then
  log "Cleaning cache directory: ${CACHE_ROOT}"
  rm -rf "${CACHE_ROOT}"
fi

case "$MODE" in
local)
  MODE="$(resolve_local_mode)"
  log "Resolved local mode to ${MODE}"
  if [[ "$MODE" == "manylinux-x86_64" ]]; then
    build_manylinux "quay.io/pypa/manylinux2014_x86_64" "manylinux-x86_64"
  else
    build_manylinux "quay.io/pypa/manylinux2014_aarch64" "manylinux-arm64"
  fi
  ;;
manylinux-x86_64)
  build_manylinux "quay.io/pypa/manylinux2014_x86_64" "manylinux-x86_64"
  ;;
manylinux-arm64)
  build_manylinux "quay.io/pypa/manylinux2014_aarch64" "manylinux-arm64"
  ;;
macos-arm64)
  die "Docker cannot produce native macOS binaries. Use GitHub Actions macOS runners (build-other job) for macos-arm64 artifacts."
  ;;
macos-x86_64)
  die "Docker cannot produce native macOS binaries. Use GitHub Actions macOS runners (build-other job) for macos-x86_64 artifacts."
  ;;
*)
  die "Unsupported mode: ${MODE}"
  ;;
esac

if [[ ! -f "${DIST_DIR}/${BINARY_NAME}" ]]; then
  die "Build finished but binary not found: ${DIST_DIR}/${BINARY_NAME}"
fi

chmod +x "${DIST_DIR}/${BINARY_NAME}"

if command -v shasum >/dev/null 2>&1; then
  shasum -a 256 "${DIST_DIR}/${BINARY_NAME}" >"${DIST_DIR}/${BINARY_NAME}.sha256"
elif command -v sha256sum >/dev/null 2>&1; then
  sha256sum "${DIST_DIR}/${BINARY_NAME}" >"${DIST_DIR}/${BINARY_NAME}.sha256"
fi

log "Build complete: ${DIST_DIR}/${BINARY_NAME}"
if [[ -f "${DIST_DIR}/${BINARY_NAME}.sha256" ]]; then
  log "Checksum: ${DIST_DIR}/${BINARY_NAME}.sha256"
fi
