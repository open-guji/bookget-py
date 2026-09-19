"""Internet Archive 上传/修补/校验。

子命令背后的实现，被 main.py 的 upload / ia-patch / ia-check 调用。
`internetarchive` 是可选依赖（`pip install bookget[ia]`），只在这里被
import，不装时其余 bookget 功能不受影响。

依赖：
  pip install internetarchive
  ia configure  # 写入 S3 keys 到 ~/.config/internetarchive/ia.ini
"""
from __future__ import annotations
import sys
from pathlib import Path

from bookget.ia_metadata import (
    apply_defaults, validate_metadata, load_metadata_file, format_issues,
)


def _require_internetarchive():
    try:
        import internetarchive
    except ImportError:
        print(
            '❌ 需要 internetarchive 包: pip install "bookget[ia]" 或 pip install internetarchive',
            file=sys.stderr,
        )
        sys.exit(1)
    return internetarchive


def _parse_kv(items: list[str] | None) -> dict:
    """解析 --set k=v 列表。重复 key 收集成 list。"""
    out: dict = {}
    for item in items or []:
        if '=' not in item:
            raise SystemExit(f'❌ --set must be key=value, got {item!r}')
        k, v = item.split('=', 1)
        if k in out:
            if isinstance(out[k], list):
                out[k].append(v)
            else:
                out[k] = [out[k], v]
        else:
            out[k] = v
    return out


def _load_md(args, defaults: bool = True) -> dict:
    md: dict = {}
    if getattr(args, 'metadata_file', None):
        md.update(load_metadata_file(args.metadata_file))
    if getattr(args, 'set', None):
        md.update(_parse_kv(args.set))
    if defaults:
        md = apply_defaults(md)
    return md


def cmd_upload(args) -> None:
    ia = _require_internetarchive()

    md = _load_md(args, defaults=True)
    strict = not args.no_strict
    issues = validate_metadata(md, strict_guji=strict)
    if issues:
        print(format_issues(issues, args.identifier), file=sys.stderr)
        sys.exit(2)

    item = ia.get_item(args.identifier)
    new_basenames = {Path(fp).name for fp in args.files}
    if item.exists:
        print(f'⚠ identifier {args.identifier!r} 已存在 '
              f'(https://archive.org/details/{args.identifier})')
        print(f'  现有文件数: {len(item.files)}')
        if not args.dry_run:
            if not args.force:
                print('  refusing to upload to existing item. 用 --force 覆盖',
                      file=sys.stderr)
                sys.exit(1)
            stale_pdfs = [
                f['name'] for f in list(item.files)
                if f['name'].lower().endswith('.pdf')
                and f['name'] not in new_basenames
            ]
            for fname in stale_pdfs:
                print(f'  [delete-old] {fname}')
                ia.delete(args.identifier, files=[fname], cascade_delete=True,
                          verbose=True)

    files: list[str] = []
    for fp in args.files:
        p = Path(fp)
        if not p.is_file():
            print(f'❌ file not found: {p}', file=sys.stderr)
            sys.exit(1)
        files.append(str(p))

    total = sum(Path(f).stat().st_size for f in files)
    print(f'\n准备上传：')
    print(f'  identifier: {args.identifier}')
    print(f'  url:        https://archive.org/details/{args.identifier}')
    print(f'  files:      {len(files)} ({total / 1024 / 1024:.1f} MB)')
    print(f'  metadata:')
    for k, v in md.items():
        print(f'    {k}: {v}')

    if args.dry_run:
        print('\n[dry-run] 不实际上传')
        return

    print('\n开始上传（首次跨境会很慢）...\n')
    responses = ia.upload(args.identifier, files=files, metadata=md, verbose=True)
    fail = [r for r in responses if r.status_code != 200]
    if fail:
        print(f'\n❌ {len(fail)} 个文件上传失败')
        for r in fail:
            print(f'  {r.url}: HTTP {r.status_code}')
        sys.exit(1)
    print(f'\n✅ 全部 {len(responses)} 个文件上传成功')
    print(f'   https://archive.org/details/{args.identifier}')


def cmd_patch(args) -> None:
    ia = _require_internetarchive()

    patches: dict = {}
    if args.metadata_file:
        patches.update(load_metadata_file(args.metadata_file))
    if args.set:
        patches.update(_parse_kv(args.set))
    if not patches:
        print('❌ patch 需要 --metadata-file 或 --set k=v', file=sys.stderr)
        sys.exit(1)

    item = ia.get_item(args.identifier)
    if not item.exists:
        print(f'❌ identifier {args.identifier!r} 不存在', file=sys.stderr)
        sys.exit(1)

    if not args.skip_validate:
        merged = dict(item.metadata)
        merged.update(patches)
        merged = apply_defaults(merged)
        issues = validate_metadata(merged, strict_guji=not args.no_strict)
        if issues:
            print(format_issues(issues, args.identifier), file=sys.stderr)
            print('\n用 --skip-validate 强制跳过校验', file=sys.stderr)
            sys.exit(2)

    print(f'patching {args.identifier}:')
    for k, v in patches.items():
        print(f'  {k} = {v}')
    if args.dry_run:
        print('[dry-run] 不实际修改')
        return
    r = ia.modify_metadata(args.identifier, metadata=patches)
    if r.status_code == 200:
        print(f'✅ patched: {r.text.strip()}')
    else:
        print(f'❌ HTTP {r.status_code}: {r.text}', file=sys.stderr)
        sys.exit(1)


def cmd_check(args) -> None:
    ia = _require_internetarchive()

    item = ia.get_item(args.identifier)
    if not item.exists:
        print(f'❌ identifier {args.identifier!r} 不存在', file=sys.stderr)
        sys.exit(1)

    md = dict(item.metadata)
    md = apply_defaults(md) if args.apply_defaults else md

    issues = validate_metadata(md, strict_guji=not args.no_strict)
    print(f'identifier: {args.identifier}')
    print(f'url:        https://archive.org/details/{args.identifier}')
    print(f'files:      {len(item.files)}')
    print(f'metadata fields: {len(md)}')
    if issues:
        print('\n' + format_issues(issues, args.identifier), file=sys.stderr)
        sys.exit(2)
    print('\n✅ metadata 合规')
