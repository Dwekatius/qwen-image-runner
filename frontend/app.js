/* Qwen Image Runner — frontend logic (vanilla ES module, no build step) */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

const S = {
  csrf: "",
  meta: null,
  engine: { state: "stopped", progress: {}, fake: false },
  queueDepth: 0,
  gpu: null,
  view: "chat",
  active: null,          // { id, kind, status, progress, startedAt }
  editRefs: [],          // { kind: 'image', id } | { kind: 'file', file, url }
  shown: null,           // currently displayed image record (generate stage)
  editResult: null,      // last edit result image record
  gallery: [],
  chat: [],              // chat messages from the server
  chats: [],             // all conversations
  chatId: null,          // active conversation id
  lastChatImage: null,   // last assistant image (edit context)
  chatForce: null,       // 'generate' | 'edit' | null (=auto)
  pendingDeleteChat: null,
  settings: null,
  assistant: {},
  profiles: [],
  profileActive: "auto",
  profileBase: null,      // saved profile the current panel values were derived from
  profileAssistantReady: false,
  settingsCollapsed: false,
  suppressManualEdit: false,
  manualEditTimer: null,
  profileConfirmTimer: null,
  samplers: ["euler"],
  backends: [],
  backendCurrent: null,
  elapsedTimer: null,
  setupReady: false,
};

const WINDOW_ID = crypto.randomUUID();

/* chat message ids already shown in this window; used so the entrance animation
   only plays for newly inserted messages, not on every list re-render */
const seenChatMessageIds = new Set();

/* ------------------------------------------------------------ helpers */
async function api(path, opts = {}, retried = false) {
  const headers = Object.assign({}, opts.headers || {});
  if (opts.method && opts.method !== "GET") headers["X-CSRF"] = S.csrf;
  let body = opts.body;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  }
  const r = await fetch(path, { ...opts, headers, body });
  if (!r.ok) {
    let detail = r.statusText;
    try { const d = await r.json(); detail = d.detail || d.error || detail; } catch { /* ignore */ }
    // the app restarted and rotated the token: pick up the fresh one and retry once
    if (r.status === 403 && /csrf/i.test(String(detail)) && !retried) {
      try {
        const meta = await fetch("/api/meta").then((x) => x.json());
        if (meta && meta.csrf) {
          S.csrf = meta.csrf;
          return api(path, opts, true);
        }
      } catch { /* ignore */ }
    }
    throw new Error(detail);
  }
  return r.json();
}

function lifecycle(path, beacon = false) {
  const payload = JSON.stringify({ id: WINDOW_ID, token: S.csrf });
  if (beacon) {
    navigator.sendBeacon(path, new Blob([payload], { type: "application/json" }));
    return;
  }
  fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF": S.csrf },
    body: payload,
    keepalive: true,
  }).catch(() => {});
}

function toast(text, kind = "", ms = 4200) {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = text;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), ms);
}

function fmtBytes(n) {
  if (!n) return "—";
  const gb = n / 1e9;
  return gb >= 1 ? `${gb.toFixed(2)} GB` : `${(n / 1e6).toFixed(0)} MB`;
}

function fmtDuration(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const m = Math.floor(sec / 60), s = sec % 60;
  return m ? `${m}:${String(s).padStart(2, "0")}` : `${s}s`;
}

function estimateMinutes(w, h, steps) {
  const mp = (w * h) / 1_000_000;
  const base = 1.7 * Math.pow(mp / 1.05, 1.35);
  return Math.max(0.2, base * (steps / 40));
}

/* ------------------------------------------------------------ engine chip */
function renderEngine() {
  const chip = $("#engine-chip"), label = $("#engine-label"), dot = $("#engine-dot");
  const st = S.engine.state || "stopped";
  chip.className = "chip " + ({ ready: "ok", busy: "busy", starting: "load", failed: "fail" }[st] || "");
  const names = { ready: "Ready", busy: "Generating", starting: "Loading…", stopped: "Stopped", failed: "Failed" };
  label.textContent = `Engine: ${names[st] || st}`;
  if (st === "failed" && S.engine.error) label.title = S.engine.error;

  const q = $("#queue-chip");
  if (S.queueDepth > 1) { q.classList.remove("hidden"); q.textContent = `Queue ${S.queueDepth}`; }
  else q.classList.add("hidden");

  const info = $("#engine-info");
  const p = S.engine.progress || {};
  const bits = [];
  bits.push(`<b>${names[st] || st}</b>`);
  if (S.engine.backend_label) bits.push(S.engine.backend_label.split(" (")[0]);
  if (S.engine.fake) bits.push("mock mode");
  if (p.phase === "sampling" && p.step) bits.push(`${p.step}/${p.total} @ ${p.rate?.toFixed?.(2)} s/it`);
  if (st === "busy" && S.active?.startedAt) bits.push(`elapsed ${fmtDuration((Date.now() - S.active.startedAt) / 1000)}`);
  let extra = "";
  if (S.engine.backend === "cpu" && st !== "failed") {
    extra = '<br><span style="color:var(--warn)">CPU mode: expect tens of minutes per image. Use 1024×1024 or smaller, fewer steps, and consider a smaller model quant.</span>';
  }
  info.innerHTML = bits.join(" · ") + extra;
}

function renderStatusChips() {
  const chip = $("#vram-chip");
  if (S.gpu) chip.textContent = `VRAM ${(S.gpu.used_mib / 1024).toFixed(1)} / ${((S.gpu.used_mib + S.gpu.free_mib) / 1024).toFixed(1)} GB · GPU ${S.gpu.util}%`;
  else chip.textContent = "VRAM —";
}

/* ------------------------------------------------------------ progress */
function progressUI(kind) {
  const wrap = kind === "edit" ? $("#edit-progress") : $("#progress-wrap");
  const fill = kind === "edit" ? $("#edit-progress-fill") : $("#progress-fill");
  const label = kind === "edit" ? $("#edit-progress-label") : $("#progress-label");
  const rateEl = $("#progress-rate");
  const elapsedEl = kind === "edit" ? $("#edit-progress-elapsed") : $("#progress-elapsed");
  return { wrap, fill, label, rateEl, elapsedEl };
}

function renderProgress(kind) {
  const ui = progressUI(kind);
  const active = S.active && S.active.kind === kind;
  ui.wrap.classList.toggle("hidden", !active);
  if (!active) return;
  const p = S.active.progress || {};
  let pct = null, label = S.active.status;
  if (p.phase === "sampling" && p.step && p.total) {
    pct = (p.step / p.total) * 100;
    label = `Step ${p.step} / ${p.total}`;
    if (ui.rateEl) ui.rateEl.textContent = `${Number(p.rate || 0).toFixed(2)} ${p.unit || "s/it"}`;
  } else if (p.phase === "decoding") { label = "Decoding image…"; }
  else if (p.phase === "saving") { label = "Saving…"; }
  else if (p.phase === "rendering") { label = "Rendering…"; }
  else if (S.active.status === "queued") { label = "Queued…"; }
  else if (S.active?.status === "running") label = "Rendering…";
  ui.label.textContent = label;
  if (pct === null) {
    ui.fill.classList.add("indeterminate");
    ui.fill.style.width = "";
  } else {
    ui.fill.classList.remove("indeterminate");
    ui.fill.style.width = pct.toFixed(1) + "%";
  }
  if (ui.elapsedEl && S.active.startedAt) {
    ui.elapsedEl.textContent = `elapsed ${fmtDuration((Date.now() - S.active.startedAt) / 1000)}`;
  }
}

function startElapsedTimer() {
  if (S.elapsedTimer) clearInterval(S.elapsedTimer);
  S.elapsedTimer = setInterval(() => {
    if (S.active) { renderProgress(S.active.kind); renderEngine(); }
    if (S.active && S.active.kind === "chat") updateChatProgress();
  }, 1000);
}

function setActive(job) {
  S.active = { ...job, startedAt: job.startedAt || Date.now() };
  renderProgress(job.kind);
  startElapsedTimer();
}

function clearActive() {
  S.active = null;
  renderProgress("generate");
  renderProgress("edit");
  if (S.elapsedTimer) { clearInterval(S.elapsedTimer); S.elapsedTimer = null; }
  renderEngine();
}

/* ------------------------------------------------------------ image display */
function showImage(record, target = "generate") {
  const transparent = record?.params?.transparent_output;
  if (target === "generate") {
    S.shown = record;
    $("#gen-placeholder").classList.toggle("hidden", !!record);
    const img = $("#gen-image");
    img.classList.toggle("hidden", !record);
    $("#gen-actions").classList.toggle("hidden", !record);
    if (record) {
      img.src = `/api/images/${record.id}/file`;
      const stage = $("#gen-stage");
      stage.classList.toggle("checker", !!transparent);
      const badge = $("#stage-badge");
      badge.classList.toggle("hidden", !transparent);
      badge.textContent = transparent ? "transparent PNG" : "PNG";
    }
    renderMeta(record);
  } else {
    S.editResult = record;
    if (record) {
      const after = $("#edit-after");
      after.src = `/api/images/${record.id}/file`;
      $("#edit-compare-placeholder").classList.add("hidden");
      $("#compare-slider").classList.remove("hidden");
      const badge = $("#edit-badge");
      badge.classList.remove("hidden");
      badge.textContent = record.params?.transparent_output ? "transparent PNG" : "edited";
      updateCompare();
    }
  }
}

function renderMeta(record) {
  const el = $("#gen-meta");
  if (!record) { el.classList.add("hidden"); return; }
  el.classList.remove("hidden");
  const p = record.params || {};
  const chips = [
    `${record.width}×${record.height}`,
    p.mode === "edit" ? "edit" : "generate",
    `${p.steps ?? "?"} steps`,
    `CFG ${p.cfg ?? "?"}`,
    p.sampler || "euler",
    `seed ${record.seed ?? "?"}`,
    p.transparent_output ? "alpha" : null,
  ].filter(Boolean);
  const dt = record.created ? new Date(record.created * 1000).toLocaleTimeString() : "";
  el.innerHTML = chips.map((c) => `<span class="m-chip">${c}</span>`).join("") +
    (dt ? `<span class="m-chip">${dt}</span>` : "");
}

function updateCompare() {
  const slider = $("#compare-slider");
  if (slider.classList.contains("hidden")) return;
  $("#compare-wrap").style.width = slider.value + "%";
}

/* ------------------------------------------------------------ history & gallery */
function historyItem(rec) {
  const div = document.createElement("div");
  div.className = "history-item";
  div.innerHTML = `
    <img src="/api/images/${rec.id}/thumb" alt="">
    <div class="hi-meta">
      <div class="hi-prompt">${escapeHtml(rec.prompt || "(no prompt)")}</div>
      <div class="hi-sub">${rec.width}×${rec.height} · seed ${rec.seed ?? "?"}</div>
    </div>`;
  div.onclick = () => { switchView("generate"); showImage(rec); };
  return div;
}

function renderHistory() {
  const el = $("#history");
  el.innerHTML = "";
  if (!S.gallery.length) { el.innerHTML = `<div class="empty small">No images yet</div>`; return; }
  S.gallery.slice(0, 30).forEach((rec) => el.appendChild(historyItem(rec)));
}

function renderGallery() {
  const grid = $("#gallery-grid");
  const filter = $("#filter-kind").value;
  const items = S.gallery.filter((r) => !filter || (r.params?.mode || "generate") === filter);
  grid.innerHTML = "";
  $("#gallery-empty").classList.toggle("hidden", items.length > 0);
  items.forEach((rec) => {
    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <img class="thumb" src="/api/images/${rec.id}/thumb" alt="">
      <div class="card-body">
        <div class="card-prompt">${escapeHtml(rec.prompt || "(no prompt)")}</div>
        <div class="small muted">${rec.width}×${rec.height} · seed ${rec.seed ?? "?"} · ${rec.params?.steps ?? "?"} steps</div>
        <div class="card-actions">
          <button class="ghost" data-act="use">Use as input</button>
          <button class="ghost" data-act="reuse">Reuse settings</button>
          <button class="ghost" data-act="saveas">Save as…</button>
          <button class="ghost" data-act="delete">Delete</button>
        </div>
      </div>`;
    card.querySelector('[data-act="use"]').onclick = () => { addRefFromImage(rec); switchView("edit"); };
    card.querySelector('[data-act="reuse"]').onclick = () => { applySettings(rec.params || {}); toast("Settings applied", "ok"); };
    card.querySelector('[data-act="saveas"]').onclick = (e) => saveAs(rec.id, e.target);
    card.querySelector('[data-act="delete"]').onclick = async () => {
      if (!confirm("Delete this image?")) return;
      try {
        await api(`/api/images/${rec.id}`, { method: "DELETE" });
        S.gallery = S.gallery.filter((r) => r.id !== rec.id);
        renderGallery(); renderHistory();
        if (S.shown?.id === rec.id) showImage(null);
        toast("Image deleted", "ok");
      } catch (e) { toast("Delete failed: " + e.message, "error"); }
    };
    grid.appendChild(card);
  });
}

const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ------------------------------------------------------------ edit refs */
function renderRefs() {
  const strip = $("#refs-strip");
  strip.innerHTML = "";
  S.editRefs.forEach((ref, i) => {
    const div = document.createElement("div");
    div.className = "ref-thumb";
    const url = ref.kind === "image" ? `/api/images/${ref.id}/thumb` : ref.url;
    div.innerHTML = `<img src="${url}" alt=""><button title="Remove">✕</button>`;
    div.querySelector("button").onclick = () => { S.editRefs.splice(i, 1); renderRefs(); };
    strip.appendChild(div);
  });
  // show the first reference as the before-image immediately
  const ph = $("#edit-compare-placeholder");
  const before = $("#edit-before");
  if (S.editRefs.length) {
    ph.classList.add("hidden");
    const first = S.editRefs[0];
    before.src = first.kind === "image" ? `/api/images/${first.id}/file` : first.url;
  } else {
    ph.classList.remove("hidden");
    before.removeAttribute("src");
  }
}

function addRefFromImage(rec) {
  if (S.editRefs.length >= 10) { toast("Maximum 10 reference images", "error"); return; }
  if (S.editRefs.some((r) => r.kind === "image" && r.id === rec.id)) return;
  S.editRefs.push({ kind: "image", id: rec.id });
  renderRefs();
}

/* ------------------------------------------------------------ views */
function switchView(view) {
  S.view = view;
  $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $$("#center .view").forEach((v) => v.classList.toggle("hidden", v.id !== `view-${view}`));
  const historySection = $("#history-section");
  if (historySection) historySection.classList.toggle("hidden", view === "chat");
  const chatsSection = $("#chats-section");
  if (chatsSection) chatsSection.classList.toggle("hidden", view !== "chat");
  if (view === "gallery") renderGallery();
  if (view === "chat") { renderChat(); updateChatContext(); }
  if (view === "guide") loadGuide();
}

/* ------------------------------------------------------------ generate */
async function generate() {
  const prompt = $("#prompt").value.trim();
  if (!prompt) { toast("Write a prompt first", "error"); return; }
  if (!requireReady()) return;
  const body = collectParams();
  body.prompt = prompt;
  body.negative = $("#negative-wrap").classList.contains("hidden") ? "" : $("#negative").value;
  try {
    const res = await api("/api/generate", { method: "POST", json: body });
    setActive({ id: res.jobs[0], kind: "generate", status: "queued", progress: {} });
    renderEngine();
  } catch (e) { toast("Generate failed: " + e.message, "error"); }
}

function collectParams() {
  return {
    width: Number($("#width").value) || 1024,
    height: Number($("#height").value) || 1024,
    steps: Number($("#steps").value) || 40,
    cfg: Number($("#cfg").value) || 6,
    sampler: $("#sampler").value,
    seed: Number($("#seed").value),
    batch: Number($("#batch").value),
    transparent: $("#btn-transparent").classList.contains("active"),
  };
}

function applySettings(p) {
  withSuppressedEdits(() => {
    if (p.width && p.height) setSize(p.width, p.height);
    if (p.steps) { $("#steps").value = p.steps; $("#steps-val").textContent = p.steps; }
    if (p.cfg) { $("#cfg").value = p.cfg; $("#cfg-val").textContent = Number(p.cfg).toFixed(1); }
    if (p.sampler) $("#sampler").value = p.sampler;
    if (p.seed !== undefined) $("#seed").value = p.seed;
    if (p.transparent !== undefined) $("#btn-transparent").classList.toggle("active", !!p.transparent);
    updateSizeHint();
    updateChatHints();
  });
  updateSettingsSummary();
}

function setSize(w, h) {
  const preset = `${w}x${h}`;
  const select = $("#size-preset");
  if ([...select.options].some((o) => o.value === preset)) {
    select.value = preset;
    $("#custom-size").classList.add("hidden");
  } else {
    select.value = "custom";
    $("#custom-size").classList.remove("hidden");
  }
  $("#width").value = w; $("#height").value = h;
  updateSizeHint();
}

function updateSizeHint() {
  const w = Number($("#width").value) || 1024;
  const h = Number($("#height").value) || 1024;
  const steps = Number($("#steps").value) || 40;
  if (S.engine && S.engine.backend === "cpu") {
    const perStep = 128 * ((w * h) / (512 * 512));   // measured 128 s/step at 512x512
    const minutes = (perStep * steps) / 60 + 4;      // + ~4 min prompt encoding
    $("#size-hint").textContent = `CPU mode: ~${minutes.toFixed(0)} min @ ${steps} steps (measured 128 s/step at 512²)`;
  } else {
    $("#size-hint").textContent = `~${estimateMinutes(w, h, steps).toFixed(1)} min on RTX 5070 Ti @ ${steps} steps`;
  }
  updateChatHints();
  updateSettingsSummary();
}

function updateSettingsSummary() {
  const el = $("#settings-fields-summary");
  if (!el) return;
  const w = Number($("#width").value) || 1024;
  const h = Number($("#height").value) || 1024;
  const steps = Number($("#steps").value) || 40;
  const cfg = Number($("#cfg").value) || 6;
  el.textContent = `${w}×${h} · ${steps} steps · cfg ${cfg.toFixed(1)}`;
}

function setSettingsCollapsed(collapsed) {
  S.settingsCollapsed = !!collapsed;
  const head = $("#settings-fields-toggle");
  const body = $("#settings-fields");
  if (head) head.setAttribute("aria-expanded", String(!S.settingsCollapsed));
  if (body) body.classList.toggle("collapsed", S.settingsCollapsed);
}

function requireReady() {
  if (S.engine.state === "ready" || S.engine.state === "busy") return true;
  toast("Engine is not ready yet — check the engine panel", "error");
  return false;
}

/* ------------------------------------------------------------ settings profiles */
function withSuppressedEdits(fn) {
  S.suppressManualEdit = true;
  try { return fn(); } finally { S.suppressManualEdit = false; }
}

function profileById(id) {
  return (S.profiles || []).find((p) => p.id === id) || null;
}

function currentProfileDefaults() {
  const p = collectParams();
  return {
    size: `${p.width}x${p.height}`,
    steps: p.steps,
    cfg: p.cfg,
    sampler: p.sampler,
    batch: p.batch,
    transparent: p.transparent,
  };
}

function renderProfiles() {
  const sel = $("#profile-select");
  if (!sel) return;
  const active = S.profileActive || "auto";
  sel.innerHTML = [
    `<option value="auto">Auto — AI adjusts settings</option>`,
    `<option value="manual">Manual (current)</option>`,
    ...(S.profiles || []).map((p) => `<option value="${escapeHtml(p.id)}">${escapeHtml(p.name)}</option>`),
  ].join("");
  sel.value = active;
  const isSaved = !!profileById(active);
  const base = profileById(S.profileBase);
  const upd = $("#profile-update"), del = $("#profile-delete");
  if (upd) {
    upd.disabled = !base;
    upd.title = base ? `Update “${base.name}”` : "";
  }
  if (del) {
    // Reset any armed "Confirm?" state: switching profiles must not make the next click delete.
    if (S.profileConfirmTimer) clearTimeout(S.profileConfirmTimer);
    delete del.dataset.confirm;
    del.textContent = "Delete";
    del.disabled = !(base || isSaved);
  }
  const hint = $("#profile-hint");
  if (!hint) return;
  hint.classList.remove("warn");
  if (active === "auto") {
    if (S.profileAssistantReady) {
      hint.textContent = "AI picks the best settings for each prompt.";
    } else {
      hint.classList.add("warn");
      hint.textContent = "⚠ Auto needs DeepSeek prompts enabled with an API key — using the current settings until then.";
    }
  } else if (active === "manual") {
    hint.textContent = base
      ? `Edited from profile “${base.name}” — Update saves it, Save as… creates a new one.`
      : "Manual — the model will not change these settings.";
  } else {
    const p = profileById(active);
    hint.textContent = p
      ? `Profile “${p.name}” — the model will not change these settings.`
      : "Manual — the model will not change these settings.";
  }
}

function applyProfilesPayload(res) {
  if (!res) return;
  S.profiles = res.profiles || [];
  S.profileActive = res.active || "auto";
  S.profileAssistantReady = !!res.assistant_ready;
  renderProfiles();
}

async function loadProfiles() {
  try {
    applyProfilesPayload(await api("/api/profiles"));
    if (profileById(S.profileActive)) S.profileBase = S.profileActive;
    renderProfiles();
  } catch { /* keep the current state */ }
}

async function selectProfile(id) {
  if (S.manualEditTimer) clearTimeout(S.manualEditTimer);
  try {
    const res = await api("/api/profiles/active", { method: "POST", json: { id } });
    applyProfilesPayload(res);
    withSuppressedEdits(() => applyDefaults(res.effective || {}));
    S.profileBase = profileById(id) ? id : null;
    setSettingsCollapsed(id === "auto");
    renderProfiles();
    if (id === "auto" && !S.profileAssistantReady) {
      toast("⚠ Auto needs DeepSeek prompts enabled with an API key — using the current settings for now.", "error", 6500);
    }
  } catch (e) {
    toast("Profile switch failed: " + e.message, "error");
    loadProfiles();
  }
}

async function saveProfile() {
  const name = $("#profile-name").value.trim();
  if (!name) { toast("Type a profile name first", "error"); return; }
  try {
    const res = await api("/api/profiles", { method: "POST", json: { name, defaults: currentProfileDefaults() } });
    applyProfilesPayload(res);
    S.profileBase = S.profileActive;
    renderProfiles();
    $("#profile-name-row").classList.add("hidden");
    $("#profile-name").value = "";
    toast(`Profile “${name}” saved`, "ok");
  } catch (e) { toast("Save profile failed: " + e.message, "error"); }
}

async function updateProfile() {
  const target = profileById(S.profileActive) || profileById(S.profileBase);
  if (!target) return;
  try {
    await api(`/api/profiles/${encodeURIComponent(target.id)}`, {
      method: "PUT",
      json: { defaults: currentProfileDefaults() },
    });
    const res = await api("/api/profiles/active", { method: "POST", json: { id: target.id } });
    applyProfilesPayload(res);
    withSuppressedEdits(() => applyDefaults(res.effective || {}));
    S.profileBase = target.id;
    renderProfiles();
    toast(`Profile “${target.name}” updated`, "ok");
  } catch (e) { toast("Update failed: " + e.message, "error"); }
}

function deleteProfile() {
  const p = profileById(S.profileActive) || profileById(S.profileBase);
  if (!p) return;
  const btn = $("#profile-delete");
  if (!btn.dataset.confirm) {
    btn.dataset.confirm = "1";
    btn.textContent = "Confirm?";
    if (S.profileConfirmTimer) clearTimeout(S.profileConfirmTimer);
    S.profileConfirmTimer = setTimeout(() => {
      delete btn.dataset.confirm;
      btn.textContent = "Delete";
    }, 3000);
    return;
  }
  clearTimeout(S.profileConfirmTimer);
  delete btn.dataset.confirm;
  btn.textContent = "Delete";
  api(`/api/profiles/${encodeURIComponent(p.id)}`, { method: "DELETE" })
    .then((res) => {
      applyProfilesPayload(res);
      withSuppressedEdits(() => applyDefaults(res.effective || {}));
      setSettingsCollapsed((res.active || "auto") === "auto");
      toast(`Profile “${p.name}” deleted`, "ok");
    })
    .catch((e) => toast("Delete failed: " + e.message, "error"));
}

async function markManualEdit() {
  if (S.suppressManualEdit) return;
  if (S.profileActive !== "manual") {
    S.profileActive = "manual";
    renderProfiles();
    try {
      const res = await api("/api/profiles/active", { method: "POST", json: { id: "manual" } });
      S.profiles = res.profiles || S.profiles;
      S.profileActive = res.active || "manual";
      S.profileAssistantReady = !!res.assistant_ready;
    } catch (e) {
      toast("Could not mark settings as manual: " + e.message, "error");
    }
    renderProfiles();
  }
  if (S.manualEditTimer) clearTimeout(S.manualEditTimer);
  S.manualEditTimer = setTimeout(() => {
    api("/api/settings", { method: "PUT", json: { defaults: currentProfileDefaults() } }).catch(() => {});
  }, 650);
}

function assistantSettingsText(s) {
  if (!s || typeof s !== "object") return "";
  const bits = [];
  if (s.size) bits.push(String(s.size).replace("x", "×"));
  if (s.steps !== undefined && s.steps !== null) bits.push(`${s.steps} steps`);
  if (s.cfg !== undefined && s.cfg !== null) bits.push(`cfg ${Number(s.cfg).toFixed(1)}`);
  if (s.transparent === true) bits.push("transparent");
  return bits.length ? `✨ AI settings: ${bits.join(" · ")}` : "";
}

function applyAssistantSettings(s) {
  const patch = {};
  if (s.size) {
    const [w, h] = String(s.size).split("x").map(Number);
    if (w && h) { patch.width = w; patch.height = h; }
  }
  if (s.steps !== undefined && s.steps !== null) patch.steps = s.steps;
  if (s.cfg !== undefined && s.cfg !== null) patch.cfg = s.cfg;
  if (s.transparent !== undefined && s.transparent !== null) patch.transparent = s.transparent;
  if (Object.keys(patch).length) applySettings(patch);
}

/* ------------------------------------------------------------ edit */
async function submitEdit() {
  const instruction = $("#instruction").value.trim();
  if (!instruction) { toast("Describe the edit first", "error"); return; }
  if (!S.editRefs.length) { toast("Add at least one reference image", "error"); return; }
  if (!requireReady()) return;
  const fd = new FormData();
  fd.append("instruction", instruction);
  fd.append("width", $("#width").value);
  fd.append("height", $("#height").value);
  fd.append("steps", $("#steps").value);
  fd.append("cfg", $("#cfg").value);
  fd.append("sampler", $("#sampler").value);
  fd.append("seed", $("#seed").value);
  fd.append("transparent", $("#edit-transparent").checked);
  fd.append("ref_asset_ids", S.editRefs.filter((r) => r.kind === "image").map((r) => r.id).join(","));
  S.editRefs.filter((r) => r.kind === "file").forEach((r) => fd.append("files", r.file, r.file.name));
  // show first ref as "before"
  const first = S.editRefs[0];
  $("#edit-before").src = first.kind === "image" ? `/api/images/${first.id}/file` : first.url;
  try {
    const res = await api("/api/edit", { method: "POST", body: fd });
    setActive({ id: res.jobs[0], kind: "edit", status: "queued", progress: {} });
  } catch (e) { toast("Edit failed: " + e.message, "error"); }
}

/* ------------------------------------------------------------ chat */
async function stopActive() {
  try {
    const res = await api("/api/queue/stop", { method: "POST" });
    toast(res.action === "reloaded" ? "Stopped — engine reloading" : "Stopping…");
  } catch (e) { toast(e.message, "error"); }
}

async function saveAs(imageId, btn) {
  const label = btn ? btn.textContent : "";
  if (btn) { btn.disabled = true; btn.textContent = "Choose location…"; }
  try {
    const res = await api(`/api/images/${imageId}/save_as`, { method: "POST" });
    if (res.saved) toast(`Saved to ${res.path}`, "ok", 6500);
    else toast("Save cancelled", "", 2500);
  } catch (e) {
    toast("Save failed: " + e.message, "error");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = label; }
  }
}

async function loadChats() {
  try {
    const res = await api("/api/chats");
    S.chats = res.chats || [];
    renderChats();
  } catch { /* ignore */ }
}

function renderChats() {
  const el = $("#chats-list");
  if (!el) return;
  el.innerHTML = "";
  if (!S.chats.length) { el.innerHTML = `<div class="empty small">No chats yet</div>`; return; }
  for (const c of S.chats) {
    const item = document.createElement("div");
    item.className = "history-item chat-item" + (c.id === S.chatId ? " active" : "");
    const thumb = c.last_image_id
      ? `<img src="/api/images/${c.last_image_id}/thumb" alt="">`
      : `<div class="chat-icon">💬</div>`;
    const when = c.updated
      ? new Date(c.updated * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
      : "";
    item.innerHTML = `${thumb}
      <div class="hi-meta">
        <div class="hi-prompt">${escapeHtml(c.title || "Chat")}</div>
        <div class="hi-sub">${c.image_count || 0} image${(c.image_count === 1) ? "" : "s"} · ${when}</div>
      </div>`;
    item.onclick = () => { switchView("chat"); loadChat(c.id); };
    const del = document.createElement("button");
    del.className = "chat-del";
    del.type = "button";
    del.title = "Delete chat";
    del.textContent = "✕";
    del.onclick = (e) => { e.stopPropagation(); askDeleteChat(c.id); };
    item.appendChild(del);
    el.appendChild(item);
  }
}

function askDeleteChat(chatId) {
  const chat = (S.chats || []).find((c) => c.id === chatId);
  if (!chat) return;
  S.pendingDeleteChat = chat.id;
  const count = chat.image_count || 0;
  $("#delete-chat-text").textContent =
    `Delete “${chat.title || "Chat"}”? This removes ${count} image(s) it created from the gallery. ` +
    "Images you saved to your own folders are kept.";
  $("#delete-chat-modal").classList.remove("hidden");
}

async function confirmDeleteChat() {
  const chatId = S.pendingDeleteChat;
  if (!chatId) return;
  S.pendingDeleteChat = null;
  $("#delete-chat-modal").classList.add("hidden");
  try {
    const res = await api(`/api/chats/${encodeURIComponent(chatId)}`, { method: "DELETE" });
    await loadChats();
    await refreshGallery();
    if (S.chatId === chatId) {
      await loadChat();
      renderChat();
    }
    const removed = res.images_deleted ?? 0;
    toast(`Chat deleted — ${removed} image${removed === 1 ? "" : "s"} removed`, "ok");
  } catch (e) {
    toast("Delete chat failed: " + e.message, "error");
  }
}

async function loadChat(chatId) {
  try {
    const url = chatId ? `/api/chat?chat_id=${encodeURIComponent(chatId)}` : "/api/chat";
    const res = await api(url);
    S.chatId = (res.chat && res.chat.id) || null;
    S.chat = res.messages || [];
    S.lastChatImage = [...S.chat].reverse().find((m) => m.image)?.image || null;
    renderChat();
    updateChatContext();
    renderChats();
  } catch { /* ignore */ }
}

function renderChat() {
  const wrap = $("#chat-messages");
  const scroller = $("#chat-scroll");
  if (!wrap || !scroller) return;
  // keep the reader's position: only auto-scroll when they were already at the bottom
  const wasNearBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 140;
  const prevTop = scroller.scrollTop;
  wrap.innerHTML = "";
  $("#chat-empty").classList.toggle("hidden", S.chat.length > 0);
  const delBtn = $("#btn-chat-delete");
  if (delBtn) delBtn.disabled = !S.chatId;
  for (const m of S.chat) {
    const el = m.role === "user" ? chatUserEl(m) : chatAssistantEl(m);
    if (m.id && !seenChatMessageIds.has(m.id)) {
      seenChatMessageIds.add(m.id);
      el.classList.add("msg-enter");
    }
    wrap.appendChild(el);
  }
  if (seenChatMessageIds.size > 4000) seenChatMessageIds.clear();
  if (S.active && S.active.kind === "chat" && S.active.id) wrap.appendChild(progressSlot());
  if (wasNearBottom) scroller.scrollTop = scroller.scrollHeight;
  else scroller.scrollTop = Math.min(prevTop, Math.max(0, scroller.scrollHeight - scroller.clientHeight));
}

function scrollChat() {
  const el = $("#chat-scroll");
  if (el) el.scrollTop = el.scrollHeight;
}

function chatUserEl(m) {
  const el = document.createElement("div");
  el.className = "chat-msg user";
  const b = document.createElement("div");
  b.className = "chat-bubble";
  b.textContent = m.text || "";
  el.appendChild(b);
  const meta = m.meta || {};
  if (meta.assistant_prompt) {
    const note = document.createElement("div");
    note.className = "chat-note";
    note.title = meta.assistant_prompt;
    const label = meta.assistant_action === "edit" ? "edit" : "prompt";
    note.textContent = `✨ DeepSeek ${label}: ${meta.assistant_prompt.length > 160 ? meta.assistant_prompt.slice(0, 160) + "…" : meta.assistant_prompt}`;
    el.appendChild(note);
  }
  const settingsText = assistantSettingsText(meta.assistant_settings);
  if (settingsText) {
    const note = document.createElement("div");
    note.className = "chat-note";
    note.textContent = settingsText;
    el.appendChild(note);
  }
  if (meta.assistant_error) {
    const note = document.createElement("div");
    note.className = "chat-note";
    note.style.color = "var(--warn)";
    note.textContent = `Prompt assistant unavailable: ${meta.assistant_error}`;
    el.appendChild(note);
  }
  return el;
}

function chatAssistantEl(m) {
  const el = document.createElement("div");
  el.className = "chat-msg assistant";
  if (!m.image) {
    const b = document.createElement("div");
    b.className = "chat-bubble chat-note";
    b.textContent = m.text || "(no output)";
    el.appendChild(b);
    return el;
  }
  const rec = m.image;
  const p = rec.params || {};
  const card = document.createElement("div");
  card.className = "chat-card";
  card.innerHTML = `
    <img class="chat-image" src="/api/images/${rec.id}/file" alt="" loading="lazy">
    <div class="chat-card-body">
      <div class="meta">
        <span class="m-chip">${rec.width}×${rec.height}</span>
        <span class="m-chip">${p.mode === "edit" ? "edit" : "generate"}</span>
        <span class="m-chip">${p.steps ?? "?"} steps</span>
        <span class="m-chip">seed ${rec.seed ?? "?"}</span>
        ${p.transparent_output ? '<span class="m-chip">alpha</span>' : ""}
      </div>
      <div class="chat-card-actions">
        <button class="ghost" data-act="saveas">Save as…</button>
        <button class="ghost" data-act="use">Use as input</button>
        <button class="ghost" data-act="reuse">Reuse settings</button>
      </div>
    </div>`;
  card.querySelector('[data-act="saveas"]').onclick = (e) => saveAs(rec.id, e.target);
  card.querySelector('[data-act="use"]').onclick = () => { addRefFromImage(rec); switchView("edit"); };
  card.querySelector('[data-act="reuse"]').onclick = () => { applySettings(p); toast("Settings applied", "ok"); };
  el.appendChild(card);
  return el;
}

function progressSlot() {
  const el = document.createElement("div");
  el.className = "chat-msg assistant";
  el.id = "chat-progress";
  const box = document.createElement("div");
  box.className = "progress-bubble";
  el.appendChild(box);
  fillProgress(box);
  return el;
}

function fillProgress(box) {
  const p = (S.active && S.active.progress) || {};
  let label = "Queued…";
  let pct = null;
  if (p.phase === "sampling" && p.step && p.total) { label = `Step ${p.step} / ${p.total}`; pct = (p.step / p.total) * 100; }
  else if (p.phase === "decoding") label = "Decoding image…";
  else if (p.phase === "saving") label = "Saving…";
  else if (p.phase === "rendering") label = "Rendering…";
  else if (S.active?.status === "running") label = "Rendering…";
  const elapsed = S.active?.startedAt ? fmtDuration((Date.now() - S.active.startedAt) / 1000) : "";
  box.innerHTML = `
    <div class="progress-bar"><div class="progress-fill ${pct === null ? "indeterminate" : ""}" style="width:${pct ?? 0}%"></div></div>
    <div class="progress-info">
      <span>${label}</span>
      <span class="muted">${p.rate ? Number(p.rate).toFixed(2) + " s/it" : ""}</span>
      <span class="muted">${elapsed ? "elapsed " + elapsed : ""}</span>
      <span class="spacer"></span>
      <button class="ghost small" id="btn-chat-stop">Stop — reloads model</button>
    </div>`;
  const stop = box.querySelector("#btn-chat-stop");
  if (stop) stop.onclick = stopActive;
}

function updateChatProgress() {
  const slot = $("#chat-progress");
  if (!slot) { if (S.active && S.active.kind === "chat") renderChat(); return; }
  fillProgress(slot.querySelector(".progress-bubble"));
}

function updateChatContext() {
  const bar = $("#chat-context");
  if (!bar) return;
  const hasImage = !!S.lastChatImage;
  bar.classList.toggle("hidden", !hasImage);
  if (!hasImage) return;
  const mode = S.chatForce || "edit";
  $("#chat-ref-thumb").src = `/api/images/${S.lastChatImage.id}/thumb`;
  $("#chat-context-label").textContent = mode === "edit" ? "Editing the image above" : "Starting a new image";
  $("#btn-chat-mode").textContent = mode === "edit" ? "New image" : "Edit last image";
}

function updateChatHints() {
  const el = $("#chat-params-hint");
  if (!el) return;
  const p = collectParams();
  const assistant = S.assistant || {};
  const suffix = assistant.enabled ? " · ✨ DeepSeek prompts" : "";
  el.textContent = `${p.width}×${p.height} · ${p.steps} steps · ${p.sampler}${suffix}`;
}

async function newChat() {
  try {
    const res = await api("/api/chats", { method: "POST", json: {} });
    S.chatForce = null;
    await loadChats();
    await loadChat(res.chat.id);
    switchView("chat");
    $("#chat-input").focus();
    toast("New chat started — previous chats are kept", "ok", 3000);
  } catch (e) { toast(e.message, "error"); }
}

async function sendChat() {
  const input = $("#chat-input");
  const text = input.value.trim();
  if (!text) return;
  if (!requireReady()) return;
  const btn = $("#btn-chat-send");
  btn.disabled = true;
  try {
    const res = await api("/api/chat/submit", {
      method: "POST",
      json: {
        text,
        mode: S.chatForce || "auto",
        params: collectParams(),
        chat_id: S.chatId,
        auto_settings: S.profileActive === "auto",
      },
    });
    input.value = "";
    S.chatForce = null;
    if (res.assistant_settings) applyAssistantSettings(res.assistant_settings);
    if (res.job) {
      setActive({ id: res.job, kind: "chat", status: "queued", progress: {} });
    } else {
      // the assistant answered in chat - there is no image job to track
      clearActive();
    }
    await loadChats();
    await loadChat(res.chat_id || S.chatId);
    updateChatContext();
  } catch (e) {
    toast("Send failed: " + e.message, "error");
  } finally {
    btn.disabled = false;
    input.focus();
  }
}

/* ------------------------------------------------------------ prompt assistant */
async function saveAssistantSettings() {
  const status = $("#set-asst-status");
  try {
    const payload = {
      assistant: {
        enabled: $("#set-asst-enabled").checked,
        model: $("#set-asst-model").value.trim() || "deepseek-chat",
        base_url: $("#set-asst-base").value.trim() || "https://api.deepseek.com",
      },
    };
    const key = $("#set-asst-key").value.trim();
    if (key) payload.assistant.api_key = key;
    const res = await api("/api/settings", { method: "PUT", json: payload });
    S.assistant = res.assistant || {};
    syncAssistantSide();
    await loadProfiles();
    $("#set-asst-key").value = "";
    $("#set-asst-keyhint").textContent = S.assistant.api_key_set
      ? "A key is stored locally in settings.json (gitignored - never sent anywhere except your provider)."
      : "No key stored yet.";
    status.textContent = "Saved.";
    updateChatHints();
    toast("Assistant settings saved", "ok");
  } catch (e) {
    status.textContent = "Save failed: " + e.message;
  }
}

async function testAssistant() {
  const status = $("#set-asst-status");
  status.textContent = "Testing…";
  try {
    const assistant = {
      model: $("#set-asst-model").value.trim(),
      base_url: $("#set-asst-base").value.trim(),
    };
    const key = $("#set-asst-key").value.trim();
    if (key) assistant.api_key = key;
    const res = await api("/api/assistant/test", { method: "POST", json: { assistant } });
    status.textContent = res.ok
      ? `Connected to ${res.model} - replied "${res.reply}"`
      : `Failed: ${res.error}`;
  } catch (e) {
    status.textContent = "Failed: " + e.message;
  }
}

/* ------------------------------------------------------------ side panel: prompt assistant */
function syncAssistantSide(focusKey = false) {
  const toggle = $("#side-asst-enabled");
  if (!toggle) return;
  const a = S.assistant || {};
  toggle.checked = !!a.enabled;
  $("#side-asst-key-wrap").classList.toggle("hidden", !a.enabled);
  const input = $("#side-asst-key");
  input.value = "";
  input.placeholder = a.api_key_set
    ? `•••••••• saved (${a.api_key_hint}) - type to replace`
    : "sk-...";
  const status = $("#side-asst-status");
  if (a.enabled && !a.api_key_set) status.textContent = "Add your DeepSeek API key to enable prompt writing.";
  else if (a.api_key_set) status.textContent = `Key stored (${a.api_key_hint}) - ready to write prompts.`;
  else status.textContent = "";
  if (focusKey && a.enabled && !a.api_key_set) input.focus();
  updateChatHints();
}

async function setAssistantEnabledSide(enabled) {
  const toggle = $("#side-asst-enabled");
  try {
    const res = await api("/api/settings", { method: "PUT", json: { assistant: { enabled } } });
    S.assistant = res.assistant || {};
    syncAssistantSide(enabled);
    await loadProfiles();
    toast(enabled ? "DeepSeek prompts enabled" : "DeepSeek prompts disabled", "ok", 2600);
  } catch (e) {
    toggle.checked = !enabled;
    toast("Could not update the prompt assistant: " + e.message, "error");
  }
}

async function saveAssistantKeySide() {
  const input = $("#side-asst-key");
  const value = input.value.trim();
  if (!value) {
    $("#side-asst-status").textContent = "Type your DeepSeek API key first.";
    input.focus();
    return;
  }
  try {
    const res = await api("/api/settings", { method: "PUT", json: { assistant: { api_key: value } } });
    S.assistant = res.assistant || {};
    input.value = "";
    syncAssistantSide();
    await loadProfiles();
    toast("DeepSeek API key saved", "ok");
  } catch (e) {
    toast("Could not save the API key: " + e.message, "error");
  }
}

/* ------------------------------------------------------------ side panel: compute toggle */
function updateComputeToggle() {
  const gpuBtn = $("#side-device-gpu");
  const cpuBtn = $("#side-device-cpu");
  if (!gpuBtn || !cpuBtn) return;
  const cpu = S.backendCurrent === "cpu";
  gpuBtn.classList.toggle("active", !cpu);
  cpuBtn.classList.toggle("active", cpu);
  gpuBtn.setAttribute("aria-pressed", String(!cpu));
  cpuBtn.setAttribute("aria-pressed", String(cpu));
  const hint = $("#side-device-hint");
  if (!hint) return;
  if (cpu) hint.textContent = "CPU only — expect slow renders.";
  else {
    const b = (S.backends || []).find((x) => x.id === S.backendCurrent);
    hint.textContent = `GPU · ${b ? b.label : (S.backendCurrent || "GPU")}`;
  }
}

function preferGpuBackend() {
  const backends = S.backends || [];
  const installed = (id) => backends.some((b) => b.id === id && b.installed);
  if (installed("cuda")) return "cuda";
  if (installed("vulkan")) return "vulkan";
  const nonCpu = backends.filter((b) => b.id !== "cpu");
  if (nonCpu.length) return (nonCpu.find((b) => b.id === "cuda") || nonCpu[0]).id;
  return "cuda";
}

async function selectGpuDevice() {
  await selectBackend(preferGpuBackend());
  updateComputeToggle();
}

async function selectCpuDevice() {
  await selectBackend("cpu");
  updateComputeToggle();
}

/* ------------------------------------------------------------ guide */
let guideLoaded = false;

async function loadGuide(force = false) {
  if (guideLoaded && !force) return;
  try {
    const res = await api("/api/guide");
    $("#guide-content").innerHTML = renderMarkdown(res.markdown || "");
    $("#guide-sub").textContent = `${res.app} v${res.version}`;
    guideLoaded = true;
  } catch (e) {
    $("#guide-content").innerHTML = `<div class="empty">Could not load the guide (${escapeHtml(e.message)})</div>`;
  }
}

function renderMarkdown(md) {
  const esc = escapeHtml;
  const inline = (t) => esc(t)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  const out = [];
  let para = [], list = null, code = null, table = null;
  const flushPara = () => { if (para.length) { out.push(`<p>${inline(para.join(" "))}</p>`); para = []; } };
  const flushList = () => { if (list) { out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`); list = null; } };
  const flushTable = () => {
    if (table) {
      const [head, ...rows] = table;
      out.push(`<table><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>` +
        rows.map((r) => `<tr>${r.map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("") + `</tbody></table>`);
      table = null;
    }
  };
  const flushAll = () => { flushPara(); flushList(); flushTable(); };

  for (const raw of String(md).replace(/\r\n/g, "\n").split("\n")) {
    const line = raw.trimEnd();
    if (code !== null) {
      if (line.trim().startsWith("```")) { out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`); code = null; }
      else code.push(raw);
      continue;
    }
    if (line.trim().startsWith("```")) { flushAll(); code = []; continue; }
    if (!line.trim()) { flushAll(); continue; }
    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    if (h) { flushAll(); const lvl = h[1].length; out.push(`<h${lvl}>${inline(h[2])}</h${lvl}>`); continue; }
    const bq = /^>\s?(.*)$/.exec(line);
    if (bq) { flushAll(); out.push(`<blockquote>${inline(bq[1])}</blockquote>`); continue; }
    if (line.trim().startsWith("|")) {
      const cells = line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((s) => s.trim());
      if (cells.every((c) => /^:?-{2,}:?$/.test(c) || c === "")) continue;
      flushPara(); flushList();
      table = table || [];
      table.push(cells);
      continue;
    }
    const ul = /^[-*]\s+(.*)$/.exec(line);
    if (ul) { flushPara(); flushTable(); if (!list || list.tag !== "ul") { flushList(); list = { tag: "ul", items: [] }; } list.items.push(ul[1]); continue; }
    const ol = /^\d+[.)]\s+(.*)$/.exec(line);
    if (ol) { flushPara(); flushTable(); if (!list || list.tag !== "ol") { flushList(); list = { tag: "ol", items: [] }; } list.items.push(ol[1]); continue; }
    para.push(line.trim());
  }
  flushAll();
  if (code) out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`);
  return out.join("");
}

/* ------------------------------------------------------------ engine backends */
async function loadBackends() {
  try {
    const res = await api("/api/engine/backends");
    S.backends = res.backends || [];
    S.backendCurrent = res.current;
    renderBackends("#set-backends", S.backends, res.current);
    renderBackends("#setup-backends", S.backends, res.current);
    updateComputeToggle();
  } catch { /* ignore */ }
}

function renderBackends(container, backends, current) {
  const el = $(container);
  if (!el) return;
  el.innerHTML = "";
  backends.forEach((b) => {
    const item = document.createElement("div");
    item.className = "backend-item" + (b.id === current ? " current" : "");
    item.innerHTML = `
      <input type="radio" name="backend-${container.slice(1)}" ${b.id === current ? "checked" : ""}>
      <div class="bi-main">
        <div class="bi-title">${escapeHtml(b.label)}${b.installed ? "" : ' <span class="badge miss">not installed</span>'}</div>
        <div class="bi-detail">${escapeHtml(b.detail || "")}</div>
        <div class="bi-speed">≈ ${escapeHtml(b.speed || "")}</div>
      </div>
      <div class="bi-actions">
        ${b.installed ? "" : '<button class="ghost small" data-act="install">Install</button>'}
        ${b.id === current ? '<span class="badge ok">active</span>' : '<button class="ghost small" data-act="select">Use</button>'}
      </div>`;
    item.querySelector("input").onchange = () => selectBackend(b.id);
    const installBtn = item.querySelector('[data-act="install"]');
    if (installBtn) installBtn.onclick = () => installBackend(b.id, installBtn);
    const useBtn = item.querySelector('[data-act="select"]');
    if (useBtn) useBtn.onclick = () => selectBackend(b.id);
    el.appendChild(item);
  });
}

async function selectBackend(id) {
  if (id === S.backendCurrent) return;
  toast("Switching engine backend…");
  try {
    const res = await api("/api/engine/backend", { method: "POST", json: { backend: id } });
    S.backendCurrent = id;
    await loadBackends();
    pollSystem();
    updateComputeToggle();
    if (!res.installed) toast("That backend is not installed yet — click Install", "error", 6000);
  } catch (e) { toast("Switch failed: " + e.message, "error"); }
}

async function installBackend(id, btn) {
  if (btn) { btn.disabled = true; btn.textContent = "Downloading…"; }
  try {
    await api("/api/engine/install", { method: "POST", json: { backend: id } });
    toast("Downloading engine build…");
  } catch (e) {
    toast("Install failed: " + e.message, "error");
    if (btn) { btn.disabled = false; btn.textContent = "Install"; }
  }
}

/* ------------------------------------------------------------ SSE */
function connectEvents() {
  const es = new EventSource("/api/events");
  es.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    if (msg.type === "job") onJobEvent(msg);
    else if (msg.type === "image") onNewImage(msg.id);
    else if (msg.type === "engine" || msg.type === "tick") {
      if (msg.engine) S.engine = msg.engine;
      if (msg.queue_depth !== undefined) S.queueDepth = msg.queue_depth;
      renderEngine();
    } else if (msg.type === "download") updateSetupDownload(msg);
    else if (msg.type === "chat") { loadChats(); loadChat(S.chatId); }
    else if (msg.type === "notice") toast(msg.text);
  };
  es.onerror = () => { /* EventSource auto-reconnects */ };
}

async function onJobEvent(msg) {
  if (!S.active || msg.id !== S.active.id) {
    // batch: subsequent jobs start after the first completes
    if (msg.status === "running" && S.active && msg.params?.batch_index > 0) {
      // keep showing the active one
    }
    return;
  }
  S.active.status = msg.status;
  if (msg.progress) S.active.progress = msg.progress;
  renderProgress(S.active.kind);
  renderEngine();
  const wasChat = S.active.kind === "chat";
  if (wasChat && msg.status === "running") updateChatProgress();
  if (msg.status === "completed") {
    clearActive();
    toast("Done", "ok", 2200);
    if (wasChat) loadChat();
  } else if (msg.status === "failed") {
    const errText = typeof msg.error === "string" ? msg.error : (msg.error?.message || "generation failed");
    toast("Generation failed: " + errText + hintFor(errText), "error", 7000);
    clearActive();
    if (wasChat) loadChat();
  } else if (msg.status === "cancelled") {
    toast("Cancelled", "", 2500);
    clearActive();
    if (wasChat) loadChat();
  } else if (msg.status === "interrupted") {
    toast("Stopped — engine reloaded", "", 3500);
    clearActive();
    if (wasChat) loadChat();
  }
  if (S.queueDepth) S.queueDepth = Math.max(0, S.queueDepth - 1);
}

function hintFor(err) {
  const low = String(err).toLowerCase();
  if (low.includes("memory") || low.includes("oom")) return " — try a smaller size or reload the engine";
  if (low.includes("connect")) return " — is the engine running?";
  return "";
}

async function onNewImage(id) {
  await refreshGallery();
  const rec = S.gallery.find((r) => r.id === id);
  if (rec) {
    if (rec.params?.mode === "edit") showImage(rec, "edit");
    else showImage(rec, "generate");
  }
}

async function refreshGallery() {
  try {
    const res = await api("/api/gallery?limit=120");
    S.gallery = res.images;
    renderHistory();
    if (S.view === "gallery") renderGallery();
  } catch { /* ignore */ }
}

/* ------------------------------------------------------------ setup overlay */
function setupNeeded() {
  return !S.setupReady;
}

async function refreshSetup() {
  const [models, meta] = await Promise.all([api("/api/models"), api("/api/meta")]);
  S.meta = meta;
  S.csrf = meta.csrf;
  const missing = models.missing_required;
  S.setupReady = missing.length === 0 && models.license_accepted;
  $("#setup-overlay").classList.toggle("hidden", S.setupReady);
  if (S.setupReady) return;

  const rows = models.components.map((c) => `
    <div class="model-row">
      <span class="m-name">${c.name}</span>
      <span class="m-size">${fmtBytes(c.bytes)}</span>
      <span class="badge ${c.present ? "ok" : "miss"}">${c.present ? "ready" : c.optional ? "optional" : "missing"}</span>
    </div>`).join("");
  $("#setup-models").innerHTML = rows;
  $("#license-check").checked = !!models.license_accepted;
  $("#btn-download").disabled = !models.license_accepted || missing.length === 0;

  const eng = meta.engine;
  const engNames = { ready: "Ready", busy: "Generating", starting: "Loading… (first start can take ~1 min)", stopped: "Stopped", failed: "Failed — " + (eng.error || "") };
  $("#setup-engine").textContent = engNames[eng.state] || eng.state;
  $("#btn-enter-app").disabled = missing.length > 0 || !(eng.state === "ready" || eng.state === "busy");
}

async function updateSetupDownload(state) {
  const wrap = $("#setup-download-wrap");
  const active = state.active;
  wrap.classList.toggle("hidden", !active && !state.error);
  if (state.error) toast("Download failed: " + state.error, "error", 8000);
  if (!state.total_bytes) { $("#setup-download-fill").classList.add("indeterminate"); }
  else {
    $("#setup-download-fill").classList.remove("indeterminate");
    $("#setup-download-fill").style.width = ((state.done_bytes / state.total_bytes) * 100).toFixed(1) + "%";
  }
  $("#setup-download-label").textContent = state.component
    ? `${state.component} — ${fmtBytes(state.done_bytes)} / ${fmtBytes(state.total_bytes)}`
    : (active ? "Starting…" : "Idle");

  // the engine-backend picker mirrors the same download stream
  const bwrap = $("#setup-backend-progress");
  if (bwrap) {
    bwrap.classList.toggle("hidden", !active);
    const bfill = $("#setup-backend-fill");
    if (!state.total_bytes) bfill.classList.add("indeterminate");
    else {
      bfill.classList.remove("indeterminate");
      bfill.style.width = ((state.done_bytes / state.total_bytes) * 100).toFixed(1) + "%";
    }
    $("#setup-backend-label").textContent = state.component
      ? `${state.component} — ${fmtBytes(state.done_bytes)} / ${fmtBytes(state.total_bytes)}`
      : (active ? "Starting…" : "Idle");
  }

  if (!active) {
    await refreshSetup();
    await loadBackends();
    if (S.setupReady) toast("All model files ready", "ok");
  }
}

/* ------------------------------------------------------------ boot */
async function boot() {
  try {
    const meta = await api("/api/meta");
    S.meta = meta; S.csrf = meta.csrf;
    S.engine = meta.engine;
    S.settings = meta.settings;
    const ver = $("#brand-ver");
    if (ver) ver.textContent = "v" + meta.version;
    applyDefaults(meta.settings?.defaults || {});
  } catch (e) {
    toast("Cannot reach the Qwen Image Runner service", "error", 8000);
    return;
  }
  // cancel a pending quit-on-close (reload) and keep this window counted as open
  lifecycle("/api/lifecycle/ping");
  setInterval(() => lifecycle("/api/lifecycle/ping"), 4000);
  connectEvents();
  try {
    const cfg = await api("/api/settings");
    S.assistant = cfg.assistant || {};
  } catch { /* ignore */ }
  await loadProfiles();
  setSettingsCollapsed(S.profileActive === "auto");
  syncAssistantSide();
  updateChatHints();
  await refreshSetup();
  await Promise.all([refreshGallery(), loadSamplers(), pollSystem(), loadChats(), loadBackends()]);
  updateComputeToggle();
  await loadChat();
  switchView(S.view);
  renderEngine();
  startElapsedTimer();
  setInterval(pollSystem, 5000);
}

function applyDefaults(d) {
  withSuppressedEdits(() => {
    if (d.size) {
      const [w, h] = String(d.size).split("x").map(Number);
      if (w && h) setSize(w, h);
    }
    if (d.steps) { $("#steps").value = d.steps; $("#steps-val").textContent = d.steps; }
    if (d.cfg) { $("#cfg").value = d.cfg; $("#cfg-val").textContent = Number(d.cfg).toFixed(1); }
    if (d.sampler) $("#sampler").value = d.sampler;
    if (d.batch) $("#batch").value = d.batch;
    if (d.transparent !== undefined) $("#btn-transparent").classList.toggle("active", !!d.transparent);
    updateSizeHint();
    updateChatHints();
  });
  updateSettingsSummary();
}

async function loadSamplers() {
  try {
    const res = await api("/api/samplers");
    S.samplers = res.samplers;
    const sel = $("#sampler");
    sel.innerHTML = S.samplers.map((s) => `<option value="${s}">${s}</option>`).join("");
    const wanted = (S.settings?.defaults || {}).sampler;
    sel.value = S.samplers.includes(wanted) ? wanted : "euler";
  } catch { /* keep default */ }
}

async function pollSystem() {
  try {
    const sys = await api("/api/system");
    S.gpu = sys.gpu;
    S.engine = sys.engine;
    S.queueDepth = sys.queue_depth;
    renderStatusChips();
    renderEngine();
    updateSizeHint();
  } catch { /* ignore */ }
}

/* ------------------------------------------------------------ wiring */
function wire() {
  $$(".nav-btn").forEach((b) => b.onclick = () => switchView(b.dataset.view));

  $("#btn-generate").onclick = generate;
  $("#prompt").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); generate(); }
  });
  $("#btn-neg").onclick = () => {
    const wrap = $("#negative-wrap");
    wrap.classList.toggle("hidden");
    $("#btn-neg").classList.toggle("active", !wrap.classList.contains("hidden"));
  };
  $("#btn-transparent").onclick = () => { $("#btn-transparent").classList.toggle("active"); markManualEdit(); };

  $("#btn-stop").onclick = stopActive;
  $("#btn-edit-stop").onclick = stopActive;

  // chat
  $("#btn-chat-send").onclick = sendChat;
  $("#chat-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); }
  });
  $("#btn-chat-mode").onclick = () => {
    const mode = S.chatForce || "edit";
    S.chatForce = mode === "edit" ? "generate" : "edit";
    updateChatContext();
  };
  $("#btn-chat-clear").onclick = newChat;
  $("#btn-new-chat").onclick = newChat;
  $("#btn-chat-delete").onclick = () => { if (S.chatId) askDeleteChat(S.chatId); };
  $("#hint-go-chat").onclick = (e) => { e.preventDefault(); switchView("chat"); $("#chat-input").focus(); };

  // generate-view actions
  $("#btn-gen-saveas").onclick = (e) => { if (S.shown) saveAs(S.shown.id, e.target); };
  $("#btn-gen-edit").onclick = () => { if (S.shown) { addRefFromImage(S.shown); switchView("edit"); } };
  $("#btn-gen-reuse").onclick = () => { if (S.shown?.params) { applySettings(S.shown.params); toast("Settings applied", "ok"); } };
  $("#sampler").addEventListener("change", () => { updateChatHints(); markManualEdit(); });
  $("#batch").addEventListener("change", () => { updateChatHints(); markManualEdit(); });

  // settings profiles
  $("#profile-select").onchange = () => selectProfile($("#profile-select").value);
  $("#profile-save").onclick = () => {
    $("#profile-name-row").classList.remove("hidden");
    $("#profile-name").focus();
  };
  $("#profile-name-ok").onclick = saveProfile;
  $("#profile-name-cancel").onclick = () => {
    $("#profile-name-row").classList.add("hidden");
    $("#profile-name").value = "";
  };
  $("#profile-name").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); saveProfile(); }
  });
  $("#profile-update").onclick = updateProfile;
  $("#profile-delete").onclick = deleteProfile;
  $("#settings-fields-toggle").onclick = () => setSettingsCollapsed(!S.settingsCollapsed);

  // params
  $("#size-preset").onchange = () => {
    const v = $("#size-preset").value;
    if (v === "custom") { $("#custom-size").classList.remove("hidden"); }
    else {
      const [w, h] = v.split("x").map(Number);
      $("#width").value = w; $("#height").value = h;
      $("#custom-size").classList.add("hidden");
    }
    updateSizeHint();
    markManualEdit();
  };
  ["#width", "#height"].forEach((sel) => $(sel).addEventListener("input", () => { updateSizeHint(); markManualEdit(); }));
  $("#steps").addEventListener("input", () => { $("#steps-val").textContent = $("#steps").value; updateSizeHint(); markManualEdit(); });
  $("#seed").addEventListener("input", () => { updateSizeHint(); markManualEdit(); });
  $("#cfg").addEventListener("input", () => { $("#cfg-val").textContent = Number($("#cfg").value).toFixed(1); updateChatHints(); updateSettingsSummary(); markManualEdit(); });
  $("#btn-fast").onclick = () => { $("#steps").value = 20; $("#steps-val").textContent = 20; updateSizeHint(); markManualEdit(); };
  $("#btn-quality").onclick = () => { $("#steps").value = 40; $("#steps-val").textContent = 40; updateSizeHint(); markManualEdit(); };
  $("#btn-dice").onclick = () => { $("#seed").value = Math.floor(Math.random() * 2 ** 31); markManualEdit(); };

  // edit
  $("#file-input").addEventListener("change", (e) => {
    for (const file of e.target.files) {
      if (S.editRefs.length >= 10) { toast("Maximum 10 reference images", "error"); break; }
      S.editRefs.push({ kind: "file", file, url: URL.createObjectURL(file) });
    }
    e.target.value = "";
    renderRefs();
  });
  $("#btn-edit").onclick = submitEdit;
  $("#instruction").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submitEdit(); }
  });
  $("#compare-slider").addEventListener("input", updateCompare);

  // gallery
  $("#btn-refresh-gallery").onclick = refreshGallery;
  $("#filter-kind").onchange = renderGallery;
  $("#btn-refresh-history").onclick = refreshGallery;

  // engine panel
  $("#btn-engine-restart").onclick = async () => {
    toast("Reloading engine…");
    try { await api("/api/engine/restart", { method: "POST" }); pollSystem(); }
    catch (e) { toast("Reload failed: " + e.message, "error"); }
  };
  $("#btn-engine-stop").onclick = async () => {
    try { await api("/api/engine/stop", { method: "POST" }); pollSystem(); }
    catch (e) { toast(e.message, "error"); }
  };

  // setup overlay
  $("#license-check").onchange = async () => {
    try {
      await api("/api/models/license", { method: "POST", json: { accepted: $("#license-check").checked } });
      refreshSetup();
    } catch (e) { toast(e.message, "error"); }
  };
  $("#btn-download").onclick = async () => {
    try { await api("/api/models/download", { method: "POST", json: {} }); updateSetupDownload({ active: true }); }
    catch (e) { toast(e.message, "error"); }
  };
  $("#btn-cancel-download").onclick = async () => { await api("/api/models/download/cancel", { method: "POST" }); };
  $("#btn-setup-start").onclick = async () => {
    toast("Starting engine — first load can take ~1 minute");
    try { await api("/api/engine/start", { method: "POST" }); refreshSetup(); pollSystem(); }
    catch (e) { toast("Engine start failed: " + e.message, "error", 8000); }
  };
  $("#btn-enter-app").onclick = () => refreshSetup();

  // modals
  $("#btn-settings").onclick = openSettings;
  $("#btn-logs").onclick = openLogs;
  $$("[data-close]").forEach((b) => b.onclick = () => $("#" + b.dataset.close).classList.add("hidden"));
  $$(".modal").forEach((m) => m.addEventListener("click", (e) => { if (e.target === m) m.classList.add("hidden"); }));
  $("#btn-delete-chat-confirm").onclick = confirmDeleteChat;
  $("#btn-delete-chat-cancel").addEventListener("click", () => { S.pendingDeleteChat = null; });

  $("#set-autostart").onchange = async () => {
    try { await api("/api/settings", { method: "PUT", json: { engine_autostart: $("#set-autostart").checked } }); }
    catch (e) { toast(e.message, "error"); }
  };
  $("#set-quit-close").onchange = async () => {
    try { await api("/api/settings", { method: "PUT", json: { app: { quit_on_window_close: $("#set-quit-close").checked } } }); }
    catch (e) { toast(e.message, "error"); }
  };
  $("#set-restart").onclick = () => $("#btn-engine-restart").click();
  $("#set-stop").onclick = () => $("#btn-engine-stop").click();

  // prompt assistant (DeepSeek)
  $("#set-asst-save").onclick = saveAssistantSettings;
  $("#set-asst-test").onclick = testAssistant;

  // prompt assistant + compute in the right-hand panel
  $("#side-asst-enabled").onchange = () => setAssistantEnabledSide($("#side-asst-enabled").checked);
  $("#side-asst-save").onclick = saveAssistantKeySide;
  $("#side-asst-key").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); saveAssistantKeySide(); }
  });
  $("#side-device-gpu").onclick = selectGpuDevice;
  $("#side-device-cpu").onclick = selectCpuDevice;
  $("#set-quit").onclick = async () => {
    if (!confirm("Quit Qwen Image Runner? The engine will stop.")) return;
    try { await api("/api/app/quit", { method: "POST" }); } catch { /* expected */ }
    document.body.innerHTML = `<div style="display:flex;height:100vh;align-items:center;justify-content:center;color:#8b93a7">Qwen Image Runner has quit. You can close this tab.</div>`;
  };
}

async function openSettings() {
  const meta = S.meta || await api("/api/meta");
  S.meta = meta;
  $("#set-autostart").checked = meta.settings?.engine_autostart !== false;
  try {
    const cfg = await api("/api/settings");
    S.assistant = cfg.assistant || {};
    $("#set-quit-close").checked = cfg.app?.quit_on_window_close !== false;
    $("#set-asst-enabled").checked = !!S.assistant.enabled;
    $("#set-asst-key").value = "";
    $("#set-asst-key").placeholder = S.assistant.api_key_set
      ? `•••••••• saved (${S.assistant.api_key_hint}) - type to replace`
      : "sk-...";
    $("#set-asst-keyhint").textContent = S.assistant.api_key_set
      ? "A key is stored locally in settings.json (gitignored - never sent anywhere except your provider)."
      : "No key stored yet.";
    $("#set-asst-model").value = S.assistant.model || "deepseek-chat";
    $("#set-asst-base").value = S.assistant.base_url || "https://api.deepseek.com";
    $("#set-asst-status").textContent = "";
    syncAssistantSide();
  } catch { /* ignore */ }
  const p = meta.paths || {};
  $("#set-paths").textContent =
    `engine     ${p.engine || ""}\n` +
    `models     ${p.models || ""}\n` +
    `outputs    ${p.outputs || ""}\n` +
    `inputs     ${p.inputs || ""}\n` +
    `database   ${p.database || ""}`;
  try {
    const models = await api("/api/models");
    const present = models.components.filter((c) => c.present).length;
    $("#set-storage").textContent = `model files: ${present}/${models.components.length} present\n` +
      models.components.map((c) => `${c.present ? "✓" : "✗"} ${c.destination} (${fmtBytes(c.bytes)})`).join("\n");
    $("#set-about").innerHTML =
      `<b>${meta.app}</b> v${meta.version} — unofficial local studio for Qwen-Image-2.1.<br>` +
      `App license: ${meta.license}. Qwen-Image-2.1 weights: Qwen Research License; Qwen3-VL encoder: Apache-2.0.<br>` +
      `Not affiliated with, endorsed by, or connected to Alibaba/Qwen.`;
  } catch { /* ignore */ }
  $("#settings-modal").classList.remove("hidden");
}

async function openLogs() {
  $("#logs-modal").classList.remove("hidden");
  try {
    const res = await api("/api/logs?lines=300");
    $("#logs-pre").textContent = res.lines.join("\n") || "(no logs yet)";
    $("#logs-pre").scrollTop = $("#logs-pre").scrollHeight;
  } catch (e) { $("#logs-pre").textContent = "cannot load logs: " + e.message; }
}

wire();

// closing the tab/page unregisters this window; the server still waits for the
// grace period, so a reload (pagehide → new ping) never stops the app.
window.addEventListener("pagehide", () => lifecycle("/api/lifecycle/closing", true));
window.addEventListener("beforeunload", () => lifecycle("/api/lifecycle/closing", true));
// hidden tabs get their timers throttled to ~1/minute; refresh the heartbeat
// as soon as the window is visible again so the app never looks stale.
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) lifecycle("/api/lifecycle/ping");
});

boot();
