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
import sys
from pathlib import Path

# Force UTF-8 stdout/stderr on Windows (avoids cp1252 encoding errors)
# In windowed mode (PyInstaller console=False), stdout/stderr may be None
if sys.stdout and sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and sys.stderr.encoding != 'utf-8':
    sys.stderr.reconfigure(encoding='utf-8')

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


async def cmd_discover(args, config: Config):
    """Handle discover command -- Phase 1: structure discovery."""
    manager = ResourceManager(config)

    try:
        output = Path(args.output) if args.output else None

        if args.json_progress:
            def progress_cb(event_type, message):
                event = {"type": "discovery", "event": event_type,
                         "message": message}
                print(json.dumps(event, ensure_ascii=False), flush=True)
        else:
            progress_cb = None

        manifest = await manager.discover(
            url=args.url,
            output_dir=output,
            depth=args.depth,
            index_id=getattr(args, 'index_id', ''),
            progress_callback=progress_cb,
        )

        if args.json:
            print(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2))
        else:
            progress = manifest.get_progress()
            logger.info(f"Title: {manifest.title}")
            logger.info(f"Nodes: {progress['total']}")
            logger.info(f"Completed: {progress['completed']}")
            logger.info(f"Discovery complete: {manifest.discovery_complete}")

    finally:
        await manager.close()


async def cmd_expand(args, config: Config):
    """Handle expand command -- expand a node in existing manifest."""
    manager = ResourceManager(config)

    try:
        output = Path(args.output)

        manifest = await manager.expand_manifest_node(
            url=args.url,
            output_dir=output,
            node_id=args.node_id,
            depth=args.depth,
        )

        if args.json:
            print(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2))
        else:
            node = manifest.find_node(args.node_id)
            if node:
                logger.info(
                    f"Expanded '{node.title}': "
                    f"{len(node.children)} children")
            else:
                logger.warning(f"Node {args.node_id} not found")

    finally:
        await manager.close()


async def cmd_download_incremental(args, config: Config):
    """Handle incremental download command."""
    manager = ResourceManager(config)

    try:
        output = Path(args.output) if args.output else None

        if args.json_progress:
            callback = json_progress_callback
            def status_cb(event_type: str, data: dict):
                event = {"type": "manifest_updated", "event": event_type, **data}
                print(json.dumps(event, ensure_ascii=False), flush=True)
        elif not args.quiet:
            callback = progress_bar
            status_cb = None
        else:
            callback = None
            status_cb = None

        manifest = await manager.download_incremental(
            url=args.url,
            output_dir=output,
            node_ids=args.section if hasattr(args, 'section') and args.section else None,
            include_images=not args.no_images,
            include_text=not args.no_text,
            index_id=getattr(args, 'index_id', ''),
            progress_callback=callback,
            status_callback=status_cb,
            concurrency=getattr(args, 'concurrency', 1) or 1,
        )

        if not args.json_progress and not args.quiet:
            print()

        progress = manifest.get_progress()
        logger.info(
            f"Progress: {progress['completed']}/{progress['total']} "
            f"({progress['percent']}%)")

        if args.json:
            print(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2))

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


async def cmd_match(args, config: Config):
    """Handle match command — exact title + author matching."""
    manager = ResourceManager(config)
    authors = [a.strip() for a in args.authors.split(",") if a.strip()] if args.authors else []

    try:
        result = await manager.match_book(
            site_id=args.site,
            title=args.title,
            authors=authors,
            delay=args.delay,
        )

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            results = result.get("results", [])
            if results:
                print(f"找到 {len(results)} 个资源:")
                for r in results:
                    print(f"  - {r['name']}: {r['url']}")
            else:
                print("未找到匹配资源")
    finally:
        await manager.close()


async def cmd_search(args, config: Config):
    """Handle search command."""
    manager = ResourceManager(config)

    try:
        result = await manager.search(
            site_id=args.site,
            query=args.query,
            limit=args.limit,
            offset=args.offset,
        )

        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            total = result.get("total_hits", 0)
            results = result.get("results", [])
            print(f"搜索 \"{args.query}\" — 共 {total} 条结果\n")

            for i, r in enumerate(results, 1):
                title = r["title"]
                is_disambig = r.get("is_disambiguation", False)
                versions = r.get("versions", [])

                tag = " [消歧义]" if is_disambig else ""
                ver_tag = f" [{len(versions)} 个版本]" if versions else ""
                print(f"  {i}. {title}{tag}{ver_tag}")

                if r.get("snippet"):
                    snippet = r["snippet"][:80]
                    print(f"     {snippet}")

                for v in versions:
                    print(f"     → {v['title']}")

                print()

            if result.get("has_more"):
                print(f"  还有更多结果，使用 --offset {result['continuation']} 翻页")

    finally:
        await manager.close()


async def cmd_serve(args, config: Config):
    """Handle serve command — start HTTP server."""
    from bookget.server.app import run_server
    from pathlib import Path as _Path
    import sys as _sys

    # Locate frontend: PyInstaller bundle first, then source tree
    if getattr(_sys, 'frozen', False):
        # Running as PyInstaller exe — assets are in sys._MEIPASS
        ui_dist = _Path(_sys._MEIPASS) / "ui" / "dist-app"
    else:
        ui_dist = _Path(__file__).parent.parent / "ui" / "dist-app"

    static_dir = ui_dist if ui_dist.exists() else None
    if static_dir:
        print(f"  Serving frontend from: {static_dir}")
    else:
        print("  Frontend not built. Run: cd ui && npm run build:app")

    runner, url = await run_server(
        config=config,
        host=args.host,
        port=args.port,
        static_dir=static_dir,
        open_browser=not args.no_open,
    )
    print(f"  bookget server running at {url}")
    print("  Press Ctrl+C to stop.\n")

    try:
        # Keep running until interrupted
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await runner.cleanup()


async def _interactive_mode():
    """Interactive CLI guide when launched without arguments.

    When running as bookget-ui.exe (frozen, no console), auto-start serve.
    """
    import sys as _sys
    # bookget-ui.exe: frozen + no console → just serve
    if getattr(_sys, 'frozen', False) and (not _sys.stdout or not _sys.stdout.isatty()):
        class _FakeArgs:
            host = "127.0.0.1"
            port = 8765
            no_open = False
            output_dir = None
        setup_logger(debug=False)
        config = Config.from_env()
        config.ensure_dirs()
        await cmd_serve(_FakeArgs(), config)
        return

    print("=" * 55)
    print("  bookget — 古籍下载工具")
    print("=" * 55)
    print()

    setup_logger(debug=False)
    config = Config.from_env()
    config.ensure_dirs()

    while True:
        try:
            # --- Step 1: URL ---
            while True:
                url = input("请输入书目 URL（输入 q 退出）: ").strip()
                if url.lower() in ("q", "quit", "exit", ""):
                    print("已退出。")
                    return
                adapter = AdapterRegistry.get_for_url(url)
                if adapter:
                    print(f"  ✓ 已识别站点：{adapter.site_name}")
                    break
                print("  ✗ 暂不支持该 URL，请重试。")

            # --- Step 2: Output dir ---
            default_out = str(Path.home() / "Downloads" / "bookget")
            out_input = input(f"下载目录 [{default_out}]: ").strip()
            output_dir = Path(out_input) if out_input else Path(default_out)
            output_dir.mkdir(parents=True, exist_ok=True)
            print(f"  → 下载到：{output_dir}")

            # --- Step 3: Concurrency ---
            conc_input = input("并行数量 [3]: ").strip()
            try:
                concurrency = max(1, int(conc_input)) if conc_input else 3
            except ValueError:
                concurrency = 3
            print(f"  → 并行数：{concurrency}")
            print()

            # --- Step 4: Discover ---
            print("正在探索书目结构……")
            manager = ResourceManager(config)
            try:
                manifest = await manager.discover(url=url, output_dir=output_dir, depth=1)
                progress = manifest.get_progress()
                print(f"  标题：{manifest.title}")
                print(f"  节点：{progress['total']}  已完成：{progress['completed']}")
            finally:
                await manager.close()

            # --- Step 5: Confirm and download ---
            confirm = input("\n开始下载所有节点？[Y/n]: ").strip().lower()
            if confirm in ("n", "no"):
                print("已取消。manifest 已保存，可用 `bookget download --incremental` 继续。\n")
                continue

            print("\n开始下载……")
            manager2 = ResourceManager(config)
            try:
                manifest2 = await manager2.download_incremental(
                    url=url,
                    output_dir=output_dir,
                    concurrency=concurrency,
                    progress_callback=progress_bar,
                )
                print()
                p = manifest2.get_progress()
                print(f"\n完成！{p['completed']}/{p['total']} 节点，输出目录：{output_dir}\n")
            except KeyboardInterrupt:
                print("\n已中断。下次运行可从中断处继续。\n")
            finally:
                await manager2.close()

        except KeyboardInterrupt:
            print("\n已退出。")
            return
        except EOFError:
            return
        except Exception as e:
            print(f"\n错误：{e}\n")
            continue


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
    p_download.add_argument("--incremental", action="store_true",
                            help="Use manifest-based incremental download")
    p_download.add_argument("--section", type=str, action="append", default=None,
                            help="Download specific sections/nodes by ID (repeat for multiple)")
    p_download.add_argument("--concurrency", type=int, default=1,
                            help="Number of nodes to download in parallel (default 1)")

    # discover command
    p_discover = subparsers.add_parser("discover", help="Discover book structure (Phase 1)")
    p_discover.add_argument("url", help="Book URL")
    p_discover.add_argument("-o", "--output", help="Output directory")
    p_discover.add_argument("--depth", type=int, default=1,
                            help="Discovery depth (-1 for full, 1 for top-level)")
    p_discover.add_argument("--json", action="store_true", help="Output manifest as JSON")
    p_discover.add_argument("--json-progress", action="store_true",
                            help="Stream JSON discovery events")
    p_discover.add_argument("--index-id", type=str, default="")

    # expand command
    p_expand = subparsers.add_parser("expand", help="Expand a node in existing manifest")
    p_expand.add_argument("url", help="Book URL")
    p_expand.add_argument("node_id", help="Node ID to expand")
    p_expand.add_argument("-o", "--output", required=True, help="Output directory")
    p_expand.add_argument("--depth", type=int, default=1)
    p_expand.add_argument("--json", action="store_true")

    # metadata command
    p_meta = subparsers.add_parser("metadata", help="Get metadata only")
    p_meta.add_argument("url", help="Book URL")
    p_meta.add_argument("--index-id", type=str, help="Global index ID", default="")
    p_meta.add_argument("--format", choices=["text", "json"], default="text")
    
    # search command
    p_search = subparsers.add_parser("search", help="Search for books on a site")
    p_search.add_argument("site", help="Site ID (e.g., wikisource)")
    p_search.add_argument("query", help="Search keywords")
    p_search.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")
    p_search.add_argument("--offset", type=int, default=0, help="Pagination offset")
    p_search.add_argument("--json", action="store_true", help="Output JSON format")

    # match command
    p_match = subparsers.add_parser("match", help="Match a book title against a site")
    p_match.add_argument("site", help="Site ID (e.g., wikisource)")
    p_match.add_argument("title", help="Book title to match")
    p_match.add_argument("--authors", type=str, default="",
                         help="Comma-separated author names")
    p_match.add_argument("--delay", type=float, default=1.0,
                         help="API request delay in seconds (default: 1.0)")
    p_match.add_argument("--json", action="store_true", help="Output JSON format")

    # sites command
    p_sites = subparsers.add_parser("sites", help="List or check supported sites")
    p_sites.add_argument("--list", action="store_true", help="List all sites")
    p_sites.add_argument("--check", type=str, help="Check if URL is supported")
    p_sites.add_argument("--json", action="store_true", help="Output JSON format")

    # serve command
    p_serve = subparsers.add_parser("serve", help="Start HTTP server with web UI")
    p_serve.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=8765, help="Port to listen on (default: 8765)")
    p_serve.add_argument("--no-open", action="store_true", help="Don't open browser automatically")
    p_serve.add_argument("--output-dir", type=str, help="Default download output directory")

    args = parser.parse_args()

    if not args.command:
        asyncio.run(_interactive_mode())
        return

    # Setup
    setup_logger(debug=args.debug)
    config = Config.from_file(Path(args.config)) if args.config else Config.from_env()
    if args.debug:
        config.debug = True
    config.ensure_dirs()

    try:
        if args.command == "download":
            if getattr(args, 'incremental', False) or getattr(args, 'section', None):
                asyncio.run(cmd_download_incremental(args, config))
            else:
                asyncio.run(cmd_download(args, config))
        elif args.command == "discover":
            asyncio.run(cmd_discover(args, config))
        elif args.command == "expand":
            asyncio.run(cmd_expand(args, config))
        elif args.command == "metadata":
            asyncio.run(cmd_metadata(args, config))
        elif args.command == "match":
            asyncio.run(cmd_match(args, config))
        elif args.command == "search":
            asyncio.run(cmd_search(args, config))
        elif args.command == "sites":
            cmd_sites(args)
        elif args.command == "serve":
            if hasattr(args, 'output_dir') and args.output_dir:
                config.storage.output_root = args.output_dir
            asyncio.run(cmd_serve(args, config))
    except AdapterNotFoundError as e:
        logger.error(f"Unsupported URL: {e.url}")
        sys.exit(1)
    except GujiResourceError as e:
        logger.error(f"Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Cancelled by user")
        sys.exit(130)


def _safe_main():
    """Top-level entry point with global exception handling."""
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        # Print to stderr if available, otherwise show a message box on Windows
        msg = f"Fatal error: {e}"
        if sys.stderr:
            print(msg, file=sys.stderr)
            import traceback
            traceback.print_exc(file=sys.stderr)
        elif sys.platform == "win32":
            # Windowed mode (no console): show a message box
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(
                    0, f"{msg}\n\n{type(e).__name__}: {e}", "bookget - Error", 0x10
                )
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    _safe_main()
