# Tests for downloader modules (unit tests, no network)

import pytest
from bookget.config import DownloadConfig
from bookget.downloaders.base import ImageDownloader
from bookget.downloaders.iiif import IIIFImageDownloader


class TestImageDownloaderVerify:
    """Tests for image verification logic."""

    def setup_method(self):
        self.dl = ImageDownloader(DownloadConfig(min_image_size=100))

    def test_verify_valid_jpeg(self):
        content = b'\xff\xd8\xff' + b'\x00' * 200
        assert self.dl._verify_image(content, "test.jpg") is True

    def test_verify_valid_png(self):
        content = b'\x89PNG' + b'\x00' * 200
        assert self.dl._verify_image(content, "test.png") is True

    def test_verify_too_small(self):
        content = b'\xff\xd8\xff' + b'\x00' * 10  # only 13 bytes
        assert self.dl._verify_image(content, "small.jpg") is False

    def test_verify_unknown_format_passes(self):
        """Unknown formats should still pass (warning logged, not rejected)."""
        content = b'\x00\x00\x00\x00' + b'\x00' * 200
        assert self.dl._verify_image(content, "unknown.dat") is True

    def test_verify_gif(self):
        content = b'GIF8' + b'\x00' * 200
        assert self.dl._verify_image(content, "test.gif") is True

    def test_verify_webp(self):
        content = b'RIFF' + b'\x00' * 200
        assert self.dl._verify_image(content, "test.webp") is True

    def test_verify_tiff_le(self):
        content = b'II\x2a\x00' + b'\x00' * 200
        assert self.dl._verify_image(content, "test.tif") is True

    def test_verify_tiff_be(self):
        content = b'MM\x00\x2a' + b'\x00' * 200
        assert self.dl._verify_image(content, "test.tif") is True


class TestRemoveSecurityHeader:
    """Tests for NLC security header removal."""

    def setup_method(self):
        self.dl = ImageDownloader()

    def test_with_header(self):
        data = b"###SECURED_IMAGE###" + b"\xff\xd8\xff real image"
        result = self.dl._remove_security_header(data)
        assert result == b"\xff\xd8\xff real image"

    def test_without_header(self):
        data = b"\xff\xd8\xff normal image"
        result = self.dl._remove_security_header(data)
        assert result == data

    def test_empty_content(self):
        assert self.dl._remove_security_header(b"") == b""


class TestIIIFImageDownloaderBuildUrl:
    """Tests for IIIF URL building."""

    def setup_method(self):
        self.dl = IIIFImageDownloader()

    def test_build_default_url(self):
        url = self.dl.build_image_url("https://iiif.example.com/image/1234")
        assert url == "https://iiif.example.com/image/1234/full/full/0/default.jpg"

    def test_build_custom_size(self):
        url = self.dl.build_image_url(
            "https://iiif.example.com/image/1234", size="max"
        )
        assert url == "https://iiif.example.com/image/1234/full/max/0/default.jpg"

    def test_build_custom_quality_and_format(self):
        url = self.dl.build_image_url(
            "https://iiif.example.com/image/1234",
            quality="color", format="png"
        )
        assert url == "https://iiif.example.com/image/1234/full/full/0/color.png"

    def test_build_with_region_and_rotation(self):
        url = self.dl.build_image_url(
            "https://iiif.example.com/image/1234",
            region="square", rotation="90"
        )
        assert url == "https://iiif.example.com/image/1234/square/full/90/default.jpg"

    def test_trailing_slash_stripped(self):
        url = self.dl.build_image_url("https://iiif.example.com/image/1234/")
        assert "//" not in url.split("://")[1]

    def test_set_size(self):
        self.dl.set_size("max")
        url = self.dl.build_image_url("https://iiif.example.com/image/1234")
        assert "/max/" in url

    def test_set_quality(self):
        self.dl.set_quality("gray")
        url = self.dl.build_image_url("https://iiif.example.com/image/1234")
        assert "/gray.jpg" in url
