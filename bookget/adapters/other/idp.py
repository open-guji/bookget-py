# International Dunhuang Programme (IDP) Adapter
# http://idp.bl.uk/ and its mirrors

import re
from typing import List, Optional
from urllib.parse import quote, unquote_plus, urlparse
import aiohttp

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType
from ...logger import logger
from ...exceptions import MetadataExtractionError

# Item pages carry the image ids in a pair of JS arrays:
#   imageRecnum[0] = "99713";
#   imagePMFolioTitles[0] = "Ch 1 ";
_RECNUM_RE = re.compile(r'imageRecnum\[\d+\]\s*=\s*"(\d+)"')
_FOLIO_RE = re.compile(r'imagePMFolioTitles\[\d+\]\s*=\s*"([^"]*)"')
_UID_RE = re.compile(r'uid=([A-Za-z0-9]+)')
_RECNUM_PARAM_RE = re.compile(r'recnum=(\d+)')
_PM_RE = re.compile(r'[?;&]pm=([^;&#]+)')

_DEFAULT_HOST = "idp.bl.uk"


def _safe_id(pressmark: str) -> str:
    """Pressmarks contain "/" and spaces (Or.8210/S.1) — make a path-safe id."""
    return re.sub(r'[\\/:*?"<>|\s]+', "_", pressmark.strip()).strip("_")


@AdapterRegistry.register
class IDPAdapter(BaseSiteAdapter):
    """Adapter for the International Dunhuang Programme.

    IDP runs the same software on every partner's mirror, and an item lives
    on whichever mirror served its URL, so one adapter covers all of them:

        idp.bl.uk (London)        idp.bnf.fr (Paris)
        idp.bbaw.de (Berlin)      idp.nlc.cn (Beijing)
        idp.korea.ac.kr (Seoul)   idp.afc.ryukoku.ac.jp (Kyoto)
        idp.orientalstudies.ru (St Petersburg)

    URL patterns:
    - Item:  http://idp.bbaw.de/database/oo_scroll_h.a4d?uid={uid};bst=1;
             recnum={recnum};index=1;img=1
    - By pressmark: http://idp.bbaw.de/database/oo_loader.a4d?pm={pressmark}
      (redirects to the uid form)
    - Image: http://{mirror}/image_IDP.a4d?type=loadRotatedMainImage;
             recnum={recnum};rotate=0;imageType=_L

    NOTE 1: `uid` is a **search-session token, not an item id**, and it only
    works together with that session's `recnum`. Measured on idp.bbaw.de:
    uid+recnum returns the right item; recnum alone or with a foreign uid
    returns an empty page; and uid alone silently returns a default item
    (Or.8210/S.1, the Diamond Sutra) rather than failing. So an item page is
    fetched at the URL the user gave us, never rebuilt from the uid alone,
    and `pm=` (the pressmark) is preferred as the id when it is present
    because it is the only stable one.

    NOTE 2: the mirrors are legacy servers and several answer on **http only**
    (https connects are refused), so URLs are used with the scheme they came
    with rather than upgraded.
    """

    site_name = "国际敦煌项目 (IDP)"
    site_id = "idp"
    site_domains = [
        "idp.bl.uk",
        "idp.bnf.fr",
        "idp.bbaw.de",
        "idp.nlc.cn",
        "idp.korea.ac.kr",
        "idp.afc.ryukoku.ac.jp",
        "idp.orientalstudies.ru",
    ]

    supports_iiif = False
    supports_images = True
    supports_text = False

    def __init__(self, config=None):
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None
        # uid -> (scheme, host) of the mirror the URL came from. An item only
        # exists on its own mirror, and the image endpoint is on that same
        # host, so this has to survive from extract_book_id to get_image_list.
        self._origins: dict = {}
        self._pages: dict = {}
        # book_id -> the URL the caller gave us. The item page cannot be
        # rebuilt from the id alone (see NOTE 1), so it has to be kept.
        self._source_urls: dict = {}

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.get_headers())
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    def extract_book_id(self, url: str) -> str:
        """Derive an id, remembering the mirror and the exact source URL."""
        pressmark = _PM_RE.search(url)
        uid = _UID_RE.search(url)
        recnum = _RECNUM_PARAM_RE.search(url)

        if pressmark:
            # The pressmark is the item's real, stable identifier.
            book_id = _safe_id(unquote_plus(pressmark.group(1)))
        elif uid and recnum:
            book_id = f"{uid.group(1)}_{recnum.group(1)}"
        elif uid:
            raise MetadataExtractionError(
                f"IDP 条目地址缺少 recnum：{url}\n"
                f"（只带 uid 时站点会**静默返回另一件默认藏品**，不是你要的那件；"
                f"请用条目页完整地址，形如 "
                f"oo_scroll_h.a4d?uid=5475972796;bst=1;recnum=69129;index=1;img=1）")
        else:
            raise MetadataExtractionError(
                f"不是 IDP 条目地址（既无 pm= 也无 uid=）：{url}")

        parsed = urlparse(url)
        if parsed.netloc:
            self._origins[book_id] = (parsed.scheme or "http", parsed.netloc)
        self._source_urls[book_id] = url
        return book_id

    def _origin(self, book_id: str):
        return self._origins.get(book_id, ("http", _DEFAULT_HOST))

    def item_url(self, book_id: str) -> str:
        """The page to fetch: the caller's URL when we have it."""
        source = self._source_urls.get(book_id)
        if source:
            return source
        # Only reachable for a pressmark id, which the loader resolves on
        # its own (it redirects to a fresh uid+recnum page).
        scheme, host = self._origin(book_id)
        return f"{scheme}://{host}/database/oo_loader.a4d?pm={quote(book_id)}"

    def image_url(self, book_id: str, recnum: str) -> str:
        scheme, host = self._origin(book_id)
        return (f"{scheme}://{host}/image_IDP.a4d?"
                f"type=loadRotatedMainImage;recnum={recnum};rotate=0;imageType=_L")

    @staticmethod
    def parse_item_page(html: str):
        """Pull (recnums, folio titles) out of an item page."""
        return _RECNUM_RE.findall(html), [t.strip() for t in _FOLIO_RE.findall(html)]

    async def _fetch_item_page(self, book_id: str) -> str:
        url = self.item_url(book_id)
        session = await self.get_session()
        try:
            async with session.get(url) as response:
                response.raise_for_status()
                return await response.text()
        except Exception as e:
            raise MetadataExtractionError(
                f"[idp] 取条目页失败：{url}（{e}）") from e

    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        html = await self._fetch_item_page(book_id)
        recnums, folios = self.parse_item_page(html)
        self._pages[book_id] = recnums

        _, host = self._origin(book_id)
        metadata = BookMetadata(
            source_id=book_id,
            source_url=self.item_url(book_id),
            source_site=self.site_id,
            index_id=index_id,
        )
        # The pressmark is the only item label that reads the same on every
        # mirror — the surrounding page is in the mirror's own language.
        metadata.title = folios[0] if folios else f"IDP {book_id}"
        metadata.collection_unit = host
        metadata.pages = len(recnums)
        return metadata

    async def get_image_list(self, book_id: str) -> List[Resource]:
        recnums = self._pages.get(book_id)
        if recnums is None:
            html = await self._fetch_item_page(book_id)
            recnums, _ = self.parse_item_page(html)
            self._pages[book_id] = recnums

        if not recnums:
            # Silence here would report a successful download of nothing.
            raise MetadataExtractionError(
                f"[idp] 条目页里没有图片记录：{self.item_url(book_id)}\n"
                f"（该 uid 可能无影像，或镜像站改版了）")

        logger.info(f"IDP {book_id}: {len(recnums)} images on {self._origin(book_id)[1]}")
        return [
            Resource(
                url=self.image_url(book_id, recnum),
                resource_type=ResourceType.IMAGE,
                order=index,
                page=str(index),
                filename=f"{book_id}_{index:04d}.jpg",
            )
            for index, recnum in enumerate(recnums, start=1)
        ]
