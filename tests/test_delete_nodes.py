# Deleting downloaded nodes.
#
# The old implementation only flipped the manifest status and deleted NO
# files, while still answering {"deleted": true} — a plain false success. It
# also required a live in-memory task, so deleting straight after 发现结构
# (nothing downloaded yet) returned 404.

import asyncio
import json

import pytest

from bookget.config import Config
from bookget.models.manifest import NodeStatus
from bookget.server.sse import EventBus
from bookget.server.tasks import TaskManager


def _manifest_dict(tmp_path):
    return {
        "version": 1,
        "book_id": "bk1",
        "source_url": "https://example.test/bk1",
        "source_site": "test",
        "title": "Test Book",
        "metadata": {},
        "structure": {
            "id": "bk1",
            "title": "Test Book",
            "type": "root",
            "status": "completed",
            "children": [
                {
                    "id": "vol_1",
                    "title": "Volume 1",
                    "type": "volume",
                    "status": "completed",
                    "total_items": 2,
                    "downloaded_items": 2,
                    "source_data": {
                        "images": [
                            {"url": "u1", "filename": "v01_0001.jpg"},
                            {"url": "u2", "filename": "v01_0002.jpg"},
                        ]
                    },
                }
            ],
        },
    }


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps(_manifest_dict(tmp_path)), encoding="utf-8")
    for name in ("v01_0001.jpg", "v01_0002.jpg"):
        (tmp_path / name).write_bytes(b"\xff\xd8\xff" + b"x" * 100)
    return tmp_path


class TestDeleteActuallyRemovesFiles:
    def test_files_are_deleted(self, workspace):
        tm = TaskManager(Config(), EventBus())
        result = asyncio.run(
            tm.delete_nodes("bk1", ["vol_1"], output_dir=str(workspace)))

        assert result["deleted"] is True
        assert result["removed_files"] == 2, "files must actually be removed"
        assert not (workspace / "v01_0001.jpg").exists()
        assert not (workspace / "v01_0002.jpg").exists()

    def test_works_without_an_in_memory_task(self, workspace):
        # Deleting straight after 发现结构 used to 404.
        tm = TaskManager(Config(), EventBus())
        assert tm.get_task("bk1") is None
        result = asyncio.run(
            tm.delete_nodes("bk1", ["vol_1"], output_dir=str(workspace)))
        assert result["deleted"] is True

    def test_node_is_redownloadable_afterwards(self, workspace):
        # Resetting to PENDING made the node permanently un-downloadable,
        # because get_downloadable_nodes() only accepts
        # {DISCOVERED, FAILED, DOWNLOADING}.
        tm = TaskManager(Config(), EventBus())
        asyncio.run(tm.delete_nodes("bk1", ["vol_1"], output_dir=str(workspace)))

        saved = json.loads((workspace / "manifest.json").read_text(encoding="utf-8"))
        vol = saved["structure"]["children"][0]
        assert vol["status"] == NodeStatus.DISCOVERED.value

    def test_missing_manifest_reports_failure(self, tmp_path):
        tm = TaskManager(Config(), EventBus())
        result = asyncio.run(
            tm.delete_nodes("bk1", ["vol_1"], output_dir=str(tmp_path)))
        assert result["deleted"] is False
        assert result["removed_files"] == 0

    def test_unknown_node_is_reported(self, workspace):
        tm = TaskManager(Config(), EventBus())
        result = asyncio.run(
            tm.delete_nodes("bk1", ["nope"], output_dir=str(workspace)))
        assert result["missing_nodes"] == ["nope"]
        # A real file must not be collateral damage.
        assert (workspace / "v01_0001.jpg").exists()

    def test_publishes_manifest_update(self, workspace):
        bus = EventBus()
        q = bus.subscribe()
        tm = TaskManager(Config(), bus)
        asyncio.run(tm.delete_nodes("bk1", ["vol_1"], output_dir=str(workspace)))
        event = q.get_nowait()
        assert event["type"] == "manifest_updated"
        assert event["taskId"] == "bk1"
