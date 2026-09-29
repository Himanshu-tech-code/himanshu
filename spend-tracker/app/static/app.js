let csrf = null, CATS = [];
const $ = id => document.getElementById(id);
const money = c => (c / 100).toLocaleString(undefined, {style: "currency", currency: "USD"});

function el(tag, props = {}, ...kids) {              // textContent only: no HTML injection
  const n = Object.assign(document.createElement(tag), props);
  kids.forEach(k => n.append(k));
  return n;
}
async function api(path, method = "GET", body) {
  const r = await fetch("/api" + path, {
    method, credentials: "same-origin",
    headers: {"Content-Type": "application/json", ...(csrf ? {"X-CSRF-Token": csrf} : {})},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (r.status === 401 && path !== "/login") { show(false); throw new Error("locked"); }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}
function show(authed) { $("login").hidden = authed; $("app").hidden = !authed; }

async function boot() {
  const s = await api("/session");
  csrf = s.csrf;
  show(s.authenticated);
  if (s.authenticated) init();
}
$("login-form").onsubmit = async e => {
  e.preventDefault();
  try { csrf = (await api("/login", "POST", {password: $("pw").value})).csrf; $("pw").value = ""; show(true); init(); }
  catch (err) { $("login-err").textContent = err.message; }
};
$("logout").onclick = async () => { await api("/logout", "POST"); csrf = null; show(false); };

async function init() {
  CATS = await api("/categories");
  for (const id of ["cat", "rule-cat"]) {
    const sel = $(id); sel.querySelectorAll("option:not([value=''])").forEach(o => o.remove());
    CATS.forEach(c => sel.append(el("option", {value: c, textContent: c})));
  }
  const months = await api("/months");
  const cur = new Date().toISOString().slice(0, 7);
  if (!months.includes(cur)) months.unshift(cur);
  $("month").replaceChildren(...months.map(m => el("option", {value: m, textContent: m})));
  await Promise.all([refresh(), loadAccounts(), loadRules()]);
}

async function refresh() {
  const m = $("month").value, cat = $("cat").value, q = $("search").value;
  const [sum, txns] = await Promise.all([
    api("/summary?month=" + m),
    api(`/transactions?month=${m}&category=${encodeURIComponent(cat)}&q=${encodeURIComponent(q)}`),
  ]);
  $("spent").textContent = money(sum.spend_cents);
  $("income").textContent = money(sum.income_cents);
  const max = Math.max(1, ...sum.by_category.map(r => Math.abs(r.cents)));
  $("breakdown").replaceChildren(...sum.by_category.map(r => {
    const bar = el("i"); bar.style.width = Math.max(0, r.cents) / max * 100 + "%";
    return el("div", {className: "bar-row"}, el("span", {textContent: r.category}),
              el("div", {className: "bar"}, bar), el("span", {className: "r", textContent: money(r.cents)}));
  }));
  $("txns").replaceChildren(...txns.map(t => {
    const sel = el("select");
    CATS.forEach(c => sel.append(el("option", {value: c, textContent: c, selected: c === t.category})));
    sel.onchange = async () => {
      const rule = confirm(`Always categorize "${t.merchant || t.name}" as ${sel.value}?`);
      await api("/transactions/" + encodeURIComponent(t.txn_id), "PATCH", {category: sel.value, create_rule: rule});
      refresh(); loadRules();
    };
    return el("tr", {className: t.pending ? "pend" : ""},
      el("td", {textContent: t.date}), el("td", {textContent: t.merchant || t.name}),
      el("td", {textContent: `${t.account_name || ""} ${t.mask ? "••" + t.mask : ""}`}),
      el("td", {className: "r" + (t.amount_cents < 0 ? " in" : ""), textContent: money(-t.amount_cents)}),
      el("td", {}, sel));
  }));
}
["month", "cat"].forEach(id => $(id).onchange = refresh);
$("search").oninput = () => { clearTimeout($("search")._t); $("search")._t = setTimeout(refresh, 250); };

async function loadAccounts() {
  const rows = await api("/accounts"), seen = new Set(), out = [];
  for (const r of rows) {
    if (!seen.has(r.item_id)) {
      seen.add(r.item_id);
      const b = el("button", {className: "ghost", textContent: "Disconnect"});
      b.onclick = async () => { if (confirm("Revoke access to " + r.institution + "?")) { await api("/items/" + r.item_id, "DELETE"); init(); } };
      out.push(el("div", {className: "row"}, el("b", {textContent: `${r.institution} (synced ${r.last_synced_at || "never"})`}), b));
    }
    if (r.account_id) out.push(el("div", {className: "row", textContent: `${r.name} ••${r.mask || ""}`}));
  }
  $("accounts").replaceChildren(...out);
}
async function loadRules() {
  const rules = await api("/rules");
  $("rules").replaceChildren(...rules.map(r => {
    const b = el("button", {className: "ghost", textContent: "Remove"});
    b.onclick = async () => { await api("/rules/" + r.id, "DELETE"); refresh(); loadRules(); };
    return el("div", {className: "row"}, el("span", {textContent: `"${r.pattern}" → ${r.category}`}), b);
  }));
}
$("rule-form").onsubmit = async e => {
  e.preventDefault();
  await api("/rules", "POST", {pattern: $("rule-pattern").value, category: $("rule-cat").value});
  $("rule-pattern").value = ""; refresh(); loadRules();
};
$("sync").onclick = async () => { $("sync").textContent = "Syncing…"; await api("/sync", "POST"); $("sync").textContent = "Sync now"; init(); };
$("connect").onclick = async () => {
  const {link_token} = await api("/link-token", "POST");
  Plaid.create({
    token: link_token,
    onSuccess: async (public_token, meta) => {
      await api("/exchange", "POST", {public_token, institution_name: meta.institution?.name || "Bank"});
      setTimeout(init, 3000);
    },
  }).open();
};
boot();
