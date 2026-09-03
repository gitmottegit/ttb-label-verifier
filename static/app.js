/* Label Verifier UI — no framework, no build step. */
"use strict";

const $ = (id) => document.getElementById(id);

const FIELD_LABELS = {
  brand_name: "Brand name",
  class_type: "Class / type",
  alcohol_content: "Alcohol content",
  net_contents: "Net contents",
};

const VERDICT_UI = {
  pass:        { cls: "pass",   icon: "✅", title: "Looks good",       },
  needs_review:{ cls: "review", icon: "⚠️", title: "Please double-check" },
  fail:        { cls: "fail",   icon: "❌", title: "Problems found",   },
};

const PILL = {
  match:            { cls: "p-pass",   text: "Match" },
  match_formatting: { cls: "p-review", text: "Check formatting" },
  mismatch:         { cls: "p-fail",   text: "Mismatch" },
  missing:          { cls: "p-fail",   text: "Not on label" },
  not_checked:      { cls: "p-skip",   text: "Skipped" },
};

const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ---------- tabs ---------- */
function selectTab(which) {
  const single = which === "single";
  $("tab-single").classList.toggle("active", single);
  $("tab-batch").classList.toggle("active", !single);
  $("tab-single").setAttribute("aria-selected", single);
  $("tab-batch").setAttribute("aria-selected", !single);
  $("panel-single").hidden = !single;
  $("panel-batch").hidden = single;
}
$("tab-single").addEventListener("click", () => selectTab("single"));
$("tab-batch").addEventListener("click", () => selectTab("batch"));

/* ---------- dropzone helper ---------- */
function wireDropzone(zoneId, inputId, onFiles) {
  const zone = $(zoneId), input = $(inputId);
  const open = () => input.click();
  zone.addEventListener("click", open);
  zone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
  });
  input.addEventListener("change", () => onFiles([...input.files]));
  ["dragover", "dragenter"].forEach((ev) => zone.addEventListener(ev, (e) => {
    e.preventDefault(); zone.classList.add("dragover");
  }));
  ["dragleave", "drop"].forEach((ev) => zone.addEventListener(ev, (e) => {
    e.preventDefault(); zone.classList.remove("dragover");
  }));
  zone.addEventListener("drop", (e) => {
    const files = [...e.dataTransfer.files].filter((f) => f.type.startsWith("image/"));
    if (files.length) onFiles(files);
  });
}

function showStatus(el, message, isError = false) {
  el.hidden = false;
  el.className = "status" + (isError ? " error" : "");
  el.innerHTML = message;
}

/* ---------- single ---------- */
let singleFile = null;

function setSingleFile(file) {
  singleFile = file;
  const img = $("preview-single");
  img.src = URL.createObjectURL(singleFile);
  img.hidden = false;
  $("btn-single").disabled = false;
}

wireDropzone("drop-single", "file-single", (files) => setSingleFile(files[0]));

/* One-click examples: load a bundled label, leave every box empty, and run —
   demonstrating that the tool needs zero typing to check a label. */
async function runExample(path, name) {
  const status = $("status-single");
  try {
    const res = await fetch(path);
    if (!res.ok) throw new Error();
    setSingleFile(new File([await res.blob()], name, { type: "image/png" }));
  } catch {
    showStatus(status, "⚠️ Could not load the example image. Please retry.", true);
    return;
  }
  $("form-single").reset();
  $("form-single").requestSubmit();
}
$("ex-good").addEventListener("click", () =>
  runExample("/static/examples/compliant.png", "example_compliant.png"));
$("ex-bad").addEventListener("click", () =>
  runExample("/static/examples/violation.png", "example_violation.png"));

$("form-single").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!singleFile) return;
  const btn = $("btn-single"), status = $("status-single"), out = $("result-single");
  btn.disabled = true;
  out.hidden = true;
  showStatus(status, "Reading the label… this usually takes a few seconds.");

  const body = new FormData(e.target);
  body.append("image", singleFile);
  try {
    const res = await fetch("/api/verify", { method: "POST", body });
    const data = await res.json();
    status.hidden = true;
    if (!data.ok) {
      showStatus(status, "⚠️ " + esc(data.error || "Something went wrong. Please retry."), true);
    } else {
      out.hidden = false;
      out.innerHTML = renderReport(data);
    }
  } catch {
    showStatus(status, "⚠️ Could not reach the server. Check your connection and retry.", true);
  } finally {
    btn.disabled = false;
  }
});

function renderReport(data) {
  const r = data.report;
  const ui = VERDICT_UI[r.overall] || VERDICT_UI.needs_review;
  const rows = r.fields.map((f) => {
    const pill = PILL[f.verdict] || PILL.not_checked;
    return `<tr>
      <th scope="row">${esc(FIELD_LABELS[f.name] || f.name)}</th>
      <td>${esc(f.application_value || "—")}</td>
      <td>${esc(f.label_value || "—")}</td>
      <td class="pill-cell"><span class="pill ${pill.cls}">${pill.text}</span>
        ${f.note ? `<div class="note">${esc(f.note)}</div>` : ""}</td>
    </tr>`;
  }).join("");

  const w = r.warning;
  const warningPill = w.verdict === "pass"
    ? `<span class="pill p-pass">Exact</span>`
    : `<span class="pill p-fail">${w.present ? "Incorrect" : "Missing"}</span>`;
  const warningNotes = (w.problems || []).map((p) => `<div class="note">${esc(p)}</div>`).join("");

  const readability = (r.readability_issues || []).length
    ? `<p class="note">📷 Image quality: ${esc(r.readability_issues.join("; "))}</p>` : "";

  return `
    <div class="verdict-banner v-${ui.cls}">
      <div class="big">${ui.icon}</div>
      <div><h3>${ui.title}</h3><p>${esc(r.summary)}</p></div>
    </div>
    <table class="checks">
      <thead><tr><th>Check</th><th>Application says</th><th>Label says</th><th>Result</th></tr></thead>
      <tbody>
        ${rows}
        <tr>
          <th scope="row">Government warning</th>
          <td>Required, word-for-word</td>
          <td>${esc(w.label_text || "—")}</td>
          <td class="pill-cell">${warningPill}${warningNotes}</td>
        </tr>
      </tbody>
    </table>
    ${readability}
    <p class="timing">⏱️ Checked in ${(data.elapsed_ms / 1000).toFixed(1)} seconds</p>
    <details class="raw"><summary>Everything read from the label</summary>
      <pre>${esc(JSON.stringify(data.extracted, null, 2))}</pre></details>`;
}

/* ---------- batch ---------- */
let batchFiles = [];

wireDropzone("drop-batch", "file-batch", (files) => {
  batchFiles = files;
  $("batch-count").textContent = `${files.length} image${files.length === 1 ? "" : "s"} selected.`;
  $("btn-batch").disabled = files.length === 0;
});

/* Labels are sent in chunks so a 300-image run shows genuine progress and no
   single request grows large enough to hit an upload or proxy limit. */
const BATCH_CHUNK_SIZE = 24;

$("btn-batch").addEventListener("click", async () => {
  const btn = $("btn-batch"), status = $("status-batch"), out = $("result-batch");
  btn.disabled = true;
  out.hidden = true;

  const csv = $("csv-batch").files[0];
  const chunks = [];
  for (let i = 0; i < batchFiles.length; i += BATCH_CHUNK_SIZE) {
    chunks.push(batchFiles.slice(i, i + BATCH_CHUNK_SIZE));
  }

  const progress = (done) => showStatus(status,
    `Checking labels… ${done} of ${batchFiles.length} done.
     <div class="progressbar"><div style="width:${
       Math.max(3, Math.round((done / batchFiles.length) * 100))}%"></div></div>`);
  progress(0);

  const results = [];
  let csvMatched = 0;
  const started = performance.now();
  try {
    for (const chunk of chunks) {
      const body = new FormData();
      chunk.forEach((f) => body.append("images", f));
      if (csv) body.append("applications_csv", csv);
      const res = await fetch("/api/batch", { method: "POST", body });
      const data = await res.json();
      if (data.error) {
        showStatus(status, "⚠️ " + esc(data.error), true);
        btn.disabled = false;
        return;
      }
      results.push(...data.results);
      csvMatched += data.csv_rows_matched || 0;
      progress(results.length);
    }
    const summary = {
      results,
      count: results.length,
      csv_rows_matched: csvMatched,
      elapsed_ms: performance.now() - started,
    };
    status.hidden = true;
    out.hidden = false;
    out.innerHTML = renderBatch(summary);
    wireBatchRows(summary);
  } catch {
    showStatus(status, "⚠️ Could not reach the server. Check your connection and retry.", true);
  } finally {
    btn.disabled = false;
  }
});

function renderBatch(data) {
  const counts = { pass: 0, needs_review: 0, fail: 0, error: 0 };
  for (const r of data.results) {
    if (!r.ok) counts.error += 1;
    else counts[r.report.overall] += 1;
  }
  const chips = `
    <div class="batch-summary">
      <span class="chip v-pass">✅ ${counts.pass} passed</span>
      <span class="chip v-review">⚠️ ${counts.needs_review} to double-check</span>
      <span class="chip v-fail">❌ ${counts.fail} with problems</span>
      ${counts.error ? `<span class="chip v-fail">🚫 ${counts.error} could not be read</span>` : ""}
    </div>`;

  const rows = data.results.map((r, i) => {
    let pill, summary;
    if (!r.ok) {
      pill = `<span class="pill p-fail">Error</span>`;
      summary = r.error;
    } else {
      const ui = VERDICT_UI[r.report.overall];
      pill = `<span class="pill p-${ui.cls === "review" ? "review" : ui.cls}">${ui.icon} ${ui.title}</span>`;
      summary = r.report.summary;
    }
    return `<tr class="batch-row" data-i="${i}" tabindex="0" role="button"
        aria-expanded="false" title="Click for details">
      <td>${esc(r.filename)}</td>
      <td class="pill-cell">${pill}</td>
      <td>${esc(summary)}</td>
      <td>${(r.elapsed_ms / 1000).toFixed(1)}s</td>
    </tr>
    <tr class="batch-detail" data-detail="${i}" hidden><td colspan="4"></td></tr>`;
  }).join("");

  return `${chips}
    <table class="checks">
      <thead><tr><th>File</th><th>Result</th><th>Summary</th><th>Time</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="timing">⏱️ ${data.count} labels checked in ${(data.elapsed_ms / 1000).toFixed(1)}
       seconds total${data.csv_rows_matched ? ` · ${data.csv_rows_matched} matched to CSV rows` : ""}</p>`;
}

function wireBatchRows(data) {
  document.querySelectorAll("tr.batch-row").forEach((row) => {
    const toggle = () => {
      const i = row.dataset.i;
      const detail = document.querySelector(`tr[data-detail="${i}"]`);
      if (!detail.hidden) {
        detail.hidden = true;
        row.setAttribute("aria-expanded", "false");
        return;
      }
      const r = data.results[i];
      detail.firstElementChild.innerHTML = r.ok
        ? renderReport(r)
        : `<p class="note">${esc(r.error)}</p>`;
      detail.hidden = false;
      row.setAttribute("aria-expanded", "true");
    };
    row.addEventListener("click", toggle);
    row.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
    });
  });
}
