#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Keep in sync with the ARG default in Dockerfile.sandbox.
DEFAULT_BASE_IMAGE="sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter:v1.1.0"

VERSION=""
HUB=""
IMAGE_NAME="castrel-sandbox"
PLATFORMS="linux/amd64,linux/arm64"
DOCKERFILE="Dockerfile.sandbox"
BASE_IMAGE="${DEFAULT_BASE_IMAGE}"
PUSH_LATEST="1"
LATEST_ONLY="0"
LOAD="0"

usage() {
  cat <<EOF
Build and push the multi-arch sandbox image with Docker Buildx.

The sandbox image overlays the built-in skills on top of a dependency-complete
base image (see Dockerfile.sandbox). It is a separate image from the proxy.

Required:
  --hub <hub>           Docker Hub namespace/repository prefix, e.g. castrelai.
                        Required for push mode; optional with --load 1 (when
                        omitted, a bare local tag like castrel-sandbox:<v> is
                        produced to match a bare sandbox.image in config.yaml).

Optional:
  --version <v>         Image version tag, e.g. 0.0.1
  --image <name>        Image name (default: castrel-sandbox)
  --platforms <list>    Buildx platforms (default: linux/amd64,linux/arm64)
  --dockerfile <path>   Dockerfile path relative to open-castrel-proxy (default: Dockerfile.sandbox)
  --base-image <ref>    Base image passed as build arg BASE_IMAGE
                        (default: ${DEFAULT_BASE_IMAGE})
  --push-latest <0|1>   Also push :latest tag (default: 1)
  --latest-only <0|1>   Only push :latest tag (default: 0)
  --load <0|1>          Local mode: build single-arch and load into the local
                        docker image store instead of pushing (default: 0).
                        Forces a single host platform; --version optional;
                        --hub optional (produces a bare local tag).
  -h, --help            Show this help

Note:
  The base image must provide manifests for every target platform. If the base
  image is single-arch, narrow --platforms accordingly (e.g. linux/amd64).

Examples:
  # Local verify, bare tag matching a bare sandbox.image in ~/.castrel/config.yaml
  ./scripts/build_and_push_sandbox.sh --load 1 --version 0.0.1
  # -> loads castrel-sandbox:0.0.1 and castrel-sandbox:latest into local docker

  # Local verify with hub namespace (config.yaml uses castrelai/castrel-sandbox:latest)
  ./scripts/build_and_push_sandbox.sh --hub castrelai --load 1

  # Publish after local verify passes
  ./scripts/build_and_push_sandbox.sh --hub castrelai --latest-only 1
  ./scripts/build_and_push_sandbox.sh --version 0.0.1 --hub castrelai
  ./scripts/build_and_push_sandbox.sh --hub castrelai --platforms linux/amd64
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      VERSION="${2:-}"
      shift 2
      ;;
    --hub)
      HUB="${2:-}"
      shift 2
      ;;
    --image)
      IMAGE_NAME="${2:-}"
      shift 2
      ;;
    --platforms)
      PLATFORMS="${2:-}"
      shift 2
      ;;
    --dockerfile)
      DOCKERFILE="${2:-}"
      shift 2
      ;;
    --base-image)
      BASE_IMAGE="${2:-}"
      shift 2
      ;;
    --push-latest)
      PUSH_LATEST="${2:-}"
      shift 2
      ;;
    --latest-only)
      LATEST_ONLY="${2:-}"
      shift 2
      ;;
    --load)
      LOAD="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "${HUB}" && "${LOAD}" != "1" ]]; then
  echo "Error: --hub is required unless --load=1." >&2
  usage
  exit 2
fi

if [[ -z "${BASE_IMAGE}" ]]; then
  echo "Error: --base-image must not be empty." >&2
  exit 2
fi

if [[ "${PUSH_LATEST}" != "0" && "${PUSH_LATEST}" != "1" ]]; then
  echo "Error: --push-latest must be 0 or 1." >&2
  exit 2
fi

if [[ "${LATEST_ONLY}" != "0" && "${LATEST_ONLY}" != "1" ]]; then
  echo "Error: --latest-only must be 0 or 1." >&2
  exit 2
fi

if [[ "${LOAD}" != "0" && "${LOAD}" != "1" ]]; then
  echo "Error: --load must be 0 or 1." >&2
  exit 2
fi

if [[ "${LOAD}" == "1" && -z "${VERSION}" ]]; then
  LATEST_ONLY="1"
fi

if [[ "${LATEST_ONLY}" == "1" ]]; then
  PUSH_LATEST="1"
fi

if [[ "${LOAD}" == "0" && "${LATEST_ONLY}" == "0" && -z "${VERSION}" ]]; then
  echo "Error: --version is required unless --latest-only=1 or --load=1." >&2
  usage
  exit 2
fi

if [[ -n "${HUB}" ]]; then
  IMAGE_BASE="${HUB}/${IMAGE_NAME}"
else
  # Bare local tag (load mode only), matches a bare sandbox.image in config.yaml.
  IMAGE_BASE="${IMAGE_NAME}"
fi
LATEST_TAG="${IMAGE_BASE}:latest"
DOCKERFILE_PATH="${PROJECT_ROOT}/${DOCKERFILE}"

if [[ ! -f "${DOCKERFILE_PATH}" ]]; then
  echo "Error: Dockerfile not found: ${DOCKERFILE_PATH}" >&2
  exit 2
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker is not installed." >&2
  exit 2
fi

if ! docker buildx version >/dev/null 2>&1; then
  echo "Error: docker buildx is not available." >&2
  exit 2
fi

if ! docker info >/dev/null 2>&1; then
  echo "Error: docker daemon is not running or not accessible." >&2
  exit 2
fi

if [[ "${LOAD}" == "1" ]]; then
  if [[ "${PLATFORMS}" == *","* ]]; then
    HOST_PLATFORM="$(docker version -f '{{.Server.Os}}/{{.Server.Arch}}' 2>/dev/null || true)"
    PLATFORMS="${HOST_PLATFORM:-linux/amd64}"
    echo "Load mode: narrowing to single host platform ${PLATFORMS}"
  fi
  # Use the buildx builder bound to the active docker context (docker driver
  # supports --load). Falls back to the default builder.
  CURRENT_CONTEXT="$(docker context show 2>/dev/null || echo default)"
  docker buildx use "${CURRENT_CONTEXT}" >/dev/null 2>&1 \
    || docker buildx use default >/dev/null
  OUTPUT_FLAG="--load"
else
  if ! docker buildx inspect multiarch-builder >/dev/null 2>&1; then
    docker buildx create --name multiarch-builder --driver docker-container --use >/dev/null
  else
    docker buildx use multiarch-builder >/dev/null
  fi
  OUTPUT_FLAG="--push"
fi

TAGS=()
if [[ "${LATEST_ONLY}" == "0" ]]; then
  VERSION_TAG="${IMAGE_BASE}:${VERSION}"
  TAGS+=("-t" "${VERSION_TAG}")
fi
if [[ "${PUSH_LATEST}" == "1" ]]; then
  TAGS+=("-t" "${LATEST_TAG}")
fi

if [[ ${#TAGS[@]} -eq 0 ]]; then
  echo "Error: no tags configured to push." >&2
  exit 2
fi

if [[ "${LATEST_ONLY}" == "0" ]]; then
  echo "Target image: ${VERSION_TAG}"
fi
if [[ "${PUSH_LATEST}" == "1" ]]; then
  echo "Target image: ${LATEST_TAG}"
fi
echo "Platforms: ${PLATFORMS}"
echo "Dockerfile: ${DOCKERFILE_PATH}"
echo "BASE_IMAGE=${BASE_IMAGE}"
echo "Output: ${OUTPUT_FLAG}"

docker buildx build \
  --platform "${PLATFORMS}" \
  --file "${DOCKERFILE_PATH}" \
  --build-arg "BASE_IMAGE=${BASE_IMAGE}" \
  "${TAGS[@]}" \
  "${OUTPUT_FLAG}" \
  "${PROJECT_ROOT}"

echo "Done."
