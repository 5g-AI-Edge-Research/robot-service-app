from __future__ import annotations

import ipaddress
import os
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from typing import Any

from flask import Flask, jsonify, request, send_from_directory


app = Flask(__name__, static_folder="static", static_url_path="/static")

AGENT_TOKEN = os.getenv("UE_AGENT_TOKEN", "").strip()
AGENT_STALE_SECONDS = float(os.getenv("AGENT_STALE_SECONDS", "35"))
COMMAND_WAIT_SECONDS = float(os.getenv("COMMAND_WAIT_SECONDS", "8"))
PROXY_WAIT_SECONDS = float(os.getenv("PROXY_WAIT_SECONDS", "25"))
MAX_PROXY_IMAGE_BYTES = int(os.getenv("MAX_PROXY_IMAGE_BYTES", "3000000"))
LONG_POLL_SECONDS = float(os.getenv("LONG_POLL_SECONDS", "25"))

PATH_TARGETS = {
    "core": {
        "target": os.getenv("CORE_ACK_TARGET", "172.16.46.1"),
        "preferred_slice": "urllc",
    },
    "mec": {
        "target": os.getenv(
            "MEC_ROBOT_URL",
            "http://172.16.49.1:5001/urllc/move",
        ),
        "preferred_slice": "mec-icn",
    },
    "cloud": {
        "target": os.getenv(
            "CLOUD_ROBOT_URL",
            "http://10.34.211.177:5000/urllc/move",
        ),
        "preferred_slice": "embb-baseline",
    },
}

# The controller derives the logical slice/DNN from the UE-assigned address.
# This intentionally does not depend on uesimtun numbering because interface
# numbers can change when PDU sessions are started in a different order.
SLICE_NETWORKS = (
    (
        ipaddress.ip_network("172.16.45.0/24"),
        {
            "slice": "embb-baseline",
            "label": "eMBB baseline",
            "dnn": "embb.testbed",
        },
    ),
    (
        ipaddress.ip_network("172.16.46.0/24"),
        {
            "slice": "urllc",
            "label": "URLLC",
            "dnn": "urllc.v2x",
        },
    ),
    (
        ipaddress.ip_network("172.16.47.0/24"),
        {
            "slice": "mmtc",
            "label": "mMTC",
            "dnn": "mmtc.testbed",
        },
    ),
    (
        ipaddress.ip_network("172.16.49.0/24"),
        {
            "slice": "mec-icn",
            "label": "MEC ICN",
            "dnn": "mec.icn.testbed",
        },
    ),
)

_lock = threading.RLock()
_changed = threading.Condition(_lock)
_agents: dict[str, dict[str, Any]] = {}
_command_queues: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
_pending: dict[str, dict[str, Any]] = {}
_results: dict[str, dict[str, Any]] = {}


def now_ts() -> float:
    return time.time()


def require_agent_auth() -> tuple[dict[str, Any] | None, tuple[Any, int] | None]:
    if not AGENT_TOKEN:
        return None, (jsonify(ok=False, error="UE_AGENT_TOKEN is not configured"), 503)

    header = request.headers.get("Authorization", "")
    supplied = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""
    if not supplied or not secrets.compare_digest(supplied, AGENT_TOKEN):
        return None, (jsonify(ok=False, error="Unauthorized UE agent"), 401)

    payload = request.get_json(silent=True) or {}
    return payload, None


def classify_tunnel(ip: str) -> dict[str, str] | None:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return None

    for network, info in SLICE_NETWORKS:
        if address in network:
            return dict(info)
    return None


def normalize_tunnels(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []

    tunnels: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue

        ip = str(item.get("ip", "")).strip()
        iface = str(item.get("iface", item.get("interface", ""))).strip()
        if not ip or not iface:
            continue

        try:
            ipaddress.ip_address(ip)
        except ValueError:
            continue

        key = (iface, ip)
        if key in seen:
            continue
        seen.add(key)

        inferred = classify_tunnel(ip)
        reported_slice = str(item.get("slice", "")).strip()
        if inferred:
            slice_name = inferred["slice"]
            label = inferred["label"]
            dnn = inferred["dnn"]
        else:
            slice_name = reported_slice or "unknown"
            label = str(item.get("label", slice_name)).strip() or slice_name
            dnn = str(item.get("dnn", "unknown")).strip() or "unknown"

        tunnels.append(
            {
                "iface": iface,
                "ip": ip,
                "slice": slice_name,
                "label": label,
                "dnn": dnn,
                "imsi": str(item.get("imsi", "unknown")).strip() or "unknown",
                "reported_slice": reported_slice or slice_name,
            }
        )

    tunnels.sort(key=lambda item: (item["slice"], item["ip"], item["iface"]))
    return tunnels


def normalize_metadata(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}

    metadata = dict(raw)
    raw_ips = metadata.get("lan_ips", [])
    if isinstance(raw_ips, str):
        raw_ips = [raw_ips]

    lan_ips: list[str] = []
    if isinstance(raw_ips, list):
        for value in raw_ips:
            value = str(value).strip()
            try:
                parsed = ipaddress.ip_address(value)
            except ValueError:
                continue
            if parsed.version == 4 and value not in lan_ips:
                lan_ips.append(value)

    for key in ("lan_ip", "host_ip"):
        value = str(metadata.get(key, "")).strip()
        if value:
            try:
                parsed = ipaddress.ip_address(value)
            except ValueError:
                continue
            if parsed.version == 4 and value not in lan_ips:
                lan_ips.append(value)

    metadata["lan_ips"] = lan_ips
    return metadata


def agent_is_online(agent: dict[str, Any], cutoff: float | None = None) -> bool:
    cutoff = cutoff if cutoff is not None else now_ts() - AGENT_STALE_SECONDS
    return float(agent["last_seen"]) >= cutoff


def serialize_agent(agent: dict[str, Any], *, include_tunnels: bool = True) -> dict[str, Any]:
    current = now_ts()
    online = agent["last_seen"] >= current - AGENT_STALE_SECONDS
    result: dict[str, Any] = {
        "device_id": agent["device_id"],
        "hostname": agent["hostname"],
        "online": online,
        "last_seen": agent["last_seen"],
        "age_seconds": max(0.0, current - agent["last_seen"]),
        "tunnel_count": len(agent["tunnels"]),
        "five_g_connected": online and bool(agent["tunnels"]),
        "metadata": agent.get("metadata", {}),
    }
    if include_tunnels:
        result["tunnels"] = [dict(tunnel) for tunnel in agent["tunnels"]]
    return result


def active_agents_locked() -> list[dict[str, Any]]:
    cutoff = now_ts() - AGENT_STALE_SECONDS
    return [agent for agent in _agents.values() if agent_is_online(agent, cutoff)]


def find_agent_for_source_locked(source_ip: str, requested_device: str) -> dict[str, Any] | None:
    for agent in active_agents_locked():
        if requested_device and agent["device_id"] != requested_device:
            continue
        if any(tunnel["ip"] == source_ip for tunnel in agent["tunnels"]):
            return agent
    return None


def queue_command_and_wait(
    agent: dict[str, Any],
    command: dict[str, Any],
    wait_seconds: float,
) -> tuple[dict[str, Any] | None, tuple[Any, int] | None]:
    command_id = command["command_id"]
    device_id = agent["device_id"]
    _pending[command_id] = command
    _command_queues[device_id].append(command)
    _changed.notify_all()

    wait_deadline = time.monotonic() + wait_seconds
    while command_id not in _results:
        remaining = wait_deadline - time.monotonic()
        if remaining <= 0:
            _pending.pop(command_id, None)
            return None, (
                jsonify(
                    success=False,
                    status="agent-timeout",
                    target=command.get("target"),
                    command_id=command_id,
                    error="UE agent did not return a result before controller timeout",
                ),
                504,
            )
        _changed.wait(timeout=remaining)

    result = _results.pop(command_id)
    _pending.pop(command_id, None)
    return result, None


def register_or_replace_agent(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, tuple[Any, int] | None]:
    device_id = str(payload.get("device_id", "")).strip()
    if not device_id:
        return None, (jsonify(ok=False, error="device_id is required"), 400)

    hostname = str(payload.get("hostname", device_id)).strip() or device_id
    tunnels = normalize_tunnels(payload.get("tunnels"))
    metadata = normalize_metadata(payload.get("metadata", {}))

    with _changed:
        _agents[device_id] = {
            "device_id": device_id,
            "hostname": hostname,
            "tunnels": tunnels,
            "metadata": metadata,
            "last_seen": now_ts(),
        }
        _changed.notify_all()
        snapshot = serialize_agent(_agents[device_id])

    return snapshot, None


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/health")
def health():
    with _lock:
        active = active_agents_locked()
        active_tunnels = sum(len(agent["tunnels"]) for agent in active)
    return jsonify(
        ok=True,
        service="urllc-robot-controller",
        role="gnb-mec-controller",
        version="4",
        active_agents=len(active),
        active_tunnels=active_tunnels,
        known_agents=len(_agents),
        agent_token_configured=bool(AGENT_TOKEN),
    )


@app.get("/api/client")
def api_client():
    remote_ip = request.headers.get("X-Forwarded-For", "").split(",", 1)[0].strip()
    if not remote_ip:
        remote_ip = request.remote_addr or ""

    matched_device_ids: list[str] = []
    with _lock:
        for agent in active_agents_locked():
            metadata = agent.get("metadata", {})
            if remote_ip and remote_ip in metadata.get("lan_ips", []):
                matched_device_ids.append(agent["device_id"])

    return jsonify(
        ok=True,
        remote_ip=remote_ip,
        matched_device_ids=matched_device_ids,
    )


@app.get("/api/agents")
def api_agents():
    with _lock:
        data = [serialize_agent(agent) for agent in _agents.values()]

    data.sort(key=lambda item: (not item["online"], item["hostname"].lower(), item["device_id"]))
    return jsonify(
        ok=True,
        agents=data,
        summary={
            "known": len(data),
            "online": sum(1 for item in data if item["online"]),
            "five_g_connected": sum(1 for item in data if item["five_g_connected"]),
            "active_tunnels": sum(item["tunnel_count"] for item in data if item["online"]),
        },
    )


@app.get("/api/agents/<device_id>")
def api_agent_detail(device_id: str):
    with _lock:
        agent = _agents.get(device_id)
        if agent is None:
            return jsonify(ok=False, error="Unknown device_id"), 404
        data = serialize_agent(agent)
    return jsonify(ok=True, agent=data)


@app.get("/api/tunnels")
def api_tunnels():
    tunnels: list[dict[str, Any]] = []
    with _lock:
        for agent in active_agents_locked():
            for tunnel in agent["tunnels"]:
                tunnels.append(
                    {
                        **tunnel,
                        "device_id": agent["device_id"],
                        "device_hostname": agent["hostname"],
                        "last_seen": agent["last_seen"],
                    }
                )

    tunnels.sort(key=lambda item: (item["device_id"], item["slice"], item["ip"]))
    return jsonify(ok=True, tunnels=tunnels, path_targets=PATH_TARGETS)


@app.post("/api/command")
def api_command():
    payload = request.get_json(silent=True) or {}
    source_ip = str(payload.get("source_ip", "")).strip()
    device_id = str(payload.get("device_id", "")).strip()
    target = str(payload.get("target", "")).strip()
    robot_command = str(payload.get("robot_command", "STOP")).upper().strip()

    if not source_ip:
        return jsonify(success=False, status="invalid", error="source_ip is required"), 400
    if not target:
        return jsonify(success=False, status="invalid", error="target is required"), 400
    if robot_command not in {"UP", "DOWN", "LEFT", "RIGHT", "STOP"}:
        return jsonify(success=False, status="invalid", error="Unsupported robot command"), 400

    try:
        payload_size = max(0, min(1400, int(payload.get("payload_size", 32))))
        deadline_ms = max(1, min(10000, int(payload.get("deadline_ms", 30))))
    except (TypeError, ValueError):
        return jsonify(success=False, status="invalid", error="Invalid numeric input"), 400

    with _changed:
        agent = find_agent_for_source_locked(source_ip, device_id)
        if agent is None:
            return (
                jsonify(
                    success=False,
                    status="ue-offline",
                    error="No online UE agent owns the selected tunnel",
                ),
                503,
            )

        command = {
            "command_id": str(uuid.uuid4()),
            "command_kind": "robot",
            "device_id": agent["device_id"],
            "source_ip": source_ip,
            "target": target,
            "payload_size": payload_size,
            "deadline_ms": deadline_ms,
            "robot_command": robot_command,
            "created_at": now_ts(),
        }
        result, wait_error = queue_command_and_wait(agent, command, COMMAND_WAIT_SECONDS)
        if wait_error:
            return wait_error
        assert result is not None

    return jsonify(result), (200 if result.get("success") else 502)


@app.post("/api/proxy")
def api_proxy():
    payload = request.get_json(silent=True) or {}
    source_ip = str(payload.get("source_ip", "")).strip()
    device_id = str(payload.get("device_id", "")).strip()
    target = str(payload.get("target", "")).strip()
    action = str(payload.get("action", "health")).strip().lower()

    if not source_ip:
        return jsonify(success=False, status="invalid", error="source_ip is required"), 400
    if not target.startswith(("http://", "https://")):
        return jsonify(success=False, status="invalid", error="target must be HTTP(S)"), 400
    if action not in {"health", "multipart-image"}:
        return jsonify(success=False, status="invalid", error="unsupported proxy action"), 400

    image_b64 = str(payload.get("image_b64", "")) if action == "multipart-image" else ""
    if action == "multipart-image":
        if not image_b64:
            return jsonify(success=False, status="invalid", error="image_b64 is required"), 400
        # Base64 expands data by roughly 4/3. This cheap bound prevents oversized
        # commands before the agent decodes the image.
        if len(image_b64) > ((MAX_PROXY_IMAGE_BYTES + 2) // 3) * 4 + 8:
            return jsonify(success=False, status="payload-too-large", error="image exceeds proxy size limit"), 413

    try:
        deadline_ms = max(1, min(60000, int(payload.get("deadline_ms", 20000))))
    except (TypeError, ValueError):
        return jsonify(success=False, status="invalid", error="invalid deadline_ms"), 400

    with _changed:
        agent = find_agent_for_source_locked(source_ip, device_id)
        if agent is None:
            return jsonify(success=False, status="ue-offline", error="No online UE agent owns the selected tunnel"), 503

        command = {
            "command_id": str(uuid.uuid4()),
            "command_kind": "http-probe" if action == "health" else "http-multipart",
            "device_id": agent["device_id"],
            "source_ip": source_ip,
            "target": target,
            "deadline_ms": deadline_ms,
            "created_at": now_ts(),
        }
        if action == "multipart-image":
            command.update(
                {
                    "image_b64": image_b64,
                    "content_type": str(payload.get("content_type", "image/jpeg")) or "image/jpeg",
                    "field_name": str(payload.get("field_name", "image")) or "image",
                    "filename": str(payload.get("filename", "frame.jpg")) or "frame.jpg",
                }
            )

        result, wait_error = queue_command_and_wait(agent, command, PROXY_WAIT_SECONDS)
        if wait_error:
            return wait_error
        assert result is not None

    return jsonify(result), (200 if result.get("success") else 502)


@app.post("/api/agent/register")
@app.post("/api/agents/register")
def agent_register():
    payload, error = require_agent_auth()
    if error:
        return error
    assert payload is not None

    snapshot, register_error = register_or_replace_agent(payload)
    if register_error:
        return register_error
    assert snapshot is not None

    return jsonify(
        ok=True,
        device_id=snapshot["device_id"],
        accepted_tunnels=snapshot["tunnel_count"],
        agent=snapshot,
    )


@app.post("/api/agent/heartbeat")
@app.post("/api/agents/heartbeat")
def agent_heartbeat():
    payload, error = require_agent_auth()
    if error:
        return error
    assert payload is not None

    device_id = str(payload.get("device_id", "")).strip()
    with _changed:
        agent = _agents.get(device_id)
        if agent is None:
            return jsonify(ok=False, error="Agent must register first"), 404
        if "tunnels" in payload:
            agent["tunnels"] = normalize_tunnels(payload.get("tunnels"))
        if "hostname" in payload:
            agent["hostname"] = str(payload.get("hostname", device_id)).strip() or device_id
        if "metadata" in payload:
            agent["metadata"] = normalize_metadata(payload.get("metadata", {}))
        agent["last_seen"] = now_ts()
        _changed.notify_all()
        snapshot = serialize_agent(agent)
    return jsonify(ok=True, agent=snapshot)


@app.get("/api/agent/commands")
def agent_commands():
    if not AGENT_TOKEN:
        return jsonify(ok=False, error="UE_AGENT_TOKEN is not configured"), 503
    header = request.headers.get("Authorization", "")
    supplied = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""
    if not supplied or not secrets.compare_digest(supplied, AGENT_TOKEN):
        return jsonify(ok=False, error="Unauthorized UE agent"), 401

    device_id = str(request.args.get("device_id", "")).strip()
    if not device_id:
        return jsonify(ok=False, error="device_id is required"), 400

    try:
        requested_timeout = float(request.args.get("timeout", LONG_POLL_SECONDS))
    except ValueError:
        requested_timeout = LONG_POLL_SECONDS
    requested_timeout = max(1.0, min(LONG_POLL_SECONDS, requested_timeout))

    with _changed:
        agent = _agents.get(device_id)
        if agent is None:
            return jsonify(ok=False, error="Agent must register first"), 404
        agent["last_seen"] = now_ts()

        end = time.monotonic() + requested_timeout
        while not _command_queues[device_id]:
            remaining = end - time.monotonic()
            if remaining <= 0:
                return ("", 204)
            _changed.wait(timeout=remaining)

        command = _command_queues[device_id].popleft()
        return jsonify(ok=True, command=command)


@app.post("/api/agent/results")
def agent_results():
    payload, error = require_agent_auth()
    if error:
        return error
    assert payload is not None

    device_id = str(payload.get("device_id", "")).strip()
    command_id = str(payload.get("command_id", "")).strip()
    if not device_id or not command_id:
        return jsonify(ok=False, error="device_id and command_id are required"), 400

    with _changed:
        command = _pending.get(command_id)
        if command is None:
            return jsonify(ok=False, error="Unknown or expired command_id"), 404
        if command["device_id"] != device_id:
            return jsonify(ok=False, error="Command belongs to another device"), 409

        success = bool(payload.get("success", False))
        try:
            rtt_ms = float(payload["rtt_ms"]) if payload.get("rtt_ms") is not None else None
        except (TypeError, ValueError):
            rtt_ms = None

        deadline_miss = bool(
            payload.get(
                "deadline_miss",
                rtt_ms is None or rtt_ms > float(command["deadline_ms"]),
            )
        )
        result = {
            "success": success,
            "status": str(payload.get("status", "ok" if success else "failed")),
            "command_id": command_id,
            "device_id": device_id,
            "target": str(payload.get("target", command["target"])),
            "source_ip": command["source_ip"],
            "robot_command": command.get("robot_command"),
            "command_kind": command.get("command_kind", "robot"),
            "transport": str(payload.get("transport", "unknown")),
            "rtt_ms": rtt_ms,
            "deadline_miss": deadline_miss,
            "http_status": payload.get("http_status"),
            "error": payload.get("error"),
            "agent_result": payload.get("details", {}),
        }
        _results[command_id] = result
        if device_id in _agents:
            _agents[device_id]["last_seen"] = now_ts()
        _changed.notify_all()

    return jsonify(ok=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)
