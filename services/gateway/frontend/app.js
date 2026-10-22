"use strict";
// Ticket text is untrusted: it is only ever rendered with textContent, never innerHTML.

const POLL_MS = 5000;
const PREVIEW_CHARS = 600;
const list = document.getElementById("review-list");
const statusEl = document.getElementById("status");
const cards = new Map(); // prediction_id -> <li>
let labels = [];

function say(msg) {
  statusEl.textContent = msg;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: { "content-type": "application/json", ...(options.headers || {}) },
  });
  let body = null;
  try {
    body = await res.json();
  } catch {
    // non-JSON (e.g. gateway error page)
  }
  return { status: res.status, body };
}

function pct(x) {
  return `${Math.round(x * 100)}%`;
}

function buildCard(item) {
  const li = document.getElementById("card-template").content.firstElementChild.cloneNode(true);
  li.querySelector(".subject").textContent = item.subject || "(no subject)";

  const bodyEl = li.querySelector(".body");
  const more = li.querySelector(".more");
  const long = item.body.length > PREVIEW_CHARS;
  bodyEl.textContent = long ? `${item.body.slice(0, PREVIEW_CHARS)}…` : item.body;
  more.hidden = !long;
  more.addEventListener("click", () => {
    const expanded = more.textContent === "Show less";
    bodyEl.textContent = expanded ? `${item.body.slice(0, PREVIEW_CHARS)}…` : item.body;
    more.textContent = expanded ? "Show more" : "Show less";
  });

  li.querySelector(".predicted").textContent = `${item.predicted_label} (${pct(item.confidence)})`;
  const topK = li.querySelector(".top-k");
  for (const s of item.top_k) {
    const entry = document.createElement("li");
    entry.textContent = `${s.label}: ${pct(s.score)}`;
    topK.append(entry);
  }
  li.querySelector(".version").textContent = item.model_version.slice(0, 7);

  const select = li.querySelector(".fix-select");
  for (const label of labels) {
    const opt = document.createElement("option");
    opt.value = label;
    opt.textContent = label === item.predicted_label ? `${label} (predicted)` : label;
    opt.disabled = label === item.predicted_label;
    select.append(opt);
  }
  select.value = labels.find((l) => l !== item.predicted_label) || "";

  const correct = li.querySelector(".correct");
  const fix = li.querySelector(".fix");
  correct.setAttribute("aria-label", `Mark prediction ${item.predicted_label} as correct`);
  correct.addEventListener("click", () => review(item, li, true, null));
  fix.addEventListener("click", () => review(item, li, false, select.value));
  return li;
}

function removeCard(id) {
  cards.get(id)?.remove();
  cards.delete(id);
  updateCount();
}

function updateCount() {
  const n = cards.size;
  document.getElementById("pending-count").textContent = n >= 20 ? "20+" : String(n);
  document.getElementById("empty").hidden = n > 0;
}

async function review(item, li, isCorrect, correctedLabel) {
  for (const b of li.querySelectorAll("button")) b.disabled = true;
  const { status, body } = await api("/feedback-api/feedback", {
    method: "POST",
    body: JSON.stringify({
      prediction_id: item.prediction_id,
      is_correct: isCorrect,
      corrected_label: correctedLabel,
    }),
  });
  if (status === 201) {
    say(isCorrect ? "Marked correct." : `Corrected to ${correctedLabel}.`);
    removeCard(item.prediction_id);
  } else if (status === 409) {
    say("Already reviewed by someone else.");
    removeCard(item.prediction_id);
  } else {
    say(`Could not save the review (${body?.detail || status}).`);
    for (const b of li.querySelectorAll("button")) b.disabled = false;
  }
}

async function poll() {
  const { status, body } = await api("/api/tickets/pending?limit=20");
  if (status !== 200) {
    say(`Could not load pending tickets (${body?.detail || status}).`);
    return;
  }
  const seen = new Set(body.map((i) => i.prediction_id));
  for (const id of [...cards.keys()]) if (!seen.has(id)) removeCard(id);
  for (const item of body) {
    if (cards.has(item.prediction_id)) continue;
    const li = buildCard(item);
    cards.set(item.prediction_id, li);
    list.append(li);
  }
  updateCount();
}

document.getElementById("manual-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const button = form.querySelector("button");
  const result = document.getElementById("manual-result");
  button.disabled = true;
  say("Predicting…");
  const subject = form.subject.value.trim();
  const { status, body } = await api("/api/tickets", {
    method: "POST",
    body: JSON.stringify({
      subject: subject || null,
      body: form.body.value,
      source: "manual",
      dataset_label: null,
    }),
  });
  button.disabled = false;
  result.hidden = false;
  if (status === 201) {
    const p = body.prediction;
    result.textContent = `Predicted queue: ${p.label} (${pct(p.confidence)}), model ${p.model_version.slice(0, 7)}`;
    say("Ticket submitted. It now appears in the review list.");
    form.reset();
    poll();
  } else if (status === 502) {
    result.textContent = "Model is waking up, try again in a minute.";
    say(result.textContent);
  } else {
    result.textContent = `Could not submit (${body?.detail || status}).`;
    say(result.textContent);
  }
});

async function start() {
  const { status, body } = await api("/api/labels");
  if (status === 200) labels = body.labels;
  await poll();
  setInterval(poll, POLL_MS);
}

start();
