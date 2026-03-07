"""Download manifest -- progressive discovery and incremental download tracking."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any


class NodeStatus(str, Enum):
    PENDING = "pending"          # Known to exist, children not yet expanded
    DISCOVERED = "discovered"    # Children expanded, ready for download
    DOWNLOADING = "downloading"  # Download in progress
    COMPLETED = "completed"      # Download finished
    FAILED = "failed"            # Download failed
    SKIPPED = "skipped"          # User chose to skip


class NodeType(str, Enum):
    ROOT = "root"         # Book root
    SECTION = "section"   # Intermediate grouping (部/篇/卷组)
    VOLUME = "volume"     # Volume (册, image container)
    CHAPTER = "chapter"   # Chapter (卷/章, text container)


class ResourceKind(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    MIXED = "mixed"


@dataclass
class ManifestNode:
    """A single node in the manifest tree."""
    id: str
    title: str = ""
    node_type: str = NodeType.CHAPTER
    status: str = NodeStatus.PENDING

    # Content counts
    resource_kind: str = ResourceKind.TEXT
    text_count: int = 0
    image_count: int = 0

    # Children
    children: List[ManifestNode] = field(default_factory=list)
    children_count: int = 0   # may differ from len(children) if partially expanded
    expandable: bool = False   # can be further expanded via expand_node()

    # Download progress (leaf nodes)
    downloaded_items: int = 0
    total_items: int = 0
    failed_items: int = 0

    # Adapter-specific data (e.g. hanchi node_id, nlc structure_id)
    source_data: Dict[str, Any] = field(default_factory=dict)

    # Local path (relative to manifest directory, set after download)
    local_path: str = ""

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize, omitting empty/default fields for readability."""
        d: dict = {"id": self.id, "title": self.title,
                   "type": self.node_type, "status": self.status}
        if self.resource_kind != ResourceKind.TEXT:
            d["resource_kind"] = self.resource_kind
        if self.text_count:
            d["text_count"] = self.text_count
        if self.image_count:
            d["image_count"] = self.image_count
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        if self.children_count and self.children_count != len(self.children):
            d["children_count"] = self.children_count
        if self.expandable:
            d["expandable"] = True
        if self.downloaded_items:
            d["downloaded_items"] = self.downloaded_items
        if self.total_items:
            d["total_items"] = self.total_items
        if self.failed_items:
            d["failed_items"] = self.failed_items
        if self.source_data:
            d["source_data"] = self.source_data
        if self.local_path:
            d["local_path"] = self.local_path
        return d

    @classmethod
    def from_dict(cls, data: dict) -> ManifestNode:
        children = [cls.from_dict(c) for c in data.get("children", [])]
        return cls(
            id=data["id"],
            title=data.get("title", ""),
            node_type=data.get("type", NodeType.CHAPTER),
            status=data.get("status", NodeStatus.PENDING),
            resource_kind=data.get("resource_kind", ResourceKind.TEXT),
            text_count=data.get("text_count", 0),
            image_count=data.get("image_count", 0),
            children=children,
            children_count=data.get("children_count", len(children)),
            expandable=data.get("expandable", False),
            downloaded_items=data.get("downloaded_items", 0),
            total_items=data.get("total_items", 0),
            failed_items=data.get("failed_items", 0),
            source_data=data.get("source_data", {}),
            local_path=data.get("local_path", ""),
        )

    # ------------------------------------------------------------------
    # Tree queries
    # ------------------------------------------------------------------

    def find_node(self, node_id: str) -> Optional[ManifestNode]:
        """DFS search for a node by ID."""
        if self.id == node_id:
            return self
        for child in self.children:
            found = child.find_node(node_id)
            if found:
                return found
        return None

    def get_leaf_nodes(self) -> List[ManifestNode]:
        """Return all leaf nodes (no children)."""
        if not self.children:
            return [self]
        leaves: list[ManifestNode] = []
        for child in self.children:
            leaves.extend(child.get_leaf_nodes())
        return leaves

    def get_text_nodes(self) -> List['ManifestNode']:
        """Return all nodes that carry downloadable text content.

        This includes leaf nodes AND non-leaf nodes that have their own
        text content (text_count > 0 and no local_path yet), which can
        happen when a section node in the source has both inline text and
        child sections (e.g. Hanchi 校印明實錄序 contains text itself
        while also having 後記 as a child).
        """
        result: list[ManifestNode] = []
        has_own_text = self.text_count and self.text_count > 0 and not self.local_path
        if not self.children:
            result.append(self)
        else:
            if has_own_text:
                result.append(self)
            for child in self.children:
                result.extend(child.get_text_nodes())
        return result

    def count_by_status(self) -> Dict[str, int]:
        """Count downloadable text nodes grouped by status."""
        counts: Dict[str, int] = {}
        for node in self.get_text_nodes():
            counts[node.status] = counts.get(node.status, 0) + 1
        return counts

    def update_ancestor_status(self):
        """Recursively update status of non-leaf nodes from children."""
        if not self.children:
            return
        for child in self.children:
            child.update_ancestor_status()
        statuses = {c.status for c in self.children}
        if statuses == {NodeStatus.COMPLETED}:
            self.status = NodeStatus.COMPLETED
        elif NodeStatus.DOWNLOADING in statuses:
            self.status = NodeStatus.DOWNLOADING
        elif NodeStatus.COMPLETED in statuses:
            # partially done
            self.status = NodeStatus.DOWNLOADING
        # else keep current status


@dataclass
class DownloadManifest:
    """Top-level manifest for a book download."""
    version: int = 1
    book_id: str = ""
    source_url: str = ""
    source_site: str = ""
    title: str = ""

    metadata: Dict[str, Any] = field(default_factory=dict)
    root: ManifestNode = field(
        default_factory=lambda: ManifestNode(id="root", node_type=NodeType.ROOT))

    discovery_complete: bool = False
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def touch(self):
        self.updated_at = datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "book_id": self.book_id,
            "source_url": self.source_url,
            "source_site": self.source_site,
            "title": self.title,
            "metadata": self.metadata,
            "structure": self.root.to_dict(),
            "discovery_complete": self.discovery_complete,
            "progress": self.get_progress(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DownloadManifest:
        return cls(
            version=data.get("version", 1),
            book_id=data.get("book_id", ""),
            source_url=data.get("source_url", ""),
            source_site=data.get("source_site", ""),
            title=data.get("title", ""),
            metadata=data.get("metadata", {}),
            root=ManifestNode.from_dict(
                data.get("structure", {"id": "root", "type": "root"})),
            discovery_complete=data.get("discovery_complete", False),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )

    def save(self, path: Path):
        self.touch()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> Optional[DownloadManifest]:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def find_node(self, node_id: str) -> Optional[ManifestNode]:
        return self.root.find_node(node_id)

    def get_progress(self) -> dict:
        counts = self.root.count_by_status()
        total = sum(counts.values())
        completed = counts.get(NodeStatus.COMPLETED, 0)
        return {
            "total": total,
            "completed": completed,
            "failed": counts.get(NodeStatus.FAILED, 0),
            "pending": counts.get(NodeStatus.PENDING, 0),
            "downloading": counts.get(NodeStatus.DOWNLOADING, 0),
            "percent": round(completed * 100 / total) if total > 0 else 0,
        }

    def get_downloadable_nodes(
        self, node_ids: List[str] = None,
    ) -> List[ManifestNode]:
        """Get nodes ready for download.

        If *node_ids* given, collect leaf descendants of those nodes.
        Otherwise collect all discovered/failed leaf nodes.
        """
        downloadable = {NodeStatus.DISCOVERED, NodeStatus.FAILED}
        if node_ids:
            nodes: list[ManifestNode] = []
            for nid in node_ids:
                node = self.find_node(nid)
                if node:
                    nodes.extend(
                        n for n in node.get_text_nodes()
                        if n.status in downloadable)
            return nodes
        return [n for n in self.root.get_text_nodes()
                if n.status in downloadable]
