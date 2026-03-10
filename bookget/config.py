# Configuration management for Guji Resource Manager

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, List
import json


@dataclass
class DownloadConfig:
    """Configuration for download behavior."""
    concurrent_downloads: int = 4
    retry_attempts: int = 3
    retry_delay: float = 1.0
    timeout: float = 30.0
    request_delay: float = 0.5  # delay between API requests (rate limiting)
    min_image_size: int = 1024  # minimum valid image size in bytes
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    

@dataclass
class StorageConfig:
    """Configuration for storage paths."""
    output_root: Path = field(default_factory=lambda: Path("./downloads"))
    cache_dir: Path = field(default_factory=lambda: Path("./.cache"))
    temp_dir: Path = field(default_factory=lambda: Path("./.temp"))
    
    def __post_init__(self):
        self.output_root = Path(self.output_root)
        self.cache_dir = Path(self.cache_dir)
        self.temp_dir = Path(self.temp_dir)


@dataclass
class Config:
    """Main configuration for Guji Resource Manager."""
    download: DownloadConfig = field(default_factory=DownloadConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    debug: bool = False
    
    # HTTP headers for requests
    default_headers: Dict[str, str] = field(default_factory=lambda: {
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    
    @classmethod
    def from_file(cls, path: Path) -> "Config":
        """Load configuration from JSON file."""
        if not path.exists():
            return cls()
        
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        kwargs = dict(
            download=DownloadConfig(**data.get("download", {})),
            storage=StorageConfig(**data.get("storage", {})),
            debug=data.get("debug", False),
        )
        if "default_headers" in data:
            kwargs["default_headers"] = data["default_headers"]
        return cls(**kwargs)
    
    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        config = cls()
        
        if output := os.environ.get("GUJI_OUTPUT_DIR"):
            config.storage.output_root = Path(output)
        
        if concurrent := os.environ.get("GUJI_CONCURRENT_DOWNLOADS"):
            config.download.concurrent_downloads = int(concurrent)
        
        if os.environ.get("GUJI_DEBUG"):
            config.debug = True
        
        return config
    
    def ensure_dirs(self):
        """Create necessary directories."""
        self.storage.output_root.mkdir(parents=True, exist_ok=True)
        self.storage.cache_dir.mkdir(parents=True, exist_ok=True)
        self.storage.temp_dir.mkdir(parents=True, exist_ok=True)
