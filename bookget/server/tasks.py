"""TaskManager — wraps ResourceManager for concurrent HTTP-driven downloads."""
import asyncio
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import Config
from ..core.resource_manager import ResourceManager
from ..models.manifest import DownloadManifest
from ..adapters.registry import AdapterRegistry
from .sse import EventBus


@dataclass
class TaskInfo:
    task_id: str
    url: str
    output_dir: str
    status: str = "pending"          # pending | running | completed | failed | cancelled
    asyncio_task: Any = field(default=None, repr=False)
    manifest: DownloadManifest | None = None
    error: str | None = None


class TaskManager:
    """
    Manages active download tasks and exposes methods for the HTTP API.
    All methods are coroutines safe to call from aiohttp handlers.
    """

    def __init__(self, config: Config, bus: EventBus):
        self.config = config
        self.bus = bus
        self._tasks: dict[str, TaskInfo] = {}

    # ── Public API ──────────────────────────────────────────────────────────

    async def discover(
        self, url: str, output_dir: str | None, depth: int = 1, index_id: str = ""
    ) -> dict:
        """Discover book structure and return manifest as dict."""
        manager = ResourceManager(self.config)
        try:
            manifest = await manager.discover(
                url=url,
                output_dir=Path(output_dir) if output_dir else None,
                depth=depth,
                index_id=index_id,
            )
            return manifest.to_dict()
        finally:
            await manager.close()

    async def expand_node(
        self, url: str, output_dir: str, node_id: str
    ) -> dict:
        """Expand a manifest node and return updated manifest as dict."""
        manager = ResourceManager(self.config)
        try:
            manifest = await manager.expand_manifest_node(
                url=url,
                output_dir=Path(output_dir),
                node_id=node_id,
            )
            return manifest.to_dict()
        finally:
            await manager.close()

    def start_download(
        self,
        url: str,
        output_dir: str,
        node_ids: list[str] | None = None,
        concurrency: int = 1,
        index_id: str = "",
    ) -> str:
        """
        Start an incremental download task asynchronously.
        Returns task_id immediately; progress is pushed via EventBus.
        """
        task_id = str(uuid.uuid4())[:8]
        info = TaskInfo(task_id=task_id, url=url, output_dir=output_dir)
        self._tasks[task_id] = info

        info.asyncio_task = asyncio.create_task(
            self._run_download(task_id, url, output_dir, node_ids, concurrency, index_id)
        )
        return task_id

    async def cancel(self, task_id: str) -> bool:
        info = self._tasks.get(task_id)
        if not info:
            return False
        if info.asyncio_task and not info.asyncio_task.done():
            info.asyncio_task.cancel()
            info.status = "cancelled"
            self.bus.publish("task_error", {"taskId": task_id, "message": "已取消"})
            return True
        return False

    async def delete_nodes(self, task_id: str, node_ids: list[str]) -> bool:
        """Delete downloaded nodes from manifest on disk."""
        info = self._tasks.get(task_id)
        if not info or not info.manifest:
            return False
        manager = ResourceManager(self.config)
        try:
            for node_id in node_ids:
                node = info.manifest.find_node(node_id)
                if node:
                    from ..models.manifest import NodeStatus
                    node.status = NodeStatus.PENDING
            manager._save_hierarchical_manifests(info.manifest, Path(info.output_dir))
            return True
        finally:
            await manager.close()

    def get_task(self, task_id: str) -> TaskInfo | None:
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[dict]:
        return [
            {
                "task_id": t.task_id,
                "url": t.url,
                "output_dir": t.output_dir,
                "status": t.status,
                "manifest_progress": t.manifest.get_progress() if t.manifest else None,
                "error": t.error,
            }
            for t in self._tasks.values()
        ]

    def get_supported_sites(self) -> list[dict]:
        return AdapterRegistry.list_adapters()

    def check_url(self, url: str) -> dict:
        adapter = AdapterRegistry.get_for_url(url)
        if adapter:
            return {
                "supported": True,
                "site": {
                    "site_id": adapter.site_id,
                    "site_name": adapter.site_name,
                    "site_domains": list(adapter.site_domains),
                    "supports_text": adapter.supports_text,
                    "supports_images": getattr(adapter, "supports_images", True),
                },
            }
        return {"supported": False}

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _run_download(
        self,
        task_id: str,
        url: str,
        output_dir: str,
        node_ids: list[str] | None,
        concurrency: int,
        index_id: str,
    ):
        info = self._tasks[task_id]
        info.status = "running"
        manager = ResourceManager(self.config)

        def progress_cb(completed: int, total: int):
            self.bus.publish("progress", {
                "taskId": task_id,
                "completed": completed,
                "total": total,
                "percent": round(completed * 100 / total) if total > 0 else 0,
            })

        def status_cb(event_type: str, data: dict):
            if event_type in ("downloaded", "expanded"):
                # Re-emit manifest after each node
                if info.manifest:
                    self.bus.publish("manifest_updated", {
                        "taskId": task_id,
                        "manifest": info.manifest.to_dict(),
                    })

        try:
            manifest = await manager.download_incremental(
                url=url,
                output_dir=Path(output_dir),
                node_ids=node_ids,
                index_id=index_id,
                progress_callback=progress_cb,
                status_callback=status_cb,
                concurrency=max(1, concurrency),
            )
            info.manifest = manifest
            info.status = "completed"
            self.bus.publish("task_completed", {
                "taskId": task_id,
                "manifest": manifest.to_dict(),
            })
        except asyncio.CancelledError:
            info.status = "cancelled"
        except Exception as exc:
            info.status = "failed"
            info.error = str(exc)
            self.bus.publish("task_error", {
                "taskId": task_id,
                "message": str(exc),
            })
        finally:
            await manager.close()
