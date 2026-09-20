"""TaskManager — wraps ResourceManager for concurrent HTTP-driven downloads."""
import asyncio
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import Config
from ..core.resource_manager import ResourceManager
from ..models.manifest import DownloadManifest
from ..adapters.registry import AdapterRegistry
from ..logger import logger
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

    async def search(
        self, site_id: str, query: str, limit: int = 20, offset: int = 0,
    ) -> dict:
        """Search for books on a specific site."""
        manager = ResourceManager(self.config)
        try:
            return await manager.search(site_id, query, limit, offset)
        finally:
            await manager.close()

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
        task_id: str | None = None,
    ) -> str:
        """
        Start an incremental download task asynchronously.
        Returns task_id immediately; progress is pushed via EventBus.

        `task_id` lets the caller supply its own id. The web UI keys its
        manifests and progress bars by the id it already used for discovery,
        so minting a fresh server-side id made every SSE event arrive under an
        id the UI had never seen: node statuses never refreshed, and each run
        added another progress bar that could not be matched to the old one.
        """
        task_id = task_id or str(uuid.uuid4())[:8]
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

    async def delete_nodes(
        self, task_id: str, node_ids: list[str], output_dir: str | None = None,
    ) -> dict:
        """Delete a node's downloaded files and reset it to PENDING.

        Two things used to be wrong here:
          * it only flipped the manifest status and **deleted no files at all**,
            yet still answered {"deleted": true} — a plain false success;
          * it required a live in-memory task, so deleting right after
            「发现结构」(no download started yet) just 404'd.

        Now the manifest is loaded from disk when the task isn't in memory, the
        files listed in each node's source_data are actually removed, and the
        caller gets the real count back.
        """
        from ..models.manifest import NodeStatus

        info = self._tasks.get(task_id)
        base_dir = Path(output_dir or (info.output_dir if info else "") or ".")

        manifest = info.manifest if info else None
        if manifest is None:
            # Fall back to the manifest on disk so delete works after a plain
            # discover, or after the server was restarted.
            manifest_path = base_dir / "manifest.json"
            if not manifest_path.is_file():
                return {"deleted": False, "error": "manifest not found",
                        "removed_files": 0}
            try:
                manifest = DownloadManifest.from_dict(
                    json.loads(manifest_path.read_text(encoding="utf-8")))
            except Exception as e:
                return {"deleted": False, "error": f"cannot read manifest: {e}",
                        "removed_files": 0}

        manager = ResourceManager(self.config)
        removed = 0
        missing_nodes: list[str] = []
        try:
            path_map = manager._build_node_path_map(manifest.root, base_dir)
            for node_id in node_ids:
                node = manifest.find_node(node_id)
                if node is None:
                    missing_nodes.append(node_id)
                    continue
                # Deleting a parent must also clear everything beneath it,
                # otherwise a volume's pages survive while it claims PENDING.
                for target in self._walk_nodes(node):
                    target_dir, _ = path_map.get(target.id, (base_dir, None))
                    removed += self._remove_node_files(target, Path(target_dir))
                    # DISCOVERED, not PENDING: get_downloadable_nodes() only
                    # picks up {DISCOVERED, FAILED, DOWNLOADING}, so resetting
                    # to PENDING ("children not yet expanded") left the node
                    # permanently un-redownloadable — the UI would report
                    # "0 downloadable" forever after a delete.
                    target.status = NodeStatus.DISCOVERED
                    target.downloaded_items = 0

            manager._save_hierarchical_manifests(manifest, base_dir)
            if info is not None:
                info.manifest = manifest
            # Tell the UI so the tree repaints without a manual re-discover.
            self.bus.publish("manifest_updated", {
                "taskId": task_id,
                "manifest": manifest.to_dict(),
            })
            return {
                "deleted": True,
                "removed_files": removed,
                "missing_nodes": missing_nodes,
            }
        finally:
            await manager.close()

    @staticmethod
    def _walk_nodes(node):
        """Yield `node` and every descendant, deepest first."""
        for child in (getattr(node, "children", None) or []):
            yield from TaskManager._walk_nodes(child)
        yield node

    @staticmethod
    def _remove_node_files(node, node_dir: Path) -> int:
        """Delete the files a node produced. Returns how many were removed."""
        removed = 0
        source = getattr(node, "source_data", None) or {}
        names = [
            item.get("filename")
            for item in (source.get("images") or [])
            if isinstance(item, dict) and item.get("filename")
        ]
        for name in names:
            target = node_dir / name
            try:
                if target.is_file():
                    target.unlink()
                    removed += 1
            except OSError as e:
                logger.warning(f"could not delete {target}: {e}")

        # Non-leaf nodes own a directory; drop it once it's empty.
        try:
            if (node_dir.is_dir() and node_dir.name
                    and not any(node_dir.iterdir())):
                node_dir.rmdir()
        except OSError:
            pass
        return removed

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
                    "supports_pdf": getattr(adapter, "supports_pdf", False),
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
            if event_type not in ("downloading", "downloaded", "expanded"):
                return
            # Prefer the LIVE manifest carried on the event. info.manifest is
            # only assigned after download_incremental() returns, so using it
            # here re-published the stale discovery-time copy and every volume
            # stayed "待下载" in the UI until the user hit 发现结构 again.
            live = data.get("manifest")
            manifest_obj = live if live is not None else info.manifest
            if manifest_obj is None:
                return
            # Keep the task's own copy current too, so /api/tasks reflects
            # in-flight state rather than lagging a whole run behind.
            if live is not None:
                info.manifest = live
            self.bus.publish("manifest_updated", {
                "taskId": task_id,
                "manifest": manifest_obj.to_dict(),
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
