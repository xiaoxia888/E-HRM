import logging
import threading
import time
from pathlib import Path

import pytest


pytest.importorskip("PySide6")

from ehrm.core.settings import load_settings
from ehrm.gui import worker as worker_module


def test_playwright_workbench_is_reused_inside_one_thread_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = threading.Event()

    class FakeWorkbench:
        instances: list["FakeWorkbench"] = []

        def __init__(self, settings, logger, progress_callback, cancel_check) -> None:
            self.started = 0
            self.stopped = 0
            self.requests: list[object] = []
            self.thread_ids: list[int] = []
            self.instances.append(self)

        def start(self) -> None:
            self.started += 1

        def run(self, request: object) -> object:
            self.requests.append(request)
            self.thread_ids.append(threading.get_ident())
            if len(self.requests) == 2:
                completed.set()
            return request

        def stop(self) -> None:
            self.stopped += 1

    monkeypatch.setattr(worker_module, "DesktopWorkbench", FakeWorkbench)
    settings = load_settings(
        Path("config/settings.example.toml"),
        data_root=tmp_path / "runtime",
    )
    worker = worker_module.AutomationWorker(settings, logging.getLogger("test.worker"))
    first = object()
    second = object()

    worker.start()
    try:
        assert worker.submit(first) is True
        deadline = time.monotonic() + 3
        while not worker.submit(second):
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert completed.wait(3)
    finally:
        worker.shutdown()
        assert worker.wait(3_000)

    assert len(FakeWorkbench.instances) == 1
    workbench = FakeWorkbench.instances[0]
    assert workbench.started == 1
    assert workbench.stopped == 1
    assert workbench.requests == [first, second]
    assert len(set(workbench.thread_ids)) == 1
    assert workbench.thread_ids[0] != threading.get_ident()
    assert worker.submit(object()) is False


def test_worker_forwards_cooperative_cancel_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    cancelled = threading.Event()

    class CancellableWorkbench:
        def __init__(self, settings, logger, progress_callback, cancel_check) -> None:
            self.cancel_check = cancel_check

        def start(self) -> None:
            pass

        def run(self, request: object) -> object:
            started.set()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if self.cancel_check():
                    cancelled.set()
                    return request
                time.sleep(0.01)
            raise AssertionError("没有收到停止请求")

        def stop(self) -> None:
            pass

    monkeypatch.setattr(worker_module, "DesktopWorkbench", CancellableWorkbench)
    settings = load_settings(
        Path("config/settings.example.toml"),
        data_root=tmp_path / "runtime",
    )
    worker = worker_module.AutomationWorker(settings, logging.getLogger("test.cancel"))
    worker.start()
    try:
        assert worker.submit(object()) is True
        assert started.wait(3)
        assert worker.cancel_current() is True
        assert cancelled.wait(3)
    finally:
        worker.shutdown()
        assert worker.wait(3_000)
