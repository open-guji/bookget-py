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
