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
    """One workflow per stage, callable two ways.

    An Execute Workflow trigger lets the orchestrator run it as a sub-workflow and
    receive its output; a webhook lets it be run on its own for debugging. Both
    feed the same HTTP call, so the two entry points cannot drift apart.
    """
    label = STAGE_LABELS[stage]
    path = f"job-agent/{stage}"

    nodes = [
        {
            "id": f"{stage}-sub", "name": "Called by orchestrator",
            "type": "n8n-nodes-base.executeWorkflowTrigger", "typeVersion": 1.1,
            "position": [0, -110],
            "parameters": {"workflowInputs": {"values": [{"name": "candidate", "type": "string"}]}},
        },
        {
            "id": f"{stage}-in", "name": "Start", "type": "n8n-nodes-base.webhook",
            "typeVersion": 2, "position": [0, 110], "webhookId": f"job-agent-{stage}",
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
                # Accepts a candidate from either entry point.
                "jsonBody": "={{ JSON.stringify({ candidate: $json.candidate || $json.body?.candidate || 'shashi' }) }}",
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
        {
            # Without this the execution is recorded green even though the stage
            # did nothing, which makes n8n's history actively misleading.
            "id": f"{stage}-stop", "name": "Mark run failed",
            "type": "n8n-nodes-base.stopAndError", "typeVersion": 1, "position": [960, 90],
            "parameters": {
                "errorMessage": "={{ 'Stage " + stage + " failed: ' + JSON.stringify($json.error || 'unknown') }}"
            },
        },
    ]

    connections = {
        "Called by orchestrator": {"main": [[{"node": f"Run {stage.upper()}", "type": "main", "index": 0}]]},
        "Start": {"main": [[{"node": f"Run {stage.upper()}", "type": "main", "index": 0}]]},
        f"Run {stage.upper()}": {"main": [[{"node": "Succeeded?", "type": "main", "index": 0}]]},
        "Succeeded?": {"main": [
            [{"node": "Return result", "type": "main", "index": 0}],
            [{"node": "Return failure", "type": "main", "index": 0}],
        ]},
        # Respond first so the caller still gets a useful body, then fail the run.
        "Return failure": {"main": [[{"node": "Mark run failed", "type": "main", "index": 0}]]},
    }

    return {
        "name": f"{stage.upper()} {label}",
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
    }


def orchestrator_workflow(
    pipeline_base: str,
    api_token: str,
    stages: List[str],
    stage_ids: Dict[str, str],
) -> Dict[str, Any]:
    """Chains the stage workflows in order, on a schedule and via webhook.

    Calls each stage as a sub-workflow rather than hitting the pipeline directly,
    so the nine workflows are genuinely wired together: the orchestrator passes
    the candidate down, each child returns its result, and every stage shows up
    in n8n's execution history under the parent run.
    """
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
        name = f"Run {stage.upper()}"
        nodes.append({
            "id": f"orch-{stage}", "name": name,
            "type": "n8n-nodes-base.executeWorkflow", "typeVersion": 1.2, "position": [x, 0],
            "parameters": {
                "workflowId": {"__rl": True, "value": stage_ids[stage], "mode": "id"},
                "workflowInputs": {
                    "mappingMode": "defineBelow",
                    "value": {"candidate": "={{ $('Set Candidate').first().json.candidate }}"},
                },
                "options": {"waitForSubWorkflow": True},
            },
            "retryOnFail": True, "maxTries": 3, "waitBetweenTries": 2000,
            # One failing stage must not abort the run; later stages still execute.
            "onError": "continueRegularOutput",
        })
        connections[previous] = {"main": [[{"node": name, "type": "main", "index": 0}]]}
        previous = name
        x += 200

    # Collapse every stage result into one run summary.
    nodes.append({
        "id": "orch-summary", "name": "Run Summary", "type": "n8n-nodes-base.code",
        "typeVersion": 2, "position": [x, 0],
        "parameters": {"jsCode": _SUMMARY_JS},
    })
    connections[previous] = {"main": [[{"node": "Run Summary", "type": "main", "index": 0}]]}

    return {
        "name": "WF-ORCHESTRATOR Full pipeline",
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
    }


_SUMMARY_JS = """
const stages = ['wf00','wf01','wf02','wf03','wf04','wf05','wf06','wf07','wf08'];
const summary = [];

// An error may arrive as a string, or as an object from the HTTP node. Flatten
// both to readable text - "[object Object]" tells nobody anything.
function describe(err) {
  if (!err) return '';
  if (typeof err === 'string') return err.slice(0, 200);
  return String(err.message || err.error || JSON.stringify(err)).slice(0, 200);
}

for (const stage of stages) {
  let entry = { stage, ok: false, detail: 'not run' };
  try {
    const out = $('Run ' + stage.toUpperCase()).first().json;
    entry = {
      stage,
      ok: out.ok === true,
      detail: out.ok === true ? (out.label || 'ok') : describe(out.error)
    };
  } catch (e) {
    // Node did not execute in this run; leave the default entry.
  }
  summary.push(entry);
}

const failed = summary.filter(s => !s.ok);
return [{ json: {
  candidate: $('Set Candidate').first().json.candidate,
  run_id: $execution.id,
  stages_ok: summary.length - failed.length,
  stages_failed: failed.length,
  failed: failed.map(f => f.stage),
  detail: summary
} }];
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the WF01-WF08 workflow set in n8n.")
    parser.add_argument("--n8n", default="http://192.168.29.100:5678")
    # Deliberately the IPv4 literal, not "localhost": Node resolves localhost to
    # the IPv6 ::1 first on Windows, while the pipeline binds IPv4 only, so
    # "localhost" produces ECONNREFUSED ::1:8800 even when the service is up.
    parser.add_argument("--pipeline", default="http://127.0.0.1:8800",
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
    stage_defs = {s: stage_workflow(s, args.pipeline, token) for s in stages}

    if args.export_only:
        # No server, so reference stages by name rather than a real id.
        _export(stage_defs, orchestrator_workflow(args.pipeline, token, stages,
                                                  {s: f"<{s}-id>" for s in stages}), token)
        return 0

    client = N8nClient(args.n8n)
    try:
        client.login(os.getenv("N8N_USER", ""), os.getenv("N8N_PASSWORD", ""))
    except urllib.error.HTTPError as exc:
        print(f"[FAIL] n8n login failed: {exc.code}")
        return 1

    existing = {w["name"]: w["id"] for w in client.list_workflows()}

    def upsert(payload: Dict[str, Any]) -> Dict[str, Any] | None:
        name = payload["name"]
        try:
            if name in existing:
                current = client.get(existing[name])
                body = dict(payload)
                body["versionId"] = current["versionId"]
                result = client.update(existing[name], body)
                action = "updated"
            else:
                result = client.create(payload)
                action = "created"
            status = ""
            if args.activate:
                status = " · active" if client.activate(result["id"]) else " · ACTIVATION FAILED"
            print(f"  [{action}] {name}{status}")
            return result
        except urllib.error.HTTPError as exc:
            print(f"  [FAIL] {name}: {exc.code} {exc.read().decode()[:200]}")
            return None

    # Children first: the orchestrator needs their real ids to call them.
    stage_ids: Dict[str, str] = {}
    for stage in stages:
        result = upsert(stage_defs[stage])
        if result:
            stage_ids[stage] = result["id"]

    missing = [s for s in stages if s not in stage_ids]
    if missing:
        print(f"[FAIL] could not create stage workflows: {', '.join(missing)}")
        return 1

    orchestrator = orchestrator_workflow(args.pipeline, token, stages, stage_ids)
    upsert(orchestrator)

    _export(stage_defs, orchestrator, token)
    return 0


def _export(stage_defs: Dict[str, Any], orchestrator: Dict[str, Any], token: str) -> None:
    """Write the workflow JSON to workflows/, with the token redacted."""
    WORKFLOWS_DIR.mkdir(exist_ok=True)
    payloads = dict(stage_defs)
    payloads["orchestrator"] = orchestrator
    for key, payload in payloads.items():
        redacted = json.loads(json.dumps(payload).replace(token, "${JOB_AGENT_API_TOKEN}"))
        (WORKFLOWS_DIR / f"{key}.json").write_text(json.dumps(redacted, indent=2), encoding="utf-8")
    print(f"[OK] exported {len(payloads)} workflow(s) to {WORKFLOWS_DIR}")


if __name__ == "__main__":
    raise SystemExit(main())
