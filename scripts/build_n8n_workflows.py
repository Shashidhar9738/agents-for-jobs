"""Create the WF01-WF08 workflow set in n8n and export it to workflows/.

Each stage becomes its own n8n workflow: a webhook entry, an HTTP node that calls
the Python stage endpoint, an IF node that routes success vs failure, and a
response. The orchestrator workflow chains them in order on a schedule.

    python scripts/build_n8n_workflows.py --n8n http://192.168.29.100:5678 \
        --pipeline http://localhost:8800
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.agent_core.bootstrap import init_runtime

init_runtime(REPO_ROOT)

from src.agent_core.stages import STAGE_LABELS, STAGE_ORDER  # noqa: E402

WORKFLOWS_DIR = REPO_ROOT / "workflows"


class N8nClient:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.cookie = ""

    def login(self, email: str, password: str) -> None:
        body = json.dumps({"emailOrLdapLoginId": email, "password": password}).encode()
        req = urllib.request.Request(
            f"{self.base}/rest/login", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            self.cookie = response.headers.get("Set-Cookie", "").split(";")[0]

    def _call(self, path: str, method: str = "GET", payload: Any = None) -> Any:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            self.base + path, data=data,
            headers={"Content-Type": "application/json", "Cookie": self.cookie},
            method=method,
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read()).get("data")

    def list_workflows(self) -> List[Dict[str, Any]]:
        return self._call("/rest/workflows") or []

    def create(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._call("/rest/workflows", "POST", payload)

    def update(self, workflow_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._call(f"/rest/workflows/{workflow_id}", "PATCH", payload)

    def get(self, workflow_id: str) -> Dict[str, Any]:
        return self._call(f"/rest/workflows/{workflow_id}")

    def activate(self, workflow_id: str) -> bool:
        # n8n requires the current versionId in the body, and an active workflow
        # must be cycled for edited code to take effect.
        current = self.get(workflow_id)
        result = self._call(
            f"/rest/workflows/{workflow_id}/activate", "POST",
            {"versionId": current["versionId"]},
        )
        return bool(result.get("active"))


def stage_workflow(stage: str, pipeline_base: str, api_token: str) -> Dict[str, Any]:
    """One workflow per stage: webhook -> call Python -> branch on success."""
    label = STAGE_LABELS[stage]
    path = f"job-agent/{stage}"

    nodes = [
        {
            "id": f"{stage}-in", "name": "Start", "type": "n8n-nodes-base.webhook",
            "typeVersion": 2, "position": [0, 0], "webhookId": f"job-agent-{stage}",
            "parameters": {"httpMethod": "POST", "path": path, "responseMode": "responseNode"},
        },
        {
            "id": f"{stage}-run", "name": f"Run {stage.upper()}",
            "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [240, 0],
            "parameters": {
                "method": "POST",
                "url": f"{pipeline_base}/api/stage/{stage}",
                "sendHeaders": True,
                "headerParameters": {"parameters": [{"name": "X-API-Key", "value": api_token}]},
                "sendBody": True, "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify({ candidate: $json.body?.candidate || 'shashi' }) }}",
                "options": {"response": {"response": {"neverError": True}}},
            },
            # External call: retry with backoff per the spec's error-handling rules.
            "retryOnFail": True, "maxTries": 3, "waitBetweenTries": 2000,
            "onError": "continueRegularOutput",
        },
        {
            "id": f"{stage}-check", "name": "Succeeded?", "type": "n8n-nodes-base.if",
            "typeVersion": 2, "position": [480, 0],
            "parameters": {
                "conditions": {
                    "options": {"caseSensitive": True, "version": 2},
                    "combinator": "and",
                    "conditions": [{
                        "id": "ok",
                        "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                        "leftValue": "={{ $json.ok === true }}", "rightValue": "",
                    }],
                }
            },
        },
        {
            "id": f"{stage}-ok", "name": "Return result",
            "type": "n8n-nodes-base.respondToWebhook", "typeVersion": 1, "position": [720, -90],
            "parameters": {"respondWith": "allIncomingItems", "options": {}},
        },
        {
            "id": f"{stage}-err", "name": "Return failure",
            "type": "n8n-nodes-base.respondToWebhook", "typeVersion": 1, "position": [720, 90],
            "parameters": {
                "respondWith": "json", "responseCode": 500,
                "responseBody": "={{ JSON.stringify({ stage: '" + stage + "', ok: false, error: $json.error || 'stage failed' }) }}",
                "options": {},
            },
        },
    ]

    connections = {
        "Start": {"main": [[{"node": f"Run {stage.upper()}", "type": "main", "index": 0}]]},
        f"Run {stage.upper()}": {"main": [[{"node": "Succeeded?", "type": "main", "index": 0}]]},
        "Succeeded?": {"main": [
            [{"node": "Return result", "type": "main", "index": 0}],
            [{"node": "Return failure", "type": "main", "index": 0}],
        ]},
    }

    return {
        "name": f"{stage.upper()} {label}",
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
    }


def orchestrator_workflow(pipeline_base: str, api_token: str, stages: List[str]) -> Dict[str, Any]:
    """Chains every stage in order, on a schedule and via webhook."""
    nodes: List[Dict[str, Any]] = [
        {
            "id": "orch-cron", "name": "Daily 09:00", "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2, "position": [0, -110],
            "parameters": {"rule": {"interval": [{"field": "cronExpression", "expression": "0 9 * * *"}]}},
        },
        {
            "id": "orch-hook", "name": "Manual trigger (webhook)", "type": "n8n-nodes-base.webhook",
            "typeVersion": 2, "position": [0, 110], "webhookId": "job-agent-run-all",
            "parameters": {"httpMethod": "POST", "path": "job-agent/run-all", "responseMode": "lastNode"},
        },
        {
            "id": "orch-ctx", "name": "Set Candidate", "type": "n8n-nodes-base.set",
            "typeVersion": 3.4, "position": [240, 0],
            "parameters": {"assignments": {"assignments": [
                {"id": "c", "name": "candidate", "value": "={{ $json.body?.candidate || 'shashi' }}", "type": "string"}
            ]}, "options": {}},
        },
    ]

    connections: Dict[str, Any] = {
        "Daily 09:00": {"main": [[{"node": "Set Candidate", "type": "main", "index": 0}]]},
        "Manual trigger (webhook)": {"main": [[{"node": "Set Candidate", "type": "main", "index": 0}]]},
    }

    previous = "Set Candidate"
    x = 480
    for stage in stages:
        name = f"{stage.upper()} {STAGE_LABELS[stage]}"
        nodes.append({
            "id": f"orch-{stage}", "name": name,
            "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [x, 0],
            "parameters": {
                "method": "POST",
                "url": f"{pipeline_base}/api/stage/{stage}",
                "sendHeaders": True,
                "headerParameters": {"parameters": [{"name": "X-API-Key", "value": api_token}]},
                "sendBody": True, "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify({ candidate: $('Set Candidate').first().json.candidate }) }}",
                "options": {"response": {"response": {"neverError": True}}},
            },
            "retryOnFail": True, "maxTries": 3, "waitBetweenTries": 2000,
            # One failing stage must not abort the run; later stages still execute.
            "onError": "continueRegularOutput",
        })
        connections[previous] = {"main": [[{"node": name, "type": "main", "index": 0}]]}
        previous = name
        x += 220

    return {
        "name": "WF-ORCHESTRATOR Full pipeline",
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the WF01-WF08 workflow set in n8n.")
    parser.add_argument("--n8n", default="http://192.168.29.100:5678")
    parser.add_argument("--pipeline", default="http://localhost:8800",
                        help="Where the Python service is reachable FROM n8n")
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--export-only", action="store_true",
                        help="Write workflows/ JSON without touching the n8n server")
    args = parser.parse_args()

    token = os.getenv("JOB_AGENT_API_TOKEN", "")
    if not token:
        print("[FAIL] JOB_AGENT_API_TOKEN is not set in .env")
        return 1

    stages = [s for s in STAGE_ORDER]
    definitions = {s: stage_workflow(s, args.pipeline, token) for s in stages}
    definitions["orchestrator"] = orchestrator_workflow(args.pipeline, token, stages)

    WORKFLOWS_DIR.mkdir(exist_ok=True)
    for key, payload in definitions.items():
        # Exported copies carry a placeholder instead of the real token.
        export = json.loads(json.dumps(payload).replace(token, "${JOB_AGENT_API_TOKEN}"))
        (WORKFLOWS_DIR / f"{key}.json").write_text(json.dumps(export, indent=2), encoding="utf-8")
    print(f"[OK] exported {len(definitions)} workflow(s) to {WORKFLOWS_DIR}")

    if args.export_only:
        return 0

    client = N8nClient(args.n8n)
    try:
        client.login(os.getenv("N8N_USER", ""), os.getenv("N8N_PASSWORD", ""))
    except urllib.error.HTTPError as exc:
        print(f"[FAIL] n8n login failed: {exc.code}")
        return 1

    existing = {w["name"]: w["id"] for w in client.list_workflows()}
    for key, payload in definitions.items():
        name = payload["name"]
        try:
            if name in existing:
                current = client.get(existing[name])
                payload_with_version = dict(payload)
                payload_with_version["versionId"] = current["versionId"]
                result = client.update(existing[name], payload_with_version)
                action = "updated"
            else:
                result = client.create(payload)
                action = "created"
            status = ""
            if args.activate:
                status = " · active" if client.activate(result["id"]) else " · ACTIVATION FAILED"
            print(f"  [{action}] {name}{status}")
        except urllib.error.HTTPError as exc:
            print(f"  [FAIL] {name}: {exc.code} {exc.read().decode()[:160]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
