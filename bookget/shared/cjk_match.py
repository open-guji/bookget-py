"""Shared CJK title / author matching utilities.

Used by site adapters (CText, Shidianguji, …) for ``search`` / ``match_book``:
繁简转换 + 异体字归一化、书名变体生成、书名/作者匹配。

之前 CText 与 识典古籍 两个适配器各自维护一份几乎相同的繁简/异体字匹配
逻辑（含一份很大的异体字对照表）。本模块抽取为单一实现，消除重复并统一
行为——CText 原本更完整（单字异体替换、strict 前缀匹配），识典缺这些，
统一后两边都获得完整能力。

OpenCC 是**正式依赖**（见 pyproject `dependencies`），不是可选项：缺了它
繁简匹配会大幅退化（论语 配不上 論語），而调用方拿到的只是「少了一半结果」，
不会看到任何报错。历史上它一直没被声明，导致 pip 安装的用户长期静默受损。
因此这里保留可运行的降级路径（仅做内置异体表替换）**但会打一条 WARNING**，
让问题可见而不是悄无声息。
"""

from __future__ import annotations

import os
import re
from typing import Optional, Union

__all__ = [
    "CJK_VARIANTS",
    "REMOVABLE_PREFIXES",
    "normalize_variants",
    "generate_title_variants",
    "title_matches",
    "author_matches",
    "surname_matches",
    "parse_author_dynasty",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# CJK variant pairs for classical Chinese book titles / author names.
# Covers common variant forms that strict simplified↔traditional (s2t/t2s)
# conversion misses, e.g. 注↔註.
CJK_VARIANTS: dict[str, str] = {
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

# Removable honorific title prefixes (四库 imperial-edition titles).
REMOVABLE_PREFIXES: list[str] = ['欽定', '御定', '御纂', '御製', '御選']

# Role words to strip from the end of author names.
_ROLE_WORDS = re.compile(r'[撰注疏輯校點箋補纂訂譯編釋]$')

# Dynasty/author snippet pattern: （朝代）作者
_DYNASTY_AUTHOR_RE = re.compile(r'^[（(]([^）)]+)[）)](.*)')

# Separators used to split a combined author string into individual names.
_NAME_SPLIT_RE = re.compile(r'[（()）,，、\s]+')

# ---------------------------------------------------------------------------
# OpenCC (lazy, optional)
# ---------------------------------------------------------------------------

_s2t = None
_t2s = None
_variant_map: Optional[dict[str, str]] = None


_warned_missing = False


def _warn_missing_opencc(exc: Exception) -> None:
    """Warn once that OpenCC is unusable, instead of degrading in silence."""
    global _warned_missing
    if _warned_missing:
        return
    _warned_missing = True
    try:
        from ..logger import logger
        logger.warning(
            "OpenCC 不可用（%s）——繁简/异体字匹配已退化，搜索与匹配会漏掉结果"
            "（例如 论语 匹配不上 論語）。请安装：pip install opencc",
            exc,
        )
    except Exception:
        pass


def _get_s2t():
    global _s2t
    if _s2t is None:
        try:
            from opencc import OpenCC
            _s2t = OpenCC('s2t')
        except Exception as e:
            _warn_missing_opencc(e)
            return None
    return _s2t


def _get_t2s():
    global _t2s
    if _t2s is None:
        try:
            from opencc import OpenCC
            _t2s = OpenCC('t2s')
        except Exception as e:
            _warn_missing_opencc(e)
            return None
    return _t2s


def _convert_s2t(text: str) -> str:
    c = _get_s2t()
    if c:
        try:
            return c.convert(text)
        except Exception:
            pass
    return text


def _convert_t2s(text: str) -> str:
    c = _get_t2s()
    if c:
        try:
            return c.convert(text)
        except Exception:
            pass
    return text


def _find_opencc_dict_dir(opencc_mod) -> Optional[str]:
    """Locate a directory holding OpenCC's plain-text ``*Variants*.txt`` dicts.

    Older OpenCC packages shipped them under ``<pkg>/dictionary``. Newer wheels
    moved data to ``<pkg>/clib/share/opencc`` and ship only binary ``.ocd2``
    files there, in which case there is no usable text dir and we return None.
    """
    base = os.path.dirname(opencc_mod.__file__)
    for rel in ('dictionary', os.path.join('clib', 'share', 'opencc'), 'share/opencc'):
        d = os.path.join(base, rel)
        if os.path.isdir(d) and any(
            f.endswith('Variants.txt') or f.endswith('VariantsRev.txt')
            for f in os.listdir(d)
        ):
            return d
    return None


def _build_variant_map_via_converters() -> dict[str, str]:
    """Derive a single-char variant→standard map using OpenCC converters.

    ``jp2t`` / ``tw2t`` / ``hk2t`` map regional variant forms back to standard
    traditional — the same JP/TW/HK coverage the old ``JPVariants.txt`` /
    ``*VariantsRev.txt`` parsing aimed for (``jp2t`` is what turns 徴 into 徵).
    We probe the CJK Unified Ideographs block once and keep only the chars that
    actually change, without depending on text dictionaries being shipped.
    """
    vmap: dict[str, str] = {}
    try:
        from opencc import OpenCC
        convs = []
        for name in ('jp2t', 'tw2t', 'hk2t'):
            try:
                convs.append(OpenCC(name))
            except Exception:
                continue
        if not convs:
            return vmap
        for cp in range(0x4E00, 0xA000):
            ch = chr(cp)
            for c in convs:
                try:
                    std = c.convert(ch)
                except Exception:
                    continue
                if len(std) == 1 and std != ch:
                    vmap[ch] = std
                    break
    except Exception:
        pass
    return vmap


def _get_variant_map() -> dict[str, str]:
    """Load CJK variant→standard mapping from OpenCC dictionary files.

    Combines JP / TW / HK variant reverse mappings so non-standard forms
    (e.g. 徴) map to their standard traditional form (e.g. 徵) — cases that
    plain s2t/t2s miss.
    """
    global _variant_map
    if _variant_map is not None:
        return _variant_map

    vmap: dict[str, str] = {}
    try:
        import opencc
        dict_dir = _find_opencc_dict_dir(opencc)
        if not dict_dir:
            # Modern wheels (OpenCC >= ~1.1) ship only binary .ocd2 dictionaries
            # and no plain-text ones, so the parsing below finds nothing. Fall
            # back to OpenCC's own tw2t/hk2t converters, which cover the same
            # TW/HK variant→standard direction (e.g. 徴→徵) char by char.
            _variant_map = _build_variant_map_via_converters()
            return _variant_map

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

    _variant_map = vmap
    return vmap


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def substitute_all(text: str) -> str:
    """Replace every CJK variant character via the built-in table (fallback)."""
    return ''.join(CJK_VARIANTS.get(ch, ch) for ch in text)


def normalize_variants(text: str) -> str:
    """Normalize CJK variant characters to standard traditional forms.

    Applies variant→standard mapping first, then OpenCC s2t. This makes
    "史徴" and "史徵" both normalize to "史徵".
    """
    vmap = _get_variant_map()
    if vmap:
        text = ''.join(vmap.get(ch, ch) for ch in text)
    return _convert_s2t(text)


def generate_title_variants(title: str) -> list[str]:
    """Generate CJK variant titles for a book title.

    Uses OpenCC for full simplified↔traditional conversion, plus single-char
    substitutions from :data:`CJK_VARIANTS` for non-s/t variant pairs
    (e.g. 注↔註), plus removal of honorific prefixes (欽定/御定/…).
    """
    variants: set[str] = {title}

    # Full s2t / t2s conversions (fallback to manual substitution).
    if _get_s2t() or _get_t2s():
        variants.add(_convert_s2t(title))
        variants.add(_convert_t2s(title))
    else:
        variants.add(substitute_all(title))

    # Single-char variant substitutions (for non-s/t pairs like 注↔註).
    for i, ch in enumerate(title):
        alt = CJK_VARIANTS.get(ch)
        if alt:
            variants.add(title[:i] + alt + title[i + 1:])

    # Removable prefixes.
    for prefix in REMOVABLE_PREFIXES:
        for v in set(variants):
            if v.startswith(prefix):
                variants.add(v[len(prefix):])

    return list(variants)


def title_matches(
    candidate: str, title_variants: list[str], strict: bool = True,
) -> bool:
    """Check if *candidate* title matches any of *title_variants*.

    Normalizes both sides (variant mapping + OpenCC) so that "論語" matches
    "论语" and "徴" matches "徵". With ``strict=False``, also matches when a
    variant is a 2+ char prefix of the candidate.
    """
    norm_candidate = normalize_variants(candidate)
    candidate_forms = {candidate, norm_candidate, _convert_t2s(norm_candidate)}

    norm_variants = set(title_variants)
    for v in title_variants:
        norm_variants.add(normalize_variants(v))

    for cf in candidate_forms:
        if cf in norm_variants:
            return True
    if not strict:
        for cf in candidate_forms:
            for v in norm_variants:
                if len(v) >= 2 and cf.startswith(v):
                    return True
    return False


def _name_list(author: Union[str, list[str], None]) -> list[str]:
    """Normalize an author argument (str | list) into a list of name strings."""
    if author is None:
        return []
    if isinstance(author, str):
        return [author]
    return [a for a in author if a]


def author_matches(
    result_author: Union[str, list[str]], query_authors: list[str],
) -> bool:
    """Check if any result author matches any query author.

    Handles role-word stripping, variant normalization, simplified↔traditional
    conversion and partial (substring) matching. ``result_author`` may be a
    single name string or a list of names.
    """
    for ra in _name_list(result_author):
        clean = _ROLE_WORDS.sub('', ra)
        norm = normalize_variants(clean)
        result_forms = {clean, norm, _convert_t2s(norm)}

        for qa in query_authors:
            clean_qa = _ROLE_WORDS.sub('', qa)
            norm_qa = normalize_variants(clean_qa)
            qa_forms = {clean_qa, norm_qa, _convert_t2s(norm_qa)}

            for rf in result_forms:
                for qf in qa_forms:
                    if rf == qf or (qf and (qf in rf or rf in qf)):
                        return True
    return False


def surname_matches(
    result_author: Union[str, list[str]], query_authors: list[str],
) -> bool:
    """Check if a result author shares a surname (first char) with a query author.

    Single-char comparison covers the vast majority of Chinese names. A
    combined result string (e.g. "（宋）朱熹") is split on separators first.
    """
    result_surnames: set[str] = set()
    for ra in _name_list(result_author):
        clean = _ROLE_WORDS.sub('', ra)
        norm = normalize_variants(clean)
        for name in _NAME_SPLIT_RE.split(norm):
            name = name.strip()
            if name:
                result_surnames.add(name[0])
                result_surnames.add(_convert_t2s(name[0]))

    for qa in query_authors:
        clean_qa = _ROLE_WORDS.sub('', qa)
        norm_qa = normalize_variants(clean_qa)
        if norm_qa:
            if norm_qa[0] in result_surnames:
                return True
            if _convert_t2s(norm_qa[0]) in result_surnames:
                return True
    return False


def parse_author_dynasty(snippet: str) -> tuple[str, str]:
    """Parse a "（朝代）作者" snippet into ``(dynasty, author_name)``."""
    if not snippet:
        return "", ""
    text = snippet.split("|")[0].strip()
    m = _DYNASTY_AUTHOR_RE.match(text)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", text
