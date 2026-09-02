"""Tests for configuration helpers."""

import yaml

from castrel_proxy.core.config import Config


def test_get_yolo_enabled_defaults_to_false(isolated_config_dir):
    """Missing yolo config should default to disabled."""
    config_file = isolated_config_dir / "config.yaml"
    config_file.write_text(
        yaml.safe_dump(
            {
                "server_url": "https://server.example.com",
                "verification_code": "code-123",
                "client_id": "client-123",
                "workspace_id": "workspace-123",
            }
        ),
        encoding="utf-8",
    )

    config = Config(config_dir=isolated_config_dir)

    assert config.get_yolo_enabled() is False


def test_save_preserves_yolo_setting(isolated_config_dir):
    """Saving pair config should not drop the yolo toggle."""
    config_file = isolated_config_dir / "config.yaml"
    config_file.write_text(
        yaml.safe_dump(
            {
                "server_url": "https://old.example.com",
                "verification_code": "old-code",
                "client_id": "old-client",
                "workspace_id": "old-workspace",
                "yolo": True,
            }
        ),
        encoding="utf-8",
    )

    config = Config(config_dir=isolated_config_dir)
    config.save(
        server_url="https://new.example.com",
        verification_code="new-code",
        client_id="new-client",
        workspace_id="new-workspace",
    )

    saved_config = yaml.safe_load(config_file.read_text(encoding="utf-8"))

    assert saved_config["yolo"] is True
    assert config.get_yolo_enabled() is True


def test_get_filesystem_roots_reads_config_list(isolated_config_dir):
    """filesystem_roots should be loaded from config.yaml when present."""
    config_file = isolated_config_dir / "config.yaml"
    config_file.write_text(
        yaml.safe_dump(
            {
                "server_url": "https://server.example.com",
                "verification_code": "code-123",
                "client_id": "client-123",
                "workspace_id": "workspace-123",
                "filesystem_roots": ["/tmp/workspace", "/Users/demo/project"],
            }
        ),
        encoding="utf-8",
    )

    config = Config(config_dir=isolated_config_dir)

    assert config.get_filesystem_roots() == ["/tmp/workspace", "/Users/demo/project"]
