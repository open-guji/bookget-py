"""REST API route handlers."""
import json
from aiohttp import web

from .sse import sse_stream


def setup_routes(app: web.Application):
    app.router.add_get("/api/search", handle_search)
    app.router.add_get("/api/config", handle_config)
    app.router.add_get("/api/sites", handle_sites)
    app.router.add_get("/api/sites/check", handle_check_url)
    app.router.add_post("/api/discover", handle_discover)
    app.router.add_post("/api/expand", handle_expand)
    app.router.add_post("/api/download", handle_start_download)
    app.router.add_delete("/api/download/{task_id}", handle_cancel_download)
    app.router.add_get("/api/tasks", handle_list_tasks)
    app.router.add_get("/api/tasks/{task_id}", handle_get_task)
    app.router.add_delete("/api/nodes", handle_delete_nodes)
    app.router.add_get("/api/events", handle_events)
    app.router.add_get("/api/events/{task_id}", handle_events_task)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _json(data, status=200):
    return web.Response(
        status=status,
        content_type="application/json",
        text=json.dumps(data, ensure_ascii=False),
    )


def _err(message: str, status=400):
    return _json({"error": message}, status=status)


async def _body(request: web.Request) -> dict:
    try:
        return await request.json()
    except Exception:
        return {}


# ── Handlers ─────────────────────────────────────────────────────────────────

async def handle_search(request: web.Request):
    site = request.rel_url.query.get("site", "")
    q = request.rel_url.query.get("q", "")
    if not (site and q):
        return _err("site and q parameters required")
    limit = int(request.rel_url.query.get("limit", "20"))
    offset = int(request.rel_url.query.get("offset", "0"))
    tm = request.app["task_manager"]
    try:
        result = await tm.search(site, q, limit, offset)
        return _json(result)
    except Exception as e:
        return _err(str(e), status=500)


async def handle_config(request: web.Request):
    """Expose server-side defaults, notably the ABSOLUTE output directory.

    The UI used to show the literal "./downloads", which resolves against the
    server process's working directory — so users could not tell where their
    files had actually gone (double-clicking the exe makes the CWD wherever
    Explorer happened to start it).
    """
    from pathlib import Path as _Path

    config = request.app["config"]
    try:
        output_root = str(_Path(config.storage.output_root).resolve())
    except Exception:
        output_root = str(config.storage.output_root)
    return _json({"defaultOutputDir": output_root})


async def handle_sites(request: web.Request):
    tm = request.app["task_manager"]
    return _json(tm.get_supported_sites())


async def handle_check_url(request: web.Request):
    url = request.rel_url.query.get("url", "")
    if not url:
        return _err("url parameter required")
    tm = request.app["task_manager"]
    return _json(tm.check_url(url))


async def handle_discover(request: web.Request):
    body = await _body(request)
    url = body.get("url", "")
    if not url:
        return _err("url is required")
    output_dir = body.get("outputDir") or body.get("output_dir")
    depth = int(body.get("depth", 1))
    tm = request.app["task_manager"]
    try:
        manifest_dict = await tm.discover(url, output_dir, depth)
        return _json(manifest_dict)
    except Exception as e:
        return _err(str(e), status=500)


async def handle_expand(request: web.Request):
    body = await _body(request)
    url = body.get("url", "")
    output_dir = body.get("outputDir") or body.get("output_dir", "")
    node_id = body.get("nodeId") or body.get("node_id", "")
    if not (url and output_dir and node_id):
        return _err("url, outputDir, nodeId are required")
    tm = request.app["task_manager"]
    try:
        manifest_dict = await tm.expand_node(url, output_dir, node_id)
        return _json(manifest_dict)
    except Exception as e:
        return _err(str(e), status=500)


async def handle_start_download(request: web.Request):
    body = await _body(request)
    url = body.get("url", "")
    output_dir = body.get("outputDir") or body.get("output_dir", "")
    node_ids = body.get("nodeIds") or body.get("node_ids")
    concurrency = int(body.get("concurrency", 1))
    # Honour a client-supplied id so SSE events land on the task the caller is
    # already tracking (the web UI keys everything by its discovery id).
    client_task_id = body.get("taskId") or body.get("task_id") or None
    if not url:
        return _err("url is required")
    tm = request.app["task_manager"]
    task_id = tm.start_download(
        url=url,
        output_dir=output_dir or "./downloads",
        node_ids=node_ids,
        concurrency=concurrency,
        task_id=client_task_id,
    )
    return _json({"taskId": task_id})


async def handle_cancel_download(request: web.Request):
    task_id = request.match_info["task_id"]
    tm = request.app["task_manager"]
    ok = await tm.cancel(task_id)
    if ok:
        return _json({"cancelled": True})
    return _err("task not found or already done", status=404)


async def handle_list_tasks(request: web.Request):
    tm = request.app["task_manager"]
    return _json(tm.list_tasks())


async def handle_get_task(request: web.Request):
    task_id = request.match_info["task_id"]
    tm = request.app["task_manager"]
    info = tm.get_task(task_id)
    if not info:
        return _err("task not found", status=404)
    result = {
        "task_id": info.task_id,
        "url": info.url,
        "status": info.status,
        "manifest": info.manifest.to_dict() if info.manifest else None,
        "error": info.error,
    }
    return _json(result)


async def handle_delete_nodes(request: web.Request):
    body = await _body(request)
    task_id = body.get("taskId") or body.get("task_id", "")
    node_ids = body.get("nodeIds") or body.get("node_ids", [])
    # Accept the output dir so delete also works when the task isn't in memory
    # (e.g. straight after 发现结构, or after the server restarted).
    output_dir = body.get("outputDir") or body.get("output_dir") or None
    if not (task_id and node_ids):
        return _err("taskId and nodeIds are required")
    tm = request.app["task_manager"]
    result = await tm.delete_nodes(task_id, node_ids, output_dir=output_dir)
    if result.get("deleted"):
        return _json(result)
    return _err(result.get("error", "task not found or no manifest"), status=404)


async def handle_events(request: web.Request):
    bus = request.app["event_bus"]
    return await sse_stream(request, bus)


async def handle_events_task(request: web.Request):
    task_id = request.match_info["task_id"]
    bus = request.app["event_bus"]
    return await sse_stream(request, bus, filter_task_id=task_id)
