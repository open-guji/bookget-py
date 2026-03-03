# CText (中国哲学书电子化计划) Adapter
# https://ctext.org/

import asyncio
import re
from typing import List, Optional
import aiohttp
from html.parser import HTMLParser

from ..base import BaseSiteAdapter
from ..registry import AdapterRegistry
from ...models.book import BookMetadata, Resource, ResourceType, Creator
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
    
    BASE_URL = "https://ctext.org"
    API_URL = "https://api.ctext.org"
    
    default_headers = {
        "Accept": "application/json, text/html",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
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
    
    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
