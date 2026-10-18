from __future__ import annotations

import argparse
import http.client
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
DEFAULT_BACKEND = "http://127.0.0.1:8000"
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


class FrontendHandler(BaseHTTPRequestHandler):
    backend_base = DEFAULT_BACKEND

    def do_GET(self) -> None:
        if self.path.startswith("/api/"):
            self._proxy()
            return
        self._serve_static()

    def do_HEAD(self) -> None:
        if self.path.startswith("/api/"):
            self._proxy()
            return
        self._serve_static(send_body=False)

    def do_POST(self) -> None:
        self._proxy()

    def do_PUT(self) -> None:
        self._proxy()

    def do_PATCH(self) -> None:
        self._proxy()

    def do_DELETE(self) -> None:
        self._proxy()

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def _serve_static(self, *, send_body: bool = True) -> None:
        parsed = urlsplit(self.path)
        requested = "index.html" if parsed.path in {"", "/"} else parsed.path.lstrip("/")
        candidate = (ROOT / requested).resolve()
        if ROOT not in candidate.parents and candidate != ROOT:
            self.send_error(403, "Forbidden")
            return
        if not candidate.is_file():
            candidate = ROOT / "index.html"

        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def _proxy(self) -> None:
        if not self.path.startswith("/api/"):
            self.send_error(404, "Only /api/* requests are proxied")
            return

        parsed_backend = urlsplit(self.backend_base)
        connection_class = http.client.HTTPSConnection if parsed_backend.scheme == "https" else http.client.HTTPConnection
        netloc = parsed_backend.netloc
        base_path = parsed_backend.path.rstrip("/")
        target_path = f"{base_path}{self.path}"
        body = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != "host"
        }

        connection = connection_class(netloc, timeout=120)
        try:
            connection.request(self.command, target_path, body=body, headers=headers)
            response = connection.getresponse()
            response_body = response.read()
        except OSError as exc:
            payload = json.dumps(
                {
                    "error": {
                        "code": "BACKEND_UNAVAILABLE",
                        "message": f"Cannot reach backend: {exc}",
                        "details": {},
                    }
                }
            ).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        finally:
            connection.close()

        self.send_response(response.status, response.reason)
        for key, value in response.getheaders():
            if key.lower() in HOP_BY_HOP_HEADERS:
                continue
            if key.lower() == "content-length":
                continue
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(response_body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the temporary StudyMate frontend.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=5173, type=int)
    parser.add_argument(
        "--backend",
        default=os.environ.get("STUDYMATE_API_BASE", DEFAULT_BACKEND),
        help="Backend origin, for example http://127.0.0.1:8000",
    )
    args = parser.parse_args()

    FrontendHandler.backend_base = args.backend.rstrip("/")
    server = ThreadingHTTPServer((args.host, args.port), FrontendHandler)
    print(f"Temporary frontend: http://{args.host}:{args.port}")
    print(f"Proxying /api/* to {FrontendHandler.backend_base}")
    server.serve_forever()


if __name__ == "__main__":
    main()
