#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bookget CLI - Download ancient Chinese book resources

Usage:
    python -m bookget download "URL" [options]
    python -m bookget download "URL1" "URL2" ... [options]      # batch
    python -m bookget download --url-file urls.txt [options]    # batch from file
    python -m bookget download --retry-failed failed_urls.txt   # retry a batch
    python -m bookget metadata "URL" [--format json]
    python -m bookget sites --list
    python -m bookget sites --check "URL"
    python -m bookget upload <identifier> <files...> [--metadata-file f]
    python -m bookget ia-patch <identifier> [--set k=v]
    python -m bookget ia-check <identifier>
"""

import argparse
import asyncio
import json
import os
import re
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
from bookget.adapters.registry import AdapterRegistry, get_adapter
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


FAILED_URLS_FILENAME = "failed_urls.txt"


def _safe_dirname(name: str) -> str:
    """Make a filesystem-safe folder name from a book id or URL.

    Book ids are not guaranteed to be path-safe — CText's look like
    ``path:analects``, and ``:`` is illegal in Windows paths (WinError 267),
    which would fail the whole download. Strip the scheme if we were handed a
    URL, then reduce anything outside [A-Za-z0-9._-] to underscores.
    """
    name = re.sub(r"^https?://", "", name)
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")
    return name[:80] or "book"


def read_url_file(path: str) -> list:
    """Read URLs from a text file, one per line.

    Blank lines and ``#`` comments are ignored so a list can be annotated.
    """
    urls = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


def collect_download_urls(args) -> list:
    """Build the URL list for `download` from positional args / --url-file.

    De-duplicates while preserving order, so a URL repeated between the
    command line and a list file is only fetched once.
    """
    urls = list(getattr(args, "url", None) or [])

    if getattr(args, "url_file", None):
        urls.extend(read_url_file(args.url_file))

    if getattr(args, "retry_failed", None):
        urls.extend(read_url_file(args.retry_failed))

    seen = set()
    deduped = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            deduped.append(u)
    return deduped


async def cmd_download(args, config: Config):
    """Handle download command (one or many URLs)."""
    urls = collect_download_urls(args)
    if not urls:
        logger.error("No URLs given. Pass URLs directly, or use --url-file / --retry-failed.")
        raise SystemExit(2)

    if len(urls) == 1:
        await _download_one(args, config, urls[0])
        return

    await _download_many(args, config, urls)


async def _download_many(args, config: Config, urls: list):
    """Download several books in sequence, isolating per-book failures.

    One bad URL must not abort the rest of the batch: each is tried, the
    outcome recorded, and a summary printed at the end. Failed URLs are
    written to `failed_urls.txt` so the batch can be resumed with
    `--retry-failed`.
    """
    base_output = Path(args.output) if args.output else Path.cwd()
    total = len(urls)
    succeeded, failed = [], []

    logger.info(f"Batch download: {total} URLs")

    for i, url in enumerate(urls, 1):
        logger.info(f"[{i}/{total}] {url}")
        try:
            # Each book gets its own subdirectory, named after the adapter's
            # book id, so a batch doesn't collapse into one mixed folder.
            await _download_one(args, config, url, output_override=base_output,
                                per_book_subdir=True)
            succeeded.append(url)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            logger.error(f"[{i}/{total}] failed: {e}")
            failed.append((url, str(e)))

    print()
    logger.info(f"Batch complete: {len(succeeded)} succeeded, {len(failed)} failed, {total} total")

    if failed:
        failed_path = base_output / FAILED_URLS_FILENAME
        try:
            base_output.mkdir(parents=True, exist_ok=True)
            with open(failed_path, "w", encoding="utf-8") as f:
                f.write("# URLs that failed in the last batch.\n")
                f.write(f"# Retry with: bookget download --retry-failed {failed_path}\n")
                for url, err in failed:
                    f.write(f"# {err}\n{url}\n")
            logger.info(f"Failed URLs written to: {failed_path}")
            logger.info(f"Retry them with: bookget download --retry-failed {failed_path}")
        except OSError as e:
            logger.warning(f"Could not write {failed_path}: {e}")
        for url, err in failed:
            logger.error(f"  FAILED {url}: {err}")

    if args.json:
        print(json.dumps({
            "total": total,
            "succeeded": len(succeeded),
            "failed": len(failed),
            "failed_urls": [u for u, _ in failed],
        }, ensure_ascii=False, indent=2))

    if failed:
        raise SystemExit(1)


async def _download_one(args, config: Config, url: str,
                        output_override: Path = None,
                        per_book_subdir: bool = False):
    """Download a single book."""
    manager = ResourceManager(config)

    try:
        logger.info(f"Starting download: {url}")

        if output_override is not None:
            output = output_override
            if per_book_subdir:
                # Keep each book in its own folder inside the batch dir,
                # otherwise every book's images/ and metadata.json overwrite
                # each other.
                try:
                    adapter = get_adapter(url, config.download)
                    book_id = adapter.extract_book_id(url) if adapter else ""
                except Exception:
                    book_id = ""
                output = output / _safe_dirname(book_id or url)
        else:
            output = Path(args.output) if args.output else None

        if args.json_progress:
            callback = json_progress_callback
        elif not args.quiet:
            callback = progress_bar
        else:
            callback = None

        task = await manager.download(
            url=url,
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
    """Handle incremental download command.

    Shares the `download` parser, whose `url` is now a list, so resolve it to
    a single URL here. Incremental download is manifest-based and inherently
    per-book, so batching isn't supported for it.
    """
    urls = collect_download_urls(args)
    if not urls:
        logger.error("No URL given.")
        raise SystemExit(2)
    if len(urls) > 1:
        logger.error(
            "--incremental / --section take a single URL "
            f"(got {len(urls)}). Run them one book at a time."
        )
        raise SystemExit(2)
    single_url = urls[0]
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
            url=single_url,
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


def cmd_ia_upload(args):
    """Handle upload command -- upload files to an Internet Archive item."""
    from bookget.ia_upload import cmd_upload
    cmd_upload(args)


def cmd_ia_patch(args):
    """Handle ia-patch command -- modify metadata of an existing IA item."""
    from bookget.ia_upload import cmd_patch
    cmd_patch(args)


def cmd_ia_check(args):
    """Handle ia-check command -- validate metadata of an existing IA item."""
    from bookget.ia_upload import cmd_check
    cmd_check(args)


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

            # --- Step 3b: IIIF image resolution (only for IIIF adapters) ---
            if getattr(adapter, "supports_iiif", False):
                print("\n选择图片分辨率：")
                print("  1) 最高清 (原始尺寸 max/full，文件最大)")
                print("  2) 高清    (2400px 宽)")
                print("  3) 阅读    (1600px 宽)  ← 默认")
                print("  4) 缩略    (800px 宽)")
                size_input = input("输入序号 [3]: ").strip() or "3"
                size_map = {"1": "max", "2": "2400,", "3": "1600,", "4": "800,"}
                chosen = size_map.get(size_input, "1600,")
                os.environ["BOOKGET_IIIF_SIZE"] = chosen
                print(f"  → 分辨率：{chosen}")
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
                attempt = 1
                while True:
                    manifest2 = await manager2.download_incremental(
                        url=url,
                        output_dir=output_dir,
                        concurrency=concurrency,
                        progress_callback=progress_bar,
                    )
                    print()
                    p = manifest2.get_progress()
                    failed = p.get('failed', 0)
                    print(
                        f"\n第 {attempt} 轮：{p['completed']}/{p['total']} 完成，"
                        f"{failed} 失败")

                    if failed == 0:
                        print(f"\n全部完成！输出目录：{output_dir}\n")
                        break

                    retry = input(
                        f"还有 {failed} 个节点失败，重试？[Y/n]: "
                    ).strip().lower()
                    if retry in ("n", "no"):
                        print(f"\n保留 {failed} 个失败节点，下次跑同一 URL+目录可继续。\n")
                        break
                    attempt += 1
                    print(f"\n开始第 {attempt} 轮重试……")
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
    p_download = subparsers.add_parser(
        "download",
        help="Download resources from one or more URLs",
        description="Download one book, or many at once. With several URLs "
                    "each book is saved into its own subdirectory of --output, "
                    "a failing URL doesn't stop the rest, and the ones that "
                    "failed are written to failed_urls.txt for --retry-failed.",
    )
    p_download.add_argument("url", nargs="*",
                            help="Book URL(s) to download; repeat for batch download")
    p_download.add_argument("--url-file", type=str,
                            help="Read URLs from a file, one per line ('#' starts a comment)")
    p_download.add_argument("--retry-failed", type=str, metavar="FILE",
                            help="Retry the URLs in FILE (e.g. the failed_urls.txt "
                                 "from a previous batch)")
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

    # upload command (Internet Archive)
    p_upload = subparsers.add_parser("upload", help="Upload files to an Internet Archive item")
    p_upload.add_argument("identifier", help="IA identifier")
    p_upload.add_argument("files", nargs="+", help="Files to upload")
    p_upload.add_argument("--metadata-file", help="JSON/YAML file with IA metadata")
    p_upload.add_argument("--set", action="append", metavar="K=V",
                          help="Override a single metadata field, repeatable. "
                               "e.g. --set title=... --set creator=曹霑")
    p_upload.add_argument("--dry-run", action="store_true")
    p_upload.add_argument("--force", action="store_true",
                          help="Allow overwriting an existing item, purge stale PDFs")
    p_upload.add_argument("--no-strict", action="store_true",
                          help="Don't enforce guji page-progression=rl (non-guji use)")

    # ia-patch command (Internet Archive)
    p_ia_patch = subparsers.add_parser("ia-patch", help="Patch metadata of an existing IA item")
    p_ia_patch.add_argument("identifier", help="IA identifier")
    p_ia_patch.add_argument("--metadata-file", help="JSON/YAML file with IA metadata")
    p_ia_patch.add_argument("--set", action="append", metavar="K=V")
    p_ia_patch.add_argument("--dry-run", action="store_true")
    p_ia_patch.add_argument("--no-strict", action="store_true")
    p_ia_patch.add_argument("--skip-validate", action="store_true",
                            help="Skip post-patch metadata validation")

    # ia-check command (Internet Archive)
    p_ia_check = subparsers.add_parser("ia-check", help="Validate metadata of an existing IA item")
    p_ia_check.add_argument("identifier", help="IA identifier")
    p_ia_check.add_argument("--no-strict", action="store_true")
    p_ia_check.add_argument("--apply-defaults", action="store_true",
                            help="Validate against metadata with defaults applied")

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
        elif args.command == "upload":
            cmd_ia_upload(args)
        elif args.command == "ia-patch":
            cmd_ia_patch(args)
        elif args.command == "ia-check":
            cmd_ia_check(args)
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
