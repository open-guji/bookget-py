# CText (中国哲学书电子化计划) Adapter
# https://ctext.org/

import asyncio
import html as html_module
import re
from typing import List, Optional
import aiohttp
from html.parser import HTMLParser

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType, Creator
from ...models.search import MatchedResource, SearchResponse, SearchResult
from ...text_parsers.base import StructuredText
from ...text_parsers.ctext_parser import CTextParser
from ...logger import logger
from ...exceptions import MetadataExtractionError


class CTextHTMLParser(HTMLParser):
    """HTML parser for extracting text from CText pages (Library and Wiki)."""
    
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.target_classes = {"ctext", "etext", "wikiitem", "libtarget"}
        self.exclude_ids = {"menu", "commcont", "pagedir"}
        self.depth = 0
        self.capture_depth = 0
        self.exclude_depth = 0
    
    def handle_starttag(self, tag, attrs):
        self.depth += 1
        attrs_dict = {k: v for k, v in attrs}
        
        # Check for exclusions (menu, comments, etc.)
        if attrs_dict.get("id") in self.exclude_ids or "noprint" in attrs_dict.get("class", ""):
            if self.exclude_depth == 0:
                self.exclude_depth = self.depth
            return

        if self.exclude_depth > 0:
            return

        # Identify target content containers
        cls = attrs_dict.get("class", "")
        is_target = any(c in cls for c in self.target_classes)
        
        # Also check for specific IDs that are always content
        if attrs_dict.get("id") == "maintext":
            is_target = True

        if is_target:
            if self.capture_depth == 0:
                self.capture_depth = self.depth
    
    def handle_endtag(self, tag):
        if self.exclude_depth == self.depth:
            self.exclude_depth = 0
        
        if self.capture_depth == self.depth:
            self.capture_depth = 0
            
        self.depth -= 1
    
    def handle_data(self, data):
        if self.capture_depth > 0 and self.exclude_depth == 0:
            text = data.strip()
            if text:
                # Basic cleaning: ignore [查看正文] and similar UI elements
                if text not in ("[", "]", "查看正文", "View reading edition"):
                    self.text_parts.append(text)
    
    def get_text(self) -> str:
        return "\n\n".join(self.text_parts)


@AdapterRegistry.register
class CTextAdapter(BaseSiteAdapter):
    """
    Adapter for 中国哲学书电子化计划 (Chinese Text Project).

    CText is one of the most important online databases of pre-modern
    Chinese texts, providing full-text transcriptions with annotations.

    CText has two main content systems:
    1. 原典 (Library): curated classical texts with path-based URLs
       - https://ctext.org/analects/xue-er/zh
    2. 維基 (Wiki): user-contributed texts
       - Book level:    https://ctext.org/wiki.pl?if=gb&res={res_id}
       - Chapter level: https://ctext.org/wiki.pl?if=gb&chapter={chapter_id}

    Other URL patterns:
    - Text by node: https://ctext.org/text.pl?node={node_id}
    - Library images: https://ctext.org/library.pl?if=zh&file={file_id}&page={n}
    """
    
    site_name = "中国哲学书电子化计划 (CText)"
    site_id = "ctext"
    site_domains = ["ctext.org"]
    
    supports_iiif = False
    supports_images = True   # Has scanned images for some texts
    supports_text = True     # Full text transcriptions
    supports_search = True
    
    BASE_URL = "https://ctext.org"
    API_URL = "https://api.ctext.org"
    
    default_headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    }
    
    def __init__(self, config=None):
        super().__init__(config)
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(headers=self.get_headers())
        return self._session
    
    def extract_book_id(self, url: str) -> str:
        """Extract text identifier from CText URL.

        Returns book_id in one of these formats:
        - "path:{slug}"           — 原典 text, e.g. path:analects/xue-er
        - "wiki-book:{res_id}"    — 維基 book level (目录页)
        - "wiki-chapter:{ch_id}"  — 維基 chapter level (正文页)
        - "library:{file_id}"     — 图书馆扫描件
        - "node:{node_id}"        — text.pl node reference
        """
        # --- library.pl ---
        match = re.search(r'library\.pl.*[?&]file=([^&]+)', url)
        if match:
            return f"library:{match.group(1)}"

        # --- wiki.pl ---
        if 'wiki.pl' in url:
            # wiki chapter: ?chapter=3658735
            match = re.search(r'[?&]chapter=(\d+)', url)
            if match:
                return f"wiki-chapter:{match.group(1)}"
            # wiki book: ?res=1347940  (also matches ?if=gb&res=1347940)
            match = re.search(r'[?&]res=(\d+)', url)
            if match:
                return f"wiki-book:{match.group(1)}"
            # bare wiki.pl?if=gb — this is just the wiki index, not a book
            raise MetadataExtractionError(
                f"Wiki URL missing res= or chapter= parameter: {url}")

        # --- text.pl ---
        match = re.search(r'[?&]node=(\d+)', url)
        if match:
            return f"node:{match.group(1)}"

        # --- path-based URL like /analects/xue-er/zh ---
        match = re.search(r'ctext\.org/([^?&#]+)', url)
        if match:
            path = match.group(1)
            # Remove trailing language codes
            path = re.sub(r'/(zh|zhs|en|ens)$', '', path)
            if path and not path.startswith(
                    ('text.pl', 'wiki.pl', 'library.pl', 'api',
                     'datawiki.pl', 'dictionary.pl', 'discuss.pl',
                     'resource.pl', 'searchxml.pl', 'account.pl')):
                return f"path:{path}"

        raise MetadataExtractionError(
            f"Could not extract text ID from URL: {url}")
    
    def _build_page_url(self, id_type: str, id_value: str) -> str:
        """Build the HTML page URL for a given book_id."""
        if id_type == "path":
            return f"{self.BASE_URL}/{id_value}/zh"
        elif id_type == "node":
            return f"{self.BASE_URL}/text.pl?node={id_value}"
        elif id_type == "wiki-book":
            return f"{self.BASE_URL}/wiki.pl?if=gb&res={id_value}"
        elif id_type == "wiki-chapter":
            return f"{self.BASE_URL}/wiki.pl?if=gb&chapter={id_value}"
        elif id_type == "library":
            file_num = id_value.split("&")[0] if "&" in id_value else id_value
            return f"{self.BASE_URL}/library.pl?if=zh&file={file_num}&page=1"
        return f"{self.BASE_URL}/{id_value}"

    def _build_api_url(self, id_type: str, id_value: str) -> Optional[str]:
        """Build the API URL. Returns None if API is not applicable."""
        if id_type == "path":
            return f"{self.API_URL}/gettext?urn=ctp:{id_value}"
        elif id_type == "node":
            return f"{self.API_URL}/gettext?node={id_value}"
        elif id_type == "wiki-chapter":
            # wiki chapter URN: ctp:ws{chapter_id}
            return f"{self.API_URL}/gettext?urn=ctp:ws{id_value}"
        # wiki-book (ctp:wb...) requires auth — no API
        # library — no text API
        return None

    async def get_metadata(self, book_id: str, index_id: str = "") -> BookMetadata:
        """Fetch metadata for a CText resource."""
        metadata = await self._get_metadata_internal(book_id)
        metadata.index_id = index_id
        return metadata

    async def _get_metadata_internal(self, book_id: str) -> BookMetadata:
        id_type, id_value = book_id.split(":", 1) if ":" in book_id else ("path", book_id)

        # Library files → parse library page
        if id_type == "library":
            return await self._parse_library_metadata(id_value)

        # Wiki book (res) → parse HTML metadata table (API requires auth)
        if id_type == "wiki-book":
            return await self._parse_wiki_book_metadata(id_value)

        # For path and wiki-chapter, try API first
        api_url = self._build_api_url(id_type, id_value)
        if api_url:
            session = await self.get_session()
            try:
                async with session.get(api_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        # Check for auth error in JSON
                        if "error" not in data:
                            return self._parse_api_metadata(data, book_id)
            except Exception as e:
                logger.warning(f"API failed, trying HTML: {e}")

        # Fallback to HTML
        return await self._parse_html_metadata(book_id)
    
    def _parse_api_metadata(self, data: dict, book_id: str) -> BookMetadata:
        """Parse CText API response."""
        metadata = BookMetadata(source_id=book_id)
        
        metadata.title = data.get("title", "")
        metadata.dynasty = data.get("dynasty", "")
        
        author = data.get("author", "")
        if author:
            metadata.creators.append(Creator(name=author))
        
        # CText uses classic Chinese text categories
        metadata.category = data.get("category", "")
        metadata.language = "lzh"  # Classical Chinese
        
        metadata.raw_metadata = data
        return metadata
    
    async def _parse_html_metadata(self, book_id: str) -> BookMetadata:
        """Fallback: parse metadata from HTML page."""
        metadata = BookMetadata(source_id=book_id)
        id_type, id_value = book_id.split(":", 1) if ":" in book_id else ("path", book_id)
        url = self._build_page_url(id_type, id_value)

        session = await self.get_session()
        try:
            async with session.get(url) as response:
                if response.status != 200:
                    return metadata
                html = await response.text()

                # Extract URN from meta tag
                urn_match = re.search(r'<meta name="ctp-urn" content="([^"]+)"', html)
                if urn_match:
                    metadata.raw_metadata = {"urn": urn_match.group(1)}

                # Extract title from <title> tag
                title_match = re.search(r'<title>([^<]+)</title>', html)
                if title_match:
                    title = title_match.group(1)
                    # Remove " - 中國哲學書電子化計劃" suffix
                    title = re.sub(r'\s*[-–]\s*中[國国]哲[學学].*$', '', title)
                    metadata.title = title.strip()

                metadata.language = "lzh"
                return metadata
        except Exception as e:
            logger.warning(f"Failed to parse HTML: {e}")
            return metadata

    async def _parse_wiki_book_metadata(self, res_id: str) -> BookMetadata:
        """Parse metadata from a wiki book page (res= URL).

        The wiki book page has a structured metadata table with fields like:
        作者, 成書年代, 版本, 其它名稱, etc.
        It also lists all chapters of the book.
        """
        metadata = BookMetadata(source_id=f"wiki-book:{res_id}")
        url = f"{self.BASE_URL}/wiki.pl?if=gb&res={res_id}"

        session = await self.get_session()
        try:
            async with session.get(url) as response:
                if response.status != 200:
                    return metadata
                html = await response.text()

                # URN
                urn_match = re.search(
                    r'<meta name="ctp-urn" content="([^"]+)"', html)
                if urn_match:
                    metadata.raw_metadata = {"urn": urn_match.group(1)}

                # Title from <title> tag
                title_match = re.search(r'<title>([^<]+)</title>', html)
                if title_match:
                    import html as html_mod
                    title = html_mod.unescape(title_match.group(1))
                    title = re.sub(r'\s*[-–]\s*中[國国]哲[學学].*$', '', title)
                    metadata.title = title.strip()

                # Metadata table: <th class="colhead2">KEY</th><td ...>VALUE</td>
                for m in re.finditer(
                        r'<th class="colhead2">(.*?)</th>'
                        r'<td class="resrow"[^>]*>(.*?)</td>',
                        html, re.DOTALL):
                    key = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                    val = re.sub(r'<[^>]+>', '', m.group(2)).strip()
                    if key == '作者' and val and val != '暫缺':
                        metadata.creators.append(Creator(name=val))
                    elif key == '成書年代' and val:
                        metadata.dynasty = val
                    elif key == '其它名稱' and val:
                        metadata.alt_titles.append(val)

                # Extract chapter list for volumes count
                # In HTML, & is encoded as &amp; so match both forms
                chapter_ids = list(dict.fromkeys(
                    re.findall(r'(?:[?&]|&amp;)chapter=(\d+)', html)))
                if chapter_ids:
                    metadata.volumes = len(chapter_ids)
                    metadata.raw_metadata = metadata.raw_metadata or {}
                    metadata.raw_metadata["chapter_ids"] = chapter_ids

                metadata.language = "lzh"
                return metadata
        except Exception as e:
            logger.warning(f"Failed to parse wiki book metadata: {e}")
            return metadata

    async def _parse_library_metadata(self, file_id: str) -> BookMetadata:
        """Parse metadata from library.ctext.org page."""
        metadata = BookMetadata(source_id=f"library:{file_id}")

        file_num = file_id.split("&")[0] if "&" in file_id else file_id
        url = f"{self.BASE_URL}/library.pl?if=zh&file={file_num}&page=1"

        session = await self.get_session()

        try:
            async with session.get(url) as response:
                if response.status != 200:
                    return metadata

                html = await response.text()

                # Extract title from breadcrumb navigation
                # Format: Library -> 濃情快史 -> 濃情快史一
                breadcrumb_match = re.search(r'<span itemprop="title">([^<]+)</span>', html)
                if breadcrumb_match:
                    metadata.title = breadcrumb_match.group(1)

                # Extract total pages
                pages_match = re.search(r'/(\d+)\s*<', html)
                if pages_match:
                    metadata.pages = int(pages_match.group(1))

                metadata.language = "lzh"
                metadata.supports_images = True
                return metadata

        except Exception as e:
            logger.warning(f"Failed to parse library metadata: {e}")
            return metadata
    
    async def get_image_list(self, book_id: str) -> List[Resource]:
        """Get list of scanned images if available."""
        # CText has images for some texts via library.ctext.org
        id_type, id_value = book_id.split(":", 1) if ":" in book_id else ("path", book_id)

        # Check if this is a library file
        if id_type == "library":
            return await self._get_library_images(id_value)

        # For regular texts, try to find associated library file
        # This would require checking if the text has a scanned version
        return []

    async def _get_library_images(self, file_id: str) -> List[Resource]:
        """Extract images from a library.ctext.org document."""
        session = await self.get_session()
        resources = []

        # Parse file_id which might be "file_id" or "file_id&page=N"
        file_num = file_id.split("&")[0] if "&" in file_id else file_id

        # Get the first page to find total pages
        library_url = f"{self.BASE_URL}/library.pl?if=zh&file={file_num}&page=1"

        try:
            async with session.get(library_url) as response:
                if response.status != 200:
                    logger.warning(f"Library page not found: {library_url}")
                    return []

                html = await response.text()

                # Extract total pages from pagination like "/84"
                pages_match = re.search(r'/(\d+)\s*<', html)
                total_pages = int(pages_match.group(1)) if pages_match else 1

                # Extract the image path pattern from the HTML
                # Look for <img src='https://library.ctext.org/...'
                img_match = re.search(r"src='(https://library\.ctext\.org/([^/]+)/([^/]+)_(\d+)\.jpg)", html)

                if not img_match:
                    logger.warning("Could not find image pattern in library page")
                    return []

                # Extract path components
                base_path = img_match.group(2)  # e.g., "h0063506"
                book_id_part = img_match.group(3)  # e.g., "h0063506"

                # Generate all image URLs
                for page_num in range(1, total_pages + 1):
                    img_url = f"https://library.ctext.org/{base_path}/{book_id_part}_{page_num:04d}.jpg"

                    resource = Resource(
                        url=img_url,
                        resource_type=ResourceType.IMAGE,
                        order=page_num,
                        page=str(page_num),
                        filename=f"{book_id_part}_{page_num:04d}.jpg"
                    )
                    resources.append(resource)

                logger.info(f"Found {len(resources)} images for library file {file_num}")
                return resources

        except Exception as e:
            logger.error(f"Failed to extract library images: {e}")
            return []
    
    async def get_structured_text(self, book_id: str, index_id: str = "") -> Optional[StructuredText]:
        """Get structured text with chapter/paragraph hierarchy.

        Returns StructuredText preserving all structural information.
        For wiki-book IDs, fetches all chapters individually.
        """
        id_type, id_value = book_id.split(":", 1) if ":" in book_id else ("path", book_id)
        url = self._build_page_url(id_type, id_value)
        text_parser = CTextParser()

        # Library files don't have text
        if id_type == "library":
            return None

        # Wiki book: fetch each chapter separately
        if id_type == "wiki-book":
            return await self._get_wiki_book_structured(id_value, url, text_parser, index_id=index_id)

        # Try API first for path / node / wiki-chapter
        api_url = self._build_api_url(id_type, id_value)
        if api_url:
            session = await self.get_session()
            try:
                async with session.get(api_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "error" not in data and "fulltext" in data:
                            return text_parser.parse_classic(data, book_id, url, index_id=index_id)
            except Exception as e:
                logger.warning(f"API text fetch failed: {e}")

        # Fallback: parse HTML
        return await self._get_structured_from_html(book_id, url, text_parser, index_id=index_id)

    async def _get_wiki_book_structured(
        self, res_id: str, url: str, text_parser: CTextParser, index_id: str = ""
    ) -> Optional[StructuredText]:
        """Fetch all chapters of a wiki book as structured text."""
        metadata = await self._parse_wiki_book_metadata(res_id)
        chapter_ids = (metadata.raw_metadata or {}).get("chapter_ids", [])

        if not chapter_ids:
            logger.warning(f"No chapters found for wiki-book:{res_id}")
            return None

        logger.info(
            f"Fetching {len(chapter_ids)} chapters for '{metadata.title}'")

        chapter_data = []
        session = await self.get_session()
        delay = getattr(getattr(self.config, 'download', None), 'request_delay', 0.5) if self.config else 0.5

        for i, ch_id in enumerate(chapter_ids):
            api_url = f"{self.API_URL}/gettext?urn=ctp:ws{ch_id}"
            try:
                async with session.get(api_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if "error" not in data and "fulltext" in data:
                            chapter_data.append((ch_id, data))
                            logger.info(
                                f"  [{i+1}/{len(chapter_ids)}] "
                                f"{data.get('title', ch_id)}")
                            if delay > 0 and i < len(chapter_ids) - 1:
                                await asyncio.sleep(delay)
                            continue
            except Exception as e:
                logger.warning(f"API failed for chapter {ch_id}: {e}")

            # Fallback: get HTML text for this chapter
            html_parts = await self._get_html_text_parts(
                f"wiki-chapter:{ch_id}")
            if html_parts:
                chapter_data.append(
                    (ch_id, {"title": f"Chapter {i+1}", "fulltext": html_parts}))

        if not chapter_data:
            return None

        book_meta = {
            "title": metadata.title,
            "dynasty": metadata.dynasty,
            "volumes": metadata.volumes,
            "urn": (metadata.raw_metadata or {}).get("urn", ""),
        }
        if metadata.creators:
            book_meta["authors"] = [
                {"name": c.name, "role": c.role or "撰", "dynasty": c.dynasty or ""}
                for c in metadata.creators
            ]

        return text_parser.parse_wiki_book(
            chapter_data, book_meta, f"wiki-book:{res_id}", url, index_id=index_id
        )

    async def _get_structured_from_html(
        self, book_id: str, url: str, text_parser: CTextParser, index_id: str = ""
    ) -> Optional[StructuredText]:
        """Extract structured text from HTML page (fallback)."""
        html_parts = await self._get_html_text_parts(book_id)
        if not html_parts:
            return None

        # Get title from HTML
        id_type, id_value = book_id.split(":", 1) if ":" in book_id else ("path", book_id)
        page_url = self._build_page_url(id_type, id_value)
        session = await self.get_session()
        title = book_id
        try:
            async with session.get(page_url) as response:
                if response.status == 200:
                    html = await response.text()
                    title_match = re.search(r'<title>([^<]+)</title>', html)
                    if title_match:
                        title = re.sub(
                            r'\s*[-–]\s*中[國国]哲[學学].*$', '',
                            title_match.group(1)).strip()
        except Exception:
            pass

        return text_parser.parse_html_text(html_parts, title, book_id, url, index_id=index_id)

    async def _get_html_text_parts(self, book_id: str) -> Optional[list[str]]:
        """Extract text parts from HTML page as a list of strings."""
        id_type, id_value = book_id.split(":", 1) if ":" in book_id else ("path", book_id)
        url = self._build_page_url(id_type, id_value)

        session = await self.get_session()
        try:
            async with session.get(url) as response:
                if response.status != 200:
                    return None
                html = await response.text()
                parser = CTextHTMLParser()
                parser.feed(html)
                return parser.text_parts if parser.text_parts else None
        except Exception as e:
            logger.warning(f"Failed to get text from HTML: {e}")
            return None
    
    # ------------------------------------------------------------------
    # Search (supports_search = True)
    # ------------------------------------------------------------------

    # CJK variant pairs for classical Chinese book titles.
    # Same set as wikisource adapter; shared for consistent matching.
    _CJK_VARIANTS: dict[str, str] = {
        '注': '註', '註': '注',
        '于': '於', '於': '于',
        '台': '臺', '臺': '台',
        '里': '裏', '裏': '里',
        '群': '羣', '羣': '群',
        '峰': '峯', '峯': '峰',
        '叙': '敘', '敘': '叙',
        '踪': '蹤', '蹤': '踪',
        '线': '綫', '綫': '线',
        '并': '並', '並': '并',
        '灾': '災', '災': '灾',
        '余': '餘', '餘': '余',
        '萬': '万', '万': '萬',
        '與': '与', '与': '與',
        '書': '书', '书': '書',
        '經': '经', '经': '經',
        '傳': '传', '传': '傳',
        '記': '记', '记': '記',
        '說': '说', '说': '說',
        '學': '学', '学': '學',
        '義': '义', '义': '義',
        '國': '国', '国': '國',
        '圖': '图', '图': '圖',
        '爲': '為', '為': '爲',
        '觀': '观', '观': '觀',
        '詩': '诗', '诗': '詩',
        '禮': '礼', '礼': '禮',
        '論': '论', '论': '論',
        '續': '续', '续': '續',
        '補': '补', '补': '補',
        '訂': '订', '订': '訂',
        '鑑': '鉴', '鉴': '鑑',
        '類': '类', '类': '類',
        '彙': '汇', '汇': '彙',
        '歷': '历', '历': '歷',
        '筆': '笔', '笔': '筆',
        # Additional pairs common in book titles
        '語': '语', '语': '語',
        '詞': '词', '词': '詞',
        '譜': '谱', '谱': '譜',
        '誌': '志', '志': '誌',
        '範': '范', '范': '範',
        '錄': '录', '录': '錄',
        '餘': '馀',  # 餘→余 already above; add 餘→馀
        '閣': '阁', '阁': '閣',
        '閱': '阅', '阅': '閱',
        '問': '问', '问': '問',
        '門': '门', '门': '門',
        '關': '关', '关': '關',
        '開': '开', '开': '開',
        '間': '间', '间': '間',
        '陽': '阳', '阳': '陽',
        '陰': '阴', '阴': '陰',
        '雲': '云', '云': '雲',
        '電': '电', '电': '電',
        '風': '风', '风': '風',
        '龍': '龙', '龙': '龍',
        '齋': '斋', '斋': '齋',
        '齊': '齐', '齐': '齊',
        '點': '点', '点': '點',
        '黃': '黄', '黄': '黃',
        '體': '体', '体': '體',
        '驗': '验', '验': '驗',
        '馬': '马', '马': '馬',
        '華': '华', '华': '華',
        '藝': '艺', '艺': '藝',
        '蘭': '兰', '兰': '蘭',
        '舊': '旧', '旧': '舊',
        '聖': '圣', '圣': '聖',
        '職': '职', '职': '職',
        '經': '经',  # already above, but ensure coverage
        '緯': '纬', '纬': '緯',
        '紀': '纪', '纪': '紀',
        '總': '总', '总': '總',
        '會': '会', '会': '會',
        '選': '选', '选': '選',
        '遺': '遗', '遗': '遺',
        '運': '运', '运': '運',
        '達': '达', '达': '達',
        '輿': '舆', '舆': '輿',
        '軍': '军', '军': '軍',
        '質': '质', '质': '質',
        '譯': '译', '译': '譯',
        '議': '议', '议': '議',
        '證': '证', '证': '證',
        '話': '话', '话': '話',
        '評': '评', '评': '評',
        '識': '识', '识': '識',
        '農': '农', '农': '農',
        '寶': '宝', '宝': '寶',
        '實': '实', '实': '實',
        '廣': '广', '广': '廣',
        '樂': '乐', '乐': '樂',
        '漢': '汉', '汉': '漢',
        '靈': '灵', '灵': '靈',
        '釋': '释', '释': '釋',
        '鏡': '镜', '镜': '鏡',
        '長': '长', '长': '長',
        '雜': '杂', '杂': '雜',
        '難': '难', '难': '難',
        '顯': '显', '显': '顯',
        '飛': '飞', '飞': '飛',
        '後': '后', '后': '後',
        '從': '从', '从': '從',
        '術': '术', '术': '術',
        '兿': '艺',  # variant form
    }

    # Removable title prefixes
    _REMOVABLE_PREFIXES: list[str] = ['欽定', '御定', '御纂', '御製', '御選']

    # Role words to strip from author names
    _ROLE_WORDS = re.compile(r'[撰注疏輯校點箋補纂訂譯編釋]$')

    # Dynasty extraction pattern: （朝代）作者
    _DYNASTY_AUTHOR_RE = re.compile(r'^[（(]([^）)]+)[）)](.*)')

    # Search result patterns
    _SEARCH_LI_RE = re.compile(r'<li([^>]*)>(.*?)</li>', re.DOTALL)
    # Match ALL <a> tags inside booksearchresult div — we take the last one
    _SEARCH_LINKS_RE = re.compile(
        r'<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>'
    )
    _SEARCH_AUTHOR_RE = re.compile(
        r'<span style="font-weight: bold;">([^<]+)</span>'
    )
    _SEARCH_TOTAL_RE = re.compile(r'共(\d+)筆資料')

    async def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> SearchResponse:
        """Search CText for books matching *query*.

        Uses the CText API (api.ctext.org/searchtexts) which returns all
        matching books with URN identifiers. This API is more reliable than
        the web search (searchbooks.pl) and is not affected by IP bans.
        """
        all_books = await self._search_books_api(query)

        # Apply offset/limit
        total_hits = len(all_books)
        page_results = all_books[offset:offset + limit]
        has_more = (offset + limit) < total_hits

        results = [
            SearchResult(
                title=book["title"],
                url=self._urn_to_url(book.get("urn", "")),
                snippet=book.get("urn", ""),
                source_site=self.site_id,
                categories=(
                    ["classic"] if not book.get("urn", "").startswith("ctp:wb")
                    else ["wiki"]
                ),
            )
            for book in page_results
            if book.get("urn")  # Skip entries without URN
        ]

        return SearchResponse(
            query=query,
            results=results,
            total_hits=total_hits,
            has_more=has_more,
            continuation=str(offset + limit) if has_more else "",
        )

    async def _search_books_api(self, query: str) -> list[dict]:
        """Call CText API searchtexts endpoint.

        Returns: list of {"title": str, "urn": str}
        The API returns ALL matching results (no pagination needed).
        """
        import urllib.parse
        encoded = urllib.parse.quote(query)
        api_url = f"{self.API_URL}/searchtexts?title={encoded}"

        session = await self.get_session()
        try:
            async with session.get(api_url) as response:
                if response.status != 200:
                    logger.warning(
                        f"CText API search returned status {response.status}")
                    return []
                data = await response.json()
                return data.get("books", [])
        except Exception as e:
            logger.warning(f"CText API search failed: {e}")
            return []

    async def _get_text_info(self, urn: str) -> dict:
        """Get metadata for a CText URN via gettextinfo API.

        Returns dict with keys: title, author, dynasty, etc.
        """
        api_url = f"{self.API_URL}/gettextinfo?urn={urn}"
        session = await self.get_session()
        try:
            async with session.get(api_url) as response:
                if response.status != 200:
                    return {}
                data = await response.json()
                if "error" in data:
                    return {}
                return data
        except Exception as e:
            logger.warning(f"CText gettextinfo failed for {urn}: {e}")
            return {}

    def _urn_to_url(self, urn: str) -> str:
        """Convert a CText URN to a human-readable URL.

        - ctp:book-of-changes  → https://ctext.org/book-of-changes/zh
        - ctp:wb129518         → https://ctext.org/wiki.pl?if=gb&res=129518
        """
        if not urn:
            return ""
        # Remove ctp: prefix
        value = urn.removeprefix("ctp:")
        if value.startswith("wb"):
            res_id = value[2:]
            return f"{self.BASE_URL}/wiki.pl?if=gb&res={res_id}"
        elif value.startswith("ws"):
            ch_id = value[2:]
            return f"{self.BASE_URL}/wiki.pl?if=gb&chapter={ch_id}"
        else:
            return f"{self.BASE_URL}/{value}/zh"

    # ------------------------------------------------------------------
    # match_book — exact title + author matching for book index
    # ------------------------------------------------------------------

    async def match_book(
        self,
        title: str,
        authors: list[str] | None = None,
        delay: float = 1.0,
    ) -> list[MatchedResource]:
        """Match a book by title + author against CText.

        Strategy (all via API, no web scraping):
        1. Call searchtexts API with title variants
        2. Filter by exact title match
        3. For candidates, call gettextinfo API to verify author/dynasty
        4. Return matched resources

        Args:
            title: Book title (e.g. "周易")
            authors: Author names for filtering (e.g. ["王弼"])
            delay: Seconds between API requests

        Returns:
            List of matched resources.
        """
        authors = authors or []
        found: list[MatchedResource] = []
        seen_urls: set[str] = set()

        def add_result(url: str, res_id: str = "ctext",
                       name: str = "CText", details: str = "",
                       quality: dict | None = None):
            if url in seen_urls:
                return
            seen_urls.add(url)
            found.append(MatchedResource(
                id=res_id, name=name, url=url, details=details,
                quality=quality or {},
            ))

        # Generate title variants
        title_variants = self._generate_title_variants(title)

        # Search API with each variant until we find matches
        search_queries = list(dict.fromkeys(title_variants))[:3]
        all_books: list[dict] = []
        seen_urns: set[str] = set()

        for i, query in enumerate(search_queries):
            if i > 0:
                await asyncio.sleep(delay)
            books = await self._search_books_api(query)
            for b in books:
                urn = b.get("urn", "")
                if urn and urn not in seen_urns:
                    seen_urns.add(urn)
                    all_books.append(b)
            # If first query has exact title matches, skip variants
            if books and any(
                self._title_matches(b["title"], title_variants)
                for b in books
            ):
                break

        # Filter by exact title match
        candidates = [
            b for b in all_books
            if b.get("urn") and self._title_matches(
                b["title"], title_variants)
        ]

        if not candidates:
            return found

        # If no authors to filter, just return all title-matched candidates
        # grouped by URN type (prefer classic over wiki duplicates)
        if not authors:
            # Return first classic match, or first wiki match
            for b in candidates:
                urn = b["urn"]
                url = self._urn_to_url(urn)
                is_classic = not urn.startswith("ctp:wb")
                add_result(
                    url=url,
                    res_id="ctext",
                    name="CText（原典）" if is_classic else "CText",
                )
            return found

        # With authors: verify via gettextinfo API
        # Pass 1: strict author match
        # Pass 2 (fallback): surname match or accept all if few candidates
        author_matched: list[tuple[dict, dict]] = []   # (book, info)
        surname_matched: list[tuple[dict, dict]] = []
        unmatched: list[tuple[dict, dict]] = []

        for i, b in enumerate(candidates):
            if i > 0:
                await asyncio.sleep(delay)

            urn = b["urn"]
            info = await self._get_text_info(urn)
            if not info:
                continue

            result_author = info.get("author", "")
            if not result_author:
                # No author info — accept as match
                author_matched.append((b, info))
            elif self._author_matches(result_author, authors):
                author_matched.append((b, info))
            elif self._surname_matches(result_author, authors):
                surname_matched.append((b, info))
            else:
                unmatched.append((b, info))

        # Use strict matches if any; else surname; else accept all if ≤ 3
        if author_matched:
            accepted = author_matched
        elif surname_matched:
            accepted = surname_matched
        elif len(unmatched) <= 3:
            # Few candidates with exact title match — likely the same work
            accepted = unmatched
        else:
            accepted = []

        for b, info in accepted:
            urn = b["urn"]
            url = self._urn_to_url(urn)
            is_classic = not urn.startswith("ctp:wb")
            result_author = info.get("author", "")
            dynasty_info = info.get("dynasty", {})
            dynasty_name = ""
            if isinstance(dynasty_info, dict):
                d_from = dynasty_info.get("from", {})
                dynasty_name = d_from.get("name", "") if d_from else ""

            details = ""
            if dynasty_name and result_author:
                details = f"（{dynasty_name}）{result_author}"
            elif result_author:
                details = result_author

            quality = {
                "is_classic": is_classic,
                "last_modified": info.get("lastmodified", ""),
            }
            edition_info = info.get("edition")
            if isinstance(edition_info, dict):
                quality["edition"] = edition_info.get("title", "")

            add_result(
                url=url,
                res_id="ctext",
                name="CText（原典）" if is_classic else "CText",
                details=details,
                quality=quality,
            )

        return found

    # -- search/match helpers --

    # Lazy-loaded OpenCC converters for full simplified↔traditional conversion
    _s2t: Optional[object] = None
    _t2s: Optional[object] = None
    _variant_map: Optional[dict[str, str]] = None

    @classmethod
    def _get_s2t(cls):
        if cls._s2t is None:
            from opencc import OpenCC
            cls._s2t = OpenCC('s2t')
        return cls._s2t

    @classmethod
    def _get_t2s(cls):
        if cls._t2s is None:
            from opencc import OpenCC
            cls._t2s = OpenCC('t2s')
        return cls._t2s

    @classmethod
    def _get_variant_map(cls) -> dict[str, str]:
        """Load CJK variant→standard character mapping from OpenCC dicts.

        Combines JP, TW, and HK variant reverse mappings so that
        non-standard forms (e.g. 徴) map to their standard traditional
        form (e.g. 徵). This handles cases that s2t/t2s miss.
        """
        if cls._variant_map is not None:
            return cls._variant_map

        import os
        vmap: dict[str, str] = {}
        try:
            import opencc
            dict_dir = os.path.join(os.path.dirname(opencc.__file__), 'dictionary')

            # JPVariants: standard\tvariant  →  variant→standard
            jp_path = os.path.join(dict_dir, 'JPVariants.txt')
            if os.path.exists(jp_path):
                with open(jp_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        parts = line.strip().split('\t')
                        if len(parts) == 2:
                            std = parts[0]
                            for v in parts[1].split(' '):
                                if len(v) == 1 and len(std) == 1 and v != std:
                                    vmap[v] = std

            # TWVariantsRev / HKVariantsRev: variant\tstandard
            for fn in ('TWVariantsRev.txt', 'HKVariantsRev.txt'):
                fp = os.path.join(dict_dir, fn)
                if os.path.exists(fp):
                    with open(fp, 'r', encoding='utf-8') as f:
                        for line in f:
                            parts = line.strip().split('\t')
                            if len(parts) == 2:
                                v = parts[0]
                                std = parts[1].split(' ')[0]
                                if len(v) == 1 and len(std) == 1 and v != std:
                                    vmap[v] = std
        except Exception:
            pass

        cls._variant_map = vmap
        return vmap

    @classmethod
    def _normalize_variants(cls, text: str) -> str:
        """Normalize CJK variant characters to standard traditional forms.

        Applies variant→standard mapping first, then OpenCC s2t conversion.
        This ensures that e.g. "史徴" and "史徵" both normalize to "史徵".
        """
        vmap = cls._get_variant_map()
        if vmap:
            text = ''.join(vmap.get(ch, ch) for ch in text)
        try:
            text = cls._get_s2t().convert(text)
        except Exception:
            pass
        return text

    def _generate_title_variants(self, title: str) -> list[str]:
        """Generate CJK variant titles.

        Uses OpenCC for full simplified↔traditional conversion, plus
        single-char substitutions from _CJK_VARIANTS for common variant
        forms (e.g. 注↔註) that are not strict s↔t pairs.
        """
        variants: set[str] = {title}

        # Full s2t and t2s conversions
        try:
            variants.add(self._get_s2t().convert(title))
            variants.add(self._get_t2s().convert(title))
        except Exception:
            # Fallback: manual substitution if opencc unavailable
            variants.add(self._substitute_all(title))

        # Single-char variant substitutions (for non-s/t pairs like 注↔註)
        for i, ch in enumerate(title):
            alt = self._CJK_VARIANTS.get(ch)
            if alt:
                variants.add(title[:i] + alt + title[i + 1:])

        # Removable prefixes
        base_variants = set(variants)
        for prefix in self._REMOVABLE_PREFIXES:
            for v in base_variants:
                if v.startswith(prefix):
                    stripped = v[len(prefix):]
                    variants.add(stripped)

        return list(variants)

    def _substitute_all(self, text: str) -> str:
        """Replace all CJK variant characters in text at once (fallback)."""
        return ''.join(self._CJK_VARIANTS.get(ch, ch) for ch in text)

    def _title_matches(
        self, candidate: str, title_variants: list[str],
        strict: bool = True,
    ) -> bool:
        """Check if candidate title matches any of the title variants.

        Normalizes both sides via variant mapping + OpenCC so that
        "論語" matches "论语" and "徴" matches "徵".
        """
        # Normalize candidate: variant→standard + s2t
        norm_candidate = self._normalize_variants(candidate)
        candidate_forms = {candidate, norm_candidate}
        try:
            candidate_forms.add(self._get_t2s().convert(norm_candidate))
        except Exception:
            candidate_forms.add(self._substitute_all(candidate))

        # Normalize variants too
        norm_variants = set(title_variants)
        for v in title_variants:
            norm_variants.add(self._normalize_variants(v))

        for cf in candidate_forms:
            for v in norm_variants:
                if cf == v:
                    return True
        if not strict:
            for cf in candidate_forms:
                for v in norm_variants:
                    if len(v) >= 2 and cf.startswith(v):
                        return True
        return False

    def _parse_author_dynasty(self, snippet: str) -> tuple[str, str]:
        """Parse dynasty and author from snippet like '（宋）朱熹'.

        Returns: (dynasty, author_name)
        """
        if not snippet:
            return "", ""

        # Snippet format: "（朝代）作者 | 原典" or just "（朝代）作者"
        text = snippet.split("|")[0].strip()
        m = self._DYNASTY_AUTHOR_RE.match(text)
        if m:
            return m.group(1).strip(), m.group(2).strip()
        return "", text

    def _surname_matches(
        self, result_author: str, query_authors: list[str],
    ) -> bool:
        """Check if result author shares a surname with any query author.

        Compares just the first character (surname) after normalization.
        Handles compound surnames would need more logic, but single-char
        comparison covers the vast majority of Chinese names.
        """
        clean_result = self._ROLE_WORDS.sub('', result_author)
        norm_result = self._normalize_variants(clean_result)
        result_surnames = set()
        for name in re.split(r'[（()）,，、\s]+', norm_result):
            name = name.strip()
            if name:
                result_surnames.add(name[0])
                try:
                    result_surnames.add(self._get_t2s().convert(name[0]))
                except Exception:
                    pass

        for qa in query_authors:
            clean_qa = self._ROLE_WORDS.sub('', qa)
            norm_qa = self._normalize_variants(clean_qa)
            if norm_qa:
                qa_surname = norm_qa[0]
                if qa_surname in result_surnames:
                    return True
                try:
                    if self._get_t2s().convert(qa_surname) in result_surnames:
                        return True
                except Exception:
                    pass
        return False

    def _author_matches(
        self, result_author: str, query_authors: list[str],
    ) -> bool:
        """Check if result author matches any of the query authors.

        Handles role-word stripping, variant normalization,
        simplified↔traditional conversion, and partial matching.
        """
        # Strip role words from result author
        clean_result = self._ROLE_WORDS.sub('', result_author)

        # Normalize: variant→standard + s2t, then also t2s
        norm_result = self._normalize_variants(clean_result)
        result_forms = {clean_result, norm_result}
        try:
            result_forms.add(self._get_t2s().convert(norm_result))
        except Exception:
            result_forms.add(self._substitute_all(clean_result))

        for qa in query_authors:
            clean_qa = self._ROLE_WORDS.sub('', qa)
            norm_qa = self._normalize_variants(clean_qa)
            qa_forms = {clean_qa, norm_qa}
            try:
                qa_forms.add(self._get_t2s().convert(norm_qa))
            except Exception:
                qa_forms.add(self._substitute_all(clean_qa))

            for rf in result_forms:
                for qf in qa_forms:
                    if rf == qf:
                        return True
                    if qf in rf or rf in qf:
                        return True
        return False

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
