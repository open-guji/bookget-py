#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bookget CLI - Download ancient Chinese book resources

Usage:
    python -m bookget download "URL" [options]
    python -m bookget metadata "URL" [--format json]
    python -m bookget sites --list
    python -m bookget sites --check "URL"
"""

import argparse
import asyncio
import json
from pathlib import Path

from bookget.config import Config
from bookget.core.resource_manager import ResourceManager
from bookget.adapters.registry import AdapterRegistry
from bookget.logger import setup_logger, logger
from bookget.exceptions import GujiResourceError, AdapterNotFoundError


def progress_bar(downloaded: int, total: int):
    """Simple progress bar callback."""
    if total == 0:
        return
    pct = downloaded * 100 // total
    bar = "=" * (pct // 2) + ">" + " " * (50 - pct // 2)
    print(f"\r[{bar}] {downloaded}/{total} ({pct}%)", end="", flush=True)


def json_progress_callback(downloaded: int, total: int):
    """Callback for JSON progress events."""
    event = {
        "type": "progress",
        "downloaded": downloaded,
        "total": total,
        "percent": round(downloaded * 100 / total) if total > 0 else 0
    }
    print(json.dumps(event, ensure_ascii=False), flush=True)


async def cmd_download(args, config: Config):
    """Handle download command."""
    manager = ResourceManager(config)
    
    try:
        logger.info(f"Starting download: {args.url}")
        
        output = Path(args.output) if args.output else None
        
        if args.json_progress:
            callback = json_progress_callback
        elif not args.quiet:
            callback = progress_bar
        else:
            callback = None

        task = await manager.download(
            url=args.url,
            output_dir=output,
            include_images=not args.no_images,
            include_text=not args.no_text,
            include_metadata=not args.no_metadata,
            index_id=args.index_id if hasattr(args, 'index_id') else "",
            progress_callback=callback
        )
        
        if not args.json_progress and not args.quiet:
            print()  # Newline after progress bar
        
        if task.metadata:
            logger.info(f"Title: {task.metadata.title}")
        logger.info(f"Downloaded: {task.downloaded_count}/{task.total_resources}")
        logger.info(f"Output: {task.output_dir}")
        
        if args.json:
            result = {
                "book_id": task.book_id,
                "title": task.metadata.title if task.metadata else "",
                "downloaded": task.downloaded_count,
                "failed": task.failed_count,
                "total": task.total_resources,
                "output_dir": task.output_dir
            }
            print(json.dumps(result, ensure_ascii=False, indent=2))
            
    finally:
        await manager.close()


async def cmd_metadata(args, config: Config):
    """Handle metadata command."""
    manager = ResourceManager(config)
    
    try:
        metadata = await manager.get_metadata(
            args.url, 
            index_id=args.index_id if hasattr(args, 'index_id') else ""
        )
        
        if args.format == "json":
            print(json.dumps(metadata.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"Title: {metadata.title}")
            print(f"Creators: {', '.join(str(c) for c in metadata.creators)}")
            print(f"Dynasty: {metadata.dynasty}")
            print(f"Date: {metadata.date}")
            print(f"Collection: {metadata.collection_unit}")
            print(f"Category: {metadata.category}")
            if metadata.iiif_manifest_url:
                print(f"IIIF: {metadata.iiif_manifest_url}")
                
    finally:
        await manager.close()


def cmd_sites(args):
    """Handle sites command."""
    if args.check:
        adapter = AdapterRegistry.get_for_url(args.check)
        if adapter:
            if args.json:
                result = {
                    "id": adapter.site_id,
                    "name": adapter.site_name,
                    "domains": list(adapter.site_domains),
                    "iiif": adapter.supports_iiif,
                    "text": adapter.supports_text,
                }
                print(json.dumps(result, ensure_ascii=False))
            else:
                print(f"Supported: {adapter.site_name} ({adapter.site_id})")
                print(f"  IIIF: {adapter.supports_iiif}")
                print(f"  Text: {adapter.supports_text}")
        else:
            print(f"Not supported: {args.check}")
            sys.exit(1)
    else:
        adapters = AdapterRegistry.list_adapters()
        if args.json:
            print(json.dumps(adapters, ensure_ascii=False))
        else:
            print(f"Supported sites ({len(adapters)}):\n")
            for a in adapters:
                flags = []
                if a.get("iiif"):
                    flags.append("IIIF")
                if a.get("text"):
                    flags.append("Text")
                flag_str = f" [{', '.join(flags)}]" if flags else ""
                print(f"  {a['name']}{flag_str}")
                for domain in a.get('domains', []):
                    print(f"    - {domain}")


def main():
    parser = argparse.ArgumentParser(
        description="Bookget - Download ancient Chinese book resources"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--config", type=str, help="Config file path")
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # download command
    p_download = subparsers.add_parser("download", help="Download resources from URL")
    p_download.add_argument("url", help="Book URL to download")
    p_download.add_argument("-o", "--output", help="Output directory")
    p_download.add_argument("--no-images", action="store_true", help="Skip images")
    p_download.add_argument("--no-text", action="store_true", help="Skip text")
    p_download.add_argument("--no-metadata", action="store_true", help="Skip metadata")
    p_download.add_argument("--json", action="store_true", help="Output JSON result on completion")
    p_download.add_argument("--json-progress", action="store_true", help="Output JSON progress events")
    p_download.add_argument("--index-id", type=str, help="Global index ID", default="")
    p_download.add_argument("-q", "--quiet", action="store_true", help="Quiet mode")
    
    # metadata command
    p_meta = subparsers.add_parser("metadata", help="Get metadata only")
    p_meta.add_argument("url", help="Book URL")
    p_meta.add_argument("--index-id", type=str, help="Global index ID", default="")
    p_meta.add_argument("--format", choices=["text", "json"], default="text")
    
    # sites command
    p_sites = subparsers.add_parser("sites", help="List or check supported sites")
    p_sites.add_argument("--list", action="store_true", help="List all sites")
    p_sites.add_argument("--check", type=str, help="Check if URL is supported")
    p_sites.add_argument("--json", action="store_true", help="Output JSON format")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Setup
    setup_logger(debug=args.debug)
    config = Config.from_file(Path(args.config)) if args.config else Config.from_env()
    if args.debug:
        config.debug = True
    config.ensure_dirs()
    
    try:
        if args.command == "download":
            asyncio.run(cmd_download(args, config))
        elif args.command == "metadata":
            asyncio.run(cmd_metadata(args, config))
        elif args.command == "sites":
            cmd_sites(args)
    except AdapterNotFoundError as e:
        logger.error(f"Unsupported URL: {e.url}")
        sys.exit(1)
    except GujiResourceError as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Cancelled by user")
        sys.exit(130)


if __name__ == "__main__":
    main()
