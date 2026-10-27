// Shared data loader for the LY balloon register.
//
// Paste your Google Sheet's published CSV link here:
//   File → Share → Publish to web → (choose the sheet) → Comma-separated values (.csv)
// Leave empty to use the local register.csv copy.
const SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vTWB9KoP8wProGKMzxsNqjgZOnnypSiqhgZoCKDckJJ_gVc433W7e2Nf1crqEtzjaImS6YNlAKZ8AS3/pub?gid=0&single=true&output=csv";
const LOCAL_CSV_URL = "register.csv";
const CACHE_KEY = "ly-register-v2";

const COLOR_TAGS = {
  red: "#d63a2f", "red-dark": "#8e1f1a", white: "#ffffff", blue: "#2f6fd6",
  "blue-dark": "#1b3a7a", yellow: "#f2c230", green: "#3a9a4a", "green-dark": "#1f5a2a",
  black: "#1a1a1a", orange: "#f08a24", gray: "#8a8f98", silver: "#c4c9d0",
  pink: "#ee7fb4", gold: "#c9a227", purple: "#7a3fb0", transparent: "transparent",
};

// Tag pill colours: [background, text]. Tags not listed use DEFAULT_TAG_STYLE.
const DEFAULT_TAG_STYLE = ["#F5F5F5", "#333333"];
const TAG_STYLES = {
  black: ["#F5F5F5", "#3D3D3D"],
  blue: ["#C0E1F6", "#0953A9"],
  "blue-dark": ["#0953A9", "#ADD0EE"],
  gold: ["#FFC71B", "#473821"],
  green: ["#D4EDBD", "#13734B"],
  "green-dark": ["#13734B", "#D4EDBD"],
  orange: ["#F37F09", "#FFFFFF"],
  pink: ["#FA73BC", "#FFFFFF"],
  purple: ["#BA08B3", "#FFFFFF"],
  red: ["#DD0B09", "#FFCFC9"],
  "red-dark": ["#800000", "#FFCFC9"],
  white: ["#FFFFFF", "#333333"],
  yellow: ["#FFE5A1", "#473821"],
};

// Matches with or without the leading dot of "private" tags like ".duplicate".
function tagStyle(tag) {
  return TAG_STYLES[tag.toLowerCase().replace(/^\./, "")] || DEFAULT_TAG_STYLE;
}

function tagPill(tag) {
  const [bg, fg] = tagStyle(tag);
  return el("span", { class: "tag", style: `--tag-bg:${bg};--tag-fg:${fg}` }, tag);
}

function parseCsv(text) {
  const result = Papa.parse(text, { header: true, skipEmptyLines: true });
  return result.data.filter((row) => row.id);
}

async function fetchCsv(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`);
  return parseCsv(await res.text());
}

async function loadBalloons() {
  try {
    const cached = sessionStorage.getItem(CACHE_KEY);
    if (cached) return JSON.parse(cached);
  } catch (_) {}

  let rows;
  if (SHEET_CSV_URL) {
    try {
      rows = await fetchCsv(SHEET_CSV_URL);
    } catch (err) {
      console.warn("Live sheet failed, using local copy:", err);
    }
  }
  if (!rows) rows = await fetchCsv(LOCAL_CSV_URL);

  try {
    sessionStorage.setItem(CACHE_KEY, JSON.stringify(rows));
  } catch (_) {}
  return rows;
}

function splitTags(value) {
  return (value || "").split(",").map((t) => t.trim()).filter(Boolean);
}

function colorTags(row) {
  return splitTags(row["tags"]).filter((t) => t in COLOR_TAGS);
}

function labelFor(column) {
  return column.replace(/_+$/, "");
}

function isBlank(value) {
  return value == null || value.trim() === "" || value.trim() === "-";
}

function regMark(row) {
  return isBlank(row["registration mark"]) ? "No mark" : row["registration mark"];
}

// Registration order, with balloons that have no mark at the end.
function byReg(a, b) {
  const ab = isBlank(a["registration mark"]), bb = isBlank(b["registration mark"]);
  if (ab !== bb) return ab ? 1 : -1;
  return (a["registration mark"] || a.id).localeCompare(b["registration mark"] || b.id);
}

// CAA status pills, keyed by slug: [title, background, text].
const STATUS_STYLES = {
  unregistered: ["Unregistered", "#E6E6E6", "#404040"],
  registered: ["Registered", "#CFF7BE", "#23800B"],
  "no-reg-history": ["No reg history", "#FFCFC8", "#AE0701"],
  expected: ["Expected", "#BEE1F6", "#0053AA"],
  unknown: ["?", "#E6E6E6", "#404040"],
};

// "no reg history" -> "no-reg-history"; empty, "?" or anything unlisted -> "unknown".
function statusSlug(status) {
  const slug = (status || "").trim().toLowerCase().replace(/\s+/g, "-");
  return slug in STATUS_STYLES ? slug : "unknown";
}

function statusPill(status) {
  const [title, bg, fg] = STATUS_STYLES[statusSlug(status)];
  return el("span", { class: "status", style: `--status-bg:${bg};--status-fg:${fg}` }, title);
}

// Small DOM helper: el("div", { class: "x" }, child, "text", ...)
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function swatches(row) {
  const tags = colorTags(row);
  if (!tags.length) return null;
  return el("span", { class: "swatches", title: tags.join(", ") },
    tags.map((t) => el("span", { class: "swatch", style: `--c:${COLOR_TAGS[t]}` })));
}

function balloonImage(row, className) {
  const wrap = el("div", { class: `img-wrap ${className || ""}` });
  const placeholder = () => {
    wrap.replaceChildren(el("div", { class: "img-placeholder", "aria-hidden": "true" }, balloonIcon()));
  };
  const src = imageSrc(row);
  if (!src) {
    placeholder();
  } else {
    const img = el("img", { src, alt: `${regMark(row)} balloon`, loading: "lazy" });
    img.addEventListener("error", placeholder);
    wrap.append(img);
  }
  return wrap;
}

// Photos live in images/<id>.jpg, made by prepare_images.py. The .img column
// names the original photo for that script; "n/a" means there is no photo.
const IMAGE_DIR = "images/";

function imageSrc(row) {
  if ((row[".img"] || "").trim().toLowerCase() === "n/a") return null;
  return IMAGE_DIR + encodeURIComponent(`${row.id}.jpg`);
}

// images/index.json ({ id: photo count }) is written by prepare_images.py.
async function loadPhotoIndex() {
  const key = `${CACHE_KEY}-photos`;
  try {
    const cached = sessionStorage.getItem(key);
    if (cached) return JSON.parse(cached);
  } catch (_) {}

  let index = {};
  try {
    const res = await fetch(`${IMAGE_DIR}index.json`, { cache: "no-store" });
    if (res.ok) index = await res.json();
  } catch (_) {}

  try {
    sessionStorage.setItem(key, JSON.stringify(index));
  } catch (_) {}
  return index;
}

// All photos for a balloon: the cover <id>.jpg, then <id>-2.jpg, <id>-3.jpg, ...
function photoSrcs(row, index) {
  const cover = imageSrc(row);
  if (!cover) return [];
  const count = index[row.id] || 1;
  const srcs = [cover];
  for (let n = 2; n <= count; n++) srcs.push(photoSrc(row.id, n));
  return srcs;
}

function photoSrc(id, n) {
  return IMAGE_DIR + encodeURIComponent(`${id}-${n}.jpg`);
}

// Try <id>-n.jpg, <id>-(n+1).jpg, ... and report each one that exists, stopping at the first gap.
function findMorePhotos(id, n, onFound, limit = 30) {
  if (n > limit) return;
  const src = photoSrc(id, n);
  const probe = new Image();
  probe.onload = () => { onFound(src); findMorePhotos(id, n + 1, onFound, limit); };
  probe.src = src;
}

function balloonIcon() {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 32");
  svg.innerHTML =
    '<path d="M12 1C6 1 2 5.5 2 11c0 5 4 9 7 12h6c3-3 7-7 7-12 0-5.5-4-10-10-10z" fill="none" stroke="currentColor" stroke-width="1.4"/>' +
    '<path d="M12 1c-3 2.5-4 6-4 10 0 4 1 8 1 12M12 1c3 2.5 4 6 4 10 0 4-1 8-1 12" fill="none" stroke="currentColor" stroke-width="1"/>' +
    '<path d="M9 23l.5 4M15 23l-.5 4" stroke="currentColor" stroke-width="1"/>' +
    '<rect x="9" y="27" width="6" height="4" rx="1" fill="none" stroke="currentColor" stroke-width="1.4"/>';
  return svg;
}
