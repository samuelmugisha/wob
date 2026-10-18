import json
import socket
import struct
import threading

import httpx
import pytest

from app.services.embeddings import HashingEmbedder, VoyageEmbedder
from app.services.scanning import ClamdScanner, ScannerError

EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


def fake_clamd(received: list[bytes], reply_for) -> tuple[str, int]:
    """A one-shot clamd speaking the INSTREAM protocol."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)

    def serve() -> None:
        conn, _ = server.accept()
        with conn, server:
            command = b""
            while not command.endswith(b"\0"):
                command += conn.recv(1)
            assert command == b"zINSTREAM\0"
            data = b""
            while True:
                (size,) = struct.unpack("!L", conn.recv(4, socket.MSG_WAITALL))
                if size == 0:
                    break
                data += conn.recv(size, socket.MSG_WAITALL)
            received.append(data)
            conn.sendall(reply_for(data))

    threading.Thread(target=serve, daemon=True).start()
    return server.getsockname()


def clamd_reply(data: bytes) -> bytes:
    if EICAR in data:
        return b"stream: Eicar-Test-Signature FOUND\0"
    return b"stream: OK\0"


def test_clamd_clean_file_streamed_in_chunks() -> None:
    received: list[bytes] = []
    payload = b"%PDF-1.7\n" + b"x" * 200_000  # several INSTREAM chunks
    result = ClamdScanner(*fake_clamd(received, clamd_reply)).scan(payload)
    assert result.clean and result.scanner == "clamav"
    assert received == [payload]


def test_clamd_detects_malware() -> None:
    result = ClamdScanner(*fake_clamd([], clamd_reply)).scan(EICAR)
    assert not result.clean
    assert result.signature == "Eicar-Test-Signature"


def test_clamd_errors_are_not_treated_as_clean() -> None:
    address = fake_clamd([], lambda _: b"INSTREAM size limit exceeded. ERROR\0")
    with pytest.raises(ScannerError, match="size limit"):
        ClamdScanner(*address).scan(b"data")


def test_clamd_unreachable() -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(ScannerError, match="unavailable"):
        ClamdScanner("127.0.0.1", port, timeout=2).scan(b"data")


def test_voyage_batches_and_orders_results() -> None:
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        assert request.headers["authorization"] == "Bearer key"
        data = [
            {"index": i, "embedding": [float(len(text)), 0.0]}
            for i, text in reversed(list(enumerate(body["input"])))
        ]
        return httpx.Response(200, json={"data": data})

    embedder = VoyageEmbedder(
        "voyage-3.5", 2, "key", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    texts = ["a" * n for n in range(1, 101)]
    vectors = embedder.embed_documents(texts)
    assert [v[0] for v in vectors] == [float(n) for n in range(1, 101)]
    assert [len(r["input"]) for r in requests] == [64, 36]
    assert {r["input_type"] for r in requests} == {"document"}
    assert requests[0]["output_dimension"] == 2
    embedder.embed_query("board")
    assert requests[-1]["input_type"] == "query"


def test_hashing_embedder_is_deterministic_and_normalised() -> None:
    embedder = HashingEmbedder(64)
    a, b = embedder.embed_documents(["Audit committee chair", "audit COMMITTEE chair"])
    assert a == b
    assert abs(sum(v * v for v in a) - 1) < 1e-9
