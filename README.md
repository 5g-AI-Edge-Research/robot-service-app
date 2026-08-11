# URLLC Robot Service — 5G AI Edge Testbed

Repository ini berisi service **URLLC Robot Controller** untuk testbed 5G SA berbasis **Open5GS + K3s**.

Service ini digunakan sebagai controller utama untuk menerima request dari web/app, memilih target eksekusi, berkomunikasi dengan UE Discovery Agent, dan meneruskan command ke backend robot baik melalui jalur MEC maupun Cloud.

---

## 1. Arsitektur Singkat

Arsitektur service robot:

```text
Client / Web App
      |
      v
URLLC Robot Controller
10.34.211.157:30800
      |
      +----------------------+
      |                      |
      v                      v
UE Discovery Agent       Direct Target
      |                      |
      v                      v
UE / UERANSIM           MEC / Cloud API
```

Komponen utama:

| Komponen | Endpoint / Lokasi | Keterangan |
|---|---|---|
| Robot Controller | `10.34.211.157:30800` | Controller utama |
| Kubernetes Namespace | `open5gs` | Namespace deployment |
| Node RAN1 | `riset-5g` | Node tempat controller dijalankan |
| MEC Robot API | `http://172.16.49.1:5001/urllc/move` | Backend robot di MEC |
| Cloud Robot API | `https://awsub.dpdns.org/urllc/move` | Backend robot melalui Cloudflare |
| Core ACK Target | `172.16.46.1` | Target jalur URLLC/Core |

---

## 2. Repository Structure

Struktur repository yang direkomendasikan:

```text
robot-service/
├── app.py
├── requirements.txt
├── Dockerfile
├── README.md
└── k8s/
    ├── deployment.yaml
    └── service.yaml
```

Jika source utama menggunakan nama file berbeda, sesuaikan `Dockerfile` dan command startup.

---

## 3. Fungsi Service

Robot Controller menangani beberapa fungsi utama:

- menerima request command robot
- menerima heartbeat / registration dari UE Discovery Agent
- mendeteksi UE yang aktif
- melakukan routing request menuju target MEC atau Cloud
- melakukan proxy request melalui UE
- melakukan health check
- menyimpan status agent dan tunnel yang aktif
- menerapkan allowlist target untuk keamanan request

---

## 4. Endpoint Utama

### Health Check

```http
GET /health
```

Contoh:

```bash
curl http://10.34.211.157:30800/health
```

Expected response:

```text
HTTP 200
```

---

### Agent API

Untuk melihat UE Discovery Agent yang terdaftar:

```bash
curl -s \
  http://10.34.211.157:30800/api/agents \
  | python3 -m json.tool
```

Agent yang aktif biasanya berisi informasi seperti:

```text
device_id
hostname
lan_ips
tunnels
last_seen
version
```

---

## 5. Target Robot

Controller memiliki dua target utama.

### MEC Robot

```text
http://172.16.49.1:5001/urllc/move
```

Traffic diarahkan menuju backend robot yang berjalan pada MEC RAN1.

### Cloud Robot

```text
https://awsub.dpdns.org/urllc/move
```

Traffic diarahkan menuju backend cloud melalui Cloudflare.

---

## 6. Environment Variables

Environment utama yang digunakan deployment:

```text
AGENT_STALE_SECONDS=35
COMMAND_WAIT_SECONDS=8
LONG_POLL_SECONDS=25
PROXY_WAIT_SECONDS=25
MAX_PROXY_IMAGE_BYTES=3000000

CORE_ACK_TARGET=172.16.46.1

MEC_ROBOT_URL=http://172.16.49.1:5001/urllc/move
CLOUD_ROBOT_URL=https://awsub.dpdns.org/urllc/move
```

Token agent disimpan sebagai secret:

```text
UE_AGENT_TOKEN
```

Jangan hardcode token production langsung ke repository.

---

## 7. Docker Build

Build image:

```bash
docker build \
  -t urllc-robot-controller:v4 .
```

Cek:

```bash
docker images | grep urllc-robot-controller
```

Expected:

```text
urllc-robot-controller   v4
```

---

## 8. Import Image ke K3s Node

Deployment saat ini menggunakan:

```yaml
imagePullPolicy: Never
```

Artinya image harus sudah tersedia secara lokal pada node tempat pod dijalankan.

Jika build dilakukan langsung di node `riset-5g`, pastikan image terlihat oleh runtime yang digunakan K3s.

Cek pod setelah deploy:

```bash
kubectl get pods \
  -n open5gs \
  -l app=urllc-robot-controller \
  -o wide
```

Controller harus berjalan pada node:

```text
riset-5g
```

---

## 9. Kubernetes Deployment

File:

```text
k8s/deployment.yaml
```

Contoh konfigurasi:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: urllc-robot-controller
  namespace: open5gs

spec:
  replicas: 1

  strategy:
    type: Recreate

  selector:
    matchLabels:
      app: urllc-robot-controller

  template:
    metadata:
      labels:
        app: urllc-robot-controller

    spec:
      nodeSelector:
        kubernetes.io/hostname: riset-5g

      containers:
        - name: urllc-robot-controller
          image: docker.io/library/urllc-robot-controller:v4
          imagePullPolicy: Never

          ports:
            - name: http
              containerPort: 8080

          env:
            - name: AGENT_STALE_SECONDS
              value: "35"

            - name: COMMAND_WAIT_SECONDS
              value: "8"

            - name: LONG_POLL_SECONDS
              value: "25"

            - name: PROXY_WAIT_SECONDS
              value: "25"

            - name: MAX_PROXY_IMAGE_BYTES
              value: "3000000"

            - name: CORE_ACK_TARGET
              value: "172.16.46.1"

            - name: MEC_ROBOT_URL
              value: "http://172.16.49.1:5001/urllc/move"

            - name: CLOUD_ROBOT_URL
              value: "https://awsub.dpdns.org/urllc/move"

            - name: UE_AGENT_TOKEN
              valueFrom:
                secretKeyRef:
                  name: urllc-robot-controller-secret
                  key: UE_AGENT_TOKEN

          readinessProbe:
            httpGet:
              path: /health
              port: http

          livenessProbe:
            httpGet:
              path: /health
              port: http
```

---

## 10. Kubernetes Service

File:

```text
k8s/service.yaml
```

Contoh:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: urllc-robot-controller
  namespace: open5gs

spec:
  type: NodePort

  selector:
    app: urllc-robot-controller

  ports:
    - name: http
      port: 8080
      targetPort: http
      nodePort: 30800
```

Dengan konfigurasi tersebut, controller dapat diakses melalui:

```text
http://10.34.211.157:30800
```

Untuk workload di dalam cluster:

```text
http://urllc-robot-controller:8080
```

---

## 11. Secret UE Agent Token

Buat secret:

```bash
kubectl create secret generic \
  urllc-robot-controller-secret \
  -n open5gs \
  --from-literal=UE_AGENT_TOKEN='<TOKEN>'
```

Cek:

```bash
kubectl get secret \
  -n open5gs \
  urllc-robot-controller-secret
```

Jangan commit nilai token ke Git.

---

## 12. Deploy ke Kubernetes

Apply Deployment:

```bash
kubectl apply \
  -f k8s/deployment.yaml
```

Apply Service:

```bash
kubectl apply \
  -f k8s/service.yaml
```

Atau sekaligus:

```bash
kubectl apply \
  -f k8s/
```

---

## 13. Cek Deployment

Status deployment:

```bash
kubectl get deployment \
  -n open5gs \
  urllc-robot-controller
```

Pod:

```bash
kubectl get pods \
  -n open5gs \
  -l app=urllc-robot-controller \
  -o wide
```

Service:

```bash
kubectl get svc \
  -n open5gs \
  urllc-robot-controller
```

Expected NodePort:

```text
8080:30800
```

---

## 14. Rollout

Setelah image atau konfigurasi berubah:

```bash
kubectl rollout restart \
  deployment/urllc-robot-controller \
  -n open5gs
```

Pantau:

```bash
kubectl rollout status \
  deployment/urllc-robot-controller \
  -n open5gs
```

---

## 15. Logs

Lihat log controller:

```bash
kubectl logs \
  -n open5gs \
  deployment/urllc-robot-controller \
  -f
```

Atau:

```bash
kubectl logs \
  -n open5gs \
  -l app=urllc-robot-controller \
  --tail=100
```

---

## 16. Test Health

Dari host yang dapat mengakses RAN1:

```bash
curl -i \
  http://10.34.211.157:30800/health
```

Expected:

```text
HTTP/1.1 200 OK
```

---

## 17. Test MEC Robot

Test backend MEC secara langsung:

```bash
curl \
  http://172.16.49.1:5001/health
```

Endpoint robot:

```text
http://172.16.49.1:5001/urllc/move
```

Method endpoint robot adalah `POST`.

---

## 18. Test Cloud Robot

Health:

```bash
curl \
  https://awsub.dpdns.org/health
```

Robot endpoint:

```text
https://awsub.dpdns.org/urllc/move
```

Endpoint `/urllc/move` menggunakan method `POST`.

Jika melakukan:

```bash
curl \
  https://awsub.dpdns.org/urllc/move
```

dan mendapatkan:

```text
405 Method Not Allowed
```

itu dapat berarti endpoint tersedia tetapi request menggunakan method yang salah.

---

## 19. UE Discovery Agent

Agent harus menggunakan controller:

```text
http://10.34.211.157:30800
```

Contoh status service:

```bash
systemctl --user status \
  ue-discovery-agent.service
```

Restart:

```bash
systemctl --user restart \
  ue-discovery-agent.service
```

Log:

```bash
journalctl --user \
  -u ue-discovery-agent.service \
  -n 50 \
  --no-pager
```

Agent berhasil terhubung jika log menunjukkan proses registration / heartbeat ke controller.

---

## 20. Allowlist Target

UE Discovery Agent menggunakan exact-match allowlist.

Contoh target yang digunakan robot:

```text
172.16.46.1
http://172.16.49.1:5001/urllc/move
https://awsub.dpdns.org/urllc/move
```

Jika target tidak berada di allowlist, request dapat menghasilkan status seperti:

```text
target-denied
```

Config biasanya berada di:

```text
~/.config/ue-discovery-agent.env
```

Setelah mengubah:

```bash
systemctl --user restart \
  ue-discovery-agent.service
```

---

## 21. Troubleshooting

### Pod `ErrImageNeverPull`

Contoh:

```text
ErrImageNeverPull
```

Penyebab:

```yaml
imagePullPolicy: Never
```

tetapi image tidak tersedia pada node tempat pod dijadwalkan.

Pastikan controller dijalankan pada:

```text
riset-5g
```

dan image:

```text
urllc-robot-controller:v4
```

tersedia pada node tersebut.

---

### Pod Dijadwalkan ke Node yang Salah

Cek:

```bash
kubectl get pods \
  -n open5gs \
  -l app=urllc-robot-controller \
  -o wide
```

Deployment seharusnya memiliki:

```yaml
nodeSelector:
  kubernetes.io/hostname: riset-5g
```

Patch jika diperlukan:

```bash
kubectl patch deployment \
  urllc-robot-controller \
  -n open5gs \
  --type='merge' \
  -p '{"spec":{"template":{"spec":{"nodeSelector":{"kubernetes.io/hostname":"riset-5g"}}}}}'
```

---

### Agent Tidak Terdeteksi

Cek controller:

```bash
curl -s \
  http://10.34.211.157:30800/api/agents \
  | python3 -m json.tool
```

Restart agent:

```bash
systemctl --user restart \
  ue-discovery-agent.service
```

Cek:

```bash
journalctl --user \
  -u ue-discovery-agent.service \
  -n 100 \
  --no-pager
```

---

### `target-denied`

Tambahkan URL target exact-match ke allowlist agent.

Contoh:

```text
https://awsub.dpdns.org/urllc/move
```

Kemudian restart agent.

---

### MEC Tidak Bisa Diakses

Cek backend:

```bash
curl \
  http://172.16.49.1:5001/health
```

Cek target environment:

```bash
kubectl exec \
  -n open5gs \
  deployment/urllc-robot-controller \
  -- env | grep MEC_ROBOT_URL
```

---

### Cloud Tidak Bisa Diakses

Cek:

```bash
curl \
  https://awsub.dpdns.org/health
```

Kemudian cek environment:

```bash
kubectl exec \
  -n open5gs \
  deployment/urllc-robot-controller \
  -- env | grep CLOUD_ROBOT_URL
```

---

## 22. Update Image

Setelah source code berubah:

```bash
docker build \
  -t urllc-robot-controller:v4 .
```

Jika menggunakan tag baru:

```bash
docker build \
  -t urllc-robot-controller:v5 .
```

Kemudian update image di:

```text
k8s/deployment.yaml
```

Contoh:

```yaml
image: docker.io/library/urllc-robot-controller:v5
```

Apply:

```bash
kubectl apply \
  -f k8s/deployment.yaml
```

Pantau:

```bash
kubectl rollout status \
  deployment/urllc-robot-controller \
  -n open5gs
```

---

## 23. Quick Start

Build:

```bash
docker build \
  -t urllc-robot-controller:v4 .
```

Deploy:

```bash
kubectl apply \
  -f k8s/
```

Cek:

```bash
kubectl get pods \
  -n open5gs \
  -l app=urllc-robot-controller \
  -o wide
```

Health:

```bash
curl \
  http://10.34.211.157:30800/health
```

Agent:

```bash
curl -s \
  http://10.34.211.157:30800/api/agents \
  | python3 -m json.tool
```

Logs:

```bash
kubectl logs \
  -n open5gs \
  deployment/urllc-robot-controller \
  -f
```

---

## 24. Catatan Keamanan

Jangan commit:

- `UE_AGENT_TOKEN`
- API token
- Cloudflare token
- private key
- password
- `.env`
- credential production

Contoh `.gitignore`:

```gitignore
.env
*.env
*.log
*.tmp
*.pid
*.backup
*.bak
__pycache__/
*.pyc
```

---

## Maintainer

5G AI Edge Testbed

GitHub Organization:

```text
5g-ai-edge
```
