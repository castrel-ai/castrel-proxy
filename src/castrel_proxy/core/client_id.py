"""
Client Unique Identifier Generation Module

Generates stable client IDs based on machine characteristics (hostname + MAC address)
"""

import hashlib
import platform
import socket
import uuid
from typing import Dict


def get_client_id() -> str:
    """
    Generate unique client identifier based on machine characteristics

    Uses a combination of hostname and MAC address to generate a SHA256 hash,
    ensuring the same machine always generates the same ID.

    Returns:
        str: 16-character unique client identifier
    """
    # Get hostname
    hostname = socket.gethostname()

    # Get MAC address (as integer)
    mac = uuid.getnode()

    # Combine machine characteristics
    identifier = f"{hostname}:{mac}"

    # Generate SHA256 hash and take first 16 characters
    hash_value = hashlib.sha256(identifier.encode()).hexdigest()[:16]

    return hash_value


def get_machine_metadata() -> Dict[str, str]:
    """
    Get current machine metadata information for sending to server

    Returns:
        dict: Dictionary containing detailed machine information
    """
    metadata = {}

    try:
        # Get machine name
        metadata["hostname"] = socket.gethostname()
    except Exception:
        metadata["hostname"] = "unknown"

    try:
        # Get MAC address
        mac = uuid.getnode()
        mac_address = ":".join(["{:02x}".format((mac >> elements) & 0xFF) for elements in range(0, 48, 8)][::-1])
        metadata["mac_address"] = mac_address
    except Exception:
        pass

    try:
        # Get operating system information
        metadata["os"] = platform.system()  # Windows, Linux, Darwin
        metadata["os_version"] = platform.version()
        metadata["os_release"] = platform.release()
    except Exception:
        pass

    try:
        # Get machine architecture
        metadata["architecture"] = platform.machine()  # x86_64, arm64, etc.
    except Exception:
        pass

    try:
        # Get Python version
        metadata["python_version"] = platform.python_version()
    except Exception:
        pass

    try:
        # Get processor information
        metadata["processor"] = platform.processor()
    except Exception:
        pass

    try:
        # Get platform information
        metadata["platform"] = platform.platform()
    except Exception:
        pass

    return metadata
