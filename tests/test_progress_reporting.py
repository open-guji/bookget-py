# Progress must be reported in IMAGES, not whole nodes.
#
# download_incremental() used to pass progress_callback=None into
# adapter.download_node(), so callers only heard about a volume once it had
# fully finished. In the web UI a 12-volume book therefore showed "0/12, 0%"
# and did not move for minutes — it looked frozen even though images were
# downloading fine.

import inspect

from bookget.core import resource_manager


class TestIncrementalProgressUnits:
    def test_download_node_receives_a_progress_callback(self):
        src = inspect.getsource(resource_manager.ResourceManager.download_incremental)
        # The regression: handing None to download_node throws per-image
        # progress away. Check the CALL, not prose about it — an explanatory
        # comment mentioning the old code must not fail this test.
        code_lines = [
            ln for ln in src.splitlines() if not ln.lstrip().startswith("#")
        ]
        code = chr(10).join(code_lines)
        assert "download_node(" in code
        assert "progress_callback=node_progress" in code, (
            "download_node must receive a real callback, otherwise the UI "
            "cannot show intra-volume progress"
        )

    def test_progress_is_summed_over_images(self):
        src = inspect.getsource(resource_manager.ResourceManager.download_incremental)
        # Totals come from per-node item counts, not len(nodes).
        assert "total_images" in src
        assert "downloaded_items" in src

    def test_node_completion_reports_images_too(self):
        # Both the per-image callback and the per-node completion path must
        # report in the same unit, or the bar jumps around.
        src = inspect.getsource(resource_manager.ResourceManager.download_incremental)
        assert src.count("progress_callback(done_images, total_images)") >= 2
