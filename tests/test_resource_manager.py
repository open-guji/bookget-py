# Tests for ResourceManager - checkpoint/resume and download resilience

import asyncio
import json
import pytest
import pytest_asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

pytestmark = pytest.mark.asyncio(loop_scope="function")

from bookget.config import Config, DownloadConfig
from bookget.core.resource_manager import ResourceManager
from bookget.models.book import BookMetadata, Resource, ResourceType, DownloadTask


@pytest.fixture
def tmp_output(tmp_path):
    """Create a temporary output directory."""
    output = tmp_path / "downloads"
    output.mkdir()
    return output


@pytest.fixture
def config(tmp_output):
    """Create a test config."""
    cfg = Config()
    cfg.storage.output_root = tmp_output
    cfg.download.concurrent_downloads = 2
    cfg.download.retry_attempts = 1
    cfg.download.request_delay = 0  # no delay in tests
    cfg.download.min_image_size = 10
    return cfg


@pytest.fixture
def manager(config):
    return ResourceManager(config)


class TestCheckpointResumeState:
    """Test download state save/load/remove."""

    def test_save_and_load_state(self, manager, tmp_path):
        dest_dir = tmp_path / "book1"
        dest_dir.mkdir()
        state = {
            "book_id": "test:123",
            "images_done": ["img001.jpg", "img002.jpg"],
            "images_failed": ["img003.jpg"],
        }
        manager._save_state(dest_dir, state)

        loaded = manager._load_state(dest_dir)
        assert loaded is not None
        assert loaded["book_id"] == "test:123"
        assert len(loaded["images_done"]) == 2
        assert "img003.jpg" in loaded["images_failed"]

    def test_load_nonexistent_state(self, manager, tmp_path):
        assert manager._load_state(tmp_path / "nonexistent") is None

    def test_remove_state(self, manager, tmp_path):
        dest_dir = tmp_path / "book2"
        dest_dir.mkdir()
        manager._save_state(dest_dir, {"test": True})
        assert manager._state_path(dest_dir).exists()

        manager._remove_state(dest_dir)
        assert not manager._state_path(dest_dir).exists()

    def test_remove_nonexistent_state(self, manager, tmp_path):
        # Should not raise
        manager._remove_state(tmp_path / "no_such_dir")


class TestSkipExistingFiles:
    """Test that already-downloaded files are skipped."""

    @pytest.mark.asyncio
    async def test_skip_existing_images(self, manager, tmp_path):
        """Images already on disk should be skipped without network requests."""
        img_dir = tmp_path / "images"
        img_dir.mkdir()

        # Create a fake existing image (>= min_image_size bytes)
        existing = img_dir / "0001.jpg"
        existing.write_bytes(b"x" * 100)

        resource = Resource(
            url="http://example.com/img1.jpg",
            resource_type=ResourceType.IMAGE,
            order=1,
            filename="0001.jpg",
        )

        task = DownloadTask(
            book_id="test",
            url="http://example.com",
            output_dir=str(tmp_path),
        )
        task.resources = [resource]
        task.total_resources = 1

        adapter = MagicMock()
        adapter.get_headers.return_value = {}

        # Mock the downloader so we can verify it's NOT called
        manager.image_downloader.download_with_retry = AsyncMock()

        await manager._download_images(task, adapter, img_dir)

        # The downloader should NOT have been called (file was skipped)
        manager.image_downloader.download_with_retry.assert_not_called()
        assert task.downloaded_count == 1
        assert resource.downloaded is True


class TestCheckpointDuringDownload:
    """Test checkpoint state is saved during downloads."""

    @pytest.mark.asyncio
    async def test_checkpoint_saved_on_failure(self, manager, tmp_path):
        """When some downloads fail, checkpoint should be saved."""
        img_dir = tmp_path / "images"
        img_dir.mkdir()

        resources = [
            Resource(url=f"http://example.com/img{i}.jpg",
                     resource_type=ResourceType.IMAGE, order=i,
                     filename=f"{i:04d}.jpg")
            for i in range(1, 4)
        ]

        task = DownloadTask(
            book_id="test",
            url="http://example.com",
            output_dir=str(tmp_path),
        )
        task.resources = resources
        task.total_resources = 3

        adapter = MagicMock()
        adapter.get_headers.return_value = {}

        # Simulate: first succeeds, second fails, third succeeds
        call_count = 0

        async def mock_download(resource, output_path, headers):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                return False  # Simulate failure
            # Write a fake file
            output_path.write_bytes(b"x" * 100)
            return True

        manager.image_downloader.download_with_retry = AsyncMock(side_effect=mock_download)

        await manager._download_images(task, adapter, img_dir)

        assert task.downloaded_count == 2
        assert task.failed_count == 1

        # Checkpoint should be saved because there was a failure
        state = manager._load_state(tmp_path)
        assert state is not None
        assert len(state["images_failed"]) == 1

    @pytest.mark.asyncio
    async def test_checkpoint_removed_on_success(self, manager, tmp_path):
        """When all downloads succeed, checkpoint should be removed."""
        img_dir = tmp_path / "images"
        img_dir.mkdir()

        resources = [
            Resource(url="http://example.com/img1.jpg",
                     resource_type=ResourceType.IMAGE, order=1,
                     filename="0001.jpg")
        ]

        task = DownloadTask(
            book_id="test",
            url="http://example.com",
            output_dir=str(tmp_path),
        )
        task.resources = resources
        task.total_resources = 1

        adapter = MagicMock()
        adapter.get_headers.return_value = {}

        async def mock_download(resource, output_path, headers):
            output_path.write_bytes(b"x" * 100)
            return True

        manager.image_downloader.download_with_retry = AsyncMock(side_effect=mock_download)

        await manager._download_images(task, adapter, img_dir)

        assert task.downloaded_count == 1
        assert task.failed_count == 0

        # Checkpoint should be removed (all succeeded)
        assert manager._load_state(tmp_path) is None


class TestTextSkip:
    """Test that text download is skipped when structured.json exists."""

    @pytest.mark.asyncio
    async def test_skip_existing_text(self, manager, tmp_path):
        """Text download should be skipped if structured.json already exists."""
        # Create existing text output
        text_dir = tmp_path / "text"
        text_dir.mkdir(parents=True)
        (text_dir / "structured.json").write_text('{"test": true}', encoding="utf-8")

        # Mock adapter
        adapter = MagicMock()
        adapter.site_name = "test"
        adapter.site_id = "test"
        adapter.supports_text = True
        adapter.extract_book_id.return_value = "book1"
        adapter.get_metadata = AsyncMock(return_value=BookMetadata(title="Test"))
        adapter.get_image_list = AsyncMock(return_value=[])
        adapter.get_structured_text = AsyncMock()
        adapter.close = AsyncMock()

        with patch("bookget.core.resource_manager.get_adapter", return_value=adapter):
            task = await manager.download(
                url="http://example.com/test",
                output_dir=tmp_path,
                include_images=False,
                include_text=True,
            )

        # get_structured_text should NOT be called (skipped)
        adapter.get_structured_text.assert_not_called()
