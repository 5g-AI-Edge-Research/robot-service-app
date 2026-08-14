const state = {
  agents: [],
  tunnels: [],
  selectedDeviceId: "",
  client: { remote_ip: "", matched_device_ids: [] },
  robot: { x: 0, y: 0 },
  goal: { x: 13, y: 8 },
  width: 14,
  height: 9,
  obstacles: new Set([
    "3,0","8,0","11,0",
    "3,1","5,1","8,1","11,1",
    "1,2","5,2","8,2",
    "1,3","2,3","5,3","10,3","11,3",
    "5,4","7,4","8,4","11,4",
    "2,5","3,5","8,5","11,5","12,5",
    "3,6","6,6","8,6",
    "3,7","6,7","10,7",
    "6,8","10,8"
  ]),
  danger: new Set(["4,2","6,2","9,3","9,4","4,5","7,6","9,7","12,7"]),
  trail: new Set(),
  score: 0,
  commands: 0,
  losses: 0,
  misses: 0,
  rtts: [],
  events: [],
  busy: false,
  reached: 0,
  autoRunning: false,
  selectedPath: "core",
  pathTargets: {
    core: { target: "172.16.46.1", preferred_slice: "urllc" },
    mec: { target: "http://172.16.49.1:5001/urllc/move", preferred_slice: "mec-icn" },
    cloud: { target: "http://10.34.211.177:5000/urllc/move", preferred_slice: "embb-baseline" },
  },
};

const $ = (id) => document.getElementById(id);

function presetTarget(value){
  $("targetInput").value = value;
}
window.presetTarget = presetTarget;

function escapeText(value){
  return String(value == null ? "" : value);
}

function ageLabel(seconds){
  const value = Number(seconds || 0);
  if(value < 2) return "just now";
  if(value < 60) return `${Math.round(value)}s ago`;
  return `${Math.round(value / 60)}m ago`;
}

function selectedAgent(){
  return state.agents.find(agent => agent.device_id === state.selectedDeviceId) || null;
}

function tunnelsForSelectedDevice(){
  if(!state.selectedDeviceId) return [];
  return state.tunnels.filter(tunnel => tunnel.device_id === state.selectedDeviceId);
}

function selectFirstTunnelBySlice(sliceName){
  const tunnel = tunnelsForSelectedDevice().find(t => t.slice === sliceName);
  if(tunnel){
    $("sourceSelect").value = tunnel.ip;
    updateSliceCard();
    return true;
  }
  return false;
}

function selectPath(path){
  state.selectedPath = path;
  const info = state.pathTargets[path] || {};
  if(info.target) presetTarget(info.target);
  if(info.preferred_slice) selectFirstTunnelBySlice(info.preferred_slice);
}
window.selectPath = selectPath;

function fmtMs(v){ return v == null ? "-" : `${Number(v).toFixed(2)} ms`; }
function avg(arr){ return arr.length ? arr.reduce((a,b)=>a+b,0)/arr.length : null; }
function jitter(arr){
  if(arr.length < 2) return null;
  const diffs = [];
  for(let i=1;i<arr.length;i++) diffs.push(Math.abs(arr[i]-arr[i-1]));
  return avg(diffs);
}
function cellKey(x,y){ return `${x},${y}`; }
function now(){ return new Date().toLocaleTimeString(); }

function renderArena(){
  const arena = $("arena");
  arena.style.gridTemplateColumns = `repeat(${state.width}, 1fr)`;
  arena.innerHTML = "";
  for(let y=0; y<state.height; y++){
    for(let x=0; x<state.width; x++){
      const key = cellKey(x,y);
      const div = document.createElement("div");
      div.className = "cell floor";
      if(x === 0 && y === 0) div.classList.add("start");
      if(state.trail.has(key)) div.classList.add("trail");
      if(state.danger.has(key)) div.classList.add("danger");
      if(state.obstacles.has(key)) div.className = "cell obstacle";
      if(x === state.goal.x && y === state.goal.y) div.className = "cell goal";
      if(x === state.robot.x && y === state.robot.y){
        div.className = "cell robot";
        div.innerHTML = `<span class="bot">🤖</span>`;
      }
      arena.appendChild(div);
    }
  }
}

function setGameState(kind, text){
  const el = $("gameState");
  el.className = `pill ${kind || "idle"}`;
  el.textContent = text || "idle";
}

function updateMetrics(){
  $("score").textContent = state.score;
  $("lastRtt").textContent = state.rtts.length ? fmtMs(state.rtts[state.rtts.length-1]) : "-";
  $("avgRtt").textContent = fmtMs(avg(state.rtts));
  $("jitter").textContent = fmtMs(jitter(state.rtts));
  $("loss").textContent = state.commands ? `${((state.losses/state.commands)*100).toFixed(1)}%` : "0%";
  $("miss").textContent = state.misses;
  $("deadlinePill").textContent = `deadline ${Number($("deadlineInput").value || 30)} ms`;
}

function renderEvents(){
  const box = $("events");
  box.classList.toggle("empty", state.events.length === 0);
  if(!state.events.length){
    box.textContent = "No command yet.";
    return;
  }
  box.innerHTML = "";
  const header = document.createElement("div");
  header.className = "event header";
  header.innerHTML = `<span>Time</span><span>Cmd</span><span>Network result</span><span>RTT</span><span>Score</span>`;
  box.appendChild(header);
  for(const ev of state.events.slice(0,100)){
    const row = document.createElement("div");
    row.className = `event ${ev.status}`;
    const values = [ev.time, ev.command, ev.message, ev.rtt, ev.score];
    values.forEach(value => {
      const span = document.createElement("span");
      span.textContent = value;
      row.appendChild(span);
    });
    box.appendChild(row);
  }
}

function addEvent(status, command, message, rtt){
  state.events.unshift({
    status,
    command,
    message,
    rtt: rtt == null ? "-" : fmtMs(rtt),
    score: state.score,
    time: now(),
  });
  renderEvents();
}

function nextPosition(command){
  let {x,y} = state.robot;
  if(command === "UP") y -= 1;
  if(command === "DOWN") y += 1;
  if(command === "LEFT") x -= 1;
  if(command === "RIGHT") x += 1;
  if(command === "STOP") return {x,y, stop:true};
  x = Math.max(0, Math.min(state.width-1, x));
  y = Math.max(0, Math.min(state.height-1, y));
  if(state.obstacles.has(cellKey(x,y))) return {...state.robot, blocked: true};
  return {x,y};
}

function shakeArena(){
  const arena = $("arena");
  arena.classList.remove("shake");
  void arena.offsetWidth;
  arena.classList.add("shake");
}

function moveRobot(command, quality){
  if(command === "STOP"){
    state.score += quality === "excellent" ? 1 : 0;
    return;
  }
  const pos = nextPosition(command);
  if(pos.blocked){
    state.score = Math.max(0, state.score - 2);
    addEvent("late", command, "Obstacle blocked the robot. Try another route.", null);
    shakeArena();
    return;
  }
  state.trail.add(cellKey(state.robot.x, state.robot.y));
  state.robot.x = pos.x;
  state.robot.y = pos.y;
  const isDanger = state.danger.has(cellKey(pos.x,pos.y));
  state.score += quality === "excellent" ? 3 : 1;
  if(isDanger){
    state.score = Math.max(0, state.score - 1);
    addEvent("late", "ZONE", "Robot entered a deadline-risk zone. Keep RTT low.", null);
  }
  if(state.robot.x === state.goal.x && state.robot.y === state.goal.y){
    state.reached += 1;
    state.score += 25;
    addEvent("good", "FINISH", `Mission completed ${state.reached} time(s). Robot returned to start.`, null);
    state.robot = {x:0,y:0};
    state.trail.clear();
  }
  renderArena();
}

function selectedTunnel(){
  const select = $("sourceSelect");
  return state.tunnels.find(t => t.device_id === state.selectedDeviceId && t.ip === select.value) || null;
}

function updateSliceCard(){
  const t = selectedTunnel();
  const agent = selectedAgent();
  $("selectedDeviceLabel").textContent = agent ? (agent.hostname || agent.device_id) : "-";
  if(!t){
    $("sliceName").textContent = "-";
    $("dnnName").textContent = "-";
    $("ifaceName").textContent = "-";
    $("sourceIpLabel").textContent = "-";
    $("sliceCard").className = "slice-card";
    return;
  }
  $("sliceName").textContent = t.label;
  $("dnnName").textContent = t.dnn;
  $("ifaceName").textContent = t.iface;
  $("sourceIpLabel").textContent = t.ip;
  const card = $("sliceCard");
  const cls = t.slice === "urllc" ? "urllc" : (t.slice === "mec-icn" ? "mec" : (t.slice === "mmtc" ? "mmtc" : "embb"));
  card.className = `slice-card ${cls}`;
}

function renderBrowserHint(){
  const matched = state.client.matched_device_ids || [];
  const remote = state.client.remote_ip || "unknown";
  const hint = $("browserHint");
  if(matched.length){
    const names = matched.map(id => {
      const agent = state.agents.find(item => item.device_id === id);
      return agent ? (agent.hostname || id) : id;
    });
    hint.className = "browser-hint matched";
    hint.textContent = `This browser (${remote}) matches registered device: ${names.join(", ")}`;
  }else{
    hint.className = "browser-hint";
    hint.textContent = `This browser is seen as ${remote}. Exact auto-match becomes available when the laptop agent reports this LAN IP.`;
  }
}

function tunnelBadgeClass(slice){
  if(slice === "urllc") return "urllc";
  if(slice === "mec-icn") return "mec";
  if(slice === "mmtc") return "mmtc";
  return "embb";
}

function renderDeviceCards(){
  const grid = $("deviceGrid");
  grid.innerHTML = "";
  grid.classList.toggle("empty", state.agents.length === 0);
  if(!state.agents.length){
    grid.textContent = "No UE agent has registered yet.";
    return;
  }

  for(const agent of state.agents){
    const card = document.createElement("button");
    card.type = "button";
    card.className = `device-card ${agent.online ? "online" : "offline"} ${agent.device_id === state.selectedDeviceId ? "selected" : ""}`;
    card.addEventListener("click", () => selectDevice(agent.device_id, true));

    const top = document.createElement("div");
    top.className = "device-card-top";

    const identity = document.createElement("div");
    const host = document.createElement("strong");
    host.textContent = agent.hostname || agent.device_id;
    const id = document.createElement("small");
    id.textContent = agent.device_id;
    identity.append(host, id);

    const status = document.createElement("div");
    status.className = `device-status ${agent.online ? "online" : "offline"}`;
    status.textContent = agent.online ? "● Online" : "○ Offline";
    top.append(identity, status);
    card.appendChild(top);

    const sub = document.createElement("div");
    sub.className = "device-substatus";
    sub.textContent = agent.five_g_connected
      ? `5G connected • ${agent.tunnel_count} tunnel(s) • ${ageLabel(agent.age_seconds)}`
      : `${agent.online ? "Agent online • 5G disconnected" : "Agent stale"} • ${ageLabel(agent.age_seconds)}`;
    card.appendChild(sub);

    const tunnelList = document.createElement("div");
    tunnelList.className = "device-tunnels";
    if(agent.tunnels && agent.tunnels.length){
      for(const tunnel of agent.tunnels){
        const badge = document.createElement("span");
        badge.className = `tunnel-badge ${tunnelBadgeClass(tunnel.slice)}`;
        badge.textContent = `${tunnel.label} · ${tunnel.ip} · ${tunnel.iface}`;
        tunnelList.appendChild(badge);
      }
    }else{
      const none = document.createElement("span");
      none.className = "no-tunnel";
      none.textContent = "No active uesimtun";
      tunnelList.appendChild(none);
    }
    card.appendChild(tunnelList);

    grid.appendChild(card);
  }
}

function chooseAutomaticDevice(previousDevice){
  const activeIds = new Set(state.agents.filter(agent => agent.online).map(agent => agent.device_id));
  const matched = (state.client.matched_device_ids || []).find(id => activeIds.has(id));
  if(matched) return matched;
  if(previousDevice && activeIds.has(previousDevice)) return previousDevice;

  const connected = state.agents.filter(agent => agent.online && agent.five_g_connected);
  if(connected.length === 1) return connected[0].device_id;

  const online = state.agents.filter(agent => agent.online);
  return online.length ? online[0].device_id : "";
}

function renderDeviceSelect(){
  const select = $("deviceSelect");
  const previous = state.selectedDeviceId;
  select.innerHTML = "";

  const online = state.agents.filter(agent => agent.online);
  if(!online.length){
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No online device";
    select.appendChild(opt);
    state.selectedDeviceId = "";
    return;
  }

  for(const agent of online){
    const opt = document.createElement("option");
    opt.value = agent.device_id;
    opt.textContent = `${agent.hostname || agent.device_id} — ${agent.five_g_connected ? `${agent.tunnel_count} 5G tunnel(s)` : "agent online, no UE tunnel"}`;
    select.appendChild(opt);
  }

  state.selectedDeviceId = chooseAutomaticDevice(previous);
  if(state.selectedDeviceId) select.value = state.selectedDeviceId;
}

function renderTunnelSelect(preferredSourceIp=""){
  const select = $("sourceSelect");
  const tunnels = tunnelsForSelectedDevice();
  select.innerHTML = "";

  if(!state.selectedDeviceId){
    $("tunnelStatus").className = "status bad";
    $("tunnelStatus").textContent = "No online UE agent selected.";
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No tunnel detected";
    select.appendChild(opt);
    updateSliceCard();
    return;
  }

  const agent = selectedAgent();
  if(!tunnels.length){
    $("tunnelStatus").className = "status bad";
    $("tunnelStatus").textContent = `${agent ? (agent.hostname || agent.device_id) : "Selected device"} is online, but no active 5G UE tunnel was reported.`;
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "Agent online — no uesimtun detected";
    select.appendChild(opt);
    updateSliceCard();
    return;
  }

  const counts = {};
  for(const tunnel of tunnels) counts[tunnel.label] = (counts[tunnel.label] || 0) + 1;
  $("tunnelStatus").className = "status ok";
  $("tunnelStatus").textContent = `${agent ? (agent.hostname || agent.device_id) : state.selectedDeviceId}: ${tunnels.length} active tunnel(s) — ${Object.entries(counts).map(([label,count]) => `${count} ${label}`).join(", ")}.`;

  for(const t of tunnels){
    const opt = document.createElement("option");
    opt.value = t.ip;
    opt.dataset.slice = t.slice;
    opt.dataset.dnn = t.dnn;
    const imsi = t.imsi && t.imsi !== "unknown" ? `${t.imsi} — ` : "";
    opt.textContent = `${imsi}${t.iface} — ${t.ip} — ${t.label} — ${t.dnn}`;
    select.appendChild(opt);
  }

  if(preferredSourceIp && tunnels.some(t => t.ip === preferredSourceIp)){
    select.value = preferredSourceIp;
  }else{
    const preferredSlice = (state.pathTargets[state.selectedPath] || {}).preferred_slice;
    const preferred = tunnels.find(t => t.slice === preferredSlice);
    if(preferred) select.value = preferred.ip;
  }
  updateSliceCard();
}

function selectDevice(deviceId, userInitiated=false){
  const previousSource = selectedTunnel()?.ip || "";
  state.selectedDeviceId = deviceId;
  $("deviceSelect").value = deviceId;
  renderTunnelSelect(previousSource);
  renderDeviceCards();
  if(userInitiated){
    const preferredSlice = (state.pathTargets[state.selectedPath] || {}).preferred_slice;
    if(preferredSlice) selectFirstTunnelBySlice(preferredSlice);
  }
}

async function fetchJson(url){
  const response = await fetch(url, {cache:"no-store"});
  if(!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response.json();
}

async function refreshTopology(){
  const previousDevice = state.selectedDeviceId;
  const previousSource = selectedTunnel()?.ip || $("sourceSelect").value || "";

  try{
    const [agentsData, tunnelsData, clientData] = await Promise.all([
      fetchJson("/api/agents"),
      fetchJson("/api/tunnels"),
      fetchJson("/api/client"),
    ]);

    state.agents = agentsData.agents || [];
    state.tunnels = tunnelsData.tunnels || [];
    state.pathTargets = tunnelsData.path_targets || state.pathTargets;
    state.client = clientData || state.client;

    const summary = agentsData.summary || {};
    $("knownDeviceCount").textContent = summary.known || 0;
    $("onlineDeviceCount").textContent = summary.online || 0;
    $("fiveGDeviceCount").textContent = summary.five_g_connected || 0;
    $("heroOnline").textContent = summary.online || 0;
    $("heroTunnels").textContent = `${summary.active_tunnels || 0} active UE tunnel(s)`;

    renderBrowserHint();
    renderDeviceSelect();

    if(previousDevice && state.agents.some(agent => agent.device_id === previousDevice && agent.online)){
      state.selectedDeviceId = previousDevice;
      $("deviceSelect").value = previousDevice;
    }

    renderTunnelSelect(previousSource);
    renderDeviceCards();
  }catch(err){
    $("tunnelStatus").className = "status bad";
    $("tunnelStatus").textContent = `Controller refresh failed: ${err}`;
  }
}

async function sendCommand(command){
  if(state.busy) return;
  const sourceIp = $("sourceSelect").value;
  if(!sourceIp){ addEvent("lost", command, "No source tunnel selected.", null); return; }

  state.busy = true;
  setGameState("idle", "sending");

  const tunnel = selectedTunnel();
  const payload = {
    source_ip: sourceIp,
    device_id: tunnel?.device_id || state.selectedDeviceId || "",
    target: $("targetInput").value.trim() || "172.16.46.1",
    payload_size: Number($("payloadInput").value || 32),
    deadline_ms: Number($("deadlineInput").value || 30),
    robot_command: command,
  };

  try{
    const res = await fetch("/api/command", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    state.commands += 1;

    if(data.success){
      state.rtts.push(Number(data.rtt_ms));
      if(state.rtts.length > 200) state.rtts.shift();
      if(data.deadline_miss){
        state.misses += 1;
        state.score = Math.max(0, state.score - 1);
        setGameState("late", "late ACK");
        addEvent("late", command, `ACK late from ${data.target} via ${data.device_id}. Robot moved with penalty.`, data.rtt_ms);
        moveRobot(command, "late");
      }else{
        setGameState("good", "ACK OK");
        addEvent("good", command, `ACK OK from ${data.target} via ${data.device_id}. Move accepted.`, data.rtt_ms);
        moveRobot(command, "excellent");
      }
    }else{
      state.losses += 1;
      state.misses += 1;
      state.score = Math.max(0, state.score - 3);
      setGameState("lost", data.status || "lost");
      addEvent("lost", command, data.error || `No ACK from ${payload.target}. Robot did not move.`, null);
      shakeArena();
    }
    updateMetrics();
  }catch(err){
    state.commands += 1;
    state.losses += 1;
    state.misses += 1;
    setGameState("lost", "error");
    addEvent("lost", command, String(err), null);
    updateMetrics();
    shakeArena();
  }finally{
    state.busy = false;
  }
}

function resetGame(){
  state.robot = {x:0,y:0};
  state.trail.clear();
  state.score = 0;
  state.commands = 0;
  state.losses = 0;
  state.misses = 0;
  state.rtts = [];
  state.reached = 0;
  setGameState("idle", "idle");
  updateMetrics();
  renderArena();
}

async function autoMission(){
  if(state.autoRunning) return;
  state.autoRunning = true;
  const plan = [
    "RIGHT","RIGHT","DOWN","DOWN","RIGHT","RIGHT","UP","UP","RIGHT","RIGHT",
    "DOWN","DOWN","RIGHT","RIGHT","RIGHT","DOWN","DOWN","RIGHT","RIGHT","RIGHT",
    "UP","UP","RIGHT","RIGHT","DOWN","DOWN","RIGHT"
  ];
  for(const cmd of plan){
    if(!state.autoRunning) break;
    await sendCommand(cmd);
    await new Promise(r => setTimeout(r, 120));
  }
  state.autoRunning = false;
}

async function latencyBurst(){
  for(let i=0;i<50;i++){
    await sendCommand(i % 5 === 0 ? "STOP" : "RIGHT");
    await new Promise(r => setTimeout(r, 100));
  }
}

function bindControls(){
  document.querySelectorAll("[data-cmd]").forEach(btn => btn.addEventListener("click", () => sendCommand(btn.dataset.cmd)));
  $("refreshBtn").addEventListener("click", refreshTopology);
  $("resetGameBtn").addEventListener("click", resetGame);
  $("autoBtn").addEventListener("click", autoMission);
  $("burstBtn").addEventListener("click", latencyBurst);
  $("clearLogBtn").addEventListener("click", () => { state.events = []; renderEvents(); });
  $("deviceSelect").addEventListener("change", (event) => selectDevice(event.target.value, true));
  $("sourceSelect").addEventListener("change", updateSliceCard);
  $("deadlineInput").addEventListener("input", updateMetrics);
  document.addEventListener("keydown", (e) => {
    const tag = (e.target.tagName || "").toLowerCase();
    if(tag === "input" || tag === "select") return;
    const map = {
      ArrowUp:"UP", ArrowDown:"DOWN", ArrowLeft:"LEFT", ArrowRight:"RIGHT",
      w:"UP", s:"DOWN", a:"LEFT", d:"RIGHT", " ":"STOP",
    };
    const cmd = map[e.key];
    if(cmd){ e.preventDefault(); sendCommand(cmd); }
  });
}

async function init(){
  renderArena();
  renderEvents();
  updateMetrics();
  bindControls();
  await refreshTopology();
  setInterval(refreshTopology, 2000);
}

init();
