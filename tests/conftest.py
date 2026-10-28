import socket

import pytest

from arena.config import Settings
from arena.store import Store
from arena.submission import SubmissionService
from arena.writer import LocalGitWriter


@pytest.fixture(autouse=True)
def no_external_tcp(monkeypatch):
    original = socket.socket.connect
    original_ex = socket.socket.connect_ex

    def check(address):
        if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError("默认测试禁止访问外网")

    def connect(sock, address):
        check(address)
        return original(sock, address)

    def connect_ex(sock, address):
        check(address)
        return original_ex(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)


@pytest.fixture
def bundle(tmp_path):
    settings = Settings(data_dir=tmp_path, staff_userids="staff", admin_userids="admin")
    store = Store(tmp_path / "registry.sqlite3")
    writer = LocalGitWriter(tmp_path / "repo")
    service = SubmissionService(settings, store, writer)
    yield settings, store, writer, service
    store.close()
