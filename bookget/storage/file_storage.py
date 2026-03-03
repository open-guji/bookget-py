# File Storage - Handle saving downloaded resources and metadata

import json
from pathlib import Path
from typing import Optional, Dict, Any
import re

from ..models.book import BookMetadata, Resource
from ..logger import logger
from ..exceptions import StorageError


class FileStorage:
    """
    Handles file storage operations for downloaded resources.
    
    Directory structure:
    output_root/
    ├── {book_id}/
    │   ├── metadata.json
    │   ├── images/
    │   │   ├── v01_0001.jpg
    │   │   └── ...
    │   ├── text/
    │   │   └── content.txt
    │   └── pdf/
    │       └── book.pdf
    """
    
    def __init__(self, output_root: Path):
        self.output_root = Path(output_root)
    
    def get_book_dir(self, book_id: str) -> Path:
        """Get the directory for a book's resources."""
        # Sanitize book_id for filesystem
        safe_id = self._sanitize_filename(book_id)
        return self.output_root / safe_id
    
    def get_image_dir(self, book_id: str) -> Path:
        """Get the images directory for a book."""
        return self.get_book_dir(book_id) / "images"
    
    def get_text_dir(self, book_id: str) -> Path:
        """Get the text directory for a book."""
        return self.get_book_dir(book_id) / "text"
    
    def get_metadata_path(self, book_id: str) -> Path:
        """Get the metadata file path for a book."""
        return self.get_book_dir(book_id) / "metadata.json"
    
    def ensure_book_dir(self, book_id: str) -> Path:
        """Create book directory structure."""
        book_dir = self.get_book_dir(book_id)
        book_dir.mkdir(parents=True, exist_ok=True)
        self.get_image_dir(book_id).mkdir(exist_ok=True)
        self.get_text_dir(book_id).mkdir(exist_ok=True)
        return book_dir
    
    def save_metadata(self, book_id: str, metadata: BookMetadata) -> Path:
        """
        Save book metadata to JSON file.
        
        Args:
            book_id: The book identifier
            metadata: BookMetadata object
            
        Returns:
            Path to the saved metadata file
        """
        self.ensure_book_dir(book_id)
        path = self.get_metadata_path(book_id)
        
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(metadata.to_dict(), f, ensure_ascii=False, indent=2)
            logger.debug(f"Saved metadata: {path}")
            return path
        except Exception as e:
            raise StorageError(f"Failed to save metadata: {e}")
    
    def load_metadata(self, book_id: str) -> Optional[BookMetadata]:
        """
        Load book metadata from JSON file.
        
        Args:
            book_id: The book identifier
            
        Returns:
            BookMetadata object or None if not found
        """
        path = self.get_metadata_path(book_id)
        if not path.exists():
            return None
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return BookMetadata.from_dict(data)
        except Exception as e:
            logger.warning(f"Failed to load metadata: {e}")
            return None
    
    def get_image_path(self, book_id: str, resource: Resource) -> Path:
        """Get the path for saving an image resource."""
        image_dir = self.get_image_dir(book_id)
        filename = resource.get_filename()
        return image_dir / filename
    
    def get_text_path(self, book_id: str, filename: str = "content.txt") -> Path:
        """Get the path for saving text content."""
        text_dir = self.get_text_dir(book_id)
        return text_dir / filename
    
    def save_text(self, book_id: str, content: str, filename: str = "content.txt") -> Path:
        """
        Save text content to file.
        
        Args:
            book_id: The book identifier
            content: Text content to save
            filename: Output filename
            
        Returns:
            Path to the saved text file
        """
        self.ensure_book_dir(book_id)
        path = self.get_text_path(book_id, filename)
        
        try:
            path.write_text(content, encoding="utf-8")
            logger.debug(f"Saved text: {path}")
            return path
        except Exception as e:
            raise StorageError(f"Failed to save text: {e}")
    
    def list_books(self) -> list:
        """List all book IDs in storage."""
        if not self.output_root.exists():
            return []
        
        return [
            d.name for d in self.output_root.iterdir()
            if d.is_dir() and (d / "metadata.json").exists()
        ]
    
    def _sanitize_filename(self, name: str) -> str:
        """Sanitize a string for use as a filename/directory name."""
        # Replace problematic characters for Windows/Linux and shell-sensitive characters
        # Including: < > : " / \ | ? * & '
        sanitized = re.sub(r'[<>:"/\\|?*&\'\s]', '_', name)
        # Limit length and remove trailing dots/spaces
        return sanitized.strip(" .")[:200]
