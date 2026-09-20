# Custom exceptions for Guji Resource Manager


class GujiResourceError(Exception):
    """Base exception for all Guji Resource Manager errors."""
    pass


class AdapterError(GujiResourceError):
    """Error in site adapter operations."""
    pass


class AdapterNotFoundError(AdapterError):
    """No adapter found for the given URL."""
    def __init__(self, url: str):
        self.url = url
        super().__init__(f"No adapter found for URL: {url}")


class MetadataExtractionError(AdapterError):
    """Error extracting metadata from source."""
    pass


class SiteChallengeError(MetadataExtractionError):
    """Site answered a bot challenge instead of content.

    A WAF challenge is not a transient failure and not a bad URL: no amount
    of retrying or URL-fixing gets past it, so it needs to be said plainly
    rather than surfacing as "manifest is not valid JSON".
    """
    def __init__(self, site_id: str, url: str, signal: str = ""):
        self.site_id = site_id
        self.url = url
        self.signal = signal
        detail = f"（{signal}）" if signal else ""
        super().__init__(
            f"[{site_id}] 站点用机器人挑战拦下了请求{detail}：{url}\n"
            f"该站要求浏览器执行 JS 挑战才放行，普通 HTTP 客户端拿不到内容。"
            f"本站点目前不可用，与 URL 是否正确无关。"
        )


class DownloadError(GujiResourceError):
    """Error during resource download."""
    pass


class ResourceNotFoundError(DownloadError):
    """Requested resource not found (404)."""
    def __init__(self, url: str):
        self.url = url
        super().__init__(f"Resource not found: {url}")


class RateLimitError(DownloadError):
    """Rate limit exceeded."""
    def __init__(self, url: str, retry_after: int = None):
        self.url = url
        self.retry_after = retry_after
        msg = f"Rate limit exceeded for: {url}"
        if retry_after:
            msg += f" (retry after {retry_after}s)"
        super().__init__(msg)


class AuthenticationError(DownloadError):
    """Authentication required or failed."""
    pass


class PreprocessingError(GujiResourceError):
    """Error in preprocessing pipeline."""
    pass


class StorageError(GujiResourceError):
    """Error in storage operations."""
    pass
