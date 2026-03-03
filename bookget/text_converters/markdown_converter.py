"""Convert structured JSON to Markdown format."""


class MarkdownConverter:
    """Convert StructuredText dict to Markdown."""

    def convert(self, data: dict) -> str:
        """Convert structured text data to Markdown string.

        Args:
            data: StructuredText dict (as returned by StructuredText.to_dict())

        Returns:
            Markdown formatted string
        """
        lines = []

        # Title
        title = data.get("title", "")
        if title:
            lines.append(f"# {title}")
            lines.append("")

        # Author info from metadata
        meta = data.get("metadata", {})
        authors = meta.get("authors", [])
        if authors:
            parts = []
            for a in authors:
                dynasty = a.get("dynasty", "")
                name = a.get("name", "")
                role = a.get("role", "")
                if dynasty:
                    parts.append(f"[{dynasty}] {name} {role}".strip())
                else:
                    parts.append(f"{name} {role}".strip())
            lines.append(f"> {', '.join(parts)}")
            lines.append("")

        # Chapters
        chapters = data.get("chapters", [])
        for ch in chapters:
            ch_title = ch.get("title", "")
            if ch_title:
                lines.append(f"## {ch_title}")
                lines.append("")

            for para in ch.get("paragraphs", []):
                text = str(para).strip()
                if text:
                    lines.append(text)
                    lines.append("")

        return "\n".join(lines)
