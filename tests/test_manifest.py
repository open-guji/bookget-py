# Tests for DownloadManifest and ManifestNode models

import json
import pytest
from pathlib import Path

from bookget.models.manifest import (
    ManifestNode, DownloadManifest,
    NodeStatus, NodeType, ResourceKind,
)


class TestManifestNode:
    """Tests for ManifestNode."""

    def test_defaults(self):
        node = ManifestNode(id="n1")
        assert node.id == "n1"
        assert node.status == NodeStatus.PENDING
        assert node.node_type == NodeType.CHAPTER
        assert node.children == []

    def test_to_dict_minimal(self):
        node = ManifestNode(id="n1", title="Test")
        d = node.to_dict()
        assert d["id"] == "n1"
        assert d["title"] == "Test"
        # Default fields should be omitted
        assert "resource_kind" not in d
        assert "children" not in d
        assert "expandable" not in d

    def test_to_dict_with_children(self):
        child = ManifestNode(id="c1", title="Child")
        node = ManifestNode(id="n1", title="Parent", children=[child])
        d = node.to_dict()
        assert len(d["children"]) == 1
        assert d["children"][0]["id"] == "c1"

    def test_to_dict_non_default_fields(self):
        node = ManifestNode(
            id="n1", title="Test",
            resource_kind=ResourceKind.IMAGE,
            text_count=5, image_count=10,
            expandable=True,
            downloaded_items=3, total_items=10, failed_items=1,
            source_data={"key": "val"},
            local_path="images/",
        )
        d = node.to_dict()
        assert d["resource_kind"] == ResourceKind.IMAGE
        assert d["text_count"] == 5
        assert d["image_count"] == 10
        assert d["expandable"] is True
        assert d["downloaded_items"] == 3
        assert d["source_data"] == {"key": "val"}
        assert d["local_path"] == "images/"

    def test_roundtrip(self):
        child = ManifestNode(id="c1", title="Child", status=NodeStatus.COMPLETED)
        node = ManifestNode(
            id="n1", title="Parent",
            node_type=NodeType.SECTION,
            children=[child],
            source_data={"foo": "bar"},
        )
        d = node.to_dict()
        restored = ManifestNode.from_dict(d)
        assert restored.id == "n1"
        assert restored.node_type == NodeType.SECTION
        assert len(restored.children) == 1
        assert restored.children[0].status == NodeStatus.COMPLETED
        assert restored.source_data == {"foo": "bar"}

    def test_find_node(self):
        grandchild = ManifestNode(id="gc1")
        child = ManifestNode(id="c1", children=[grandchild])
        root = ManifestNode(id="root", children=[child])

        assert root.find_node("root") is root
        assert root.find_node("c1") is child
        assert root.find_node("gc1") is grandchild
        assert root.find_node("missing") is None

    def test_get_leaf_nodes(self):
        leaf1 = ManifestNode(id="l1")
        leaf2 = ManifestNode(id="l2")
        branch = ManifestNode(id="b1", children=[leaf1, leaf2])
        root = ManifestNode(id="root", children=[branch])

        leaves = root.get_leaf_nodes()
        assert len(leaves) == 2
        assert {n.id for n in leaves} == {"l1", "l2"}

    def test_get_leaf_nodes_single(self):
        node = ManifestNode(id="solo")
        assert node.get_leaf_nodes() == [node]

    def test_count_by_status(self):
        leaves = [
            ManifestNode(id="1", status=NodeStatus.COMPLETED),
            ManifestNode(id="2", status=NodeStatus.COMPLETED),
            ManifestNode(id="3", status=NodeStatus.FAILED),
            ManifestNode(id="4", status=NodeStatus.PENDING),
        ]
        root = ManifestNode(id="root", children=leaves)
        counts = root.count_by_status()
        assert counts[NodeStatus.COMPLETED] == 2
        assert counts[NodeStatus.FAILED] == 1
        assert counts[NodeStatus.PENDING] == 1

    def test_update_ancestor_status_all_completed(self):
        children = [
            ManifestNode(id="1", status=NodeStatus.COMPLETED),
            ManifestNode(id="2", status=NodeStatus.COMPLETED),
        ]
        root = ManifestNode(id="root", children=children)
        root.update_ancestor_status()
        assert root.status == NodeStatus.COMPLETED

    def test_update_ancestor_status_partial(self):
        children = [
            ManifestNode(id="1", status=NodeStatus.COMPLETED),
            ManifestNode(id="2", status=NodeStatus.PENDING),
        ]
        root = ManifestNode(id="root", children=children)
        root.update_ancestor_status()
        assert root.status == NodeStatus.DOWNLOADING

    def test_update_ancestor_status_downloading(self):
        children = [
            ManifestNode(id="1", status=NodeStatus.DOWNLOADING),
            ManifestNode(id="2", status=NodeStatus.PENDING),
        ]
        root = ManifestNode(id="root", children=children)
        root.update_ancestor_status()
        assert root.status == NodeStatus.DOWNLOADING


class TestDownloadManifest:
    """Tests for DownloadManifest."""

    def test_defaults(self):
        m = DownloadManifest()
        assert m.version == 1
        assert m.book_id == ""
        assert m.discovery_complete is False
        assert m.created_at != ""
        assert m.updated_at == m.created_at

    def test_touch(self):
        m = DownloadManifest()
        old_updated = m.updated_at
        m.touch()
        # updated_at should change (or at least not be earlier)
        assert m.updated_at >= old_updated

    def test_to_dict(self):
        m = DownloadManifest(book_id="test", title="Test Book", source_site="nlc")
        d = m.to_dict()
        assert d["book_id"] == "test"
        assert d["title"] == "Test Book"
        assert "progress" in d
        assert "structure" in d

    def test_roundtrip(self):
        child = ManifestNode(id="ch1", title="Chapter 1", status=NodeStatus.COMPLETED)
        root = ManifestNode(id="root", node_type=NodeType.ROOT, children=[child])
        m = DownloadManifest(
            book_id="b1", title="Book", source_site="test",
            root=root, discovery_complete=True,
            metadata={"key": "val"},
        )
        d = m.to_dict()
        restored = DownloadManifest.from_dict(d)
        assert restored.book_id == "b1"
        assert restored.title == "Book"
        assert restored.discovery_complete is True
        assert len(restored.root.children) == 1
        assert restored.root.children[0].status == NodeStatus.COMPLETED

    def test_save_and_load(self, tmp_path):
        m = DownloadManifest(book_id="save_test", title="Save Test")
        path = tmp_path / "manifest.json"
        m.save(path)
        assert path.exists()

        loaded = DownloadManifest.load(path)
        assert loaded is not None
        assert loaded.book_id == "save_test"
        assert loaded.title == "Save Test"

    def test_load_nonexistent(self, tmp_path):
        assert DownloadManifest.load(tmp_path / "no_such.json") is None

    def test_load_corrupt(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not valid json {{{", encoding="utf-8")
        assert DownloadManifest.load(path) is None

    def test_find_node(self):
        leaf = ManifestNode(id="leaf1")
        child = ManifestNode(id="section1", children=[leaf])
        root = ManifestNode(id="root", children=[child])
        m = DownloadManifest(root=root)

        assert m.find_node("leaf1") is leaf
        assert m.find_node("missing") is None

    def test_get_progress(self):
        leaves = [
            ManifestNode(id="1", status=NodeStatus.COMPLETED),
            ManifestNode(id="2", status=NodeStatus.COMPLETED),
            ManifestNode(id="3", status=NodeStatus.FAILED),
            ManifestNode(id="4", status=NodeStatus.PENDING),
        ]
        root = ManifestNode(id="root", children=leaves)
        m = DownloadManifest(root=root)
        prog = m.get_progress()

        assert prog["total"] == 4
        assert prog["completed"] == 2
        assert prog["failed"] == 1
        assert prog["pending"] == 1
        assert prog["percent"] == 50

    def test_get_progress_empty(self):
        m = DownloadManifest()
        prog = m.get_progress()
        assert prog["total"] == 1  # root itself is a leaf
        assert prog["percent"] == 0

    def test_get_downloadable_nodes_all(self):
        nodes = [
            ManifestNode(id="1", status=NodeStatus.DISCOVERED),
            ManifestNode(id="2", status=NodeStatus.FAILED),
            ManifestNode(id="3", status=NodeStatus.COMPLETED),
            ManifestNode(id="4", status=NodeStatus.PENDING),
        ]
        root = ManifestNode(id="root", children=nodes)
        m = DownloadManifest(root=root)

        downloadable = m.get_downloadable_nodes()
        ids = {n.id for n in downloadable}
        assert ids == {"1", "2"}

    def test_get_downloadable_nodes_by_id(self):
        leaf1 = ManifestNode(id="l1", status=NodeStatus.DISCOVERED)
        leaf2 = ManifestNode(id="l2", status=NodeStatus.DISCOVERED)
        section = ManifestNode(id="s1", children=[leaf1, leaf2])
        other = ManifestNode(id="l3", status=NodeStatus.DISCOVERED)
        root = ManifestNode(id="root", children=[section, other])
        m = DownloadManifest(root=root)

        # Only get leaves under section s1
        downloadable = m.get_downloadable_nodes(node_ids=["s1"])
        ids = {n.id for n in downloadable}
        assert ids == {"l1", "l2"}
