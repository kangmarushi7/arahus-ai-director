const SAMPLES = [
  "Fall of Constantinople",
  "Apollo 11 moon landing",
  "A cyberpunk street market at night",
  "Quarterly earnings board meeting",
];

const STAGE_ORDER = ["Domain", "Research", "Director", "Prompt", "Review", "Images"];

const els = {
  form: document.getElementById("run-form"),
  topic: document.getElementById("topic"),
  runBtn: document.getElementById("run-btn"),
  samples: document.getElementById("samples"),
  banner: document.getElementById("banner"),
  chips: document.getElementById("status-chips"),
  live: document.getElementById("live"),
  liveMeta: document.getElementById("live-meta"),
  progressFill: document.getElementById("progress-fill"),
  stageBars: document.getElementById("stage-bars"),
  log: document.getElementById("log"),
  results: document.getElementById("results"),
  footHint: document.getElementById("foot-hint"),
};

function showBanner(text, kind) {
  els.banner.hidden = !text;
  els.banner.textContent = text || "";
  els.banner.className = `banner ${kind || ""}`.trim();
}

function renderChips(status) {
  const items = [
    ["LLM", status.llm],
    ["RunPod", status.runpod],
    ["R2", status.r2],
    ["DB", status.database],
  ];
  els.chips.innerHTML = "";
  for (const [label, ok] of items) {
    const chip = document.createElement("span");
    chip.className = `chip ${ok ? "ok" : "bad"}`;
    chip.textContent = `${label}: ${ok ? "ready" : "off"}`;
    els.chips.appendChild(chip);
  }
  if (status.allow_stubs) {
    const chip = document.createElement("span");
    chip.className = "chip warn";
    chip.textContent = "stubs on";
    els.chips.appendChild(chip);
  }
}

function renderSamples() {
  els.samples.innerHTML = "";
  for (const sample of SAMPLES) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "sample";
    btn.textContent = sample;
    btn.addEventListener("click", () => {
      els.topic.value = sample;
      els.topic.focus();
    });
    els.samples.appendChild(btn);
  }
}

function renderStageBars(stages) {
  els.stageBars.innerHTML = "";
  for (const name of STAGE_ORDER) {
    const value = Number((stages && stages[name]) || 0);
    const row = document.createElement("div");
    row.className = "stage-row";
    row.innerHTML = `
      <span>${name}</span>
      <div class="mini-track"><div class="mini-fill" style="width:${Math.round(value * 100)}%"></div></div>
      <span>${Math.round(value * 100)}%</span>
    `;
    els.stageBars.appendChild(row);
  }
}

function appendLog(message) {
  const next = els.log.textContent ? `${els.log.textContent}\n${message}` : message;
  els.log.textContent = next;
  els.log.scrollTop = els.log.scrollHeight;
}

function setRunning(running) {
  els.runBtn.disabled = running;
  els.runBtn.textContent = running ? "Running…" : "Run pipeline";
  els.footHint.textContent = running ? "Pipeline in progress" : "Ready when you are";
}

function activateTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("is-active", tab.dataset.tab === name);
  });
  document.querySelectorAll(".panel").forEach((panel) => {
    panel.classList.toggle("is-active", panel.id === `panel-${name}`);
  });
}

function listHtml(items) {
  if (!items || !items.length) return "<p>—</p>";
  return `<ul>${items.map((item) => `<li>${escapeHtml(String(item))}</li>`).join("")}</ul>`;
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function renderResult(result) {
  els.results.hidden = false;

  const overview = document.getElementById("panel-overview");
  const domain = result.domain
    ? `<strong>${escapeHtml(result.domain.domain)}</strong> · ${(result.domain.confidence * 100).toFixed(0)}% · ${escapeHtml(result.domain.reasoning || "")}`
    : "—";
  overview.innerHTML = `
    <div class="grid-2">
      <div class="card"><h4>Topic</h4><p>${escapeHtml(result.topic)}</p></div>
      <div class="card"><h4>Request id</h4><p>${
        result.run_id
          ? `<a class="run-id-link" href="/admin#${escapeHtml(result.run_id)}">${escapeHtml(result.run_id)}</a>`
          : "—"
      }</p></div>
      <div class="card"><h4>Domain</h4><p>${domain}</p></div>
      <div class="card"><h4>Review</h4><p>${result.review.approved ? "Approved" : "Rejected"} · score ${Math.round(result.review.overall_score)}</p></div>
      <div class="card"><h4>Images</h4><p>${result.images.filter((i) => i.url).length}/${result.images.length} with URLs${result.using_stub_services ? " · stubs used" : ""}</p></div>
    </div>
    ${result.character_bible ? `<div class="card" style="margin-top:1rem"><h4>Character bible</h4><pre class="prompt">${escapeHtml(result.character_bible)}</pre></div>` : ""}
  `;

  const research = result.research || {};
  document.getElementById("panel-research").innerHTML = `
    <div class="grid-2">
      <div class="card"><h4>Period / place</h4><p>${escapeHtml(research.time_period || "—")}<br>${escapeHtml(research.location || "—")}</p></div>
      <div class="card"><h4>Key people</h4>${listHtml(research.key_people)}</div>
      <div class="card"><h4>Events</h4>${listHtml(research.important_events)}</div>
      <div class="card"><h4>Notes</h4>${listHtml(research.historical_notes)}</div>
    </div>
  `;

  const scenes = (result.storyboard && result.storyboard.scenes) || [];
  document.getElementById("panel-scenes").innerHTML = scenes
    .map(
      (scene) => `
      <article class="scene">
        <h4>Scene ${scene.id}: ${escapeHtml(scene.title)}</h4>
        <p>${escapeHtml(scene.description || "")}</p>
        <pre class="prompt">${escapeHtml(scene.image_prompt || "")}</pre>
      </article>
    `
    )
    .join("");

  const review = result.review;
  document.getElementById("panel-review").innerHTML = `
    <div class="metrics">
      <div class="metric"><strong>${Math.round(review.overall_score)}</strong><span>Overall</span></div>
      <div class="metric"><strong>${Math.round(review.domain_accuracy)}</strong><span>Domain</span></div>
      <div class="metric"><strong>${Math.round(review.visual_quality)}</strong><span>Visual</span></div>
      <div class="metric"><strong>${Math.round(review.scene_continuity)}</strong><span>Continuity</span></div>
      <div class="metric"><strong>${Math.round(review.prompt_quality)}</strong><span>Prompts</span></div>
    </div>
    <div class="grid-2" style="margin-top:1rem">
      <div class="card"><h4>Issues</h4>${listHtml(review.issues)}</div>
      <div class="card"><h4>Recommendations</h4>${listHtml(review.recommendations)}</div>
    </div>
  `;

  const images = result.images || [];
  document.getElementById("panel-images").innerHTML = images.length
    ? `<div class="images">${images
        .map((item) => {
          if (item.url) {
            return `<figure><img src="${escapeHtml(item.url)}" alt="${escapeHtml(item.title)}" loading="lazy" /><figcaption>Scene ${item.scene_id}: ${escapeHtml(item.title)} · ${escapeHtml(item.status)}</figcaption></figure>`;
          }
          return `<figure><figcaption>Scene ${item.scene_id}: ${escapeHtml(item.title)} · ${escapeHtml(item.status)} (no URL)</figcaption></figure>`;
        })
        .join("")}</div>`
    : "<p>No images produced.</p>";

  document.getElementById("panel-metrics").innerHTML = `
    <pre class="prompt">${escapeHtml(JSON.stringify(result.metrics || {}, null, 2))}</pre>
  `;

  activateTab("overview");
}

async function loadStatus() {
  const res = await fetch("/api/status");
  const status = await res.json();
  renderChips(status);
  if (!status.llm) {
    showBanner("Set OPENROUTER_API_KEY to run the pipeline.", "danger");
  } else if (!status.ready) {
    showBanner(
      "RunPod/R2 missing. Add credentials or set ALLOW_STUB_SERVICES=true for dry runs.",
      "warn"
    );
  } else if (status.allow_stubs && (!status.runpod || !status.r2)) {
    showBanner("Stub mode is on — images may be skipped.", "warn");
  } else {
    showBanner("", "");
  }
  return status;
}

async function readSse(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";
    for (const chunk of chunks) {
      const line = chunk
        .split("\n")
        .find((part) => part.startsWith("data: "));
      if (!line) continue;
      const payload = JSON.parse(line.slice(6));
      onEvent(payload);
    }
  }
}

els.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const topic = els.topic.value.trim();
  if (!topic) return;

  setRunning(true);
  els.live.hidden = false;
  els.results.hidden = true;
  els.log.textContent = "";
  els.progressFill.style.width = "0%";
  els.liveMeta.textContent = "0%";
  renderStageBars({});
  showBanner("", "");

  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      const detail = err.detail;
      const message = Array.isArray(detail)
        ? detail.map((item) => item.msg || JSON.stringify(item)).join("; ")
        : detail || "Request failed";
      throw new Error(message);
    }

    await readSse(res, (payload) => {
      if (payload.type === "run_id" && payload.run_id) {
        appendLog(`Request id: ${payload.run_id}`);
        els.footHint.innerHTML = `Request <a class="run-id-link" href="/admin#${payload.run_id}">${payload.run_id}</a>`;
      } else if (payload.type === "progress") {
        const pct = Math.round((payload.fraction || 0) * 100);
        els.progressFill.style.width = `${pct}%`;
        els.liveMeta.textContent = `${pct}%`;
        renderStageBars(payload.stages || {});
        if (payload.message) appendLog(payload.message);
      } else if (payload.type === "result") {
        renderResult(payload.result);
        const runId = payload.run_id || payload.result?.run_id;
        showBanner(
          runId
            ? `Pipeline finished. Open admin logs for request ${runId}.`
            : "Pipeline finished.",
          "ok"
        );
        els.footHint.textContent = "Run complete";
      } else if (payload.type === "error") {
        const message = payload.error?.message || "Pipeline failed";
        appendLog(`ERROR: ${message}`);
        showBanner(message, "danger");
      }
    });
  } catch (error) {
    showBanner(error.message || String(error), "danger");
    appendLog(`ERROR: ${error.message || error}`);
  } finally {
    setRunning(false);
  }
});

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => activateTab(tab.dataset.tab));
});

renderSamples();
loadStatus().catch((error) => {
  showBanner(`Could not load status: ${error.message}`, "danger");
});
