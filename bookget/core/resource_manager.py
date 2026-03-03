# Resource Manager - Main orchestrator for downloading resources

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Callable
import json

from ..config import Config
from ..models.book import BookMetadata, Resource, DownloadTask, ResourceType
from ..adapters.registry import get_adapter, AdapterRegistry
from ..adapters.base import BaseSiteAdapter
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

                structured = await adapter.get_structured_text(book_id, index_id=index_id)
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
    
    async def close(self):
        """Close all resources."""
        await self.image_downloader.close()
        await self.text_downloader.close()
