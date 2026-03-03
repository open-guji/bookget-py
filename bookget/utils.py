# Utility functions for Guji Resource Manager

import re
import asyncio
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse, parse_qs, urljoin
import aiohttp


def extract_domain(url: str) -> str:
    """Extract domain from URL."""
    try:
        parsed = urlparse(url)
        return parsed.netloc.lower()
    except Exception:
        return ""


def extract_path(url: str) -> str:
    """Extract path from URL."""
    try:
        parsed = urlparse(url)
        return parsed.path
    except Exception:
        return ""


def extract_query_param(url: str, param: str) -> Optional[str]:
    """Extract a query parameter from URL."""
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        values = params.get(param, [])
        return values[0] if values else None
    except Exception:
        return None


def sanitize_filename(name: str, max_length: int = 200) -> str:
    """
    Sanitize a string for use as a filename.
    
    Removes or replaces characters that are illegal in filenames
    on Windows, macOS, and Linux.
    """
    # Replace illegal characters
    illegal = r'[<>:"/\\|?*\x00-\x1f]'
    sanitized = re.sub(illegal, '_', name)
    
    # Remove leading/trailing spaces and dots
    sanitized = sanitized.strip(' .')
    
    # Limit length
    if len(sanitized) > max_length:
        # Keep extension if present
        if '.' in sanitized[-10:]:
            base, ext = sanitized.rsplit('.', 1)
            sanitized = base[:max_length - len(ext) - 1] + '.' + ext
        else:
            sanitized = sanitized[:max_length]
    
    return sanitized or "unnamed"


def normalize_chinese_text(text: str) -> str:
    """
    Normalize Chinese text for comparison.
    
    Converts traditional to simplified (if needed) and removes
    common variations in character forms.
    """
    # Basic normalization - remove extra whitespace
    text = re.sub(r'\s+', '', text)
    
    # Common traditional/simplified variations
    replacements = {
        '臺': '台',
        '國': '国',
        '書': '书',
        '館': '馆',
        '圖': '图',
        '學': '学',
    }
    
    for trad, simp in replacements.items():
        text = text.replace(trad, simp)
    
    return text


async def fetch_json(
    url: str, 
    headers: Dict[str, str] = None,
    session: aiohttp.ClientSession = None
) -> Optional[Dict[str, Any]]:
    """
    Fetch JSON from URL with error handling.
    
    Returns None on failure instead of raising exception.
    """
    close_session = session is None
    
    try:
        if session is None:
            session = aiohttp.ClientSession()
        
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                return await response.json()
            return None
            
    except Exception:
        return None
        
    finally:
        if close_session and session:
            await session.close()


async def fetch_with_retry(
    url: str,
    session: aiohttp.ClientSession,
    headers: Dict[str, str] = None,
    retries: int = 3,
    delay: float = 1.0
) -> Optional[bytes]:
    """
    Fetch URL content with retry logic.
    
    Returns bytes content on success, None on failure.
    """
    for attempt in range(retries):
        try:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    return await response.read()
                elif response.status in (429, 503):
                    # Rate limited or service unavailable - wait longer
                    await asyncio.sleep(delay * (attempt + 2))
                elif response.status >= 400:
                    return None
        except aiohttp.ClientError:
            if attempt < retries - 1:
                await asyncio.sleep(delay * (attempt + 1))
            continue
    
    return None


def parse_dynasty(text: str) -> tuple[str, str]:
    """
    Parse dynasty and date from a Chinese date string.
    
    Examples:
        "清乾隆四十六年 (1781)" -> ("清", "1781")
        "明萬曆" -> ("明", "")
        "[宋]" -> ("宋", "")
    
    Returns:
        Tuple of (dynasty, year) where year is Gregorian if found
    """
    dynasty = ""
    year = ""
    
    # Extract dynasty
    dynasty_patterns = [
        r'\[([^]]+)\]',           # [宋]
        r'(唐|宋|元|明|清|民国)',
    ]
    
    for pattern in dynasty_patterns:
        match = re.search(pattern, text)
        if match:
            dynasty = match.group(1)
            break
    
    # Extract Gregorian year
    year_match = re.search(r'\(?(\d{3,4})\)?', text)
    if year_match:
        year = year_match.group(1)
    
    return dynasty, year


def format_creators(creators: List[dict]) -> str:
    """
    Format a list of creators into a display string.
    
    Args:
        creators: List of dicts with 'name', 'role', 'dynasty' keys
    
    Returns:
        Formatted string like "[唐] 李白 撰; 王安石 注"
    """
    parts = []
    
    for c in creators:
        name = c.get('name', '')
        role = c.get('role', '')
        dynasty = c.get('dynasty', '')
        
        if not name:
            continue
        
        item = ""
        if dynasty:
            item += f"[{dynasty}] "
        item += name
        if role:
            item += f" {role}"
        
        parts.append(item)
    
    return "; ".join(parts)
