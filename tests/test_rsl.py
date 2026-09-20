"""Offline tests for the Russian State Library adapter."""

import pytest

from bookget.adapters.other.rsl import RslAdapter
from bookget.exceptions import MetadataExtractionError


class TestExtractBookId:
    @pytest.mark.parametrize("url", [
        "https://viewer.rsl.ru/ru/rsl01000001234",
        "https://viewer.rsl.ru/ru/rsl01000001234?page=5",
        "https://viewer.rsl.ru/RSL01000001234",
    ])
    def test_url_forms(self, url):
        assert RslAdapter().extract_book_id(url) == "rsl01000001234"

    def test_url_without_document(self):
        with pytest.raises(MetadataExtractionError):
            RslAdapter().extract_book_id("https://viewer.rsl.ru/")


class TestCheckAccess:
    def test_free_document_passes(self):
        RslAdapter.check_access({"isAvailable": True, "accessLevel": "free"})

    def test_restricted_document_is_reported_up_front(self):
        """Pages would all 403; say so once instead."""
        with pytest.raises(MetadataExtractionError, match="不开放下载"):
            RslAdapter.check_access({
                "isAvailable": False,
                "accessLevel": "restricted",
                "accessInformationMessage": "Документ охраняется авторским правом.",
            })

    def test_login_requirement_is_mentioned(self):
        with pytest.raises(MetadataExtractionError, match="需登录"):
            RslAdapter.check_access({
                "isAvailable": False,
                "isAuthorizationRequired": True,
                "accessLevel": "restricted",
            })


@pytest.mark.asyncio
class TestGetImageList:
    async def _adapter(self, info):
        adapter = RslAdapter()

        async def fake_info(_book_id):
            return info

        adapter._fetch_info = fake_info
        return adapter

    async def test_pages_are_one_indexed(self):
        """page/0 answers 404 — bookget's Go original starts at 0."""
        adapter = await self._adapter({"isAvailable": True, "pageCount": 3})
        images = await adapter.get_image_list("rsl01000001234")
        assert len(images) == 3
        assert images[0].url.endswith("/page/1")
        assert images[-1].url.endswith("/page/3")
        assert images[0].filename == "rsl01000001234_0001.jpg"

    async def test_zero_pages_raises(self):
        adapter = await self._adapter({"isAvailable": True, "pageCount": 0})
        with pytest.raises(MetadataExtractionError, match="没有可下载的页面"):
            await adapter.get_image_list("rsl01000001234")

    async def test_restricted_document_raises_before_listing(self):
        adapter = await self._adapter({
            "isAvailable": False, "accessLevel": "restricted", "pageCount": 560})
        with pytest.raises(MetadataExtractionError, match="不开放下载"):
            await adapter.get_image_list("rsl01004094306")
