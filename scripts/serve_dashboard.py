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
from src.agent_core.auth import SessionStore, User, UserStore  # noqa: E402
from src.agent_core.interview_prep import generate_interview_prep  # noqa: E402
from src.agent_core.resume_ingest import ingest_master_resume  # noqa: E402
from src.agent_core.vault import CredentialVault, VaultError  # noqa: E402

ALLOWED_RESUME_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024

USERS = UserStore(REPO_ROOT / "config" / "users.json")
SESSIONS = SessionStore()
VAULT = CredentialVault(REPO_ROOT / "config" / "vault.json")
SESSION_COOKIE = "jobagent_session"

# Routes reachable without a session. Everything else requires login.
_PUBLIC_ROUTES = {"/login", "/api/login", "/api/session"}

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


def _portal_catalog() -> List[Dict[str, Any]]:
    """Portals from config, annotated with what each one needs to sign in."""
    portals = json.loads((REPO_ROOT / "config" / "portals.json").read_text(encoding="utf-8"))
    catalog: List[Dict[str, Any]] = []
    for name, config in sorted(portals.items()):
        if not isinstance(config, dict):
            continue
        catalog.append(
            {
                "portal": name,
                "enabled": bool(config.get("enabled")),
                "needs_login": bool(config.get("requires_auth", True)),
            }
        )
    return catalog


def _suggest_portals(run_context: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Recommend job boards for this candidate, with a deterministic fallback."""
    from src.agent_core.ai_client import AIClient, AIClientError
    from src.agent_core.prompt_loader import PromptLoadError, load_prompt

    profile = run_context.get("candidate_profile", {})
    preferences = run_context.get("candidate_preferences", {})

    try:
        client = AIClient.from_run_context(run_context)
        system_prompt = load_prompt(REPO_ROOT, "system")
    except (AIClientError, PromptLoadError):
        return _fallback_portal_suggestions()

    if not client.available:
        return _fallback_portal_suggestions()

    user_prompt = "\n\n".join(
        [
            "## Task\nRecommend job boards for this candidate to search.",
            "## Candidate\n" + json.dumps(
                {
                    "current_title": profile.get("current_title", ""),
                    "experience_years": profile.get("experience_years", 0),
                    "skills": profile.get("skills", [])[:15],
                    "target_roles": preferences.get("target_roles", []),
                    "locations": preferences.get("locations", []),
                },
                indent=2,
            ),
            "## Required Output\n"
            "Return JSON with key 'suggestions': an array of at most 8 objects, each with "
            "portal (lowercase single-word id, e.g. linkedin, naukri, indeed, instahyre, "
            "wellfound, hirist, cutshort, glassdoor), display_name, reason (one sentence on why "
            "it fits this candidate), and priority (high, medium, or low). Recommend only real, "
            "currently-operating job boards appropriate to the candidate's locations.",
        ]
    )

    try:
        response = client.complete_json(
            system_prompt=system_prompt.text,
            user_prompt=user_prompt,
            purpose="portal_suggestions",
            max_tokens=900,
        )
    except AIClientError:
        return _fallback_portal_suggestions()

    raw = (response.data or {}).get("suggestions")
    if not isinstance(raw, list) or not raw:
        return _fallback_portal_suggestions()

    suggestions: List[Dict[str, Any]] = []
    for item in raw[:8]:
        if not isinstance(item, dict):
            continue
        portal = str(item.get("portal", "")).strip().lower()
        if not portal:
            continue
        suggestions.append(
            {
                "portal": portal,
                "display_name": str(item.get("display_name", portal.title())),
                "reason": str(item.get("reason", "")),
                "priority": str(item.get("priority", "medium")).lower(),
                "source": "ai",
            }
        )
    return suggestions or _fallback_portal_suggestions()


def _fallback_portal_suggestions() -> List[Dict[str, Any]]:
    """Used when no model is reachable, so the picker still works offline."""
    return [
        {"portal": "linkedin", "display_name": "LinkedIn", "priority": "high",
         "reason": "Largest professional network with the broadest recruiter reach.", "source": "default"},
        {"portal": "naukri", "display_name": "Naukri", "priority": "high",
         "reason": "Highest posting volume for India-based technology roles.", "source": "default"},
        {"portal": "indeed", "display_name": "Indeed", "priority": "medium",
         "reason": "Wide aggregator coverage across employers and regions.", "source": "default"},
        {"portal": "instahyre", "display_name": "Instahyre", "priority": "medium",
         "reason": "Curated India tech roles with direct employer contact.", "source": "default"},
        {"portal": "hirist", "display_name": "Hirist", "priority": "low",
         "reason": "India-focused board specialising in technology positions.", "source": "default"},
    ]


def _admin_overview() -> Dict[str, Any]:
    """Cross-candidate rollup. Admin-only; never exposed to candidate logins."""
    rows: List[Dict[str, Any]] = []
    for candidate_id in _candidate_ids():
        index = build_index(REPO_ROOT, candidate_id)
        dashboard_path = REPO_ROOT / "output" / candidate_id / "dashboard" / "dashboard_summary.json"
        summary: Dict[str, Any] = {}
        if dashboard_path.exists():
            try:
                summary = json.loads(dashboard_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                summary = {}

        rows.append(
            {
                "candidate_id": candidate_id,
                "targets": index["total_targets"],
                "interview_ready": index["interview_ready_count"],
                "applied": summary.get("applied", 0),
                "jobs_found": summary.get("jobs_found", 0),
                "tokens": summary.get("token_usage", 0),
                "cost_usd": summary.get("estimated_cost", 0),
                "portals_configured": len(VAULT.configured_portals(candidate_id)),
            }
        )

    return {
        "candidates": rows,
        "totals": {
            "targets": sum(row["targets"] for row in rows),
            "interview_ready": sum(row["interview_ready"] for row in rows),
            "cost_usd": round(sum(float(row["cost_usd"] or 0) for row in rows), 6),
            "tokens": sum(int(row["tokens"] or 0) for row in rows),
        },
    }


def _parse_answers_markdown(text: str) -> List[Dict[str, Any]]:
    """Split Answers.md into {heading, items} blocks the dashboard can render.

    WF07 writes '# Heading' sections containing either numbered questions or
    '- ' bullets, so both list styles collapse to a plain item list here.
    """
    sections: List[Dict[str, Any]] = []
    current: Dict[str, Any] | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.startswith("# "):
            current = {"heading": line[2:].strip(), "items": []}
            sections.append(current)
            continue
        if current is None or not line.strip():
            continue

        stripped = line.strip()
        item = re.sub(r"^(?:\d+\.|-)\s*", "", stripped)
        if item:
            current["items"].append(item)

    return [section for section in sections if section["items"]]


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

    # ---- auth ----------------------------------------------------------
    def _session_token(self) -> str | None:
        raw = self.headers.get("Cookie", "")
        for chunk in raw.split(";"):
            name, _, value = chunk.strip().partition("=")
            if name == SESSION_COOKIE:
                return value
        return None

    def _current_user(self) -> User | None:
        return SESSIONS.get(self._session_token())

    def _require_user(self) -> User | None:
        """Return the signed-in user, or send 401 and return None."""
        user = self._current_user()
        if user is None:
            self._send_json({"error": "authentication required"}, 401)
            return None
        return user

    def _require_candidate_access(self, user: User, candidate_id: str) -> bool:
        """A candidate may only ever touch their own data."""
        if not candidate_id or candidate_id not in _candidate_ids():
            self._send_json({"error": "unknown candidate"}, 400)
            return False
        if not user.can_access(candidate_id):
            self._send_json({"error": "forbidden"}, 403)
            return False
        return True

    def _visible_candidates(self, user: User) -> List[str]:
        if user.is_admin:
            return _candidate_ids()
        return [user.candidate_id] if user.candidate_id in _candidate_ids() else []

    # ---- routes --------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        user = self._current_user()

        if route not in _PUBLIC_ROUTES and user is None:
            # Page requests bounce to the login screen; API calls get a 401.
            if route.startswith("/api/") or route == "/file":
                self._send_json({"error": "authentication required"}, 401)
            else:
                self._send_login_page()
            return

        if route in ("/", "/index.html"):
            template = REPO_ROOT / "src" / "dashboard" / "index.html"
            if not template.exists():
                self._send_json({"error": "dashboard template missing"}, 500)
                return
            self._send_bytes(template.read_bytes(), "text/html; charset=utf-8")
            return

        if route == "/login":
            self._send_login_page()
            return

        if route == "/api/session":
            self._send_json(
                {"authenticated": user is not None, "user": user.as_public() if user else None,
                 "setup_required": not USERS.exists()}
            )
            return

        if route == "/api/candidates":
            self._send_json({"candidates": self._visible_candidates(user), "user": user.as_public()})
            return

        if route == "/api/credentials":
            candidate = (self._query().get("candidate") or [""])[0].strip()
            if not self._require_candidate_access(user, candidate):
                return
            self._send_json({"candidate": candidate, "credentials": VAULT.list_masked(candidate),
                             "portals": _portal_catalog()})
            return

        if route == "/api/index":
            candidate = (self._query().get("candidate") or [""])[0].strip()
            if not self._require_candidate_access(user, candidate):
                return
            index = build_index(REPO_ROOT, candidate or None)
            index["resume_uploaded"] = self._resume_state(candidate)
            self._send_json(index)
            return

        if route == "/api/admin/overview":
            if not user.is_admin:
                self._send_json({"error": "forbidden"}, 403)
                return
            self._send_json(_admin_overview())
            return

        if route == "/api/run-status":
            self._send_json(_run_state)
            return

        if route == "/api/interview":
            self._handle_interview_read()
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

        if route == "/api/login":
            self._handle_login()
            return

        if route == "/api/logout":
            SESSIONS.destroy(self._session_token())
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", f"{SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict")
            self.send_header("Content-Length", "15")
            self.end_headers()
            self.wfile.write(b'{"ok": true}   '[:15])
            return

        if self._current_user() is None:
            self._send_json({"error": "authentication required"}, 401)
            return

        if route == "/api/credentials":
            self._handle_set_credential()
            return

        if route == "/api/credentials/delete":
            self._handle_delete_credential()
            return

        if route == "/api/suggest-portals":
            self._handle_suggest_portals()
            return

        if route == "/api/upload-resume":
            self._handle_upload()
            return

        if route == "/api/run":
            self._handle_run()
            return

        if route == "/api/generate-prep":
            self._handle_generate_prep()
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

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 1_000_000:
            return {}
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _send_login_page(self) -> None:
        template = REPO_ROOT / "src" / "dashboard" / "login.html"
        if not template.exists():
            self._send_json({"error": "login template missing"}, 500)
            return
        self._send_bytes(template.read_bytes(), "text/html; charset=utf-8")

    def _handle_login(self) -> None:
        body = self._read_json_body()
        user = USERS.authenticate(str(body.get("username", "")), str(body.get("password", "")))
        if user is None:
            # Deliberately vague: never reveal whether the username exists.
            self._send_json({"error": "Invalid username or password"}, 401)
            return

        token = SESSIONS.create(user)
        payload = json.dumps({"ok": True, "user": user.as_public()}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        # HttpOnly keeps the token out of reach of page scripts.
        self.send_header(
            "Set-Cookie",
            f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=28800",
        )
        self.end_headers()
        self.wfile.write(payload)

    def _handle_set_credential(self) -> None:
        user = self._require_user()
        if user is None:
            return
        body = self._read_json_body()
        candidate = str(body.get("candidate", "")).strip()
        if not self._require_candidate_access(user, candidate):
            return

        portal = str(body.get("portal", "")).strip().lower()
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
        if not portal or not username:
            self._send_json({"error": "portal and username are required"}, 400)
            return

        try:
            VAULT.set_credential(candidate, portal, username, password)
        except VaultError as exc:
            self._send_json({"error": str(exc)}, 500)
            return
        self._send_json({"ok": True, "credentials": VAULT.list_masked(candidate)})

    def _handle_delete_credential(self) -> None:
        user = self._require_user()
        if user is None:
            return
        body = self._read_json_body()
        candidate = str(body.get("candidate", "")).strip()
        if not self._require_candidate_access(user, candidate):
            return

        removed = VAULT.delete_credential(candidate, str(body.get("portal", "")).strip().lower())
        self._send_json({"ok": removed, "credentials": VAULT.list_masked(candidate)})

    def _handle_suggest_portals(self) -> None:
        """Ask the model which job boards suit this candidate's profile."""
        user = self._require_user()
        if user is None:
            return
        body = self._read_json_body()
        candidate = str(body.get("candidate", "")).strip()
        if not self._require_candidate_access(user, candidate):
            return

        try:
            context = build_runtime_context(REPO_ROOT, candidate_override=candidate)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)
            return

        suggestions = _suggest_portals(context)
        self._send_json({"ok": True, "suggestions": suggestions})

    def _safe_target_dir(self, raw: str) -> Path | None:
        """Resolve a job-target folder, confined to Profiles/."""
        try:
            resolved = Path(raw).resolve()
            resolved.relative_to(REPO_ROOT / "Profiles")
        except (ValueError, OSError):
            return None
        return resolved if resolved.is_dir() else None

    def _handle_interview_read(self) -> None:
        raw = (self._query().get("dir") or [""])[0]
        target = self._safe_target_dir(raw)
        if target is None:
            self._send_json({"error": "unknown job folder"}, 404)
            return

        answers = target / "Answers.md"
        if not answers.exists():
            self._send_json({"exists": False, "sections": []})
            return

        self._send_json(
            {
                "exists": True,
                "sections": _parse_answers_markdown(answers.read_text(encoding="utf-8")),
                "pdf_path": str(target / "InterviewQuestions.pdf")
                if (target / "InterviewQuestions.pdf").exists()
                else "",
            }
        )

    def _handle_generate_prep(self) -> None:
        candidate = (self._query().get("candidate") or [""])[0].strip()
        raw = (self._query().get("dir") or [""])[0]
        target = self._safe_target_dir(raw)

        if candidate not in _candidate_ids() or target is None:
            self._send_json({"error": "unknown candidate or job folder"}, 400)
            return

        try:
            context = build_runtime_context(REPO_ROOT, candidate_override=candidate)
            result = generate_interview_prep(REPO_ROOT, context, target)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)
            return

        self._send_json(
            {
                "ok": True,
                "mode": result.generation_mode,
                "answers_path": str(result.answers_md_path),
                "pdf_path": str(result.interview_questions_pdf_path),
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
