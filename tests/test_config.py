# Tests for configuration management

import json
import os
import pytest
from pathlib import Path

from bookget.config import Config, DownloadConfig, StorageConfig


class TestDownloadConfig:
    """Tests for DownloadConfig defaults."""

    def test_defaults(self):
        cfg = DownloadConfig()
        assert cfg.concurrent_downloads == 4
        assert cfg.retry_attempts == 3
        assert cfg.retry_delay == 1.0
        assert cfg.timeout == 30.0
        assert cfg.request_delay == 0.5
        assert cfg.min_image_size == 1024

    def test_custom_values(self):
        cfg = DownloadConfig(concurrent_downloads=8, retry_attempts=5)
        assert cfg.concurrent_downloads == 8
        assert cfg.retry_attempts == 5


class TestStorageConfig:
    """Tests for StorageConfig path coercion."""

    def test_defaults_are_paths(self):
        cfg = StorageConfig()
        assert isinstance(cfg.output_root, Path)
        assert isinstance(cfg.cache_dir, Path)
        assert isinstance(cfg.temp_dir, Path)

    def test_string_coerced_to_path(self):
        cfg = StorageConfig(output_root="/tmp/out", cache_dir="/tmp/cache", temp_dir="/tmp/temp")
        assert isinstance(cfg.output_root, Path)
        assert cfg.output_root == Path("/tmp/out")


class TestConfig:
    """Tests for Config loading and directory creation."""

    def test_default_config(self):
        cfg = Config()
        assert isinstance(cfg.download, DownloadConfig)
        assert isinstance(cfg.storage, StorageConfig)
        assert cfg.debug is False
        assert "Accept" in cfg.default_headers

    def test_from_file_nonexistent(self, tmp_path):
        cfg = Config.from_file(tmp_path / "nonexistent.json")
        # Should return defaults
        assert cfg.download.concurrent_downloads == 4
        assert cfg.debug is False

    def test_from_file_valid(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({
            "download": {"concurrent_downloads": 16, "retry_attempts": 5},
            "storage": {"output_root": str(tmp_path / "output")},
            "debug": True,
        }), encoding="utf-8")

        cfg = Config.from_file(config_file)
        assert cfg.download.concurrent_downloads == 16
        assert cfg.download.retry_attempts == 5
        assert cfg.debug is True
        assert cfg.storage.output_root == tmp_path / "output"

    def test_from_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GUJI_OUTPUT_DIR", str(tmp_path / "env_out"))
        monkeypatch.setenv("GUJI_CONCURRENT_DOWNLOADS", "12")
        monkeypatch.setenv("GUJI_DEBUG", "1")

        cfg = Config.from_env()
        assert cfg.storage.output_root == tmp_path / "env_out"
        assert cfg.download.concurrent_downloads == 12
        assert cfg.debug is True

    def test_from_env_no_vars(self, monkeypatch):
        monkeypatch.delenv("GUJI_OUTPUT_DIR", raising=False)
        monkeypatch.delenv("GUJI_CONCURRENT_DOWNLOADS", raising=False)
        monkeypatch.delenv("GUJI_DEBUG", raising=False)

        cfg = Config.from_env()
        assert cfg.download.concurrent_downloads == 4
        assert cfg.debug is False

    def test_ensure_dirs(self, tmp_path):
        cfg = Config()
        cfg.storage.output_root = tmp_path / "out"
        cfg.storage.cache_dir = tmp_path / "cache"
        cfg.storage.temp_dir = tmp_path / "temp"

        cfg.ensure_dirs()

        assert (tmp_path / "out").is_dir()
        assert (tmp_path / "cache").is_dir()
        assert (tmp_path / "temp").is_dir()

    def test_ensure_dirs_idempotent(self, tmp_path):
        cfg = Config()
        cfg.storage.output_root = tmp_path / "out"
        cfg.storage.cache_dir = tmp_path / "cache"
        cfg.storage.temp_dir = tmp_path / "temp"

        cfg.ensure_dirs()
        cfg.ensure_dirs()  # second call should not raise

        assert (tmp_path / "out").is_dir()
