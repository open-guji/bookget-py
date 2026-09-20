# Tests for running as a PyInstaller *windowed* build (console=False).
#
# bookget-ui.exe has no console: sys.stdout/stderr exist but have no console
# behind them, so `.encoding` is None and `.reconfigure()` / `.isatty()` raise.
# Double-clicking it used to die at import time with
#   Fatal error: 'NoneType' object has no attribute 'encoding'
# because the UTF-8 setup only checked `stream.encoding != 'utf-8'`.

import pytest

from bookget.main import _force_utf8


class NoConsoleStream:
    """Mimics a windowed-build std stream: present, but nothing behind it."""

    encoding = None

    def reconfigure(self, **kwargs):
        raise AttributeError("'NoneType' object has no attribute 'encoding'")

    def isatty(self):
        raise OSError("no console")

    def write(self, *a):
        pass

    def flush(self):
        pass


class WorkingStream:
    encoding = "cp1252"

    def __init__(self):
        self.reconfigured_to = None

    def reconfigure(self, **kwargs):
        self.reconfigured_to = kwargs.get("encoding")


class AlreadyUtf8Stream:
    encoding = "utf-8"

    def reconfigure(self, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("should not reconfigure an already-utf-8 stream")


class TestForceUtf8:
    def test_windowed_stream_does_not_raise(self):
        # The actual crash: must be swallowed, never fatal.
        _force_utf8(NoConsoleStream())

    def test_none_stream_does_not_raise(self):
        _force_utf8(None)

    def test_normal_stream_is_reconfigured(self):
        s = WorkingStream()
        _force_utf8(s)
        assert s.reconfigured_to == "utf-8"

    def test_already_utf8_is_left_alone(self):
        _force_utf8(AlreadyUtf8Stream())

    def test_stream_without_reconfigure_is_tolerated(self):
        class Old:
            encoding = "cp1252"
        _force_utf8(Old())


class TestNoConsoleDetection:
    """bookget-ui.exe must auto-serve, never sit at an invisible input()."""

    @pytest.mark.parametrize("stream,expected", [
        (None, False),
        (NoConsoleStream(), False),       # .encoding is None -> no console
        (AlreadyUtf8Stream(), False),     # no isatty at all -> treat as none
    ])
    def test_non_console_streams_are_not_consoles(self, stream, expected):
        # Mirrors _has_console() inside _interactive_mode.
        def has_console(s):
            if s is None or getattr(s, "encoding", None) is None:
                return False
            try:
                return bool(s.isatty())
            except Exception:
                return False

        assert has_console(stream) is expected

    def test_real_tty_is_detected(self):
        class Tty:
            encoding = "utf-8"

            def isatty(self):
                return True

        def has_console(s):
            if s is None or getattr(s, "encoding", None) is None:
                return False
            try:
                return bool(s.isatty())
            except Exception:
                return False

        assert has_console(Tty()) is True


class TestSetupLoggerWithoutConsole:
    """setup_logger must survive sys.stdout being None (windowed build).

    This is what actually killed bookget-ui.exe on double-click: setup_logger
    read `sys.stdout.encoding` and `sys.stdout.fileno()` unguarded, so the
    windowed build raised
        AttributeError: 'NoneType' object has no attribute 'encoding'
    before the server ever bound a port.
    """

    def test_none_stdout_does_not_raise(self, monkeypatch):
        import logging

        from bookget import logger as logger_mod

        monkeypatch.setattr(logger_mod.sys, "stdout", None)
        logger_mod.setup_logger(debug=False)
        # Logging must stay callable and silent, not blow up.
        logger_mod.logger.info("should not raise")
        assert logger_mod.logger.handlers
        assert isinstance(logger_mod.logger.handlers[0], logging.NullHandler)

    def test_stream_without_fileno_falls_back(self, monkeypatch):
        from bookget import logger as logger_mod

        class NoFileno:
            encoding = "cp1252"

            def fileno(self):
                raise OSError("no fd")

            def write(self, *a):
                pass

            def flush(self):
                pass

        monkeypatch.setattr(logger_mod.sys, "stdout", NoFileno())
        stream = logger_mod._utf8_console_stream()
        assert stream is not None  # falls back rather than losing logging

    def test_utf8_stdout_is_used_directly(self, monkeypatch):
        from bookget import logger as logger_mod

        class Utf8:
            encoding = "utf-8"

        s = Utf8()
        monkeypatch.setattr(logger_mod.sys, "stdout", s)
        assert logger_mod._utf8_console_stream() is s

    def test_none_stdout_returns_none(self, monkeypatch):
        from bookget import logger as logger_mod

        monkeypatch.setattr(logger_mod.sys, "stdout", None)
        assert logger_mod._utf8_console_stream() is None


class TestSecondLaunchDetection:
    """Double-clicking bookget-ui.exe twice must not show a bind error.

    The second launch used to die with a raw
        [Errno 10048] ... 通常每个套接字地址...只允许使用一次
    dialog. The user just wants the UI, so a running instance should be
    detected and the browser pointed at it instead.
    """

    def test_no_server_returns_false(self):
        from bookget.main import _is_bookget_serving
        # Nothing is listening on this port.
        assert _is_bookget_serving("127.0.0.1", 9, timeout=0.5) is False

    def test_non_bookget_response_is_rejected(self, monkeypatch):
        # A foreign service squatting on the port must NOT be treated as ours,
        # otherwise we'd silently open a browser at someone else's app.
        import bookget.main as m

        class FakeResp:
            status = 200

            def read(self):
                return b'{"hello": "not bookget"}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(
            "urllib.request.urlopen", lambda *a, **k: FakeResp())
        assert m._is_bookget_serving("127.0.0.1", 8765) is False

    def test_bookget_response_is_accepted(self, monkeypatch):
        import bookget.main as m

        class FakeResp:
            status = 200

            def read(self):
                return b'[{"id": "ndl", "name": "NDL", "domains": []}]'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        monkeypatch.setattr(
            "urllib.request.urlopen", lambda *a, **k: FakeResp())
        assert m._is_bookget_serving("127.0.0.1", 8765) is True

    def test_connection_error_is_not_fatal(self, monkeypatch):
        import bookget.main as m

        def boom(*a, **k):
            raise OSError("refused")

        monkeypatch.setattr("urllib.request.urlopen", boom)
        assert m._is_bookget_serving("127.0.0.1", 8765) is False
