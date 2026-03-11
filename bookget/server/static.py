"""Static file serving — serve the built React app from dist-app/."""
from pathlib import Path
from aiohttp import web


def setup_static(app: web.Application, static_dir: Path):
    """
    Serve static files from static_dir.
    All unmatched routes fall back to index.html (SPA routing).
    """
    index = static_dir / "index.html"

    async def serve_index(request: web.Request):
        if index.exists():
            return web.FileResponse(index)
        return web.Response(
            status=200,
            content_type="text/html",
            text="<h2>bookget server running</h2><p>Frontend not built yet. Run <code>npm run build:app</code> in ui/</p>",
        )

    # Serve static assets
    app.router.add_static("/assets", static_dir / "assets", show_index=False)

    # SPA fallback: any non-API GET → index.html
    app.router.add_get("/", serve_index)
    app.router.add_get("/{path:(?!api/).*}", serve_index)
