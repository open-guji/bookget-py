"""Convert structured JSON to plain text format."""


class PlainTextConverter:
    """Convert StructuredText dict to plain text (no markup)."""

    def convert(self, data: dict) -> str:
        """Convert structured text data to plain text string.

        Args:
            data: StructuredText dict (as returned by StructuredText.to_dict())

        Returns:
            Plain text string
        """
        lines = []

        for ch in data.get("chapters", []):
            ch_title = ch.get("title", "")
            if ch_title:
                lines.append(ch_title)
                lines.append("")

            for para in ch.get("paragraphs", []):
                text = str(para).strip()
                if text:
                    lines.append(text)
            lines.append("")

        return "\n".join(lines)
