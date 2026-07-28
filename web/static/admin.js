const els = {
  modelsPanel: document.getElementById("models-panel"),
  taskModels: document.getElementById("task-models"),
  modelsMeta: document.getElementById("models-meta"),
  modelsBanner: document.getElementById("models-banner"),
  modelFilter: document.getElementById("model-filter"),
  refreshModelsBtn: document.getElementById("refresh-models-btn"),
  saveModelsBtn: document.getElementById("save-models-btn"),
  listView: document.getElementById("list-view"),
  detailView: document.getElementById("detail-view"),
  runsTable: document.getElementById("runs-table"),
  listEmpty: document.getElementById("list-empty"),
  listMeta: document.getElementById("list-meta"),
  refreshBtn: document.getElementById("refresh-btn"),
  backBtn: document.getElementById("back-btn"),
  detailTitle: document.getElementById("detail-title"),
  detailMeta: document.getElementById("detail-meta"),
  exportOne: document.getElementById("export-one"),
  summary: document.getElementById("summary"),
  tagFilters: document.getElementById("tag-filters"),
  flow: document.getElementById("flow"),
};

let currentRun = null;
let activeTag = "all";
let catalogModels = [];
let taskRows = [];
let selectedModels = {};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function shortId(id) {
  const text = String(id || "");
  return text.length > 12 ? `${text.slice(0, 8)}…${text.slice(-4)}` : text;
}

function formatWhen(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function formatMoney(value) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  const n = Number(value);
  if (n === 0) return "$0";
  if (n < 0.0001) return `$${n.toFixed(8)}`;
  if (n < 0.01) return `$${n.toFixed(6)}`;
  return `$${n.toFixed(4)}`;
}

function showModelsBanner(text, kind) {
  els.modelsBanner.hidden = !text;
  els.modelsBanner.textContent = text || "";
  els.modelsBanner.className = `banner ${kind || ""}`.trim();
}

function modelById(id) {
  return catalogModels.find((m) => m.id === id) || null;
}

function estimateForModel(model, outputTokens) {
  if (!model) return null;
  const out = Math.max(1, Number(outputTokens) || 1000);
  const inp = 2000;
  return (
    (inp / 1_000_000) * Number(model.input_per_million || 0) +
    (out / 1_000_000) * Number(model.output_per_million || 0)
  );
}

async function loadCatalog(forceRefresh) {
  const q = els.modelFilter.value.trim();
  const params = new URLSearchParams({ limit: "800" });
  if (q) params.set("q", q);
  if (forceRefresh) params.set("refresh", "true");
  const res = await fetch(`/api/admin/models?${params}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Model catalog failed (${res.status})`);
  }
  const body = await res.json();
  catalogModels = body.models || [];
  els.modelsMeta.textContent = `${body.total_matched || catalogModels.length} models`;
}

async function loadTaskModels() {
  const res = await fetch("/api/admin/task-models");
  if (!res.ok) throw new Error(`Failed to load task models (${res.status})`);
  const body = await res.json();
  taskRows = body.tasks || [];
  selectedModels = {};
  for (const row of taskRows) {
    selectedModels[row.task] = row.effective_model;
  }
}

function renderTaskModels() {
  els.taskModels.innerHTML = "";
  if (!taskRows.length) {
    els.taskModels.innerHTML = `<p class="banner">No task routes configured.</p>`;
    return;
  }

  for (const row of taskRows) {
    const selected = selectedModels[row.task] || row.effective_model;
    const model = modelById(selected);
    const sampleOut = Math.min(1000, Number(row.max_tokens) || 1000);
    const est = estimateForModel(model, sampleOut);
    const options = buildModelOptions(selected);

    const card = document.createElement("div");
    card.className = "task-model-row";
    card.innerHTML = `
      <div class="task-label">${escapeHtml(row.task)}</div>
      <div>
        <select data-task="${escapeHtml(row.task)}" aria-label="${escapeHtml(row.task)} model">
          ${options}
        </select>
        <div class="source-pill">source: ${escapeHtml(row.source)} · yaml ${escapeHtml(row.yaml_model)}</div>
      </div>
      <div class="task-cost" data-cost-for="${escapeHtml(row.task)}">
        ${costHtml(model, est, sampleOut)}
      </div>
    `;
    const select = card.querySelector("select");
    select.addEventListener("change", () => {
      selectedModels[row.task] = select.value;
      const next = modelById(select.value);
      const nextEst = estimateForModel(next, sampleOut);
      card.querySelector(`[data-cost-for="${row.task}"]`).innerHTML = costHtml(
        next,
        nextEst,
        sampleOut
      );
    });
    els.taskModels.appendChild(card);
  }
}

function buildModelOptions(selectedId) {
  const ids = new Set(catalogModels.map((m) => m.id));
  let html = "";
  if (selectedId && !ids.has(selectedId)) {
    html += `<option value="${escapeHtml(selectedId)}" selected>${escapeHtml(selectedId)} (current)</option>`;
  }
  for (const model of catalogModels) {
    const label = `${model.id}${model.is_free ? " · free" : ""} · $${Number(model.input_per_million || 0).toFixed(2)}/$${Number(model.output_per_million || 0).toFixed(2)} per 1M`;
    const selected = model.id === selectedId ? " selected" : "";
    html += `<option value="${escapeHtml(model.id)}"${selected}>${escapeHtml(label)}</option>`;
  }
  return html;
}

function costHtml(model, est, sampleOut) {
  if (!model) {
    return `<strong>Pricing unknown</strong><br/>Model not in OpenRouter catalog yet.`;
  }
  return `
    <strong>${formatMoney(est)}</strong> est. / call<br/>
    in $${Number(model.input_per_million || 0).toFixed(2)} · out $${Number(model.output_per_million || 0).toFixed(2)} per 1M tokens<br/>
    sample 2k in + ${sampleOut} out${model.is_free ? " · free tier" : ""}
  `;
}

async function refreshModelsUI(forceRefresh) {
  showModelsBanner("", "");
  await loadCatalog(forceRefresh);
  await loadTaskModels();
  renderTaskModels();
}

async function saveModels() {
  const payload = { models: { ...selectedModels } };
  const res = await fetch("/api/admin/task-models", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Save failed (${res.status})`);
  }
  const body = await res.json();
  taskRows = body.tasks || [];
  for (const row of taskRows) {
    selectedModels[row.task] = row.effective_model;
  }
  renderTaskModels();
  showModelsBanner("Model overrides saved. New pipeline runs will use them.", "ok");
}

async function loadRuns() {
  const res = await fetch("/api/admin/runs?limit=200");
  if (!res.ok) throw new Error(`Failed to load runs (${res.status})`);
  const body = await res.json();
  const runs = body.runs || [];
  els.listMeta.textContent = `${runs.length} request${runs.length === 1 ? "" : "s"}`;
  els.listEmpty.hidden = runs.length > 0;
  els.runsTable.innerHTML = "";
  for (const run of runs) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "run-row";
    btn.setAttribute("role", "listitem");
    btn.innerHTML = `
      <span class="run-id" title="${escapeHtml(run.id)}">${escapeHtml(shortId(run.id))}</span>
      <span class="run-topic">${escapeHtml(run.topic || "")}</span>
      <span class="run-status ${escapeHtml(run.status || "")}">${escapeHtml(run.status || "")}</span>
      <span class="run-meta">${escapeHtml(formatWhen(run.started_at))}<br/>${run.llm_steps || 0} llm · ${run.image_steps || 0} img</span>
    `;
    btn.addEventListener("click", () => openRun(run.id));
    els.runsTable.appendChild(btn);
  }
}

async function openRun(runId) {
  const res = await fetch(`/api/admin/runs/${encodeURIComponent(runId)}`);
  if (!res.ok) throw new Error(`Run not found (${res.status})`);
  currentRun = await res.json();
  activeTag = "all";
  history.replaceState(null, "", `#${runId}`);
  renderDetail();
}

function showList() {
  currentRun = null;
  els.modelsPanel.hidden = false;
  els.listView.hidden = false;
  els.detailView.hidden = true;
  history.replaceState(null, "", location.pathname);
}

function renderDetail() {
  const run = currentRun;
  if (!run) return;
  els.modelsPanel.hidden = true;
  els.listView.hidden = true;
  els.detailView.hidden = false;
  els.detailTitle.textContent = run.topic || "Request";
  els.detailMeta.textContent = `id ${run.id} · ${run.status} · started ${formatWhen(run.started_at)}`;
  els.exportOne.href = `/api/admin/runs/${encodeURIComponent(run.id)}/export`;

  const summary = run.summary || {};
  const stats = [
    ["Status", run.status],
    ["LLM steps", run.llm_steps ?? 0],
    ["Images", run.image_steps ?? 0],
    ["Video", run.video_steps ?? 0],
    ["Review", summary.review_score ?? "—"],
    ["Seconds", summary.total_seconds ?? "—"],
  ];
  els.summary.innerHTML = stats
    .map(
      ([label, value]) =>
        `<div class="stat"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></div>`
    )
    .join("");

  const tags = ["all", ...new Set((run.steps || []).map((s) => s.tag).filter(Boolean))];
  els.tagFilters.innerHTML = "";
  for (const tag of tags) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = `tag-chip${tag === activeTag ? " is-active" : ""}`;
    chip.textContent = tag;
    chip.addEventListener("click", () => {
      activeTag = tag;
      renderDetail();
    });
    els.tagFilters.appendChild(chip);
  }

  const steps = (run.steps || []).filter(
    (step) => activeTag === "all" || step.tag === activeTag
  );
  els.flow.innerHTML = "";
  if (!steps.length) {
    els.flow.innerHTML = `<p class="banner">No steps for this filter.</p>`;
    return;
  }
  for (const step of steps) {
    els.flow.appendChild(renderStep(step));
  }
}

function renderStep(step) {
  const card = document.createElement("article");
  card.className = "step-card";
  const metaBits = [
    step.model ? `model ${step.model}` : null,
    step.provider ? `provider ${step.provider}` : null,
    step.latency_ms != null ? `${Number(step.latency_ms).toFixed(0)} ms` : null,
    step.estimated_cost != null ? `$${Number(step.estimated_cost).toFixed(6)}` : null,
    formatWhen(step.created_at),
  ].filter(Boolean);

  let body = "";
  if (step.kind === "image" && step.response) {
    body += `<div class="prompt-block"><h3>Image</h3><img src="${escapeHtml(step.response)}" alt="${escapeHtml(step.meta?.title || "scene")}" /></div>`;
  }
  if (step.kind === "video") {
    body += `<div class="prompt-block"><h3>Video</h3><pre>${escapeHtml(step.request || "Video not generated")}${step.response ? `\n${step.response}` : ""}</pre></div>`;
  } else {
    if (step.request) {
      body += `<div class="prompt-block"><h3>Request / prompt</h3><pre>${escapeHtml(step.request)}</pre></div>`;
    }
    if (step.response && step.kind !== "image") {
      body += `<div class="prompt-block"><h3>Response</h3><pre>${escapeHtml(step.response)}</pre></div>`;
    }
  }
  if (step.error || step.success === false) {
    body += `<p class="step-fail">${escapeHtml(step.error || "Step failed")}</p>`;
  }

  card.innerHTML = `
    <div class="step-head">
      <span class="tag-pill">${escapeHtml(step.tag || "general")}</span>
      <span class="kind-pill">${escapeHtml(step.kind || "step")}</span>
      <span class="kind-pill">${escapeHtml(metaBits.join(" · "))}</span>
    </div>
    <div class="step-body">${body}</div>
  `;
  return card;
}

els.refreshBtn.addEventListener("click", () => {
  loadRuns().catch((err) => {
    els.listMeta.textContent = String(err.message || err);
  });
});
els.backBtn.addEventListener("click", showList);
els.refreshModelsBtn.addEventListener("click", () => {
  refreshModelsUI(true).catch((err) => showModelsBanner(String(err.message || err), "danger"));
});
els.saveModelsBtn.addEventListener("click", () => {
  saveModels().catch((err) => showModelsBanner(String(err.message || err), "danger"));
});

let filterTimer = null;
els.modelFilter.addEventListener("input", () => {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(() => {
    loadCatalog(false)
      .then(() => renderTaskModels())
      .catch((err) => showModelsBanner(String(err.message || err), "danger"));
  }, 250);
});

async function boot() {
  await Promise.all([
    loadRuns(),
    refreshModelsUI(false).catch((err) => {
      showModelsBanner(String(err.message || err), "warn");
    }),
  ]);
  const hash = location.hash.replace(/^#/, "").trim();
  if (hash) {
    await openRun(hash);
  }
}

boot().catch((err) => {
  els.listMeta.textContent = String(err.message || err);
});
