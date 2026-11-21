// Terkini recorded-run page. Reads i18n.json and cases/*.json (written by scripts/build-pages.py); no key, no live calls.
// Every piece of recorded text is inserted with textContent, never as HTML.
"use strict";

const VERDICTS = ["outdated", "current", "unverifiable"];
const LANG_KEY = "terkini-lang";
const state = { strings: {}, languages: [], lang: "en", cases: [], current: null, failed: false };

const $ = (sel) => document.querySelector(sel);

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else n.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined && k !== false) n.append(k);
  return n;
}

function icon(verdict) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("width", "16");
  svg.setAttribute("height", "16");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(ns, "use");
  use.setAttribute("href", `#i-${verdict}`);
  svg.append(use);
  return svg;
}

function t(key, vars = {}) {
  const s = (state.strings[state.lang] || {})[key] ?? (state.strings[state.languages[0]] || {})[key] ?? key;
  return s.replace(/\{(\w+)\}/g, (_, k) => (k in vars ? String(vars[k]) : `{${k}}`));
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  if (Number.isNaN(d.getTime())) return iso;
  const locale = state.lang === "ms" ? "ms-MY" : "en-GB";
  return new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(d);
}

const normalise = (s) => s.replace(/\s+/g, " ").trim();
// Markdown bold markers in model answers are shown as plain text; the words themselves are unchanged.
// Markdown code fences are dropped the same way.
const plain = (s) => s.replace(/\*\*|^```\w*$/gm, "");

// --- Language -------------------------------------------------------------------------------------------------------

function pickLang() {
  const ok = (l) => state.languages.includes(l);
  const fromUrl = new URLSearchParams(location.search).get("lang");
  if (fromUrl && ok(fromUrl)) return fromUrl;
  let saved = null;
  try { saved = localStorage.getItem(LANG_KEY); } catch (_) { /* storage blocked */ }
  if (saved && ok(saved)) return saved;
  const nav = (navigator.languages || [navigator.language || ""]).map((l) => l.slice(0, 2).toLowerCase());
  if (nav.some((l) => l === "ms" || l === "id") && ok("ms")) return "ms";
  return state.languages[0];
}

function applyLang(lang) {
  state.lang = lang;
  document.documentElement.lang = lang;
  try { localStorage.setItem(LANG_KEY, lang); } catch (_) { /* storage blocked */ }
  document.title = t("title");
  document.querySelector('meta[name="description"]').setAttribute("content", t("meta_description"));
  document.querySelectorAll("[data-i18n]").forEach((n) => { n.textContent = t(n.dataset.i18n); });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((n) => { n.placeholder = t(n.dataset.i18nPlaceholder); });
  document.querySelectorAll("[data-i18n-aria-label]").forEach((n) => n.setAttribute("aria-label", t(n.dataset.i18nAriaLabel)));
  document.querySelectorAll("[data-lang]").forEach((b) => {
    b.setAttribute("aria-pressed", String(b.dataset.lang === lang));
    b.setAttribute("title", t("lang_name"));
  });
  renderCaseList();
  if (state.current) renderCase(state.current);
  else if (state.failed) renderFailed();
  const msg = $("#answer-msg");
  if (msg.dataset.key) msg.textContent = t(msg.dataset.key);
}

// --- Case list --------------------------------------------------------------------------------------------------------

function tally(counts) {
  return el("span", { class: "tally" }, VERDICTS.filter((v) => counts[v]).map((v) =>
    el("span", { title: t(`verdict_${v}`) }, el("i", { class: `dot ${v}`, "aria-hidden": "true" }),
      `${counts[v]}`, el("span", { class: "sr", text: ` ${t(`verdict_${v}`)}` }))));
}

function renderCaseList() {
  const list = $("#cases");
  list.replaceChildren(...state.cases.map((c) => {
    const counts = Object.fromEntries(VERDICTS.map((v) => [v, c.report.results.filter((r) => r.verdict === v).length]));
    const btn = el("button", { type: "button", class: "case", "aria-current": String(state.current === c), "data-id": c.id },
      el("span", { class: "case-q", text: c.question }),
      el("span", { class: "case-meta" }, el("span", { text: c.model.name }), tally(counts)));
    btn.addEventListener("click", () => select(c, true));
    return el("li", {}, btn);
  }));
}

function select(c, focusResult) {
  state.current = c;
  history.replaceState(null, "", `#case=${encodeURIComponent(c.id)}`);
  document.querySelectorAll(".case").forEach((b) => b.setAttribute("aria-current", String(b.dataset.id === c.id)));
  renderCase(c);
  if (focusResult && window.matchMedia("(max-width: 59.99rem)").matches) {
    $("#result").focus({ preventScroll: true });
    $("#result").scrollIntoView({ block: "start" });
  }
}

// --- One case ---------------------------------------------------------------------------------------------------------

function answerText(c) {
  const box = el("div", { class: "answer" });
  let at = 0;
  for (const sp of c.spans) {
    if (sp.start > at) box.append(plain(c.answer.slice(at, sp.start)));
    const first = sp.claims[0];
    box.append(el("a", { class: `hl ${sp.verdict}`, href: `#claim-${first + 1}`, title: t("jump_to_claim"),
      "aria-label": `${plain(c.answer.slice(sp.start, sp.end))} (${t(`verdict_${sp.verdict}`)})` },
      plain(c.answer.slice(sp.start, sp.end))));
    at = sp.end;
  }
  if (at < c.answer.length) box.append(plain(c.answer.slice(at)));
  return box;
}

function stated(claim) {
  const v = claim.value || "";
  const u = claim.unit || "";
  // A bare number gets its unit ("48 hours per week"); a value that names its own ("RM 20 million", "6%") is shown as written.
  return u && /^[0-9.,]+$/.test(v.trim()) ? `${v} ${u}` : v;
}

function fact(cls, label, value) {
  return value ? el("div", { class: cls }, el("dt", { text: label }), el("dd", { text: value })) : null;
}

function claimCard(r, i) {
  const host = (() => { try { return new URL(r.source_url).hostname.replace(/^www\./, ""); } catch (_) { return r.source_url; } })();
  const tags = [r.source_label && t(`label_${r.source_label}`), r.cached_copy && t("flag_cached"), r.snippet_only && t("flag_snippet")]
    .filter(Boolean).map((x) => el("span", { class: "tag", text: x }));
  const quote = r.evidence_quote && r.source_url
    ? el("figure", { class: "quote" },
        el("p", { class: "quote-h", text: t("field_quote") }),
        el("blockquote", { cite: r.source_url, text: r.evidence_quote }),
        el("figcaption", {}, `${t("field_source")}: `, el("a", { href: r.source_url, rel: "noopener", text: host }),
          tags.length ? el("span", { class: "tags" }, tags) : null))
    : el("p", { class: "why", text: t("no_source") });
  return el("li", { class: "claim", id: `claim-${i + 1}` },
    el("div", { class: "claim-top" },
      el("span", { class: `badge ${r.verdict}` }, icon(r.verdict), t(`verdict_${r.verdict}`)),
      el("span", { class: "score" }, `${t("field_score")} `, el("b", { text: t("score_out_of", { score: r.score }) }))),
    el("p", { class: "claim-text", text: r.claim.claim }),
    el("dl", { class: "facts" },
      fact(r.verdict === "outdated" ? "stated" : "", t("field_stated"), stated(r.claim)),
      fact("now", t("field_official"), r.current_value),
      fact("", t("field_effective"), fmtDate(r.effective_date)),
      fact("", t("field_checked"), fmtDate(r.checked_on))),
    quote,
    r.verdict === "unverifiable" && r.reason && r.evidence_quote ? el("p", { class: "why", text: r.reason }) : null);
}

function renderCase(c) {
  const r = c.report;
  const n = Object.fromEntries(VERDICTS.map((v) => [v, r.results.filter((x) => x.verdict === v).length]));
  const asof = r.as_of_before ? t(r.as_of_mixed ? "as_of_mixed" : "as_of", { date: fmtDate(r.as_of_before) }) : "";
  $("#result").replaceChildren(...[
    el("p", { class: "run-label" }, el("b", { text: t("recorded_run", { date: fmtDate(c.run_at) }) }),
      el("span", { text: t(`source_${c.source}`) })),
    el("h2", { class: "q", text: c.question }),
    el("p", { class: "by", text: t("answer_by", { model: c.model.name, vendor: c.model.vendor }) }),
    answerText(c),
    el("p", { class: "legend" }, el("span", { text: t("legend") }),
      VERDICTS.map((v) => el("span", {}, el("i", { class: `dot ${v}`, "aria-hidden": "true" }), t(`verdict_${v}`)))),
    el("p", { class: "summary", text: t("summary", { checked: r.results.length, ...n }) }),
    asof ? el("p", { class: "asof", text: asof }) : null,
    el("p", { class: "credits", text: t("credits", { credits: r.credits }) }),
    el("h3", { class: "claims-h", text: t("claims_heading") }),
    el("ol", { class: "claims" }, r.results.map(claimCard)),
    r.not_checked.map((x) => el("p", { class: "other", text: t("not_checked", { claim: x.claim }) })),
    r.errors.map((x) => el("p", { class: "other", text: t("claim_error", { claim: x.claim.claim }) })),
  ].flat().filter(Boolean));
}

function renderFailed() {
  $("#result").replaceChildren(el("p", { class: "state", role: "alert", text: t("load_failed") }));
}

// --- Paste ------------------------------------------------------------------------------------------------------------

function onPaste(ev) {
  ev.preventDefault();
  const msg = $("#answer-msg");
  const text = normalise($("#paste").value);
  const say = (key) => { msg.dataset.key = key; msg.textContent = t(key); };
  if (!text) return say("paste_empty");
  const hit = state.cases.find((c) => normalise(c.answer) === text || normalise(plain(c.answer)) === text);
  if (!hit) return say("paste_no_match");
  say("paste_matched");
  select(hit, true);
}

// --- Start ------------------------------------------------------------------------------------------------------------

async function getJSON(path) {
  const res = await fetch(path, { cache: "no-cache" });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

async function start() {
  document.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", () => applyLang(b.dataset.lang)));
  $("#answer-form").addEventListener("submit", onPaste);
  try {
    const i18n = await getJSON("i18n.json");
    state.strings = i18n.strings;
    state.languages = i18n.languages;
  } catch (_) {
    state.languages = ["en"];
  }
  state.lang = pickLang();
  try {
    const index = await getJSON("cases/index.json");
    state.cases = await Promise.all(index.cases.map((c) => getJSON(`cases/${encodeURIComponent(c.id)}.json`)));
  } catch (_) {
    state.failed = true;
  }
  const want = decodeURIComponent((location.hash.match(/^#case=(.+)$/) || [])[1] || "");
  state.current = state.cases.find((c) => c.id === want) || state.cases[0] || null;
  applyLang(state.lang);
}

start();
