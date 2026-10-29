import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import requests
from urllib3.util.retry import Retry

import orbit.pipeline.extract as extract


def serve(statuses: list[int]):
    """Start a local server that answers with each status in turn (then repeats the last).

    Returns (url, calls) where calls counts the requests received.
    """
    calls = {"n": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status = statuses[min(calls["n"], len(statuses) - 1)]
            calls["n"] += 1
            body = json.dumps([{"OBJECT_NAME": "TEST-1"}]).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):   # keep test output quiet
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}/gp.php", calls, server


@pytest.fixture
def fast_session():
    """Same retry rules as production, without the backoff waits."""
    retry = Retry(
        total=extract.RETRY.total,
        backoff_factor=0,
        status_forcelist=extract.RETRY.status_forcelist,
        allowed_methods=extract.RETRY.allowed_methods,
        raise_on_status=False,
    )
    return extract.make_session(retry)


def test_server_error_is_retried_then_succeeds(fast_session):
    url, calls, server = serve([500, 503, 200])
    try:
        records = extract.fetch_group("starlink", fast_session, url=url)
    finally:
        server.shutdown()
    assert records == [{"OBJECT_NAME": "TEST-1"}]
    assert calls["n"] == 3


def test_persistent_server_error_raises_after_retries(fast_session):
    url, calls, server = serve([500])
    try:
        with pytest.raises(requests.HTTPError):
            extract.fetch_group("starlink", fast_session, url=url)
    finally:
        server.shutdown()
    assert calls["n"] == 1 + extract.RETRY.total     # first try + retries


def test_client_error_is_not_retried(fast_session):
    url, calls, server = serve([403])
    try:
        with pytest.raises(requests.HTTPError):
            extract.fetch_group("starlink", fast_session, url=url)
    finally:
        server.shutdown()
    assert calls["n"] == 1                             # a 403 block shouldn't be hammered


def test_one_group_failing_does_not_stop_the_others(tmp_path, monkeypatch):
    monkeypatch.setattr("orbit.pipeline.extract.RAW_DATA_DIR", tmp_path)

    def fake_fetch(group, session):
        if group == "starlink":
            raise requests.HTTPError("500 Server Error")
        return [{"OBJECT_NAME": f"{group.upper()}-1"}]

    monkeypatch.setattr("orbit.pipeline.extract.fetch_group", fake_fetch)

    failed = extract.extract_all(["kuiper", "starlink", "other"], session=None)

    assert failed == ["starlink"]
    assert len(list((tmp_path / "kuiper").glob("*.json"))) == 1
    assert len(list((tmp_path / "other").glob("*.json"))) == 1
    assert not (tmp_path / "starlink").exists()
