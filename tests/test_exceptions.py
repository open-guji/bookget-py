# Tests for exception hierarchy

import pytest
from bookget.exceptions import (
    GujiResourceError,
    AdapterError,
    AdapterNotFoundError,
    MetadataExtractionError,
    DownloadError,
    ResourceNotFoundError,
    RateLimitError,
    AuthenticationError,
    PreprocessingError,
    StorageError,
)


class TestExceptionHierarchy:
    """Tests for exception inheritance chain."""

    def test_base_exception(self):
        with pytest.raises(GujiResourceError):
            raise GujiResourceError("test")

    def test_adapter_error_is_guji_error(self):
        with pytest.raises(GujiResourceError):
            raise AdapterError("adapter fail")

    def test_download_error_is_guji_error(self):
        with pytest.raises(GujiResourceError):
            raise DownloadError("download fail")

    def test_storage_error_is_guji_error(self):
        with pytest.raises(GujiResourceError):
            raise StorageError("storage fail")

    def test_preprocessing_error_is_guji_error(self):
        with pytest.raises(GujiResourceError):
            raise PreprocessingError("preprocessing fail")

    def test_metadata_error_is_adapter_error(self):
        with pytest.raises(AdapterError):
            raise MetadataExtractionError("metadata fail")

    def test_resource_not_found_is_download_error(self):
        with pytest.raises(DownloadError):
            raise ResourceNotFoundError("http://example.com/missing")

    def test_rate_limit_is_download_error(self):
        with pytest.raises(DownloadError):
            raise RateLimitError("http://example.com/api")

    def test_authentication_is_download_error(self):
        with pytest.raises(DownloadError):
            raise AuthenticationError("auth fail")


class TestExceptionAttributes:
    """Tests for exception-specific attributes."""

    def test_adapter_not_found_url(self):
        exc = AdapterNotFoundError("https://unknown.com/book/1")
        assert exc.url == "https://unknown.com/book/1"
        assert "https://unknown.com/book/1" in str(exc)

    def test_resource_not_found_url(self):
        exc = ResourceNotFoundError("https://example.com/img.jpg")
        assert exc.url == "https://example.com/img.jpg"
        assert "https://example.com/img.jpg" in str(exc)

    def test_rate_limit_with_retry_after(self):
        exc = RateLimitError("https://api.example.com", retry_after=60)
        assert exc.url == "https://api.example.com"
        assert exc.retry_after == 60
        assert "60" in str(exc)

    def test_rate_limit_without_retry_after(self):
        exc = RateLimitError("https://api.example.com")
        assert exc.retry_after is None
        assert "https://api.example.com" in str(exc)
