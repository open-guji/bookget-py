# Resource Manager - Main orchestrator for downloading resources

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Callable
import json

from ..config import Config
from ..models.book import BookMetadata, Resource, DownloadTask, ResourceType
from ..adapters.registry import get_adapter, AdapterRegistry
from ..adapters.base import BaseSiteAdapter
from ..models.manifest import (
    DownloadManifest, ManifestNode, NodeStatus, NodeType, ResourceKind,
)
from ..downloaders.base import ImageDownloader, TextDownloader
from ..storage.file_storage import FileStorage
from ..logger import logger
from ..exceptions import AdapterNotFoundError, DownloadError


class ResourceManager:
    """
    Main orchestrator for downloading and managing ancient book resources.
    
    Usage:
        manager = ResourceManager(config)
        result = await manager.download("https://guji.nlc.cn/...")
    """
    
    def __init__(self, config: Config = None):
        self.config = config or Config()
        self.storage = FileStorage(self.config.storage.output_root)
        self.image_downloader = ImageDownloader(self.config.download)
        self.text_downloader = TextDownloader(self.config.download)
    
    async def download(
        self,
        url: str,
        output_dir: Path = None,
        include_images: bool = True,
        include_text: bool = True,
        include_metadata: bool = True,
        index_id: str = "",
        progress_callback: Callable[[int, int], None] = None
    ) -> DownloadTask:
        """
        Download all resources from a URL.
        
        Args:
            url: The book URL to download from
            output_dir: Optional custom output directory
            include_images: Whether to download images
            include_text: Whether to download text content
            include_metadata: Whether to save metadata
            progress_callback: Optional callback (downloaded, total)
            
        Returns:
            DownloadTask with results
        """
        # Find adapter for URL
        adapter = get_adapter(url, self.config)
        if not adapter:
            raise AdapterNotFoundError(url)
        
        try:
            # Extract book ID
            book_id = adapter.extract_book_id(url)
            logger.info(f"Downloading: {adapter.site_name} - {book_id}")
            
            # Create download task
            task = DownloadTask(
                book_id=book_id,
                url=url,
                output_dir=str(output_dir) if output_dir else str(self.storage.get_book_dir(book_id)),
                include_images=include_images,
                include_text=include_text,
                include_metadata=include_metadata,
                index_id=index_id,
            )
            
            # Get metadata
            task.metadata = await adapter.get_metadata(book_id, index_id=index_id)
            task.metadata.source_url = url
            task.metadata.source_site = adapter.site_id
            
            # Determine effective output directory
            dest_dir = Path(task.output_dir)
            dest_dir.mkdir(parents=True, exist_ok=True)
            
            if include_metadata:
                metadata_path = dest_dir / "metadata.json"
                with open(metadata_path, "w", encoding="utf-8") as f:
                    json.dump(task.metadata.to_dict(), f, ensure_ascii=False, indent=2)
                logger.info(f"Saved metadata to: {metadata_path}")
            
            # Get and download images
            if include_images:
                task.resources = await adapter.get_image_list(book_id)
                task.total_resources = len(task.resources)
                logger.info(f"Found {task.total_resources} images")
                
                # Create images subdir
                img_dir = dest_dir / "images"
                img_dir.mkdir(exist_ok=True)
                
                await self._download_images(
                    task, adapter, img_dir, progress_callback
                )
            
            # Get and save text (raw API response + optional conversions)
            if include_text and adapter.supports_text:
                # Skip if text already downloaded (check both new and legacy names)
                text_dir = dest_dir / "text"
                raw_json = text_dir / f"raw.{adapter.site_id}.json"
                legacy_json = text_dir / "structured.json"
                if (raw_json.exists() and raw_json.stat().st_size > 0) or \
                   (legacy_json.exists() and legacy_json.stat().st_size > 0):
                    logger.info(f"Text already downloaded, skipping")
                    return task

                import inspect
                sig = inspect.signature(adapter.get_structured_text)
                kwargs: dict = {"index_id": index_id}
                if "progress_callback" in sig.parameters:
                    kwargs["progress_callback"] = progress_callback
                structured = await adapter.get_structured_text(book_id, **kwargs)
                if structured:
                    text_dir = dest_dir / "text"
                    text_dir.mkdir(exist_ok=True)

                    # 1. Save raw API response (naming: raw.<source_id>.json)
                    raw_path = text_dir / f"raw.{adapter.site_id}.json"
                    raw_path.write_text(
                        json.dumps(structured.to_dict(), ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    logger.info(f"Saved raw text data to: {raw_path}")
                else:
                    # Fallback: try old get_text_content for adapters without structured support
                    text_content = await adapter.get_text_content(book_id)
                    if text_content:
                        text_dir = dest_dir / "text"
                        text_dir.mkdir(exist_ok=True)
                        text_path = text_dir / "content.txt"
                        text_path.write_text(text_content, encoding="utf-8")
                        logger.info(f"Saved text content to: {text_path}")
            
            return task
            
        finally:
            await adapter.close()
    
    async def _download_images(
        self,
        task: DownloadTask,
        adapter: BaseSiteAdapter,
        img_dir: Path,
        progress_callback: Callable[[int, int], None] = None
    ):
        """Download all images for a task with rate limiting, skip, and checkpoint."""
        headers = adapter.get_headers()
        request_delay = self.config.download.request_delay
        min_image_size = self.config.download.min_image_size
        dest_dir = Path(task.output_dir)

        # Load checkpoint state
        state = self._load_state(dest_dir) or {
            "book_id": task.book_id,
            "url": task.url,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "metadata_done": True,
            "text_done": False,
            "images_total": task.total_resources,
            "images_done": [],
            "images_failed": [],
        }
        done_set = set(state.get("images_done", []))
        failed_set = set(state.get("images_failed", []))

        async def download_one(resource: Resource) -> bool:
            filename = resource.get_filename()
            output_path = img_dir / filename

            # Skip if already marked done in checkpoint
            if filename in done_set:
                task.downloaded_count += 1
                resource.downloaded = True
                resource.local_path = str(output_path)
                if progress_callback:
                    progress_callback(task.downloaded_count, task.total_resources)
                return True

            # Skip already-downloaded files on disk
            if output_path.exists() and output_path.stat().st_size >= min_image_size:
                logger.debug(f"Skipping existing: {filename}")
                task.downloaded_count += 1
                resource.downloaded = True
                resource.local_path = str(output_path)
                done_set.add(filename)
                if progress_callback:
                    progress_callback(task.downloaded_count, task.total_resources)
                return True

            # Rate limiting: delay before each download
            if request_delay > 0:
                await asyncio.sleep(request_delay)

            try:
                success = await self.image_downloader.download_with_retry(
                    resource, output_path, headers
                )
                if success:
                    task.downloaded_count += 1
                    done_set.add(filename)
                else:
                    task.failed_count += 1
                    failed_set.add(filename)

                if progress_callback:
                    progress_callback(task.downloaded_count, task.total_resources)

                # Periodically save checkpoint (every 10 files)
                if (task.downloaded_count + task.failed_count) % 10 == 0:
                    state["images_done"] = list(done_set)
                    state["images_failed"] = list(failed_set)
                    self._save_state(dest_dir, state)

                return success
            except Exception as e:
                logger.error(f"Failed to download {resource.url}: {e}")
                task.failed_count += 1
                failed_set.add(filename)
                return False

        # Download concurrently with semaphore limiting
        await asyncio.gather(*[download_one(r) for r in task.resources])

        # Final state update
        if task.failed_count == 0:
            # All done — remove checkpoint
            self._remove_state(dest_dir)
        else:
            # Save final state for retry
            state["images_done"] = list(done_set)
            state["images_failed"] = list(failed_set)
            self._save_state(dest_dir, state)

        logger.info(
            f"Download complete: {task.downloaded_count}/{task.total_resources} "
            f"({task.failed_count} failed)"
        )
    
    # --- Checkpoint / Resume support ---

    def _state_path(self, dest_dir: Path) -> Path:
        return dest_dir / ".download_state.json"

    def _load_state(self, dest_dir: Path) -> Optional[dict]:
        path = self._state_path(dest_dir)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def _save_state(self, dest_dir: Path, state: dict):
        path = self._state_path(dest_dir)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _remove_state(self, dest_dir: Path):
        path = self._state_path(dest_dir)
        if path.exists():
            path.unlink()

    async def get_metadata(self, url: str, index_id: str = "") -> BookMetadata:
        """
        Get metadata only, without downloading resources.
        
        Args:
            url: The book URL
            
        Returns:
            BookMetadata object
        """
        adapter = get_adapter(url, self.config)
        if not adapter:
            raise AdapterNotFoundError(url)
        
        try:
            book_id = adapter.extract_book_id(url)
            metadata = await adapter.get_metadata(book_id, index_id=index_id)
            metadata.source_url = url
            metadata.source_site = adapter.site_id
            return metadata
        finally:
            await adapter.close()
    
    def list_supported_sites(self) -> List[dict]:
        """List all supported sites."""
        return AdapterRegistry.list_adapters()
    
    def is_url_supported(self, url: str) -> bool:
        """Check if a URL is supported."""
        return AdapterRegistry.get_for_url(url) is not None

    # ------------------------------------------------------------------
    # Incremental discovery & download (new API)
    # ------------------------------------------------------------------

    MANIFEST_FILENAME = "manifest.json"

    async def discover(
        self,
        url: str,
        output_dir: Path = None,
        depth: int = 1,
        index_id: str = "",
        progress_callback: Callable = None,
    ) -> DownloadManifest:
        """Phase 1: Discover book structure and create/update manifest.

        If a manifest already exists with discovery_complete=True,
        returns it as-is.
        """
        adapter = get_adapter(url, self.config)
        if not adapter:
            raise AdapterNotFoundError(url)

        try:
            book_id = adapter.extract_book_id(url)
            dest_dir = output_dir or Path(
                self.storage.get_book_dir(book_id))
            dest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = dest_dir / self.MANIFEST_FILENAME

            # Load existing manifest
            existing = DownloadManifest.load(manifest_path)
            if existing and existing.discovery_complete:
                logger.info("Manifest already complete, returning cached")
                return existing

            # Discover structure via adapter
            manifest = await adapter.discover_structure(
                book_id, index_id=index_id, depth=depth,
                progress_callback=progress_callback,
            )

            # Save metadata.json alongside
            metadata = await adapter.get_metadata(book_id, index_id=index_id)
            metadata.source_url = url
            metadata.source_site = adapter.site_id
            metadata_path = dest_dir / "metadata.json"
            metadata_path.write_text(
                json.dumps(metadata.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            # Merge download statuses from old manifest
            if existing:
                self._merge_manifest_statuses(existing.root, manifest.root)

            self._save_hierarchical_manifests(manifest, dest_dir)
            logger.info(
                f"Manifest saved: {manifest_path} "
                f"({manifest.get_progress()['total']} nodes)")
            return manifest

        finally:
            await adapter.close()

    async def expand_manifest_node(
        self,
        url: str,
        output_dir: Path,
        node_id: str,
        depth: int = 1,
        progress_callback: Callable = None,
    ) -> DownloadManifest:
        """Expand a specific node in an existing manifest."""
        adapter = get_adapter(url, self.config)
        if not adapter:
            raise AdapterNotFoundError(url)

        try:
            book_id = adapter.extract_book_id(url)
            manifest_path = output_dir / self.MANIFEST_FILENAME
            manifest = DownloadManifest.load(manifest_path)
            if not manifest:
                raise DownloadError(
                    f"No manifest found at {manifest_path}. "
                    "Run 'discover' first.")

            await adapter.expand_node(
                book_id, manifest, node_id, depth, progress_callback)

            self._save_hierarchical_manifests(manifest, output_dir)
            return manifest

        finally:
            await adapter.close()

    @staticmethod
    def _safe_dir_name(node_id: str, title: str) -> str:
        """Build a safe directory name from title only."""
        safe_title = re.sub(r'[<>:"/\\|?*]', '_', title).strip()[:60]
        return safe_title

    def _build_node_path_map(
        self, root: ManifestNode, base_dir: Path,
    ) -> dict:
        """Build a mapping {node_id: (node_dir, parent_node)} for all nodes.

        Leaf nodes go directly in their parent directory (Method A).
        Non-leaf nodes get their own subdirectory.
        """
        path_map: dict = {}  # node_id -> (directory Path, parent ManifestNode or None)

        def walk(node: ManifestNode, node_dir: Path, parent: Optional[ManifestNode]):
            path_map[node.id] = (node_dir, parent)
            for child in node.children:
                if child.children:
                    # Non-leaf: gets its own subdirectory
                    child_dir = node_dir / self._safe_dir_name(child.id, child.title)
                else:
                    # Leaf: goes directly in current node's directory
                    child_dir = node_dir
                walk(child, child_dir, node)

        walk(root, base_dir, None)
        return path_map

    def _save_hierarchical_manifests(
        self, manifest: DownloadManifest, base_dir: Path,
    ):
        """Save per-directory manifest.json files for all non-leaf nodes.

        Each directory gets a manifest whose structure only contains the
        direct children of that directory's node.
        """
        def walk(node: ManifestNode, node_dir: Path):
            if not node.children:
                return

            # Create a manifest scoped to this node's directory
            sub_manifest = DownloadManifest(
                version=manifest.version,
                book_id=manifest.book_id,
                source_url=manifest.source_url,
                source_site=manifest.source_site,
                title=node.title,
                metadata=manifest.metadata,
                created_at=manifest.created_at,
                updated_at=manifest.updated_at,
            )
            sub_manifest.root = node

            manifest_path = node_dir / self.MANIFEST_FILENAME
            node_dir.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(sub_manifest.to_shallow_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            for child in node.children:
                if child.children:
                    child_dir = node_dir / self._safe_dir_name(child.id, child.title)
                    walk(child, child_dir)

        walk(manifest.root, base_dir)

    async def download_incremental(
        self,
        url: str,
        output_dir: Path = None,
        node_ids: List[str] = None,
        include_images: bool = True,
        include_text: bool = True,
        index_id: str = "",
        progress_callback: Callable[[int, int], None] = None,
        status_callback: Callable[[str, dict], None] = None,
        concurrency: int = 1,
    ) -> DownloadManifest:
        """Phase 2: Download content node by node with manifest checkpointing.

        If *node_ids* is given, only download those nodes (and their
        leaf descendants).  Otherwise download all discovered-but-not-
        completed nodes.

        Files are stored hierarchically mirroring the manifest tree.
        Each directory contains its own manifest.json (shallow, direct
        children only) plus chapter JSON files for its leaf children.

        Args:
            concurrency: Number of nodes to download in parallel (default 1).
                         Set >1 for concurrent downloads.

        Saves manifest after each node completes (checkpoint).
        """
        adapter = get_adapter(url, self.config)
        if not adapter:
            raise AdapterNotFoundError(url)

        try:
            book_id = adapter.extract_book_id(url)
            dest_dir = output_dir or Path(
                self.storage.get_book_dir(book_id))
            dest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = dest_dir / self.MANIFEST_FILENAME

            # Load or auto-discover manifest
            manifest = DownloadManifest.load(manifest_path)
            if not manifest:
                logger.info("No manifest found, auto-discovering…")
                manifest = await adapter.discover_structure(
                    book_id, index_id=index_id, depth=-1)
                self._save_hierarchical_manifests(manifest, dest_dir)

            # Expand any pending (not-yet-expanded) nodes before collecting
            if node_ids:
                for nid in node_ids:
                    node = manifest.find_node(nid)
                    if node and node.expandable:
                        logger.info(f"Auto-expanding node {nid} ({node.title})…")
                        if status_callback:
                            status_callback('expanding', {
                                'node_id': nid,
                                'title': node.title,
                            })
                        await adapter.expand_node(book_id, manifest, nid, depth=-1)
                        # Save after each expand so progress is visible immediately
                        self._save_hierarchical_manifests(manifest, dest_dir)
                        if status_callback:
                            status_callback('expanded', {
                                'node_id': nid,
                                'title': node.title,
                            })

            # Collect nodes to download
            nodes = manifest.get_downloadable_nodes(node_ids)
            if not nodes:
                logger.info("No nodes to download")
                return manifest

            # Build path map: node_id -> (directory, parent_node)
            path_map = self._build_node_path_map(manifest.root, dest_dir)

            total = len(nodes)
            completed = 0
            lock = asyncio.Lock()
            semaphore = asyncio.Semaphore(max(1, concurrency))
            logger.info(f"Downloading {total} nodes (concurrency={max(1, concurrency)})…")

            # tqdm progress bar
            try:
                from tqdm import tqdm
                pbar = tqdm(total=total, unit="node", desc="Downloading",
                            dynamic_ncols=True, leave=True)
            except ImportError:
                pbar = None

            # Pre-spawn sessions if adapter supports it
            if concurrency > 1 and hasattr(adapter, 'warm_up_sessions'):
                if status_callback:
                    status_callback('warming_up', {
                        'message': f'预创建 {concurrency} 个会话…',
                    })
                await adapter.warm_up_sessions(book_id, concurrency)

            async def _download_one(node: ManifestNode) -> bool:
                nonlocal completed
                import time as _time
                t_wait = _time.monotonic()
                async with semaphore:
                    wait_ms = (_time.monotonic() - t_wait) * 1000
                    if wait_ms > 100:
                        logger.debug(f"[node {node.id}] semaphore wait={wait_ms:.0f}ms")
                    node_dir, _ = path_map.get(node.id, (dest_dir, None))
                    logger.debug(f"Downloading node {node.id} ({node.title})…")
                    if status_callback:
                        status_callback('downloading', {
                            'node_id': node.id,
                            'title': node.title,
                            'completed': completed,
                            'total': total,
                        })
                    try:
                        await asyncio.wait_for(
                            adapter.download_node(
                                book_id, node, node_dir, progress_callback=None),
                            timeout=120,  # 单节点最多 120 秒
                        )
                        success = node.status == NodeStatus.COMPLETED
                    except asyncio.TimeoutError:
                        logger.error(f"Node {node.id} timed out after 120s")
                        node.status = NodeStatus.FAILED
                        success = False
                    except Exception as e:
                        logger.error(f"Failed node {node.id}: {e}")
                        node.status = NodeStatus.FAILED
                        success = False

                    # Checkpoint + progress under lock to avoid race
                    async with lock:
                        if success:
                            completed += 1
                        # Propagate status to ancestor (folder) nodes
                        manifest.root.update_ancestor_status()
                        # Save all per-directory manifests (shallow, direct children only)
                        self._save_hierarchical_manifests(manifest, dest_dir)
                        if pbar:
                            pbar.update(1)
                        if progress_callback:
                            progress_callback(completed, total)
                        if status_callback:
                            status_callback('downloaded', {
                                'node_id': node.id,
                                'title': node.title,
                                'completed': completed,
                                'total': total,
                            })
                    return success

            await asyncio.gather(*[_download_one(n) for n in nodes])

            if pbar:
                pbar.close()

            logger.info(
                f"Download complete: {completed}/{total} "
                f"({total - completed} failed)")
            return manifest

        finally:
            await adapter.close()

    @staticmethod
    def _merge_manifest_statuses(
        old_root: ManifestNode, new_root: ManifestNode,
    ):
        """Preserve completed/downloading statuses when re-discovering."""
        old_map: dict[str, ManifestNode] = {}

        def collect(node: ManifestNode):
            old_map[node.id] = node
            for c in node.children:
                collect(c)
        collect(old_root)

        def apply(node: ManifestNode):
            old = old_map.get(node.id)
            if old and old.status in (
                NodeStatus.COMPLETED, NodeStatus.DOWNLOADING,
            ):
                node.status = old.status
                node.downloaded_items = old.downloaded_items
                node.local_path = old.local_path
            for c in node.children:
                apply(c)
        apply(new_root)

    async def close(self):
        """Close all resources."""
        await self.image_downloader.close()
        await self.text_downloader.close()
