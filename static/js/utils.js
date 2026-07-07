/* Audia — utils.js
   Funciones compartidas por todas las páginas */

"use strict";

// ── Toast ──────────────────────────────────────────────────────────────────

function showToast(msg, type = "ok", duration = 3000) {
  let container = document.getElementById("toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    document.body.appendChild(container);
  }
  const t = document.createElement("div");
  t.className = `toast toast-${type}`;
  t.textContent = msg;
  container.appendChild(t);
  setTimeout(() => {
    t.style.opacity = "0";
    t.style.transition = "opacity 0.3s";
    setTimeout(() => t.remove(), 350);
  }, duration);
}

// ── Modal de confirmación ──────────────────────────────────────────────────

function confirm(opts) {
  // opts: { title, body, confirmLabel, confirmClass, onConfirm }
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true">
      <p class="modal-title">${opts.title || "¿Confirmar?"}</p>
      <p class="modal-body">${opts.body || ""}</p>
      <div class="modal-actions">
        <button class="btn btn-outline" id="modal-cancel">Cancelar</button>
        <button class="btn ${opts.confirmClass || "btn-danger"}" id="modal-confirm">
          ${opts.confirmLabel || "Confirmar"}
        </button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  requestAnimationFrame(() => overlay.classList.add("open"));

  overlay.querySelector("#modal-cancel").addEventListener("click", () => closeModal(overlay));
  overlay.querySelector("#modal-confirm").addEventListener("click", () => {
    closeModal(overlay);
    opts.onConfirm?.();
  });
  overlay.addEventListener("click", e => { if (e.target === overlay) closeModal(overlay); });
}

function closeModal(overlay) {
  overlay.classList.remove("open");
  setTimeout(() => overlay.remove(), 250);
}

// ── API helper ─────────────────────────────────────────────────────────────

async function api(path, method = "GET", body = null) {
  const opts = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (body !== null) opts.body = JSON.stringify(body);
  try {
    const res = await fetch(path, opts);
    const data = await res.json();
    return { ok: res.ok, status: res.status, data };
  } catch (err) {
    return { ok: false, status: 0, data: { error: err.message } };
  }
}

// ── Expose ─────────────────────────────────────────────────────────────────
window.FS = { showToast, confirm, api };
