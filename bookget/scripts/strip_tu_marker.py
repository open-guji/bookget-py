"""
strip_tu_marker.py — 清理已下载 JSON 中的 【圖】 占位符

用法：
    python -m bookget.scripts.strip_tu_marker <目录或文件> [--dry-run]

说明：
    递归处理目录下所有 .json 文件，将 paragraphs 里的 【圖】 删除。
    修改后原地保存（除非指定 --dry-run）。
"""

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

MARKER = '【圖】'


def strip_tu(paragraphs: list[str]) -> tuple[list[str], int]:
    """从段落列表中去除 【圖】，返回 (新列表, 修改数量)。"""
    count = 0
    result = []
    for p in paragraphs:
        if MARKER in p:
            new_p = p.replace(MARKER, '').lstrip()  # 去除后可能有前导空格
            count += 1
            if new_p:
                result.append(new_p)
            # 若整段只有 【圖】（去掉后为空），则丢弃该段
        else:
            result.append(p)
    return result, count


def process_file(path: Path, dry_run: bool) -> int:
    """处理单个 JSON 文件，返回修改的段落数。"""
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f'[跳过] {path}: {e}', file=sys.stderr)
        return 0

    if not isinstance(data, dict):
        return 0

    total = 0
    pages = data.get('pages')
    if not isinstance(pages, list):
        return 0

    for page in pages:
        paras = page.get('paragraphs')
        if not isinstance(paras, list):
            continue
        new_paras, n = strip_tu(paras)
        if n:
            page['paragraphs'] = new_paras
            total += n

    if total:
        print(f'{"[试运行] " if dry_run else ""}修改 {total} 处: {path}')
        if not dry_run:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    return total


def main():
    parser = argparse.ArgumentParser(description='清理 JSON 中的 【圖】 占位符')
    parser.add_argument('target', help='目录或单个 .json 文件')
    parser.add_argument('--dry-run', action='store_true', help='仅预览，不写入')
    args = parser.parse_args()

    target = Path(args.target)
    files = list(target.rglob('*.json')) if target.is_dir() else [target]

    total_files = 0
    total_changes = 0
    for f in files:
        n = process_file(f, args.dry_run)
        if n:
            total_files += 1
            total_changes += n

    print(f'\n共处理 {total_files} 个文件，{total_changes} 处 【圖】 已{"标记" if args.dry_run else "删除"}。')


if __name__ == '__main__':
    main()
