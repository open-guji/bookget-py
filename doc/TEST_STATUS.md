# Adapter Test Status Report

## Test Results (2026-02-07)

| Adapter | API Status | CLI Test | Notes |
|---------|------------|----------|-------|
| NDL (Japan) | ✅ 200 | ✅ Works | Full IIIF support |
| BSB (Munich) | ✅ 200 | ✅ Works | Full IIIF support |
| CText | ✅ 200 | ✅ Works | HTML parsing for metadata |
| BnF Gallica | ✅ 200 | ✅ Works | Requires Referer header (Fixed) |
| NLC Guji | ✅ 200 | ✅ Works | Use metadataId=1012798 (Verified) |
| Harvard | ✅ 200 | ✅ Works | Handle ids: and drs: (Fixed) |
| Shidianguji | 🔄 Untested | - | Needs live URL test |
| Princeton | 🔄 Untested | - | Needs live URL test |
| Stanford | 🔄 Untested | - | Needs live URL test |
| Berkeley | 🔄 Untested | - | Needs live URL test |
| British Library | 🔄 Untested | - | Needs live URL test |
| NCL Taiwan | 🔄 Untested | - | Needs live URL test |
| NPM Taipei | 🔄 Untested | - | Needs live URL test |

## Verified Working Commands

```bash
cd D:\workspace\guji-platform\src
set PYTHONIOENCODING=utf-8

# NDL (Japan)
python -m bookget metadata "https://dl.ndl.go.jp/pid/2592420" --format json

# BSB (Munich)
python -m bookget metadata "https://www.digitale-sammlungen.de/de/view/bsb00089142" --format json

# CText
python -m bookget metadata "https://ctext.org/analects" --format json

# Harvard
python -m bookget metadata "https://curiosity.lib.harvard.edu/chinese-rare-books/catalog/49-990096027880203941" --format json

# BnF Gallica
python -m bookget metadata "https://gallica.bnf.fr/ark:/12148/btv1b107206728" --format json

# NLC Guji
python -m bookget metadata "https://guji.nlc.cn/read/book?metadataId=1012798" --format json
```

## Known Issues

1. **Windows Unicode**: Use `set PYTHONIOENCODING=utf-8` before commands
2. **BnF Gallica**: Returns 403, may need different auth approach
3. **NLC Guji**: Sample metadataId returns "查询种详情失败", need valid ID
4. **Harvard**: Manifest URL pattern may have changed

## Unit Tests

```bash
# All 52 tests pass
python -m pytest bookget/tests/ -v
```
