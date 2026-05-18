/* ════════════════════════════════════════════════
   FIFA 2026 Sticker Exchange — Frontend
════════════════════════════════════════════════ */

// ── State ─────────────────────────────────────
let token       = localStorage.getItem("se_token") || null;
let currentUser = null;
let myStickers  = [];
let collectionTab = "all";

// ── API helper ────────────────────────────────
async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (token) opts.headers["Authorization"] = "Bearer " + token;
  if (body)  opts.body = JSON.stringify(body);
  const res  = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Something went wrong");
  return data;
}

// ── Bootstrap ─────────────────────────────────
window.addEventListener("DOMContentLoaded", async () => {
  if (token) {
    try {
      currentUser = await api("GET", "/api/me");
      enterApp();
    } catch {
      token = null;
      localStorage.removeItem("se_token");
      showAuth();
    }
  } else {
    showAuth();
  }
});

// ── Auth ──────────────────────────────────────
function showAuth() {
  document.getElementById("header").style.display = "none";
  showOnly("page-auth");
}

function enterApp() {
  document.getElementById("header").style.display = "flex";
  document.getElementById("user-pill").textContent = "👤 " + currentUser.name;
  updatePendingBadge(currentUser.pending_swaps || 0);
  showPage("collection");
}

function toggleAuth(mode) {
  document.getElementById("auth-login").style.display    = mode === "login"    ? "" : "none";
  document.getElementById("auth-register").style.display = mode === "register" ? "" : "none";
}

async function doLogin() {
  clearAlert("login-alert");
  try {
    const data = await api("POST", "/api/login", {
      username: v("login-username"),
      password: v("login-password")
    });
    token = data.token;
    currentUser = data.user;
    localStorage.setItem("se_token", token);
    enterApp();
  } catch (e) { showAlert("login-alert", e.message, "error"); }
}

async function doRegister() {
  clearAlert("register-alert");
  const code = document.getElementById("reg-code").value.trim().toUpperCase();
  try {
    const data = await api("POST", "/api/register", {
      invite_code: code,
      name:        v("reg-name"),
      username:    v("reg-username"),
      password:    v("reg-password")
    });
    token = data.token;
    currentUser = data.user;
    localStorage.setItem("se_token", token);
    enterApp();
  } catch (e) { showAlert("register-alert", e.message, "error"); }
}

async function logout() {
  try { await api("POST", "/api/logout"); } catch {}
  token = null; currentUser = null; myStickers = [];
  localStorage.removeItem("se_token");
  showAuth();
}

// ── Page routing ──────────────────────────────
function showPage(page) {
  ["collection","add","exchanges","swaps","friends"].forEach(p => {
    document.getElementById("page-"+p).style.display = p === page ? "" : "none";
  });
  document.querySelectorAll("nav button[data-page]").forEach(b =>
    b.classList.toggle("active", b.dataset.page === page)
  );
  if (page === "collection") refreshCollection();
  if (page === "exchanges")  refreshExchanges();
  if (page === "swaps")      refreshSwaps();
  if (page === "friends")    refreshFriends();
  if (page === "add")        document.getElementById("add-preview").innerHTML = renderStickersGrid(myStickers, false);
}

function showOnly(id) {
  ["page-auth","page-collection","page-add","page-exchanges","page-swaps","page-friends"].forEach(p =>
    document.getElementById(p).style.display = p === id ? "" : "none"
  );
}

function updatePendingBadge(n) {
  const el = document.getElementById("badge-swaps");
  if (n > 0) { el.textContent = n; el.style.display = ""; }
  else        { el.style.display = "none"; }
}

// ── Collection ────────────────────────────────
async function refreshCollection() {
  document.getElementById("collection-content").innerHTML =
    '<div class="empty-state"><div class="spinner"></div></div>';
  try {
    myStickers = await api("GET", "/api/stickers");
    renderCollection();
  } catch (e) {
    document.getElementById("collection-content").innerHTML =
      `<div class="alert alert-error">${e.message}</div>`;
  }
}

function switchCollectionTab(tab, btn) {
  collectionTab = tab;
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  renderCollection();
}

function renderCollection() {
  const unique = myStickers.length;
  const total  = myStickers.reduce((s,x) => s + x.quantity, 0);
  const dupes  = myStickers.filter(x => x.quantity > 1).length;
  document.getElementById("stat-unique").textContent = unique;
  document.getElementById("stat-total").textContent  = total;
  document.getElementById("stat-dupes").textContent  = dupes;

  let list = collectionTab === "dupes"
    ? myStickers.filter(x => x.quantity > 1)
    : myStickers;

  const el = document.getElementById("collection-content");
  if (!list.length) {
    el.innerHTML = unique === 0
      ? `<div class="empty-state"><div class="icon">📦</div><p>No stickers yet. Go to <strong>Add Stickers</strong>!</p></div>`
      : `<div class="empty-state"><div class="icon">✨</div><p>No duplicates yet — every sticker appears just once.</p></div>`;
    return;
  }
  el.innerHTML = renderStickersGrid(list, true);
}

function renderStickersGrid(stickers, withDelete) {
  if (!stickers.length) return "";
  const sorted = [...stickers].sort((a,b) => naturalSort(a.number, b.number));
  return `<div class="sticker-grid">${sorted.map(s => `
    <div class="sticker-badge ${s.quantity>1?"duplicate":""}">
      <span class="num">${esc(s.number)}</span>
      <span class="qty ${s.quantity===1?"single":""}">x${s.quantity}</span>
      ${withDelete ? `<button class="del-btn" onclick="deleteSticker('${esc(s.number)}')" title="Remove">✕</button>` : ""}
    </div>`).join("")}</div>`;
}

async function deleteSticker(number) {
  if (!confirm(`Remove sticker #${number}?`)) return;
  try {
    await api("DELETE", `/api/stickers/${encodeURIComponent(number)}`);
    myStickers = myStickers.filter(s => s.number !== number);
    renderCollection();
  } catch (e) { alert(e.message); }
}

// ── Add stickers ──────────────────────────────
function switchMode(mode, btn) {
  document.querySelectorAll(".mode-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  document.getElementById("mode-single").style.display = mode === "single" ? "" : "none";
  document.getElementById("mode-bulk").style.display   = mode === "bulk"   ? "" : "none";
}

async function addStickers() {
  clearAlert("add-alert");
  const raw = v("sticker-input");
  if (!raw) return showAlert("add-alert", "Enter at least one sticker number.", "error");
  const parsed = parseSingleInput(raw);
  if (!parsed.length) return showAlert("add-alert", "Couldn't parse those numbers.", "error");
  try {
    const data = await api("POST", "/api/stickers", { stickers: parsed });
    myStickers = data.stickers;
    document.getElementById("sticker-input").value = "";
    showAlert("add-alert", `✅ Added ${data.added} sticker type(s)!`, "success");
    document.getElementById("add-preview").innerHTML = renderStickersGrid(myStickers, false);
  } catch (e) { showAlert("add-alert", e.message, "error"); }
}

async function addBulk() {
  clearAlert("bulk-alert");
  const raw = document.getElementById("bulk-input").value;
  if (!raw.trim()) return showAlert("bulk-alert", "Paste some sticker numbers first.", "error");
  const parsed = parseBulkInput(raw);
  if (!parsed.length) return showAlert("bulk-alert", "No valid numbers found.", "error");
  try {
    const data = await api("POST", "/api/stickers", { stickers: parsed });
    myStickers = data.stickers;
    document.getElementById("bulk-input").value = "";
    showAlert("bulk-alert", `✅ Added ${data.added} sticker type(s)!`, "success");
    document.getElementById("add-preview").innerHTML = renderStickersGrid(myStickers, false);
  } catch (e) { showAlert("bulk-alert", e.message, "error"); }
}

function parseSingleInput(raw) {
  const result = [];
  for (const part of raw.split(/[,\s]+/).filter(Boolean)) {
    const range = part.match(/^(\d+)-(\d+)$/);
    if (range) {
      let [a, b] = [parseInt(range[1]), parseInt(range[2])];
      if (a > b) [a,b] = [b,a];
      if (b-a <= 500) for (let i=a; i<=b; i++) result.push(String(i));
      continue;
    }
    const mult = part.match(/^([A-Za-z0-9-]+)[xX](\d+)$/);
    if (mult) {
      const n = mult[1].toUpperCase(), q = Math.min(parseInt(mult[2]), 100);
      for (let i=0; i<q; i++) result.push(n);
      continue;
    }
    if (/^[A-Za-z0-9-]+$/.test(part)) result.push(part.toUpperCase());
  }
  return result;
}

function parseBulkInput(raw) {
  return parseSingleInput(raw.replace(/\n/g," ").replace(/\t/g," "));
}

// ── Exchange suggestions ───────────────────────
async function refreshExchanges() {
  document.getElementById("exchanges-content").innerHTML =
    '<div class="empty-state"><div class="spinner"></div></div>';
  try {
    const data = await api("GET", "/api/exchanges");
    renderExchanges(data);
  } catch (e) {
    document.getElementById("exchanges-content").innerHTML =
      `<div class="alert alert-error">${e.message}</div>`;
  }
}

function renderExchanges(list) {
  const el = document.getElementById("exchanges-content");
  if (!list.length) {
    el.innerHTML = `<div class="empty-state"><div class="icon">🤝</div>
      <p>No exchange opportunities yet.<br>Make sure you and your friends have added your collections!</p></div>`;
    return;
  }
  el.innerHTML = list.map(opp => {
    const initial = (opp.name||"?")[0].toUpperCase();
    const hasOpen = opp.open_swap;

    const giveHtml = opp.i_can_give.length
      ? opp.i_can_give.map(n=>`<span class="sticker-pill give">${esc(n)}</span>`).join("")
      : `<span class="no-pills">nothing right now</span>`;
    const wantHtml = opp.they_can_give.length
      ? opp.they_can_give.map(n=>`<span class="sticker-pill want">${esc(n)}</span>`).join("")
      : `<span class="no-pills">nothing right now</span>`;

    let actionBtn = "";
    if (hasOpen) {
      const statusLabel = {proposed:"Pending…", accepted:"Accepted ✓", done:"Done"}[hasOpen.status] || hasOpen.status;
      actionBtn = `<button class="btn btn-ghost btn-sm" onclick="showPage('swaps')">
        📋 Swap ${statusLabel}
      </button>`;
    } else {
      actionBtn = `<button class="btn btn-success btn-sm" onclick="proposeSwap(${opp.user_id})">
        📤 Propose Swap
      </button>`;
    }

    return `
    <div class="exchange-card">
      <div class="ec-header">
        <div class="avatar">${initial}</div>
        <div>
          <div class="ec-name">${esc(opp.name)}</div>
          <div class="ec-sub">@${esc(opp.username)}</div>
        </div>
        <div class="ec-score">${opp.score} sticker${opp.score!==1?"s":""} to swap</div>
        ${actionBtn}
      </div>
      <div class="exchange-grid">
        <div class="exchange-col give">
          <h4>📤 You give them (${opp.i_can_give.length})</h4>
          <div class="sticker-pills">${giveHtml}</div>
        </div>
        <div class="exchange-col want">
          <h4>📥 They give you (${opp.they_can_give.length})</h4>
          <div class="sticker-pills">${wantHtml}</div>
        </div>
      </div>
    </div>`;
  }).join("");
}

async function proposeSwap(otherId) {
  try {
    await api("POST", "/api/swaps", { other_user_id: otherId });
    showAlert_toast("✅ Swap proposal sent!");
    refreshExchanges();
    showPage("swaps");
  } catch (e) { alert(e.message); }
}

// ── My Swaps ──────────────────────────────────
async function refreshSwaps() {
  document.getElementById("swaps-content").innerHTML =
    '<div class="empty-state"><div class="spinner"></div></div>';
  try {
    const data = await api("GET", "/api/swaps");
    // refresh pending count
    const me = await api("GET", "/api/me");
    updatePendingBadge(me.pending_swaps || 0);
    renderSwaps(data);
  } catch (e) {
    document.getElementById("swaps-content").innerHTML =
      `<div class="alert alert-error">${e.message}</div>`;
  }
}

function renderSwaps(list) {
  const el = document.getElementById("swaps-content");
  if (!list.length) {
    el.innerHTML = `<div class="empty-state"><div class="icon">📬</div>
      <p>No swaps yet.<br>Go to <strong>Find Swaps</strong> to propose one!</p></div>`;
    return;
  }

  const active  = list.filter(s => !["done","cancelled"].includes(s.status));
  const history = list.filter(s =>  ["done","cancelled"].includes(s.status));

  let html = "";

  if (active.length) {
    html += `<div class="section-title" style="margin-bottom:14px">Active swaps</div>`;
    html += active.map(s => swapCard(s)).join("");
  }

  if (history.length) {
    html += `<div class="section-title" style="margin-top:28px;margin-bottom:14px">History</div>`;
    html += history.map(s => swapCard(s)).join("");
  }

  el.innerHTML = html;
}

function swapCard(swap) {
  const initial = (swap.other_name||"?")[0].toUpperCase();
  const iGive   = swap.i_am_a ? swap.a_gives : swap.b_gives;
  const iGet    = swap.i_am_a ? swap.b_gives : swap.a_gives;
  const iProposed = swap.i_am_a;

  const STATUS = {
    proposed: { label:"⏳ Awaiting acceptance", color:"var(--muted)" },
    accepted: { label:"✅ Accepted — prepare envelopes", color:"var(--green)" },
    done:     { label:"🏆 Completed", color:"var(--accent)" },
    cancelled:{ label:"❌ Cancelled", color:"var(--red)" },
  };
  const st = STATUS[swap.status] || { label: swap.status, color: "var(--muted)" };

  // Action buttons based on state
  let actions = "";
  if (swap.status === "proposed" && !iProposed) {
    // I am user_b and can accept
    actions = `
      <button class="btn btn-success btn-sm" onclick="swapAction(${swap.id},'accept')">✅ Accept</button>
      <button class="btn btn-danger btn-sm"  onclick="swapAction(${swap.id},'cancel')">✗ Decline</button>`;
  } else if (swap.status === "proposed" && iProposed) {
    actions = `<button class="btn btn-ghost btn-sm" onclick="swapAction(${swap.id},'cancel')">↩ Cancel proposal</button>`;
  } else if (swap.status === "accepted") {
    actions = `<button class="btn btn-primary btn-sm" onclick="swapAction(${swap.id},'complete')">🏁 Mark as done</button>`;
  }

  // The swap code block — shown when accepted
  let codeBlock = "";
  if (swap.swap_code && swap.status !== "done" && swap.status !== "cancelled") {
    codeBlock = `
    <div class="swap-code-block">
      <div class="swap-code-label">✉️ Write this code on both envelopes / pouches:</div>
      <div class="swap-code">${esc(swap.swap_code)}</div>
      <div class="swap-code-hint">Put your stickers in an envelope, write the code on it, and hand it to <strong>${esc(swap.other_name)}</strong>.</div>
    </div>`;
  }

  return `
  <div class="swap-card">
    <div class="ec-header">
      <div class="avatar">${initial}</div>
      <div>
        <div class="ec-name">${esc(swap.other_name)}</div>
        <div class="ec-sub">@${esc(swap.other_username)}</div>
      </div>
      <div class="swap-status" style="color:${st.color}">${st.label}</div>
    </div>

    ${codeBlock}

    <div class="exchange-grid" style="margin-top:${codeBlock?"16px":"0"}">
      <div class="exchange-col give">
        <h4>📤 You give (${iGive.length})</h4>
        <div class="sticker-pills">
          ${iGive.length ? iGive.map(n=>`<span class="sticker-pill give">${esc(n)}</span>`).join("") : '<span class="no-pills">none</span>'}
        </div>
      </div>
      <div class="exchange-col want">
        <h4>📥 You get (${iGet.length})</h4>
        <div class="sticker-pills">
          ${iGet.length ? iGet.map(n=>`<span class="sticker-pill want">${esc(n)}</span>`).join("") : '<span class="no-pills">none</span>'}
        </div>
      </div>
    </div>

    ${actions ? `<div class="swap-actions">${actions}</div>` : ""}
  </div>`;
}

async function swapAction(id, action) {
  const labels = { accept:"accept this swap?", complete:"mark this swap as done?\n(Both collections will be updated automatically)", cancel:"cancel this swap?" };
  if (!confirm(`Are you sure you want to ${labels[action]}`)) return;
  try {
    await api("POST", `/api/swaps/${id}/${action}`);
    refreshSwaps();
    if (action === "complete") {
      myStickers = await api("GET", "/api/stickers");
    }
  } catch (e) { alert(e.message); }
}

// ── Friends ───────────────────────────────────
async function refreshFriends() {
  document.getElementById("friends-content").innerHTML =
    '<div class="empty-state"><div class="spinner"></div></div>';
  try {
    const data = await api("GET", "/api/users");
    renderFriends(data);
  } catch (e) {
    document.getElementById("friends-content").innerHTML =
      `<div class="alert alert-error">${e.message}</div>`;
  }
}

function renderFriends(users) {
  const el = document.getElementById("friends-content");
  if (!users.length) {
    el.innerHTML = `<div class="empty-state"><div class="icon">👥</div><p>No one registered yet.</p></div>`;
    return;
  }
  el.innerHTML = `<div class="users-list">${users.map(u => {
    const isMe = currentUser && u.id === currentUser.id;
    return `<div class="user-row">
      <div class="avatar">${(u.name||"?")[0].toUpperCase()}</div>
      <div class="info">
        <div class="uname">${esc(u.name)} ${isMe?'<span class="me-badge">You</span>':""}</div>
        <div class="ustats">@${esc(u.username)} · ${u.unique_stickers} unique · ${u.total_stickers} total</div>
      </div>
    </div>`;
  }).join("")}</div>`;
}

// ── Utilities ─────────────────────────────────
function v(id)  { return document.getElementById(id).value.trim(); }
function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
}
function showAlert(id, msg, type) {
  document.getElementById(id).innerHTML =
    `<div class="alert alert-${type==="error"?"error":"success"}">${msg}</div>`;
}
function clearAlert(id) { document.getElementById(id).innerHTML = ""; }
function naturalSort(a, b) {
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
}

let _toastTimer;
function showAlert_toast(msg) {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    el.style.cssText = "position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:var(--green);color:#111;padding:12px 24px;border-radius:8px;font-weight:600;z-index:9999;box-shadow:0 4px 16px rgba(0,0,0,.4)";
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.style.display = "block";
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { el.style.display = "none"; }, 2800);
}
