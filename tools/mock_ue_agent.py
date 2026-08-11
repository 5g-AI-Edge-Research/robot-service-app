#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import socket
import time
import urllib.error
import urllib.parse
import urllib.request


def request_json(method: str, url: str, token: str, body=None, timeout: float = 30.0):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            if response.status == 204 or not raw:
                return response.status, None
            return response.status, json.loads(raw.decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {raw}") from exc


def main():
    parser = argparse.ArgumentParser(description="Temporary fake UE agent for controller smoke tests")
    parser.add_argument("--controller", default="http://10.34.211.157:30800")
    parser.add_argument("--token", required=True)
    parser.add_argument("--device-id", default="mock-ue-01")
    args = parser.parse_args()

    base = args.controller.rstrip("/")
    tunnels = [
        {
            "iface": "uesimtun0",
            "ip": "172.16.45.92",
            "slice": "embb-baseline",
            "label": "eMBB baseline (mock)",
            "dnn": "embb.testbed",
            "imsi": "imsi-001011000000001",
        },
        {
            "iface": "uesimtun1",
            "ip": "172.16.46.92",
            "slice": "urllc",
            "label": "URLLC (mock)",
            "dnn": "urllc.v2x",
            "imsi": "imsi-001012000000001",
        },
        {
            "iface": "uesimtun3",
            "ip": "172.16.49.92",
            "slice": "mec-icn",
            "label": "MEC ICN (mock)",
            "dnn": "mec.icn.testbed",
            "imsi": "imsi-001014000000001",
        },
    ]

    register_body = {
        "device_id": args.device_id,
        "hostname": socket.gethostname(),
        "tunnels": tunnels,
        "metadata": {"mode": "mock", "warning": "No real UE traffic"},
    }
    status, body = request_json("POST", f"{base}/api/agent/register", args.token, register_body)
    print(f"registered: HTTP {status} {body}")
    print("mock agent is running; stop with Ctrl+C")

    while True:
        query = urllib.parse.urlencode({"device_id": args.device_id, "timeout": 25})
        status, body = request_json(
            "GET",
            f"{base}/api/agent/commands?{query}",
            args.token,
            timeout=30,
        )
        if status == 204 or not body:
            continue

        command = body["command"]
        selected_ip = command["source_ip"]
        if selected_ip.startswith("172.16.49."):
            rtt_ms = round(random.uniform(2.0, 7.0), 3)
        elif selected_ip.startswith("172.16.46."):
            rtt_ms = round(random.uniform(8.0, 20.0), 3)
        else:
            rtt_ms = round(random.uniform(20.0, 55.0), 3)

        time.sleep(rtt_ms / 1000.0)
        result = {
            "device_id": args.device_id,
            "command_id": command["command_id"],
            "success": True,
            "status": "mock-ack",
            "target": command["target"],
            "transport": "mock",
            "rtt_ms": rtt_ms,
            "deadline_miss": rtt_ms > float(command["deadline_ms"]),
            "http_status": 200,
            "details": {"mock": True, "robot_command": command["robot_command"]},
        }
        request_json("POST", f"{base}/api/agent/results", args.token, result)
        print(f"ACK {command['robot_command']} via {selected_ip}: {rtt_ms} ms")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nmock agent stopped")
