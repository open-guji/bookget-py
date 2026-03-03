# Guji Resource Manager - CLI Commands Reference

## Quick Start

```bash
cd D:\workspace\guji-platform\src
python -m bookget --help
```

---

## List Supported Sites

```bash
python -m bookget sites --list
```

## Check URL Support

```bash
python -m bookget sites --check "URL"
```

---

## Test Commands by Website

### 中华古籍智慧化服务平台 (NLC Guji)

```bash
# Check support
python -m bookget sites --check "https://guji.nlc.cn/guji/pjkf/detail?metadataId=0021001379780000"

# Get metadata only
python -m bookget metadata "https://guji.nlc.cn/guji/pjkf/detail?metadataId=0021001379780000" --format json

# Download (when ready)
python -m bookget download "https://guji.nlc.cn/guji/pjkf/detail?metadataId=0021001379780000" -o ./downloads/nlc
```

---

### 国立国会図書館 (NDL Japan)

```bash
# Check support
python -m bookget sites --check "https://dl.ndl.go.jp/pid/2592420"

# Get metadata
python -m bookget metadata "https://dl.ndl.go.jp/pid/2592420" --format json

# Download
python -m bookget download "https://dl.ndl.go.jp/pid/2592420" -o ./downloads/ndl
```

---

### 哈佛大学图书馆 (Harvard)

```bash
# Check support
python -m bookget sites --check "https://curiosity.lib.harvard.edu/chinese-rare-books/catalog/49-990080724750203941"

# Get metadata
python -m bookget metadata "https://curiosity.lib.harvard.edu/chinese-rare-books/catalog/49-990080724750203941" --format json

# Download
python -m bookget download "https://curiosity.lib.harvard.edu/chinese-rare-books/catalog/49-990080724750203941" -o ./downloads/harvard
```

---

### 中国哲学书电子化计划 (CText)

```bash
# Check support  
python -m bookget sites --check "https://ctext.org/analects"

# Get metadata
python -m bookget metadata "https://ctext.org/analects" --format json

# Get text transcription
python -m bookget download "https://ctext.org/analects" -o ./downloads/ctext
```

---

### 识典古籍 (Shidianguji)

```bash
# Check support
python -m bookget sites --check "https://www.shidianguji.com/book/1"

# Get metadata  
python -m bookget metadata "https://www.shidianguji.com/book/1" --format json
```

---

### 法国国家图书馆 (BnF Gallica)

```bash
# Check support
python -m bookget sites --check "https://gallica.bnf.fr/ark:/12148/btv1b9006423x"

# Get metadata
python -m bookget metadata "https://gallica.bnf.fr/ark:/12148/btv1b9006423x" --format json

# Download
python -m bookget download "https://gallica.bnf.fr/ark:/12148/btv1b9006423x" -o ./downloads/bnf
```

---

### 大英图书馆 (British Library)

```bash
# Check support
python -m bookget sites --check "https://www.bl.uk/manuscripts/Viewer.aspx?ref=or_8210-s_6983"

# Get metadata
python -m bookget metadata "https://www.bl.uk/manuscripts/Viewer.aspx?ref=or_8210-s_6983" --format json
```

---

### 巴伐利亚州立图书馆 (BSB Munich)

```bash
# Check support
python -m bookget sites --check "https://www.digitale-sammlungen.de/de/view/bsb00089142"

# Get metadata
python -m bookget metadata "https://www.digitale-sammlungen.de/de/view/bsb00089142" --format json

# Download
python -m bookget download "https://www.digitale-sammlungen.de/de/view/bsb00089142" -o ./downloads/bsb
```

---

### 普林斯顿大学图书馆 (Princeton)

```bash
# Check support
python -m bookget sites --check "https://dpul.princeton.edu/eastasian/catalog/abc123"

# Get metadata
python -m bookget metadata "https://dpul.princeton.edu/eastasian/catalog/abc123" --format json
```

---

### 斯坦福大学图书馆 (Stanford)

```bash
# Check support
python -m bookget sites --check "https://purl.stanford.edu/bd123cd4567"

# Get metadata
python -m bookget metadata "https://purl.stanford.edu/bd123cd4567" --format json
```

---

### 臺灣國家圖書館 (NCL Taiwan)

```bash
# Check support
python -m bookget sites --check "https://rbook.ncl.edu.tw/ncltwcatchtitle/12345"

# Get metadata
python -m bookget metadata "https://rbook.ncl.edu.tw/ncltwcatchtitle/12345" --format json
```

---

### 臺灣故宮博物院 (NPM Taipei)

```bash
# Check support
python -m bookget sites --check "https://digitalarchive.npm.gov.tw/Painting/Content?pid=12345"

# Get metadata
python -m bookget metadata "https://digitalarchive.npm.gov.tw/Painting/Content?pid=12345" --format json
```

---

### Generic IIIF Manifest

```bash
# Any IIIF manifest URL
python -m bookget sites --check "https://example.com/iiif/manifest.json"

# Get metadata from manifest
python -m bookget metadata "https://example.com/iiif/manifest.json" --format json

# Download images
python -m bookget download "https://example.com/iiif/manifest.json" -o ./downloads/iiif
```

---

## Download Options

```bash
# Full download with all options
python -m bookget download "URL" \
    -o ./output_directory \    # Output directory
    --no-images \              # Skip image downloads
    --no-text \                # Skip text downloads
    --no-metadata \            # Skip metadata save
    --json \                   # Output JSON result
    -q \                       # Quiet mode (no progress)
    --debug                    # Enable debug logging
```

---

## Run Tests

```bash
# Run all tests
python -m pytest src/bookget/tests/ -v

# Run specific test file
python -m pytest src/bookget/tests/test_adapters.py -v

# Run with coverage
python -m pytest src/bookget/tests/ --cov=bookget
```
