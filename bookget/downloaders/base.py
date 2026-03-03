# Base Downloader - Abstract base class for resource downloaders

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from pathlib import Path
import aiohttp
import asyncio

from ..models.book import Resource, ResourceType
from ..config import DownloadConfig
from ..logger import logger
from ..exceptions import DownloadError, ResourceNotFoundError, RateLimitError


class BaseDownloader(ABC):
    """
    Abstract base class for resource downloaders.
    
    Handles the actual downloading of resources (images, text, PDFs)
    with retry logic, rate limiting, and error handling.
    """
    
    def __init__(self, config: DownloadConfig = None):
        self.config = config or DownloadConfig()
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
    
    async def get_session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={"User-Agent": self.config.user_agent}
            )
        return self._session
    
    async def get_semaphore(self) -> asyncio.Semaphore:
        """Get or create the concurrency semaphore."""
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.config.concurrent_downloads)
        return self._semaphore
    
    @abstractmethod
    async def download(
        self,
        resource: Resource,
        output_path: Path,
        headers: Dict[str, str] = None
    ) -> bool:
        """
        Download a single resource.
        
        Args:
            resource: The Resource object to download
            output_path: Where to save the downloaded file
            headers: Optional additional HTTP headers
            
        Returns:
            True if download succeeded, False otherwise
        """
        pass
    
    async def download_with_retry(
        self,
        resource: Resource,
        output_path: Path,
        headers: Dict[str, str] = None
    ) -> bool:
        """
        Download with retry logic.
        
        Args:
            resource: The Resource object to download
            output_path: Where to save the downloaded file
            headers: Optional additional HTTP headers
            
        Returns:
            True if download succeeded, False otherwise
        """
        semaphore = await self.get_semaphore()
        
        async with semaphore:
            for attempt in range(self.config.retry_attempts):
                try:
                    success = await self.download(resource, output_path, headers)
                    if success:
                        resource.downloaded = True
                        resource.local_path = str(output_path)
                        return True
                except RateLimitError as e:
                    wait_time = e.retry_after or (self.config.retry_delay * (attempt + 1))
                    logger.warning(f"Rate limited, waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)
                except ResourceNotFoundError:
                    logger.error(f"Resource not found: {resource.url}")
                    return False
                except Exception as e:
                    logger.warning(f"Download attempt {attempt + 1} failed: {e}")
                    if attempt < self.config.retry_attempts - 1:
                        await asyncio.sleep(self.config.retry_delay * (attempt + 1))
            
            return False
    
    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None


class ImageDownloader(BaseDownloader):
    """Downloader for image resources."""
    
    async def download(
        self,
        resource: Resource,
        output_path: Path,
        headers: Dict[str, str] = None
    ) -> bool:
        """Download an image resource."""
        session = await self.get_session()
        request_headers = headers or {}
        
        try:
            async with session.get(resource.url, headers=request_headers) as response:
                if response.status == 404:
                    raise ResourceNotFoundError(resource.url)
                if response.status == 429:
                    retry_after = response.headers.get("Retry-After")
                    raise RateLimitError(resource.url, int(retry_after) if retry_after else None)
                
                response.raise_for_status()
                
                # Ensure output directory exists
                output_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Check for NLC security header and remove if present
                content = await response.read()
                content = self._remove_security_header(content)

                # Verify content
                if not self._verify_image(content, output_path.name):
                    return False

                # Write to file
                output_path.write_bytes(content)

                logger.debug(f"Downloaded: {output_path.name}")
                return True
                
        except aiohttp.ClientError as e:
            raise DownloadError(f"Failed to download {resource.url}: {e}")
    
    def _remove_security_header(self, content: bytes) -> bytes:
        """Remove NLC security header if present."""
        # NLC uses "###SECURED_IMAGE###" prefix
        security_marker = b"###SECURED_IMAGE###"
        if content.startswith(security_marker):
            return content[len(security_marker):]
        return content

    def _verify_image(self, content: bytes, filename: str) -> bool:
        """Verify downloaded image content is valid."""
        min_size = self.config.min_image_size if self.config else 1024

        if len(content) < min_size:
            logger.warning(
                f"Image too small ({len(content)} bytes): {filename}")
            return False

        # Check for common image magic bytes
        valid_signatures = [
            b'\xff\xd8\xff',      # JPEG
            b'\x89PNG',           # PNG
            b'GIF8',              # GIF
            b'RIFF',              # WebP
            b'II\x2a\x00',       # TIFF (little-endian)
            b'MM\x00\x2a',       # TIFF (big-endian)
        ]
        if not any(content.startswith(sig) for sig in valid_signatures):
            logger.warning(f"Unrecognized image format: {filename}")
            # Don't reject — some sites use unusual formats
        return True


class TextDownloader(BaseDownloader):
    """Downloader for text resources."""
    
    async def download(
        self,
        resource: Resource,
        output_path: Path,
        headers: Dict[str, str] = None
    ) -> bool:
        """Download a text resource."""
        session = await self.get_session()
        request_headers = headers or {}
        
        try:
            async with session.get(resource.url, headers=request_headers) as response:
                if response.status == 404:
                    raise ResourceNotFoundError(resource.url)
                if response.status == 429:
                    raise RateLimitError(resource.url)
                
                response.raise_for_status()
                
                # Ensure output directory exists
                output_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Read as text with UTF-8 encoding
                text = await response.text(encoding='utf-8')
                
                # Write to file
                output_path.write_text(text, encoding='utf-8')
                
                logger.debug(f"Downloaded text: {output_path.name}")
                return True
                
        except aiohttp.ClientError as e:
            raise DownloadError(f"Failed to download {resource.url}: {e}")
