# Data models for Guji Resource Manager

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class ResourceType(Enum):
    """Type of downloadable resource."""
    IMAGE = "image"
    TEXT = "text"
    PDF = "pdf"
    MANIFEST = "manifest"


@dataclass
class Creator:
    """Author/contributor information."""
    name: str
    role: str = ""           # 注、撰、輯、釋文 等
    dynasty: str = ""        # 三國魏、晉、唐 等
    
    def __str__(self) -> str:
        parts = []
        if self.dynasty:
            parts.append(f"[{self.dynasty}]")
        parts.append(self.name)
        if self.role:
            parts.append(self.role)
        return " ".join(parts)


@dataclass
class Resource:
    """A downloadable resource (image, text, etc.)."""
    url: str
    resource_type: ResourceType
    order: int = 0           # Order/sequence number
    volume: str = ""         # Volume/册 identifier
    page: str = ""           # Page number
    filename: str = ""       # Suggested filename
    
    # IIIF specific
    iiif_service_id: str = ""
    width: int = 0
    height: int = 0
    
    # Download status
    downloaded: bool = False
    local_path: str = ""
    
    def get_filename(self) -> str:
        """Generate filename if not provided."""
        if self.filename:
            return self.filename
        
        parts = []
        if self.volume:
            parts.append(f"v{self.volume}")
        parts.append(f"{self.order:04d}")
        
        ext = ".jpg" if self.resource_type == ResourceType.IMAGE else ".txt"
        return "_".join(parts) + ext


@dataclass
class BookMetadata:
    """Complete metadata for a book."""
    # Core identifiers
    id: str = ""                    # Internal ID (from book_index_manager)
    source_id: str = ""             # Source site's ID
    source_url: str = ""            # Original URL
    source_site: str = ""           # Site name (e.g., "harvard", "nlc_guji")
    index_id: str = ""              # Global index ID (Base58)
    
    # Basic info
    title: str = ""
    alt_titles: List[str] = field(default_factory=list)
    creators: List[Creator] = field(default_factory=list)
    
    # Publication info
    dynasty: str = ""               # 朝代
    date: str = ""                  # 出版年代 (原始格式)
    date_normalized: str = ""       # 标准化年份 (公元)
    publisher: str = ""
    place: str = ""                 # 出版地
    
    # Physical description
    volumes: int = 0                # 册数
    volume_info: str = ""           # 原始描述如 "3冊"
    pages: int = 0                  # 总页数
    binding: str = ""               # 装帧形式
    dimensions: str = ""            # 开本尺寸
    layout: str = ""                # 行款版式
    
    # Classification
    category: str = ""              # 四部分类
    doc_type: str = ""              # 文献类型
    language: str = ""              # 语种
    
    # Collection info
    collection_unit: str = ""       # 收藏单位
    call_number: str = ""           # 索书号
    doi: str = ""                   # DOI
    
    # Additional
    notes: List[str] = field(default_factory=list)
    provenance: List[str] = field(default_factory=list)    # 批校题跋
    subjects: List[str] = field(default_factory=list)       # 主题
    
    # Rights
    rights: str = ""                # 版权信息
    license: str = ""               # 许可协议
    
    # IIIF specific
    iiif_manifest_url: str = ""
    
    # Raw data for preservation
    raw_metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "source_id": self.source_id,
            "source_url": self.source_url,
            "source_site": self.source_site,
            "title": self.title,
            "alt_titles": self.alt_titles,
            "creators": [
                {"name": c.name, "role": c.role, "dynasty": c.dynasty}
                for c in self.creators
            ],
            "dynasty": self.dynasty,
            "date": self.date,
            "date_normalized": self.date_normalized,
            "publisher": self.publisher,
            "place": self.place,
            "volumes": self.volumes,
            "volume_info": self.volume_info,
            "pages": self.pages,
            "binding": self.binding,
            "dimensions": self.dimensions,
            "layout": self.layout,
            "category": self.category,
            "doc_type": self.doc_type,
            "language": self.language,
            "collection_unit": self.collection_unit,
            "call_number": self.call_number,
            "doi": self.doi,
            "notes": self.notes,
            "provenance": self.provenance,
            "subjects": self.subjects,
            "rights": self.rights,
            "license": self.license,
            "iiif_manifest_url": self.iiif_manifest_url,
            "index_id": self.index_id,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BookMetadata":
        """Create from dictionary."""
        creators = [
            Creator(**c) for c in data.pop("creators", [])
        ]
        return cls(creators=creators, **data)


@dataclass 
class DownloadTask:
    """A download task for a book."""
    book_id: str
    url: str
    metadata: Optional[BookMetadata] = None
    resources: List[Resource] = field(default_factory=list)
    output_dir: str = ""
    index_id: str = ""
    
    # Progress tracking
    total_resources: int = 0
    downloaded_count: int = 0
    failed_count: int = 0
    
    # Options
    include_images: bool = True
    include_text: bool = True
    include_metadata: bool = True
    max_concurrent: int = 4
    
    @property
    def progress(self) -> float:
        """Download progress as percentage."""
        if self.total_resources == 0:
            return 0.0
        return (self.downloaded_count / self.total_resources) * 100
