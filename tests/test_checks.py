import os
import socket
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from opswatch.checks.backup import check_backup
from opswatch.checks.disk import check_disk
from opswatch.checks.http import check_http, days_until
from opswatch.checks.tcp import check_tcp
from opswatch.models import Status


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/missing":
            self.send_response(404)
            self.end_headers()
            return
        if self.path == "/slow":
            time.sleep(0.15)
        body = b"hello opswatch"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class HttpCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_ok(self):
        status, message = check_http({"url": self.base + "/"}, 2)
        self.assertEqual(status, Status.OK)
        self.assertIn("HTTP 200", message)

    def test_wrong_status_fails(self):
        status, message = check_http({"url": self.base + "/missing"}, 2)
        self.assertEqual(status, Status.FAIL)
        self.assertIn("404", message)

    def test_expected_error_status_passes(self):
        status, _ = check_http({"url": self.base + "/missing", "expect_status": 404}, 2)
        self.assertEqual(status, Status.OK)

    def test_missing_text_fails(self):
        status, message = check_http({"url": self.base + "/", "contains": "nope"}, 2)
        self.assertEqual(status, Status.FAIL)
        self.assertIn("does not contain", message)

    def test_matching_text_passes(self):
        status, _ = check_http({"url": self.base + "/", "contains": "opswatch"}, 2)
        self.assertEqual(status, Status.OK)

    def test_slow_response_warns(self):
        status, message = check_http({"url": self.base + "/slow", "latency_warn_ms": 50}, 2)
        self.assertEqual(status, Status.WARN)
        self.assertIn("slower", message)

    def test_connection_refused_fails(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        status, message = check_http({"url": f"http://127.0.0.1:{port}/"}, 1)
        self.assertEqual(status, Status.FAIL)
        self.assertIn("request failed", message)


class CertificateTests(unittest.TestCase):
    def test_days_until(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # ssl.cert_time_to_seconds parses this exact certificate format
        left = days_until("Jan 31 00:00:00 2026 GMT", now)
        self.assertAlmostEqual(left, 30, places=3)

    def test_expired_is_negative(self):
        now = datetime(2026, 3, 1, tzinfo=timezone.utc)
        self.assertLess(days_until("Jan 31 00:00:00 2026 GMT", now), 0)


class TcpCheckTests(unittest.TestCase):
    def test_open_and_closed_ports(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen()
            port = server.getsockname()[1]
            status, _ = check_tcp({"host": "127.0.0.1", "port": port}, 1)
            self.assertEqual(status, Status.OK)
        status, message = check_tcp({"host": "127.0.0.1", "port": port}, 1)
        self.assertEqual(status, Status.FAIL)
        self.assertIn("cannot connect", message)


class DiskCheckTests(unittest.TestCase):
    def test_thresholds(self):
        path = tempfile.gettempdir()
        ok, _ = check_disk({"path": path, "max_used_percent": 100, "warn_used_percent": 100}, 1)
        self.assertEqual(ok, Status.OK)
        warn, _ = check_disk({"path": path, "max_used_percent": 100, "warn_used_percent": 0}, 1)
        self.assertEqual(warn, Status.WARN)
        fail, message = check_disk({"path": path, "max_used_percent": 0}, 1)
        self.assertEqual(fail, Status.FAIL)
        self.assertIn("limit", message)


class BackupCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.now = time.time()

    def tearDown(self):
        self.tmp.cleanup()

    def _make(self, name, hours_old, size=2048):
        path = self.dir / name
        path.write_bytes(b"x" * size)
        stamp = self.now - hours_old * 3600
        os.utime(path, (stamp, stamp))
        return path

    def _opts(self, **extra):
        return {"path": str(self.dir), "pattern": "*.sql.gz", "max_age_hours": 24, **extra}

    def test_fresh_backup_ok(self):
        self._make("db-1.sql.gz", 2)
        status, message = check_backup(self._opts(), 1, now=self.now)
        self.assertEqual(status, Status.OK)
        self.assertIn("db-1.sql.gz", message)

    def test_newest_file_wins(self):
        self._make("old.sql.gz", 100)
        self._make("new.sql.gz", 1)
        status, message = check_backup(self._opts(), 1, now=self.now)
        self.assertEqual(status, Status.OK)
        self.assertIn("new.sql.gz", message)

    def test_stale_fails(self):
        self._make("db.sql.gz", 30)
        status, message = check_backup(self._opts(), 1, now=self.now)
        self.assertEqual(status, Status.FAIL)
        self.assertIn("stale", message)

    def test_aging_warns(self):
        self._make("db.sql.gz", 20)  # past the default 75% warning point (18 h), under 24 h
        status, _ = check_backup(self._opts(), 1, now=self.now)
        self.assertEqual(status, Status.WARN)

    def test_tiny_file_fails(self):
        self._make("db.sql.gz", 1, size=10)
        status, message = check_backup(self._opts(min_size_bytes=1024), 1, now=self.now)
        self.assertEqual(status, Status.FAIL)
        self.assertIn("too small", message)

    def test_no_match_and_missing_folder_fail(self):
        status, message = check_backup(self._opts(), 1, now=self.now)
        self.assertEqual(status, Status.FAIL)
        self.assertIn("no files matching", message)
        status, message = check_backup({**self._opts(), "path": str(self.dir / "nope")}, 1)
        self.assertEqual(status, Status.FAIL)
        self.assertIn("not found", message)


if __name__ == "__main__":
    unittest.main()
