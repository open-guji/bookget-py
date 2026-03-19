# Adapter Registry - Auto-discovery and registration of site adapters

from typing import Dict, List, Optional, Type
import importlib
import pkgutil
import sys
from pathlib import Path

from .base import BaseSiteAdapter
from ..logger import logger


class AdapterRegistry:
    """
    Registry for site adapters.
    
    Provides auto-discovery and lookup of adapters by URL or site ID.
    """
    
    _adapters: Dict[str, Type[BaseSiteAdapter]] = {}
    _initialized: bool = False
    
    @classmethod
    def register(cls, adapter_class: Type[BaseSiteAdapter]) -> Type[BaseSiteAdapter]:
        """
        Register an adapter class.
        
        Can be used as a class decorator:
            @AdapterRegistry.register
            class MyAdapter(BaseSiteAdapter):
                ...
        """
        site_id = adapter_class.site_id or adapter_class.__name__
        cls._adapters[site_id] = adapter_class
        logger.debug(f"Registered adapter: {site_id} ({adapter_class.site_name})")
        return adapter_class
    
    @classmethod
    def get_by_id(cls, site_id: str) -> Optional[Type[BaseSiteAdapter]]:
        """Get adapter class by site ID."""
        cls._ensure_initialized()
        return cls._adapters.get(site_id)
    
    @classmethod
    def get_for_url(cls, url: str) -> Optional[Type[BaseSiteAdapter]]:
        """
        Find an adapter that can handle the given URL.
        
        Args:
            url: The URL to find an adapter for
            
        Returns:
            Adapter class or None if no adapter found
        """
        cls._ensure_initialized()
        
        for adapter_class in cls._adapters.values():
            if adapter_class.can_handle(url):
                return adapter_class
        
        return None
    
    @classmethod
    def list_adapters(cls) -> List[Dict[str, str]]:
        """List all registered adapters."""
        cls._ensure_initialized()
        
        return [
            {
                "id": site_id,
                "name": adapter.site_name,
                "domains": adapter.site_domains,
                "iiif": adapter.supports_iiif,
                "text": adapter.supports_text,
            }
            for site_id, adapter in cls._adapters.items()
        ]
    
    @classmethod
    def _ensure_initialized(cls):
        """Ensure adapters have been discovered."""
        if not cls._initialized:
            cls._discover_adapters()
            cls._initialized = True
    
    # Explicit module list for PyInstaller frozen environments
    _ADAPTER_MODULES = [
        'bookget.adapters.iiif.base_iiif',
        'bookget.adapters.iiif.harvard',
        'bookget.adapters.iiif.ndl',
        'bookget.adapters.iiif.princeton',
        'bookget.adapters.iiif.stanford',
        'bookget.adapters.other.archive_org',
        'bookget.adapters.other.ctext',
        'bookget.adapters.other.european',
        'bookget.adapters.other.hanchi',
        'bookget.adapters.other.nlc_guji',
        'bookget.adapters.other.shidianguji',
        'bookget.adapters.other.taiwan',
        'bookget.adapters.other.wikisource',
        'bookget.adapters.other.wikimedia_commons',
    ]

    @classmethod
    def _discover_adapters(cls):
        """
        Auto-discover and import adapter modules.

        In frozen (PyInstaller) environments, uses an explicit module list.
        In normal environments, scans subdirectories.
        """
        if getattr(sys, 'frozen', False):
            # PyInstaller: filesystem scan won't work, use explicit list
            for module_name in cls._ADAPTER_MODULES:
                try:
                    importlib.import_module(module_name)
                    logger.debug(f"Imported adapter module: {module_name}")
                except Exception as e:
                    logger.warning(f"Failed to import {module_name}: {e}")
        else:
            # Normal: scan subdirectories
            adapters_path = Path(__file__).parent
            for subdir in ["iiif", "other"]:
                subdir_path = adapters_path / subdir
                if subdir_path.exists():
                    cls._import_from_directory(subdir_path, f"bookget.adapters.{subdir}")

    @classmethod
    def _import_from_directory(cls, directory: Path, package_prefix: str):
        """Import all Python modules from a directory."""
        for item in directory.iterdir():
            if item.suffix == ".py" and not item.name.startswith("_"):
                module_name = f"{package_prefix}.{item.stem}"
                try:
                    importlib.import_module(module_name)
                    logger.debug(f"Imported adapter module: {module_name}")
                except Exception as e:
                    logger.warning(f"Failed to import {module_name}: {e}")


def get_adapter(url: str, config=None) -> Optional[BaseSiteAdapter]:
    """
    Get an adapter instance for the given URL.
    
    Args:
        url: The URL to get an adapter for
        config: Optional configuration object
        
    Returns:
        Adapter instance or None if no adapter found
    """
    adapter_class = AdapterRegistry.get_for_url(url)
    if adapter_class:
        return adapter_class(config=config)
    return None
