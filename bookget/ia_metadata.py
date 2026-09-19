"""Internet Archive metadata 构建与校验，upload/patch 命令共用。

中心逻辑：
  - 必填字段红线（title/creator/date/language/page-progression 等）
  - page-progression='rl' 是古籍硬约束（漏了 IA viewer 会反着翻）
  - 默认值（mediatype=texts / collection=opensource / license / rights）

移植自 open-guji/overview 仓 scripts/ia-toolkit/metadata.py。
"""
from __future__ import annotations
import json
from pathlib import Path


REQUIRED_FIELDS = {
    'mediatype': '资源类型 (texts/image/audio/etc)',
    'title': '书名',
    'creator': '作者（数组）',
    'date': '原书年代',
    'language': 'ISO 639-2/3 语言数组',
    'page-progression': '古籍必须 rl（右→左竖排翻页）',
    'description': '说明（建议含 HTML 结构）',
    'collection': 'IA collection (默认 opensource)',
    'licenseurl': '许可证 URL',
    'rights': '版权声明',
}

# 古籍专用红线：page-progression 必须 rl。其他 mediatype 不强制
GUJI_HARDLINE = {'page-progression': 'rl'}

DEFAULT_RIGHTS = '原書屬公有領域（古代著作，著作權保護期已屆滿）。本上傳為學術研究與公益保存目的。'
DEFAULT_LICENSE = 'http://creativecommons.org/publicdomain/mark/1.0/'
DEFAULT_LANGUAGE = ['chi', 'zho-Hant']


class MetadataError(ValueError):
    pass


def apply_defaults(md: dict) -> dict:
    """补默认值。已设置的不覆盖。"""
    md.setdefault('mediatype', 'texts')
    md.setdefault('collection', 'opensource')
    md.setdefault('licenseurl', DEFAULT_LICENSE)
    md.setdefault('rights', DEFAULT_RIGHTS)
    md.setdefault('language', DEFAULT_LANGUAGE)
    # 古籍硬约束：page-progression 默认 rl（古籍竖排是右→左翻）
    md.setdefault('page-progression', 'rl')
    return md


def validate_metadata(md: dict, strict_guji: bool = True) -> list[str]:
    """返回 issues 列表。空 = 合规。strict_guji=True 时强制古籍红线。"""
    issues = []
    for field, hint in REQUIRED_FIELDS.items():
        if field not in md or md[field] in (None, '', [], {}):
            issues.append(f'missing required field {field!r} ({hint})')

    if strict_guji:
        for field, expected in GUJI_HARDLINE.items():
            actual = md.get(field)
            if actual != expected:
                issues.append(
                    f'guji hard-line: {field!r} must be {expected!r}, got {actual!r}. '
                    f'古籍竖排必须 page-progression=rl，否则 IA viewer 会反着翻页'
                )

    return issues


def load_metadata_file(path: str | Path) -> dict:
    """读 JSON 或 YAML metadata 文件。"""
    p = Path(path)
    text = p.read_text(encoding='utf-8')
    if p.suffix.lower() in ('.yaml', '.yml'):
        try:
            import yaml
        except ImportError:
            raise MetadataError('需要 pyyaml: pip install pyyaml')
        return yaml.safe_load(text)
    return json.loads(text)


def format_issues(issues: list[str], identifier: str = '') -> str:
    head = f'❌ metadata 校验未通过 ({identifier}):' if identifier else '❌ metadata 校验未通过:'
    return head + '\n' + '\n'.join(f'  - {i}' for i in issues)
