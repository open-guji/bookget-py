# Tests for data models

import pytest
from bookget.models import (
    BookMetadata,
    Resource,
    ResourceType,
    Creator,
    DownloadTask,
)


class TestCreator:
    """Tests for Creator model."""
    
    def test_str_basic(self):
        creator = Creator(name="李白")
        assert str(creator) == "李白"
    
    def test_str_with_role(self):
        creator = Creator(name="朱熹", role="注")
        assert str(creator) == "朱熹 注"
    
    def test_str_with_dynasty(self):
        creator = Creator(name="李白", dynasty="唐", role="撰")
        assert str(creator) == "[唐] 李白 撰"


class TestResource:
    """Tests for Resource model."""
    
    def test_get_filename_default(self):
        resource = Resource(
            url="https://example.com/image.jpg",
            resource_type=ResourceType.IMAGE,
            order=5
        )
        filename = resource.get_filename()
        assert filename == "0005.jpg"
    
    def test_get_filename_with_volume(self):
        resource = Resource(
            url="https://example.com/image.jpg",
            resource_type=ResourceType.IMAGE,
            order=5,
            volume="2"
        )
        filename = resource.get_filename()
        assert filename == "v2_0005.jpg"
    
    def test_get_filename_explicit(self):
        resource = Resource(
            url="https://example.com/image.jpg",
            resource_type=ResourceType.IMAGE,
            order=5,
            filename="custom.jpg"
        )
        assert resource.get_filename() == "custom.jpg"
    
    def test_text_extension(self):
        resource = Resource(
            url="https://example.com/text",
            resource_type=ResourceType.TEXT,
            order=1
        )
        assert resource.get_filename().endswith(".txt")


class TestBookMetadata:
    """Tests for BookMetadata model."""
    
    def test_to_dict(self):
        metadata = BookMetadata(
            id="test123",
            title="論語",
            dynasty="春秋",
            creators=[Creator(name="孔子")]
        )
        d = metadata.to_dict()
        
        assert d["id"] == "test123"
        assert d["title"] == "論語"
        assert d["dynasty"] == "春秋"
        assert len(d["creators"]) == 1
        assert d["creators"][0]["name"] == "孔子"
    
    def test_from_dict(self):
        data = {
            "id": "test123",
            "title": "論語",
            "dynasty": "春秋",
            "creators": [{"name": "孔子", "role": "", "dynasty": ""}]
        }
        metadata = BookMetadata.from_dict(data)
        
        assert metadata.id == "test123"
        assert metadata.title == "論語"
        assert len(metadata.creators) == 1
        assert metadata.creators[0].name == "孔子"


class TestDownloadTask:
    """Tests for DownloadTask model."""
    
    def test_progress_empty(self):
        task = DownloadTask(book_id="test", url="https://example.com")
        assert task.progress == 0.0
    
    def test_progress_partial(self):
        task = DownloadTask(
            book_id="test",
            url="https://example.com",
            total_resources=10,
            downloaded_count=5
        )
        assert task.progress == 50.0
    
    def test_progress_complete(self):
        task = DownloadTask(
            book_id="test",
            url="https://example.com",
            total_resources=10,
            downloaded_count=10
        )
        assert task.progress == 100.0
