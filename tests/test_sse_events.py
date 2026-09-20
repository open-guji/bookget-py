# SSE event delivery.
#
# Two bugs made the web UI stop updating mid-download, so volume statuses only
# refreshed when the user clicked 发现结构 again:
#
#  1. EventBus.publish() handed the SAME dict to every subscriber queue, and
#     the stream handler popped "type" off it. The first subscriber consumed
#     the name; everyone else saw the generic "message" event, which the
#     frontend does not listen for.
#  2. tasks.py re-published `info.manifest`, which is only assigned after the
#     download finishes — i.e. the stale discovery-time manifest.

import asyncio

import pytest

from bookget.server.sse import EventBus, make_sse_data


class TestEventBusIsolation:
    @pytest.mark.asyncio
    async def test_each_subscriber_gets_its_own_copy(self):
        bus = EventBus()
        q1, q2 = bus.subscribe(), bus.subscribe()
        bus.publish("manifest_updated", {"taskId": "t1"})

        e1, e2 = await q1.get(), await q2.get()
        assert e1 is not e2, "subscribers must not share one mutable dict"

    @pytest.mark.asyncio
    async def test_one_consumer_cannot_strip_type_from_another(self):
        bus = EventBus()
        q1, q2 = bus.subscribe(), bus.subscribe()
        bus.publish("manifest_updated", {"taskId": "t1"})

        e1, e2 = await q1.get(), await q2.get()
        e1.pop("type", None)  # what the stream handler used to do
        assert e2.get("type") == "manifest_updated"

    @pytest.mark.asyncio
    async def test_event_carries_type_and_payload(self):
        bus = EventBus()
        q = bus.subscribe()
        bus.publish("progress", {"taskId": "t1", "completed": 3, "total": 9})
        e = await q.get()
        assert e["type"] == "progress"
        assert e["completed"] == 3


class TestSseFraming:
    def test_named_event_is_emitted(self):
        # The frontend uses addEventListener('manifest_updated', ...), so the
        # event name must survive into the wire format.
        msg = make_sse_data("manifest_updated", {"taskId": "t1"})
        assert msg.startswith("event: manifest_updated\n")
        assert "data: " in msg
        assert msg.endswith("\n\n")

    def test_type_is_not_duplicated_into_payload(self):
        import json

        msg = make_sse_data("progress", {"taskId": "t1", "completed": 1})
        data_line = [l for l in msg.splitlines() if l.startswith("data: ")][0]
        payload = json.loads(data_line[len("data: "):])
        assert "type" not in payload
        assert payload["completed"] == 1


class TestLiveManifestIsPublished:
    def test_status_cb_prefers_event_manifest(self):
        # Guard the second bug: the handler must use the manifest carried on
        # the event, not the task's not-yet-assigned copy.
        import inspect

        from bookget.server import tasks

        src = inspect.getsource(tasks)
        assert 'data.get("manifest")' in src, (
            "status_cb must use the live manifest from the event"
        )

    def test_resource_manager_sends_manifest_with_node_events(self):
        import inspect

        from bookget.core import resource_manager

        src = inspect.getsource(resource_manager.ResourceManager.download_incremental)
        assert "'manifest': manifest," in src
