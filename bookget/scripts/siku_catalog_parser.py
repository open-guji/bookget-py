import json
import re
import sys
from pathlib import Path


def emit_progress(event_type: str, **kwargs):
    """Emit a JSONL progress event to stdout."""
    event = {"type": event_type, **kwargs}
    print(json.dumps(event, ensure_ascii=False), flush=True)

# Common dynasties in Siku Catalog
DYNASTIES = [
    "周", "秦", "漢", "魏", "蜀", "吳", "晉", "宋", "齊", "梁", "陳", "隋", "唐", "元", "明", "清", "國朝", 
    "後周", "北齊", "北周", "南唐", "後唐", "後晉", "後漢", "遼", "金", "西夏"
]

def _is_standalone_heading(text: str) -> bool:
    """Check if a plain-text line should be promoted to a category heading.

    Handles lines like "附錄" that CText stores without any * prefix.
    Also handles already-promoted "**附錄" from normalized data.
    """
    return text in ("附錄",)


def parse_siku_catalog(json_path: str):
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    books = []
    current_section = ""
    current_category = ""

    for chapter in data.get("chapters", []):
        paragraphs = chapter.get("paragraphs", [])
        i = 0
        while i < len(paragraphs):
            p = paragraphs[i].strip()

            # Section header: *經部一
            if p.startswith("*") and not p.startswith("**") and not p.startswith("***"):
                current_section = p.lstrip("*")
                i += 1
                continue

            # Category header: **易類
            if p.startswith("**") and not p.startswith("***"):
                current_category = p.lstrip("*")
                i += 1
                continue

            # Standalone heading (e.g. "附錄" without * prefix)
            if _is_standalone_heading(p):
                current_category = p
                i += 1
                continue
                
            # Book record: ***《Title》Volumes
            if p.startswith("***《"):
                title_line = p.lstrip("*")
                matches = re.findall(r"《(.*?)》(.*?)($|，| |、)", title_line)
                
                titles_vols = []
                for m in matches:
                    titles_vols.append({"title": m[0], "volumes": m[1].strip()})
                
                i += 1
                content_paragraphs = []
                notes = []
                
                # Next paragraphs might be summary or notes
                while i < len(paragraphs):
                    next_p = paragraphs[i].strip()
                    if next_p.startswith("*") or _is_standalone_heading(next_p):
                        break # Next section/category/book/heading
                    
                    if next_p.startswith("謹案："):
                        notes.append(next_p)
                    elif next_p.startswith("{{{"):
                         # Possible note or embedded info
                         notes.append(next_p)
                    else:
                        content_paragraphs.append(next_p)
                    i += 1
                
                # If no content paragraphs but we have notes, the first note might contain author
                if not content_paragraphs and notes:
                    # Heuristic: if a note starts with {{{謹案：...}}} but contains author info after it
                    # Example: {{{謹案：《總目》此部不存。}}}明成矩撰。
                    first_note = notes[0]
                    if "}}} " in first_note or "}}}" in first_note:
                        parts = re.split(r"}}}", first_note, maxsplit=1)
                        if len(parts) > 1 and parts[1].strip():
                            content_paragraphs.append(parts[1].strip())
                            notes[0] = parts[0] + "}}}"
                
                summary = "\n".join(content_paragraphs)
                full_notes = "\n".join(notes)
                
                for tv in titles_vols:
                    author = extract_author(summary)
                    if not author and full_notes:
                         # Try extracting from notes if summary is empty
                         author = extract_author(full_notes)
                    
                    books.append({
                        "title": tv["title"],
                        "volumes": tv["volumes"],
                        "author": author,
                        "summary": summary,
                        "notes": full_notes,
                        "section": current_section,
                        "category": current_category
                    })
                continue
            
            i += 1
            
    return books

def extract_author(text: str) -> str:
    """Extract author using improved heuristics."""
    if not text:
        return ""
    
    # Try to clean up the start
    text = re.sub(r"^.*?}}}", "", text).strip()
    
    # First sentence usually contains author
    # Handle both full-width and half-width punctuation
    first_sentence = re.split(r"[。！？]", text)[0]
    
    # Look for roles
    roles = ["撰", "編", "註", "注", "輯", "著", "述", "正", "校", "刪", "次", "訂", "集"]
    
    # Sort roles by length descending to catch multi-character roles if any (though usually single)
    
    # Try to find a role-based signature
    # Pattern: [Dynasty] [Name] [Role]
    for role in roles:
        role_search = re.search(r"([^，、 ]*?)" + role, first_sentence)
        if role_search:
            author_candidate = role_search.group(1) + role
            # Check if it starts with a dynasty
            for d in DYNASTIES:
                if author_candidate.startswith(d):
                    return author_candidate
            
            # If no dynasty found but role matches, still might be it
            # But avoid too short strings or common words
            if len(author_candidate) > 2:
                return author_candidate
                
    # Fallback: check for "題...撰"
    題撰 = re.search(r"題(.*?)撰", first_sentence)
    if 題撰:
        return "題" + 題撰.group(1) + "撰"

    return ""

def _clean_markup(text: str) -> str:
    """Remove CText wiki markup like {{{...}}} wrappers."""
    # Remove {{{ and }}} markers but keep content
    text = re.sub(r'\{\{\{', '', text)
    text = re.sub(r'\}\}\}', '', text)
    return text.strip()


def parse_by_volume(json_path: str, output_dir: str, json_progress: bool = False):
    """Parse raw.ctext.json into per-juan JSON files with hierarchical structure.

    Output format per juan (juan01.json, juan02.json, ...):
    {
      "volume": 1,
      "volume_title": "卷一",
      "sections": [{
        "section": "經部一",
        "categories": [{
          "category": "易類",
          "books": [{
            "id": "juan01:001",
            "title": "《子夏易傳》十一卷",
            "detail": "...",
            "comment": "...",
            "author": "...",
            "order": 1
          }]
        }]
      }],
      "stats": { "sections": N, "categories": N, "books": N }
    }
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    total_books = 0
    summary_volumes = []

    for vol_idx, chapter in enumerate(data.get("chapters", [])):
        vol_num = vol_idx + 1
        vol_title = chapter.get("title", f"卷{vol_num}")
        paragraphs = chapter.get("paragraphs", [])

        sections = []
        current_section = None
        current_category = None
        book_order = 0

        i = 0
        while i < len(paragraphs):
            p = paragraphs[i].strip()

            # Section header: *經部一
            if p.startswith("*") and not p.startswith("**"):
                section_name = p.lstrip("*").strip()
                current_section = {
                    "section": section_name,
                    "categories": []
                }
                sections.append(current_section)
                current_category = None
                i += 1
                continue

            # Category header: **易類  (also handles standalone headings like "附錄")
            is_star_category = p.startswith("**") and not p.startswith("***")
            is_standalone = (not p.startswith("*")) and _is_standalone_heading(p)
            if is_star_category or is_standalone:
                cat_name = p.lstrip("*").strip()
                current_category = {
                    "category": cat_name,
                    "books": []
                }
                if current_section is None:
                    # Edge case: category before section (continuation from previous volume)
                    current_section = {"section": "(續)", "categories": []}
                    sections.append(current_section)
                current_section["categories"].append(current_category)
                i += 1
                continue

            # Book record: ***《Title》
            if p.startswith("***"):
                book_order += 1
                title_line = p.lstrip("*").strip()
                title_line = _clean_markup(title_line)

                # Collect subsequent non-* paragraphs as detail/comment
                i += 1
                detail_parts = []
                comment_parts = []

                while i < len(paragraphs):
                    next_p = paragraphs[i].strip()
                    if next_p.startswith("*") or _is_standalone_heading(next_p):
                        break

                    cleaned = _clean_markup(next_p)
                    if cleaned.startswith("謹案") or cleaned.startswith("案："):
                        comment_parts.append(cleaned)
                    else:
                        detail_parts.append(cleaned)
                    i += 1

                detail = "\n".join(detail_parts)
                comment = "\n".join(comment_parts)
                author = extract_author(detail)
                if not author and comment:
                    author = extract_author(comment)

                book_entry = {
                    "id": f"juan{vol_num:02d}:{book_order:03d}",
                    "title": title_line,
                    "detail": detail,
                    "comment": comment,
                    "author": author,
                    "order": book_order
                }

                if current_category is None:
                    # Edge case: book before any category header
                    if current_section is None:
                        current_section = {"section": "(續)", "categories": []}
                        sections.append(current_section)
                    current_category = {"category": "(續)", "books": []}
                    current_section["categories"].append(current_category)

                current_category["books"].append(book_entry)
                continue

            i += 1

        # Calculate stats
        n_sections = len(sections)
        n_categories = sum(len(s["categories"]) for s in sections)
        n_books = book_order
        total_books += n_books

        vol_data = {
            "volume": vol_num,
            "volume_title": vol_title,
            "sections": sections,
            "stats": {
                "sections": n_sections,
                "categories": n_categories,
                "books": n_books
            }
        }

        # Write per-volume JSON
        vol_file = out / f"juan{vol_num:02d}.json"
        with open(vol_file, 'w', encoding='utf-8') as f:
            json.dump(vol_data, f, ensure_ascii=False, indent=2)

        summary_volumes.append({
            "volume": vol_num,
            "title": vol_title,
            "sections": n_sections,
            "categories": n_categories,
            "books": n_books
        })

        total_chapters = len(data.get("chapters", []))
        if json_progress:
            emit_progress("progress", task="parse-text",
                          current=vol_num, total=total_chapters,
                          message=f"解析卷{vol_num} ({n_books} 条)")
        else:
            print(f"  juan{vol_num:02d}.json: {n_sections} sections, {n_categories} categories, {n_books} books")

    # Write summary
    summary = {
        "total_volumes": len(summary_volumes),
        "total_books": total_books,
        "volumes": summary_volumes
    }
    summary_file = out / "summary.json"
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    if json_progress:
        emit_progress("complete", task="parse-text",
                      message=f"全部 {len(summary_volumes)} 卷解析完成, 共 {total_books} 条")
    else:
        print(f"\nTotal: {len(summary_volumes)} volumes, {total_books} books")
        print(f"Output: {output_dir}")
    return summary


if __name__ == "__main__":
    args = sys.argv[1:]
    json_progress = "--json-progress" in args
    if json_progress:
        args.remove("--json-progress")

    if len(args) < 1:
        print("Usage:")
        print("  python siku_catalog_parser.py <raw.ctext.json> [output_json]        # flat list")
        print("  python siku_catalog_parser.py --by-volume <raw.ctext.json> <output_dir>  # per-volume")
        print("  Add --json-progress for JSONL progress output")
        sys.exit(1)

    if args[0] == "--by-volume":
        if len(args) < 3:
            print("Usage: python siku_catalog_parser.py --by-volume <raw.ctext.json> <output_dir>")
            sys.exit(1)
        parse_by_volume(args[1], args[2], json_progress=json_progress)
    else:
        books = parse_siku_catalog(args[0])
        if not json_progress:
            print(f"Extracted {len(books)} books.")

        output_path = args[1] if len(args) > 1 else "siku_books.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(books, f, ensure_ascii=False, indent=2)
        if json_progress:
            emit_progress("complete", task="parse-text",
                          message=f"提取 {len(books)} 条书目")
        else:
            print(f"Saved to {output_path}")
