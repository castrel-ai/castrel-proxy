#!/bin/sh
# Container entrypoint for the bundled proxy image.
#
# Runs as root to reconcile Docker-out-of-Docker socket permissions, then drops
# privileges to the unprivileged "castrel" user before launching the proxy.
#
# Why this is needed: the proxy launches sibling sandbox containers through the
# mounted /var/run/docker.sock. That socket's group differs per host (root:root
# on Docker Desktop for macOS, root:docker with a host-specific GID on Linux),
# so the group cannot be baked in at build time. We detect the socket's GID at
# runtime and add "castrel" to the matching group so the daemon is reachable as
# the unprivileged user.
set -eu

TARGET_USER="castrel"
DOCKER_SOCK="${DOCKER_HOST_SOCK:-/var/run/docker.sock}"
SANDBOX_WORKSPACE_ROOT="${CASTREL_SANDBOX_WORKSPACE_ROOT:-/home/${TARGET_USER}/.castrel/sandbox}"
SKILLS_DIR="${CASTREL_SKILLS_DIR:-/home/${TARGET_USER}/.castrel/skills}"

prepare_owned_directory() {
    directory="$1"
    case "${directory}" in
        ""|"/")
            echo "Invalid writable directory: ${directory}" >&2
            exit 1
            ;;
    esac
    mkdir -p "${directory}"
    chown "${TARGET_USER}:${TARGET_USER}" "${directory}"
    chmod 0750 "${directory}"
}

if [ -S "${DOCKER_SOCK}" ]; then
    SOCK_GID="$(stat -c '%g' "${DOCKER_SOCK}" 2>/dev/null || echo '')"
    if [ -n "${SOCK_GID}" ]; then
        if [ "${SOCK_GID}" = "0" ]; then
            # Docker Desktop (macOS/Windows): socket is root:root. Grant the
            # unprivileged user access via the root group.
            usermod -aG root "${TARGET_USER}" 2>/dev/null || true
        else
            # Linux host: ensure a group with the socket's GID exists, then add
            # the user to it.
            if ! getent group "${SOCK_GID}" >/dev/null 2>&1; then
                groupadd -g "${SOCK_GID}" dockerhost 2>/dev/null || true
            fi
            usermod -aG "${SOCK_GID}" "${TARGET_USER}" 2>/dev/null || true
        fi
    fi
fi

# Docker creates missing bind-mount sources as root:root. Give the proxy user
# ownership of its writable shared directories without making them
# world-writable.
prepare_owned_directory "${SANDBOX_WORKSPACE_ROOT}"
prepare_owned_directory "${SKILLS_DIR}"

# Drop privileges to the unprivileged user, reloading supplementary groups so
# the docker socket group membership above takes effect. HOME/USER are exported
# explicitly because the container starts as root and setpriv does not reset the
# environment, otherwise the proxy would resolve ~ to /root.
export HOME="/home/${TARGET_USER}"
export USER="${TARGET_USER}"
exec setpriv --reuid "${TARGET_USER}" --regid "${TARGET_USER}" --init-groups \
    castrel-proxy "$@"
