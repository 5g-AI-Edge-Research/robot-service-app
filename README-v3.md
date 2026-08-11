# URLLC Robot Controller v3 — Multi-device UE Discovery

This version keeps all v2 robot command endpoints and adds a multi-device UE registry UI.

## Backward compatibility

Existing endpoints remain available:

- `GET /health`
- `GET /api/tunnels`
- `POST /api/command`
- `POST /api/agent/register`
- `POST /api/agent/heartbeat`
- `GET /api/agent/commands`
- `POST /api/agent/results`

New/expanded endpoints:

- `GET /api/agents` — full device inventory, tunnel list, online/5G state
- `GET /api/agents/<device_id>` — one device
- `GET /api/client` — browser-visible source IP and optional agent match
- `POST /api/agents/register` — plural alias
- `POST /api/agents/heartbeat` — plural alias

## Slice mapping

The controller derives the slice from UE IP, independent of the `uesimtun` number:

- `172.16.45.0/24` → eMBB / `embb.testbed`
- `172.16.46.0/24` → URLLC / `urllc.v2x`
- `172.16.47.0/24` → mMTC / `mmtc.testbed`
- `172.16.49.0/24` → MEC ICN / `mec.icn.testbed`

## Laptop auto-match contract

A future laptop agent should include its LAN addresses in registration metadata:

```json
{
  "device_id": "laptop-farrel",
  "hostname": "farrel-laptop",
  "metadata": {
    "lan_ips": ["10.34.211.50"],
    "role": "ue-laptop"
  },
  "tunnels": [
    {
      "iface": "uesimtun0",
      "ip": "172.16.49.40"
    }
  ]
}
```

The controller then reports the matching device in `GET /api/client` when the browser source IP equals one of the registered `lan_ips`.

## Deployment note

Do not `kubectl apply` the bundled deployment manifest over the live v2 Deployment unless you have intentionally reviewed all environment overrides. For the existing installation, import image `v3` on the RAN node and use `kubectl set image` from the Core so the live Secret and current path target environment variables remain unchanged.
