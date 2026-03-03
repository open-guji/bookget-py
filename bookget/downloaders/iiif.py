# IIIF Image Downloader
# Optimized for IIIF Image API 2.0/3.0

from typing import Dict, Optional
from pathlib import Path
import aiohttp
import asyncio
from urllib.parse import urlparse, urljoin

from .base import BaseDownloader
from ..models.book import Resource, ResourceType
from ..config import DownloadConfig
from ..logger import logger
from ..exceptions import DownloadError, ResourceNotFoundError


class IIIFImageDownloader(BaseDownloader):
    """
    Specialized downloader for IIIF Image API.
    
    Supports:
    - Flexible image sizes (full, max, custom dimensions)
    - Quality settings (default, color, gray, bitonal)
    - Format selection (jpg, png, webp, etc.)
    - Automatic fallback for unsupported features
    
    IIIF Image API URL format:
    {scheme}://{server}{/prefix}/{identifier}/{region}/{size}/{rotation}/{quality}.{format}
    """
    
    DEFAULT_SIZE = "full"       # "full", "max", or "{width},{height}"
    DEFAULT_QUALITY = "default" # "default", "color", "gray", "bitonal"
    DEFAULT_FORMAT = "jpg"
    
    def __init__(self, config: DownloadConfig = None):
        super().__init__(config)
        self.size = self.DEFAULT_SIZE
        self.quality = self.DEFAULT_QUALITY
        self.format = self.DEFAULT_FORMAT
    
    def set_size(self, size: str):
        """
        Set download size.
        
        Args:
            size: "full", "max", "{width},", ",{height}", or "{width},{height}"
        """
        self.size = size
    
    def set_quality(self, quality: str):
        """Set image quality: "default", "color", "gray", "bitonal"."""
        self.quality = quality
    
    def build_image_url(
        self, 
        service_id: str, 
        region: str = "full",
        size: str = None,
        rotation: str = "0",
        quality: str = None,
        format: str = None
    ) -> str:
        """
        Build IIIF Image API URL.
        
        Args:
            service_id: The IIIF Image service @id
            region: Region parameter (full, square, x,y,w,h, pct:x,y,w,h)
            size: Size parameter (full, max, w,, ,h, pct:n, w,h, !w,h)
            rotation: Rotation (0, 90, 180, 270, or arbitrary degrees)
            quality: Quality (default, color, gray, bitonal)
            format: Format (jpg, png, gif, webp, etc.)
        
        Returns:
            Complete IIIF Image API URL
        """
        size = size or self.size
        quality = quality or self.quality
        format = format or self.format
        
        # Ensure service_id doesn't have trailing slash
        service_id = service_id.rstrip("/")
        
        return f"{service_id}/{region}/{size}/{rotation}/{quality}.{format}"
    
    async def download(
        self,
        resource: Resource,
        output_path: Path,
        headers: Dict[str, str] = None
    ) -> bool:
        """
        Download a IIIF image resource.
        
        If resource has iiif_service_id, builds optimal URL.
        Otherwise falls back to resource.url.
        """
        session = await self.get_session()
        request_headers = headers or {}
        
        # Determine URL
        if resource.iiif_service_id:
            url = self.build_image_url(resource.iiif_service_id)
        else:
            url = resource.url
        
        try:
            async with session.get(url, headers=request_headers) as response:
                if response.status == 404:
                    raise ResourceNotFoundError(url)
                
                # Handle IIIF-specific errors
                if response.status == 400:
                    # Bad request - try fallback URL
                    if resource.iiif_service_id:
                        return await self._download_with_fallback(
                            resource, output_path, headers
                        )
                    raise DownloadError(f"Bad request: {url}")
                
                response.raise_for_status()
                
                # Ensure output directory exists
                output_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Write to file
                content = await response.read()
                output_path.write_bytes(content)
                
                logger.debug(f"Downloaded IIIF: {output_path.name}")
                return True
                
        except aiohttp.ClientError as e:
            raise DownloadError(f"Failed to download {url}: {e}")
    
    async def _download_with_fallback(
        self,
        resource: Resource,
        output_path: Path,
        headers: Dict[str, str] = None
    ) -> bool:
        """Try alternative IIIF parameters if default fails."""
        session = await self.get_session()
        request_headers = headers or {}
        
        # Try "max" instead of "full" for size
        fallback_sizes = ["max", "1024,", "!1024,1024"]
        
        for size in fallback_sizes:
            url = self.build_image_url(resource.iiif_service_id, size=size)
            
            try:
                async with session.get(url, headers=request_headers) as response:
                    if response.status == 200:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        content = await response.read()
                        output_path.write_bytes(content)
                        logger.debug(f"Downloaded IIIF (fallback {size}): {output_path.name}")
                        return True
            except Exception:
                continue
        
        # Final fallback: use resource.url directly
        if resource.url:
            try:
                async with session.get(resource.url, headers=request_headers) as response:
                    if response.status == 200:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        content = await response.read()
                        output_path.write_bytes(content)
                        logger.debug(f"Downloaded (direct URL): {output_path.name}")
                        return True
            except Exception as e:
                logger.warning(f"Direct URL fallback failed: {e}")
        
        return False
    
    async def get_image_info(self, service_id: str) -> Optional[dict]:
        """
        Fetch IIIF Image info.json for a service.
        
        Returns information about available sizes, formats, etc.
        """
        session = await self.get_session()
        url = f"{service_id.rstrip('/')}/info.json"
        
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
        except Exception as e:
            logger.warning(f"Failed to get image info: {e}")
        
        return None
