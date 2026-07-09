"use strict";

const state = {
  entries: [],
  sortKey: "f1",
  sortAsc: false,
  expanded: null,
};

const pct = (v) => (v == null ? "-" : (v * 100).toFixed(1) + "%");
const num = (v) => (v == null ? "-" : Number(v).toLocaleString());
const secs = (v) => (v == null ? "-" : Number(v).toFixed(1) + "s");

async function load() {
  const statusEl = document.getElementById("status");
  try {
    const res = await fetch("leaderboard.json", { cache: "no-store" });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    state.entries = data.entries || [];
    statusEl.textContent =
      `${state.entries.length} 条提交 · benchmark: ${data.benchmark || "AACR-Bench"}` +
      (data.generated_at ? ` · 更新于 ${data.generated_at.slice(0, 10)}` : "");
    render();
  } catch (err) {
    statusEl.textContent = "加载 leaderboard.json 失败：" + err.message;
  }
}

function sortEntries() {
  const { sortKey, sortAsc } = state;
  state.entries.sort((a, b) => {
    let av = a[sortKey], bv = b[sortKey];
    if (typeof av === "string") {
      return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
    }
    av = av ?? 0; bv = bv ?? 0;
    return sortAsc ? av - bv : bv - av;
  });
  // rank 始终按 f1 固定，不随排序变化 —— 用后端给的 rank
}

function coverageCell(e) {
  const partial = e.missing_instances > 0;
  const cls = partial ? "coverage partial" : "coverage";
  return `<td class="num ${cls}">${e.submitted_instances}/${e.total_instances}</td>`;
}

function rowHtml(e) {
  const rankCls = e.rank === 1 ? "rank rank-1" : "rank";
  const sub = [e.reviewer, e.org].filter(Boolean).join(" · ");
  return `
    <tr data-id="${e.submission_id}">
      <td class="num ${rankCls}">${e.rank}</td>
      <td class="model-cell">
        <strong>${escapeHtml(e.model || e.submission_name)}</strong>
        ${sub ? `<span class="sub">${escapeHtml(sub)}</span>` : ""}
      </td>
      <td class="num f1">${pct(e.f1)}</td>
      <td class="num">${pct(e.precision)}</td>
      <td class="num">${pct(e.recall)}</td>
      ${coverageCell(e)}
      <td class="num">${secs(e.avg_duration_seconds)}</td>
      <td class="num">${num(e.avg_tokens)}</td>
      <td>${escapeHtml(e.date || "-")}</td>
    </tr>`;
}

function detailHtml(e) {
  const link = e.url ? `<a href="${escapeHtml(e.url)}" target="_blank" rel="noopener">${escapeHtml(e.url)}</a>` : "-";
  return `
    <tr class="detail-row" data-detail="${e.submission_id}">
      <td colspan="9">
        <div class="detail-inner">
          <h3>${escapeHtml(e.submission_name)}</h3>
          <div class="detail-grid">
            <div><span>Reviewer:</span> ${escapeHtml(e.reviewer || "-")}</div>
            <div><span>Model:</span> ${escapeHtml(e.model || "-")}</div>
            <div><span>Org:</span> ${escapeHtml(e.org || "-")}</div>
            <div><span>Judge:</span> ${escapeHtml(e.judge_mode || "-")}</div>
            <div><span>Precision:</span> ${pct(e.precision)}</div>
            <div><span>Recall:</span> ${pct(e.recall)}</div>
            <div><span>Submitted:</span> ${e.submitted_instances}/${e.total_instances}（缺失 ${e.missing_instances}）</div>
            <div><span>Avg input tokens:</span> ${num(e.avg_input_tokens)}</div>
            <div><span>Avg output tokens:</span> ${num(e.avg_output_tokens)}</div>
            <div><span>Link:</span> ${link}</div>
          </div>
        </div>
      </td>
    </tr>`;
}

function render() {
  sortEntries();
  const body = document.getElementById("board-body");
  if (!state.entries.length) {
    body.innerHTML = `<tr><td colspan="9" class="empty">暂无提交。成为第一个刷榜的人！</td></tr>`;
    return;
  }
  let html = "";
  for (const e of state.entries) {
    html += rowHtml(e);
    if (state.expanded === e.submission_id) html += detailHtml(e);
  }
  body.innerHTML = html;

  body.querySelectorAll("tr[data-id]").forEach((tr) => {
    tr.addEventListener("click", () => {
      const id = tr.getAttribute("data-id");
      state.expanded = state.expanded === id ? null : id;
      render();
    });
  });

  document.querySelectorAll("th.sortable").forEach((th) => {
    const key = th.getAttribute("data-key");
    th.classList.toggle("active", key === state.sortKey);
    th.classList.toggle("asc", key === state.sortKey && state.sortAsc);
  });
}

function bindSort() {
  document.querySelectorAll("th.sortable").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.getAttribute("data-key");
      if (state.sortKey === key) {
        state.sortAsc = !state.sortAsc;
      } else {
        state.sortKey = key;
        state.sortAsc = false;
      }
      render();
    });
  });
}

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

bindSort();
load();
