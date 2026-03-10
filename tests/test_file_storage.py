# Tests for FileStorage

import json
import pytest
from pathlib import Path

from bookget.storage.file_storage import FileStorage
from bookget.models.book import BookMetadata, Resource, ResourceType, Creator


class TestFileStoragePaths:
    """Tests for path generation."""

    def test_get_book_dir(self, tmp_path):
        storage = FileStorage(tmp_path)
        book_dir = storage.get_book_dir("test_book")
        assert book_dir == tmp_path / "test_book"

    def test_get_book_dir_sanitizes(self, tmp_path):
        storage = FileStorage(tmp_path)
        # Characters like : and / should be replaced
        book_dir = storage.get_book_dir("hanchi:30211001")
        assert ":" not in book_dir.name

    def test_get_image_dir(self, tmp_path):
        storage = FileStorage(tmp_path)
        assert storage.get_image_dir("book1") == tmp_path / "book1" / "images"

    def test_get_text_dir(self, tmp_path):
        storage = FileStorage(tmp_path)
        assert storage.get_text_dir("book1") == tmp_path / "book1" / "text"

    def test_get_metadata_path(self, tmp_path):
        storage = FileStorage(tmp_path)
        assert storage.get_metadata_path("book1") == tmp_path / "book1" / "metadata.json"


class TestFileStorageEnsureDirs:
    """Tests for directory creation."""

    def test_ensure_book_dir(self, tmp_path):
        storage = FileStorage(tmp_path)
        book_dir = storage.ensure_book_dir("my_book")

        assert book_dir.is_dir()
        assert (book_dir / "images").is_dir()
        assert (book_dir / "text").is_dir()

    def test_ensure_book_dir_idempotent(self, tmp_path):
        storage = FileStorage(tmp_path)
        storage.ensure_book_dir("my_book")
        storage.ensure_book_dir("my_book")  # should not raise


class TestFileStorageMetadata:
    """Tests for metadata save/load."""

    def test_save_and_load_metadata(self, tmp_path):
        storage = FileStorage(tmp_path)
        metadata = BookMetadata(
            id="test123",
            title="論語",
            dynasty="春秋",
            creators=[Creator(name="孔子")],
        )

        path = storage.save_metadata("test123", metadata)
        assert path.exists()

        loaded = storage.load_metadata("test123")
        assert loaded is not None
        assert loaded.title == "論語"
        assert loaded.dynasty == "春秋"
        assert len(loaded.creators) == 1
        assert loaded.creators[0].name == "孔子"

    def test_load_metadata_nonexistent(self, tmp_path):
        storage = FileStorage(tmp_path)
        assert storage.load_metadata("nonexistent") is None

    def test_save_metadata_creates_dirs(self, tmp_path):
        storage = FileStorage(tmp_path)
        metadata = BookMetadata(id="new_book", title="Test")
        path = storage.save_metadata("new_book", metadata)
        assert path.exists()
        assert (tmp_path / "new_book" / "images").is_dir()


class TestFileStorageText:
    """Tests for text save."""

    def test_save_text(self, tmp_path):
        storage = FileStorage(tmp_path)
        path = storage.save_text("book1", "天地玄黃，宇宙洪荒。")
        assert path.exists()
        assert path.read_text(encoding="utf-8") == "天地玄黃，宇宙洪荒。"

    def test_save_text_custom_filename(self, tmp_path):
        storage = FileStorage(tmp_path)
        path = storage.save_text("book1", "content", filename="chapter1.txt")
        assert path.name == "chapter1.txt"
        assert path.read_text(encoding="utf-8") == "content"


class TestFileStorageImagePath:
    """Tests for image path generation."""

    def test_get_image_path(self, tmp_path):
        storage = FileStorage(tmp_path)
        resource = Resource(
            url="http://example.com/img.jpg",
            resource_type=ResourceType.IMAGE,
            order=5,
        )
        path = storage.get_image_path("book1", resource)
        assert path == tmp_path / "book1" / "images" / "0005.jpg"


class TestFileStorageListBooks:
    """Tests for listing books."""

    def test_list_books_empty(self, tmp_path):
        storage = FileStorage(tmp_path)
        assert storage.list_books() == []

    def test_list_books_with_metadata(self, tmp_path):
        storage = FileStorage(tmp_path)
        # Create two books with metadata
        storage.save_metadata("book_a", BookMetadata(id="a", title="A"))
        storage.save_metadata("book_b", BookMetadata(id="b", title="B"))

        # Create a directory without metadata (should not appear)
        (tmp_path / "not_a_book").mkdir()

        books = storage.list_books()
        assert len(books) == 2
        assert "book_a" in books
        assert "book_b" in books
        assert "not_a_book" not in books

    def test_list_books_nonexistent_root(self):
        storage = FileStorage(Path("/nonexistent/path"))
        assert storage.list_books() == []


class TestSanitizeFilename:
    """Tests for _sanitize_filename."""

    def test_removes_colon(self):
        storage = FileStorage(Path("/tmp"))
        assert ":" not in storage._sanitize_filename("hanchi:30211001")

    def test_removes_slash(self):
        storage = FileStorage(Path("/tmp"))
        assert "/" not in storage._sanitize_filename("path/with/slashes")
        assert "\\" not in storage._sanitize_filename("path\\back")

    def test_length_limit(self):
        storage = FileStorage(Path("/tmp"))
        long_name = "a" * 300
        assert len(storage._sanitize_filename(long_name)) <= 200

    def test_trailing_dots_stripped(self):
        storage = FileStorage(Path("/tmp"))
        assert not storage._sanitize_filename("name...").endswith(".")
