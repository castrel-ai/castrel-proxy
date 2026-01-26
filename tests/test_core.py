"""Tests for core functionality"""

from castrel_proxy.core import get_client_id, get_machine_metadata


def test_get_client_id():
    """Test client ID generation"""
    client_id1 = get_client_id()
    client_id2 = get_client_id()

    # Should be consistent on same machine
    assert client_id1 == client_id2

    # Should be 16 characters
    assert len(client_id1) == 16

    # Should be hexadecimal
    assert all(c in "0123456789abcdef" for c in client_id1)


def test_get_machine_metadata():
    """Test machine metadata retrieval"""
    metadata = get_machine_metadata()

    # Should contain basic fields
    assert "hostname" in metadata
    assert metadata["hostname"] != "unknown"

    # Should have OS information
    assert "os" in metadata
    assert metadata["os"] in ["Windows", "Linux", "Darwin"]
