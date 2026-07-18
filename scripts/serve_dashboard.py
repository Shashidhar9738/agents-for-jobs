"""Local dashboard server for the AI Job Application Platform.

Serves the artifact browser, accepts a master-resume upload, and triggers the
pipeline. Binds to 127.0.0.1 only - this is a local operator tool and must never
be exposed to a network.

    python scripts/serve_dashboard.py --candidate shashi --port 8800
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import subprocess
import sys
import threading
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.agent_core.bootstrap import init_runtime

init_runtime(REPO_ROOT)

from src.agent_core.artifact_store import build_index  # noqa: E402
from src.agent_core.config_loader import build_runtime_context  # noqa: E402
from src.agent_core.resume_ingest import ingest_master_resume  # noqa: E402

ALLOWED_RESUME_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024

# Guards the pipeline against concurrent triggers from double-clicks.
_run_lock = threading.Lock()
_run_state: Dict[str, Any] = {"status": "idle", "started_at": None, "finished_at": None, "log": []}


def _candidate_ids() -> List[str]:
    workspace = json.loads((REPO_ROOT / "config" / "workspace.json").read_text(encoding="utf-8"))
    return sorted(workspace.get("candidates", {}).keys())


def _resume_folder(candidate_id: str) -> Path:
    context = build_runtime_context(REPO_ROOT, candidate_override=candidate_id)
    return Path(context["paths"]["resume_folder"])


# Being inside the repo is not enough to be servable: secrets live there too.
_DENIED_NAMES = {".env", ".env.example", ".env.local", "n8n.local.credentials.json"}
_DENIED_DIRS = {".git", "node_modules", "__pycache__", ".vscode"}
_DENIED_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
# Only artifact-shaped files are ever exposed.
_ALLOWED_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".json", ".png", ".csv"}


def _safe_repo_path(raw: str) -> Path | None:
    """Resolve a requested file path, refusing anything outside the repo or sensitive.

    Confinement alone is insufficient - .env and credential files sit inside the
    repo, so this also enforces a denylist and an artifact-type allowlist.
    """
    try:
        resolved = Path(raw).resolve()
        resolved.relative_to(REPO_ROOT)
    except (ValueError, OSError):
        return None

    if not resolved.is_file():
        return None
    if resolved.name in _DENIED_NAMES or resolved.name.startswith(".env"):
        return None
    if resolved.suffix.lower() in _DENIED_SUFFIXES:
        return None
    if resolved.suffix.lower() not in _ALLOWED_SUFFIXES:
        return None
    if any(part in _DENIED_DIRS for part in resolved.relative_to(REPO_ROOT).parts):
        return None
    return resolved


def _parse_multipart_file(body: bytes, content_type: str) -> Tuple[str, bytes] | None:
    """Extract (filename, bytes) from a single-file multipart body.

    Hand-rolled because the stdlib cgi module was removed in Python 3.13 and this
    only ever handles one small upload field.
    """
    match = re.search(r'boundary="?([^";]+)"?', content_type)
    if not match:
        return None
    boundary = ("--" + match.group(1)).encode()

    for part in body.split(boundary):
        if b"filename=" not in part:
            continue
        header_blob, _, payload = part.partition(b"\r\n\r\n")
        name_match = re.search(rb'filename="([^"]*)"', header_blob)
        if not name_match or not name_match.group(1):
            continue
        filename = name_match.group(1).decode("utf-8", "replace")
        return filename, payload.rstrip(b"\r\n-")
    return None


def _run_pipeline(candidate_id: str) -> None:
    global _run_state
    started = datetime.now(timezone.utc).isoformat()
    _run_state = {"status": "running", "started_at": started, "finished_at": None, "log": []}
    try:
        completed = subprocess.run(
            [sys.executable, "scripts/run_full_pipeline.py", "--candidate", candidate_id],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=1800,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        _run_state["log"] = output.strip().splitlines()[-80:]
        _run_state["status"] = "success" if completed.returncode == 0 else "failed"
    except Exception:
        _run_state["status"] = "failed"
        _run_state["log"] = traceback.format_exc().splitlines()[-40:]
    finally:
        _run_state["finished_at"] = datetime.now(timezone.utc).isoformat()
        _run_lock.release()


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "JobAgentDashboard/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("  %s - %s\n" % (self.address_string(), fmt % args))

    # ---- helpers -------------------------------------------------------
    def _send_json(self, payload: Dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body: bytes, content_type: str, disposition: str | None = None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if disposition:
            self.send_header("Content-Disposition", disposition)
        self.end_headers()
        self.wfile.write(body)

    def _query(self) -> Dict[str, List[str]]:
        return parse_qs(urlparse(self.path).query)

    # ---- routes --------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path

        if route in ("/", "/index.html"):
            template = REPO_ROOT / "src" / "dashboard" / "index.html"
            if not template.exists():
                self._send_json({"error": "dashboard template missing"}, 500)
                return
            self._send_bytes(template.read_bytes(), "text/html; charset=utf-8")
            return

        if route == "/api/candidates":
            self._send_json({"candidates": _candidate_ids()})
            return

        if route == "/api/index":
            candidate = (self._query().get("candidate") or [""])[0].strip()
            index = build_index(REPO_ROOT, candidate or None)
            index["resume_uploaded"] = self._resume_state(candidate)
            self._send_json(index)
            return

        if route == "/api/run-status":
            self._send_json(_run_state)
            return

        if route == "/file":
            raw = (self._query().get("path") or [""])[0]
            target = _safe_repo_path(raw)
            if target is None:
                self._send_json({"error": "file not found or outside project"}, 404)
                return
            guessed = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            inline = target.suffix.lower() in {".pdf", ".txt", ".md", ".json", ".png"}
            self._send_bytes(
                target.read_bytes(),
                guessed,
                f'{"inline" if inline else "attachment"}; filename="{target.name}"',
            )
            return

        self._send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path

        if route == "/api/upload-resume":
            self._handle_upload()
            return

        if route == "/api/run":
            self._handle_run()
            return

        self._send_json({"error": "not found"}, 404)

    # ---- handlers ------------------------------------------------------
    def _resume_state(self, candidate_id: str) -> Dict[str, Any]:
        if not candidate_id:
            return {"present": False}
        try:
            folder = _resume_folder(candidate_id)
        except Exception:
            return {"present": False}
        for suffix in (".pdf", ".docx", ".txt", ".md"):
            path = folder / f"resume_master{suffix}"
            if path.exists():
                stat = path.stat()
                return {
                    "present": True,
                    "name": path.name,
                    "size_bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    "path": str(path),
                }
        return {"present": False, "expected_folder": str(folder)}

    def _handle_upload(self) -> None:
        candidate = (self._query().get("candidate") or [""])[0].strip()
        if candidate not in _candidate_ids():
            self._send_json({"error": "unknown candidate"}, 400)
            return

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_UPLOAD_BYTES:
            self._send_json({"error": f"file must be between 1 byte and {MAX_UPLOAD_BYTES // (1024 * 1024)} MB"}, 400)
            return

        parsed = _parse_multipart_file(self.rfile.read(length), self.headers.get("Content-Type", ""))
        if parsed is None:
            self._send_json({"error": "no file found in upload"}, 400)
            return

        filename, payload = parsed
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_RESUME_SUFFIXES:
            self._send_json(
                {"error": f"unsupported file type '{suffix}'. Use PDF, DOCX, TXT, or MD."}, 400
            )
            return
        if not payload:
            self._send_json({"error": "uploaded file was empty"}, 400)
            return

        folder = _resume_folder(candidate)
        folder.mkdir(parents=True, exist_ok=True)

        # The master resume is immutable input, so a replacement archives the
        # previous one rather than destroying it.
        destination = folder / f"resume_master{suffix}"
        if destination.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            archive = folder / "previous"
            archive.mkdir(exist_ok=True)
            destination.replace(archive / f"resume_master__{stamp}{suffix}")

        destination.write_bytes(payload)

        # The resume is the source of truth for the profile, so uploading it
        # immediately re-derives skills, title, and contact details.
        ingest_summary: Dict[str, Any] = {"ran": False}
        try:
            context = build_runtime_context(REPO_ROOT, candidate_override=candidate)
            result = ingest_master_resume(REPO_ROOT, candidate, context)
            ingest_summary = {
                "ran": True,
                "mode": result.extraction_mode,
                "fields_updated": result.fields_updated,
                "skills_found": result.skills_found,
                "rejected_skills": result.rejected_skills,
            }
        except Exception as exc:  # Upload already succeeded; ingestion is best-effort.
            ingest_summary = {"ran": False, "error": str(exc)}

        self._send_json(
            {
                "ok": True,
                "saved_to": str(destination),
                "size_bytes": len(payload),
                "ingest": ingest_summary,
            }
        )

    def _handle_run(self) -> None:
        candidate = (self._query().get("candidate") or [""])[0].strip()
        if candidate not in _candidate_ids():
            self._send_json({"error": "unknown candidate"}, 400)
            return

        if not _run_lock.acquire(blocking=False):
            self._send_json({"error": "a run is already in progress", "state": _run_state}, 409)
            return

        threading.Thread(target=_run_pipeline, args=(candidate,), daemon=True).start()
        self._send_json({"ok": True, "status": "running", "candidate": candidate})


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the local job-agent dashboard.")
    parser.add_argument("--port", type=int, default=8800)
    parser.add_argument("--candidate", default=None, help="Informational default for the UI")
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), DashboardHandler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Dashboard running at {url}")
    print(f"Candidates: {', '.join(_candidate_ids())}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
