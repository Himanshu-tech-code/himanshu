#!/usr/bin/env python3
"""Trade report: one visual HTML page per run, built from the trader/ files.

    python3 report.py collect TSLA            # bundle today's files + charts -> trader/runs/TSLA.json
    python3 report.py build TSLA NVDA --out trader/report.html

`collect` runs right after a ticker's pipeline (the pipeline files are per
ticker and get overwritten by the next one). `build` renders every collected
ticker into one page with an overall signal, indicators, charts and the plan.
Standard library only. The signal is a rules read of the data, not advice.
"""
import argparse
import html
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

UA = "day-trader-skill/2.0 (trader-report)"
RUNS = "trader/runs"


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- data

def fetch_chart(sym, interval, rng):
    res, err = None, None
    for attempt, host in enumerate(("query2", "query2", "query1", "query1")):
        if attempt:
            time.sleep(2 * attempt)
        url = ("https://%s.finance.yahoo.com/v8/finance/chart/%s?interval=%s&range=%s"
               % (host, sym.replace(".", "-"), interval, rng))
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                res = json.load(r)["chart"]["result"][0]
            break
        except urllib.error.HTTPError as exc:
            err = str(exc)[:200]
            if exc.code != 429 and exc.code < 500:
                break
        except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            err = str(exc)[:200]
    if res is None:
        return {"error": err}
    meta = res.get("meta", {})
    q = (res.get("indicators", {}).get("quote") or [{}])[0]
    off = int(meta.get("gmtoffset") or 0)
    bars = []
    for i, ts in enumerate(res.get("timestamp") or []):
        o, h, l, c, v = (q.get(k, [None])[i] if i < len(q.get(k, [])) else None
                         for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, l, c):
            continue
        local = datetime.fromtimestamp(ts + off, tz=timezone.utc)
        bars.append({"t": local.strftime("%Y-%m-%d %H:%M"), "o": round(o, 4), "h": round(h, 4),
                     "l": round(l, 4), "c": round(c, 4), "v": v or 0})
    period = (meta.get("currentTradingPeriod") or {})
    return {"price": meta.get("regularMarketPrice"), "prev_close": meta.get("chartPreviousClose"),
            "previous_close": meta.get("previousClose"), "name": meta.get("longName") or meta.get("shortName"),
            "period": period, "bars": bars, "fetched_at": int(time.time())}


def market_state(intraday):
    p = (intraday or {}).get("period") or {}
    if not p:
        return "unknown"
    now = time.time()
    reg = p.get("regular") or {}
    if reg.get("start") and reg.get("end"):
        if reg["start"] <= now < reg["end"]:
            return "open"
        pre = p.get("pre") or {}
        if pre.get("start") and pre["start"] <= now < reg["start"]:
            return "pre-market"
        post = p.get("post") or {}
        if post.get("end") and reg["end"] <= now < post["end"]:
            return "after-hours"
    return "closed"


def collect(sym):
    sym = sym.upper()
    entry = load("trader/entry.json")
    if not entry or entry.get("symbol") != sym:
        entry = None
    triggered = bool(entry and entry.get("status") == "triggered")
    plan = load("trader/plan.json") if triggered else None
    if plan and (plan.get("symbol") != sym or plan.get("date") != entry.get("date")):
        plan = None
    tm = load("trader/timemachine.json") if plan else None
    if tm and (tm.get("plan") or {}).get("symbol") != sym:
        tm = None
    if tm:
        tm.get("mc", {}).pop("sample_paths", None)
    orders = load("trader/orders.json") if plan else None
    order = None
    if orders:
        order = next((o for o in orders.get("orders", []) if o.get("symbol") == sym), None)
    risk_doc = load("trader/risk-%s.json" % sym) if plan else None
    risk = None
    if risk_doc:
        risk = next((r for r in risk_doc.get("results", []) if r.get("symbol") == sym), None)
        if risk is not None:
            risk = dict(risk, cash_after=risk_doc.get("cash_after"), today=risk_doc.get("today"))
    news = load("trader/news-%s.json" % sym)
    facts_doc = load("trader/facts-%s.json" % sym)
    facts = None
    if isinstance(facts_doc, list):
        facts = next((f for f in facts_doc if f.get("ticker") == sym), None)
    watch = load("trader/watchlist.json")
    scan = None
    if watch and watch.get("mode") == "daily":
        hit = next((h for h in watch.get("hits", []) if h.get("symbol") == sym), None)
        scan = {"as_of": watch.get("as_of"), "hit": hit, "scanned": watch.get("scanned")}
    intraday = fetch_chart(sym, "5m", "1d")
    daily = fetch_chart(sym, "1d", "6mo")
    bundle = {"symbol": sym, "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "market": market_state(intraday), "entry": entry, "plan": plan, "timemachine": tm,
              "order": order, "orders_note": (orders or {}).get("note"), "risk": risk, "news": news,
              "facts": facts, "scan": scan, "intraday": intraday, "daily": daily}
    os.makedirs(RUNS, exist_ok=True)
    out = os.path.join(RUNS, "%s.json" % sym)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(bundle, fh)
    print("Collected %s -> %s (market %s, entry %s)" % (sym, out, bundle["market"],
                                                       (entry or {}).get("status", "none")))
    return 0


# ---------------------------------------------------------------- format

def esc(s):
    return html.escape("" if s is None else str(s), quote=True)


def money(x, cents=True):
    if x is None:
        return "–"
    return ("$%s" % format(x, ",.2f")) if cents else ("$%s" % format(round(x), ","))


def big_money(x):
    if x is None:
        return "–"
    a = abs(x)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if a >= div:
            return "%s$%.2f%s" % ("-" if x < 0 else "", a / div, suf)
    return money(x)


def pct(x, signed=True, digits=1):
    if x is None:
        return "–"
    return ("%+.*f%%" if signed else "%.*f%%") % (digits, x)


def safe_url(u):
    u = str(u or "")
    return u if u.startswith("https://") or u.startswith("http://") else ""


def hm(t):
    """'2026-11-02 10:25' or '10:25' or '10:25 AM' -> minutes since midnight."""
    s = str(t).strip()
    if " " in s and "-" in s.split(" ")[0]:
        s = s.split(" ", 1)[1]
    ampm = None
    if s.upper().endswith(("AM", "PM")):
        ampm = s[-2:].upper()
        s = s[:-2].strip()
    h, m = s.split(":")[:2]
    h, m = int(h), int(m)
    if ampm == "PM" and h != 12:
        h += 12
    if ampm == "AM" and h == 12:
        h = 0
    return h * 60 + m


def clock_label(minutes):
    h, m = divmod(minutes, 60)
    return "%d:%02d" % (h if h <= 12 else h - 12, m)


# ---------------------------------------------------------------- signal

def earnings_heat(news):
    items = (news or {}).get("items") or []
    return [i for i in items if "earnings" in (i.get("tags") or [])]


def read_signal(b):
    """Return (key, label, headline, advice, reasons, indicators)."""
    entry, plan, tm, risk = b.get("entry"), b.get("plan"), b.get("timemachine"), b.get("risk")
    status = (entry or {}).get("status")
    ind = []
    reasons = []
    intraday = b.get("intraday") or {}
    price, prev = intraday.get("price"), intraday.get("prev_close") or intraday.get("previous_close")
    chg = ((price - prev) / prev * 100) if price and prev else None

    # momentum vs 20-day average
    closes = [x["c"] for x in (b.get("daily") or {}).get("bars", [])]
    trend = None
    if len(closes) >= 21 and price:
        sma20 = sum(closes[-20:]) / 20
        hi20 = max(closes[-21:-1])
        trend = {"sma20": sma20, "hi20": hi20, "above": price >= sma20}
        state = "good" if price >= sma20 else "bad"
        ind.append(("Trend", "Above 20-day avg" if price >= sma20 else "Below 20-day avg", state,
                    "Price %s vs 20-day average %s" % (money(price), money(sma20))))

    # entry
    if status == "triggered":
        ind.append(("Entry", "Triggered", "good", "%s at %s" % (entry.get("time"), money(entry.get("price")))))
    elif status == "waiting":
        lvl = entry.get("level") or (entry.get("opening_range") or {}).get("high")
        ind.append(("Entry", "Waiting", "neutral",
                    "Needs a 5-min close above %s" % money(lvl) if lvl else "Waiting for the breakout"))
    elif status == "expired":
        ind.append(("Entry", "Expired", "bad", "No breakout before the cutoff"))
    else:
        ind.append(("Entry", "No signal", "neutral", (entry or {}).get("reason") or "Entry check not run"))

    # odds & expectancy
    mc = (tm or {}).get("mc") or {}
    hist = (tm or {}).get("history") or {}
    score = 0
    if mc:
        pt, ps = mc.get("p_target", 0), mc.get("p_stop", 0)
        share = pt / (pt + ps) if (pt + ps) else 0
        need = 1 / (1 + (mc.get("r_at_target") or 2))
        st = "good" if share >= need + 0.07 else ("bad" if share < need - 0.05 else "warn")
        score += {"good": 1, "bad": -1}.get(st, 0)
        ind.append(("Odds", "%.0f%% target · %.0f%% stop" % (pt * 100, ps * 100), st,
                    "Target comes first in %.0f%% of decided replays; break-even is %.0f%%"
                    % (share * 100, need * 100)))
        if st == "bad":
            reasons.append("The stop is hit first far more often than the target (%.1f%% vs %.1f%%)."
                           % (ps * 100, pt * 100))
        elif st == "good":
            reasons.append("The target comes first often enough to beat break-even.")
        avg = mc.get("avg_R")
        st = "good" if avg is not None and avg > 0.1 else ("bad" if avg is not None and avg < -0.05 else "warn")
        score += {"good": 1, "bad": -1}.get(st, 0)
        ind.append(("Simulated edge", "%+.2f R per trade" % (avg or 0), st,
                    "Average result over %s replays" % format(mc.get("replays", 0), ",")))
    if hist.get("triggered"):
        havg = hist.get("avg_R")
        n = hist["triggered"]
        st = "good" if havg > 0.1 else ("bad" if havg < -0.05 else "warn")
        if n >= 10:
            score += {"good": 1, "bad": -1}.get(st, 0)
        ind.append(("Track record", "%+.2f R over %d trades" % (havg, n), st,
                    "%d target · %d stop · %d neither, last %d sessions"
                    % (hist.get("target", 0), hist.get("stop", 0), hist.get("close", 0), hist.get("sessions", 0))))
        if st == "bad" and n >= 10:
            reasons.append("The same setup lost on average over its last %d appearances (%+.2f R)." % (n, havg))
        elif st == "good" and n >= 10:
            reasons.append("The same setup made money on average over its last %d appearances." % n)

    # risk
    if risk:
        v = risk.get("verdict")
        ind.append(("Risk check", v, "good" if v == "PASS" else "bad",
                    "; ".join(risk.get("reasons") or []) or "Max loss %s, reward:risk %.1f"
                    % (money(risk.get("max_loss")), risk.get("reward_risk") or 0)))

    # event risk
    earn = earnings_heat(b.get("news"))
    if earn:
        st = "warn" if len(earn) >= 2 else "neutral"
        if st == "warn":
            score -= 1
            reasons.append("Earnings are in the headlines (%d stories). A report inside the trade "
                           "can gap the price straight past the stop." % len(earn))
        ind.append(("Event risk", "Earnings in the news", st, "%d earnings-tagged headlines in 24 hours" % len(earn)))
    else:
        ind.append(("Event risk", "Nothing flagged", "good", "No earnings-tagged headlines in 24 hours"))

    if chg is not None:
        ind.insert(0, ("Today", pct(chg), "good" if chg >= 0 else "bad",
                       "%s vs previous close %s" % (money(price), money(prev))))

    # verdict
    market = b.get("market")
    if status == "triggered" and risk and risk.get("verdict") != "PASS":
        return ("bad", "Skip", "The risk rules block this trade.",
                "Do not place it. " + " ".join(risk.get("reasons") or []), reasons, ind)
    if status == "triggered" and mc:
        if score >= 2:
            return ("good", "Favorable", "The entry triggered and the numbers back it.",
                    "The plan fits your rules and the odds favor it. If you take it, use the bracket "
                    "order exactly as sized and be flat by %s." % (plan or {}).get("flat_by", "15:55"),
                    reasons, ind)
        if score >= 0:
            return ("warn", "Mixed", "The entry triggered, but the evidence is split.",
                    "Only take it at the planned size or smaller, and respect the stop. Waiting for a "
                    "cleaner setup is reasonable.", reasons, ind)
        return ("bad", "Unfavorable", "The entry triggered, but the odds lean against it.",
                "Your rules would allow it, but the replays and the track record point to the stop. "
                "Passing on this trade is the conservative choice.", reasons, ind)
    if status == "triggered":
        return ("warn", "Unscored", "The entry triggered; the odds were not computed.",
                "Run the Time Machine before deciding.", reasons, ind)
    if status == "waiting":
        lvl = (entry or {}).get("level") or ((entry or {}).get("opening_range") or {}).get("high")
        return ("neutral", "Wait", "No entry yet.",
                "Nothing to do until a 5-minute bar closes above %s. Run it again later or set a "
                "price alert." % money(lvl), reasons, ind)
    if status == "expired":
        return ("neutral", "No trade", "The setup did not trigger today.",
                "No breakout happened before the entry cutoff. Check again tomorrow.", reasons, ind)
    if status == "no-data":
        return ("neutral", "No data", "The entry check got no bars.",
                (entry or {}).get("reason", "Yahoo sent no bars.") + ". Run it again in a few minutes.", reasons, ind)
    if market == "open" and not entry:
        return ("neutral", "Not checked", "The entry check did not run for this ticker.",
                "Run /trader-run %s to check the entry, odds and risk." % b["symbol"], reasons, ind)
    if market == "unknown":
        return ("neutral", "No data", "Market data did not load for this run.",
                "Yahoo Finance did not answer. Run it again in a few minutes.", reasons, ind)
    if market != "open":
        return ("neutral", "Market closed", "The market is %s." % market.replace("-", " "),
                "Run it again after 9:45 AM New York time, once the opening range is set.", reasons, ind)
    return ("neutral", "Too early", "The opening range is still forming.",
            "Run it again after 9:45 AM New York time.", reasons, ind)


# ---------------------------------------------------------------- charts

def scale(d0, d1, r0, r1):
    span = (d1 - d0) or 1
    return lambda v: r0 + (v - d0) / span * (r1 - r0)


def intraday_svg(b):
    bars = (b.get("intraday") or {}).get("bars") or []
    plan = b.get("plan") or {}
    entry = b.get("entry") or {}
    mc = ((b.get("timemachine") or {}).get("mc")) or {}
    if not bars:
        return '<p class="muted">Intraday bars unavailable.</p>'
    day = bars[-1]["t"][:10]
    bars = [x for x in bars if x["t"].startswith(day)]
    W, H, L, R, T, B = 760, 320, 6, 70, 14, 26
    x = scale(570, 960, L, W - R)
    ys = [v for br in bars for v in (br["h"], br["l"])]
    orng = plan.get("opening_range") or entry.get("opening_range") or {}
    for v in (plan.get("stop"), plan.get("target"), orng.get("high"), orng.get("low")):
        if v:
            ys.append(v)
    bands = mc.get("bands") or []
    btimes = mc.get("band_times") or []
    for bd in bands:
        ys += [bd[0], bd[-1]]
    lo, hi = min(ys), max(ys)
    pad = (hi - lo) * 0.06 or 1
    y = scale(lo - pad, hi + pad, H - B, T)
    out = ['<svg viewBox="0 0 %d %d" class="chart" role="img" aria-label="Intraday price with plan levels">' % (W, H)]
    # grid + price ticks
    step = nice_step((hi - lo) / 5)
    v = (int((lo - pad) / step) + 1) * step
    while v < hi + pad:
        out.append('<line class="grid" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % (L, W - R, y(v), y(v)))
        out.append('<text class="tick" x="%d" y="%.1f">%s</text>' % (W - R + 6, y(v) + 4, fmt_px(v)))
        v += step
    for m in range(600, 961, 60):
        out.append('<text class="tick" text-anchor="middle" x="%.1f" y="%d">%s</text>' % (x(m), H - 8, clock_label(m)))
    out.append('<text class="tick" text-anchor="start" x="%.1f" y="%d">9:30</text>' % (x(570), H - 8))
    # opening range
    if orng.get("high") and orng.get("low"):
        mins = orng.get("minutes", 15)
        out.append('<rect class="orbox" x="%.1f" y="%.1f" width="%.1f" height="%.1f"/>'
                   % (x(570), y(orng["high"]), x(570 + mins) - x(570), y(orng["low"]) - y(orng["high"])))
        for v in (orng["high"], orng["low"]):
            out.append('<line class="orline" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % (L, W - R, y(v), y(v)))
    # forecast fan
    if bands and btimes and len(bands) == len(btimes):
        xs = [x(hm(t)) for t in btimes]
        outer = " ".join("%.1f,%.1f" % (xs[i], y(bands[i][-1])) for i in range(len(xs))) + " " + \
            " ".join("%.1f,%.1f" % (xs[i], y(bands[i][0])) for i in reversed(range(len(xs))))
        inner = " ".join("%.1f,%.1f" % (xs[i], y(bands[i][-2])) for i in range(len(xs))) + " " + \
            " ".join("%.1f,%.1f" % (xs[i], y(bands[i][1])) for i in reversed(range(len(xs))))
        med = " ".join("%.1f,%.1f" % (xs[i], y(bands[i][2])) for i in range(len(xs)))
        out.append('<polygon class="fan-o" points="%s"/>' % outer)
        out.append('<polygon class="fan-i" points="%s"/>' % inner)
        out.append('<polyline class="fan-m" points="%s"/>' % med)
    # candles
    cw = (x(575) - x(570)) * 0.62
    for br in bars:
        m = hm(br["t"])
        if m < 570 or m >= 960:
            continue
        cx = x(m + 2.5)
        cls = "up" if br["c"] >= br["o"] else "dn"
        out.append('<line class="wick %s" x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f"/>' % (cls, cx, cx, y(br["h"]), y(br["l"])))
        top, bot = y(max(br["o"], br["c"])), y(min(br["o"], br["c"]))
        out.append('<rect class="body %s" x="%.1f" y="%.1f" width="%.1f" height="%.1f"/>'
                   % (cls, cx - cw / 2, top, cw, max(bot - top, 1)))
    # plan lines
    labels = []
    for key, cls, name in (("target", "tgt", "Target"), ("entry", "ent", "Entry"), ("stop", "stp", "Stop")):
        v = plan.get(key)
        if v:
            out.append('<line class="lvl %s" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % (cls, L, W - R, y(v), y(v)))
            labels.append((y(v), cls, "%s %s" % (name, fmt_px(v))))
    labels.sort()
    last = -99
    for yy, cls, txt in labels:
        yy = max(yy, last + 15)
        last = yy
        out.append('<text class="lvltxt %s" x="%d" y="%.1f" text-anchor="end">%s</text>' % (cls, W - R - 4, yy - 4, esc(txt)))
    if plan.get("flat_by"):
        fx = x(hm(plan["flat_by"]))
        out.append('<line class="flat" x1="%.1f" x2="%.1f" y1="%d" y2="%d"/>' % (fx, fx, T, H - B))
        out.append('<text class="tick halo" x="%.1f" y="%d" text-anchor="end">flat by %s</text>' % (fx - 4, H - B - 6, esc(plan["flat_by"])))
    if plan.get("entry") and plan.get("entry_time"):
        out.append('<circle class="entrydot" cx="%.1f" cy="%.1f" r="5"/>' % (x(hm(plan["entry_time"])), y(plan["entry"])))
    lb = bars[-1]
    out.append('<circle class="lastdot" cx="%.1f" cy="%.1f" r="4"/>' % (x(hm(lb["t"]) + 2.5), y(lb["c"])))
    out.append("</svg>")
    return "".join(out)


def nice_step(raw):
    if raw <= 0:
        return 1
    import math
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def fmt_px(v):
    return ("%.2f" % v) if v < 1000 else format(v, ",.0f")


def daily_svg(b):
    bars = (b.get("daily") or {}).get("bars") or []
    if len(bars) < 25:
        return '<p class="muted">Daily history unavailable.</p>'
    closes = [x["c"] for x in bars]
    sma = [None] * 19 + [sum(closes[i - 19:i + 1]) / 20 for i in range(19, len(closes))]
    hi20 = [None] * 20 + [max(closes[i - 20:i]) for i in range(20, len(closes))]
    W, H, L, R, T, B = 760, 220, 6, 70, 12, 24
    x = scale(0, len(closes) - 1, L, W - R)
    vals = closes + [v for v in sma + hi20 if v]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.06 or 1
    y = scale(lo - pad, hi + pad, H - B, T)
    out = ['<svg viewBox="0 0 %d %d" class="chart" role="img" aria-label="Six months of daily closes">' % (W, H)]
    step = nice_step((hi - lo) / 4)
    v = (int((lo - pad) / step) + 1) * step
    while v < hi + pad:
        out.append('<line class="grid" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % (L, W - R, y(v), y(v)))
        out.append('<text class="tick" x="%d" y="%.1f">%s</text>' % (W - R + 6, y(v) + 4, fmt_px(v)))
        v += step
    seen = set()
    for i, br in enumerate(bars):
        mo = br["t"][:7]
        if mo not in seen and i > 0:
            seen.add(mo)
            out.append('<text class="tick" text-anchor="middle" x="%.1f" y="%d">%s</text>'
                       % (x(i), H - 6, datetime.strptime(mo, "%Y-%m").strftime("%b")))
        seen.add(mo)
    pts = " ".join("%.1f,%.1f" % (x(i), y(c)) for i, c in enumerate(closes))
    area = pts + " %.1f,%d %.1f,%d" % (x(len(closes) - 1), H - B, x(0), H - B)
    out.append('<polygon class="area" points="%s"/>' % area)
    out.append('<polyline class="sma" points="%s"/>' % " ".join("%.1f,%.1f" % (x(i), y(v)) for i, v in enumerate(sma) if v))
    out.append('<polyline class="hi20" points="%s"/>' % " ".join("%.1f,%.1f" % (x(i), y(v)) for i, v in enumerate(hi20) if v))
    out.append('<polyline class="px" points="%s"/>' % pts)
    out.append('<circle class="lastdot" cx="%.1f" cy="%.1f" r="4"/>' % (x(len(closes) - 1), y(closes[-1])))
    out.append("</svg>")
    return "".join(out)


def hist_svg(b):
    mc = ((b.get("timemachine") or {}).get("mc")) or {}
    h = mc.get("hist") or {}
    bins = h.get("bins") or []
    plan = b.get("plan") or {}
    if not bins:
        return ""
    W, H, L, R, T, B = 760, 170, 6, 6, 16, 26
    lo, hi = h["lo"], h["hi"]
    x = scale(lo, hi, L, W - R)
    top = max(bins)
    y = scale(0, top, H - B, T)
    bw = (W - L - R) / len(bins)
    out = ['<svg viewBox="0 0 %d %d" class="chart" role="img" aria-label="Where the price ends in the replays">' % (W, H)]
    for i, n in enumerate(bins):
        mid = lo + (i + 0.5) * (hi - lo) / len(bins)
        cls = "hb-stop" if plan.get("stop") and mid <= plan["stop"] else (
            "hb-tgt" if plan.get("target") and mid >= plan["target"] else "hb-mid")
        out.append('<rect class="%s" x="%.1f" y="%.1f" width="%.1f" height="%.1f"/>'
                   % (cls, L + i * bw + 1, y(n), bw - 2, (H - B) - y(n)))
    for key, cls, name in (("stop", "stp", "Stop"), ("entry", "ent", "Entry"), ("target", "tgt", "Target")):
        v = plan.get(key)
        if v and lo <= v <= hi:
            out.append('<line class="lvl %s" x1="%.1f" x2="%.1f" y1="%d" y2="%d"/>' % (cls, x(v), x(v), T - 6, H - B))
            out.append('<text class="lvltxt %s" x="%.1f" y="%d" text-anchor="middle">%s %s</text>'
                       % (cls, x(v), H - 8, name, fmt_px(v)))
    out.append("</svg>")
    return "".join(out)


def ladder_svg(plan, qty):
    e, s, t = plan.get("entry"), plan.get("stop"), plan.get("target")
    if not (e and s and t):
        return ""
    W, H = 260, 220
    y = scale(s - (t - s) * 0.08, t + (t - s) * 0.08, H - 10, 10)
    out = ['<svg viewBox="0 0 %d %d" class="ladder" role="img" aria-label="Bracket: stop, entry and target">' % (W, H)]
    out.append('<rect class="zone-gain" x="20" y="%.1f" width="34" height="%.1f"/>' % (y(t), y(e) - y(t)))
    out.append('<rect class="zone-loss" x="20" y="%.1f" width="34" height="%.1f"/>' % (y(e), y(s) - y(e)))
    rows = [(t, "tgt", "Target", (t - e) * qty), (e, "ent", "Entry", None), (s, "stp", "Stop", (s - e) * qty)]
    for v, cls, name, pl in rows:
        out.append('<line class="lvl %s" x1="14" x2="60" y1="%.1f" y2="%.1f"/>' % (cls, y(v), y(v)))
        out.append('<text class="ltxt" x="70" y="%.1f">%s</text>' % (y(v) - 2, name))
        out.append('<text class="lnum %s" x="70" y="%.1f">%s%s</text>'
                   % (cls, y(v) + 14, money(v), "" if pl is None else "  (%s%s)" % ("+" if pl >= 0 else "−", money(abs(pl)))))
    out.append("</svg>")
    return "".join(out)


def rev_svg(rows):
    rows = [r for r in rows if r.get("revenue")][::-1][-8:]
    if len(rows) < 2:
        return ""
    W, H, L, R, T, B = 760, 190, 6, 6, 22, 40
    top = max(r["revenue"] for r in rows)
    y = scale(0, top, H - B, T)
    bw = (W - L - R) / len(rows)
    out = ['<svg viewBox="0 0 %d %d" class="chart" role="img" aria-label="Quarterly revenue">' % (W, H)]
    for i, r in enumerate(rows):
        cx = L + i * bw + bw / 2
        out.append('<rect class="%s" x="%.1f" y="%.1f" width="%.1f" height="%.1f"/>'
                   % ("rev-d" if r.get("derived") else "rev", cx - bw * 0.32, y(r["revenue"]), bw * 0.64, (H - B) - y(r["revenue"])))
        out.append('<text class="tick" text-anchor="middle" x="%.1f" y="%.1f">%s</text>' % (cx, y(r["revenue"]) - 6, big_money(r["revenue"])))
        out.append('<text class="tick" text-anchor="middle" x="%.1f" y="%d">%s</text>' % (cx, H - 22, esc(r.get("fiscal", r.get("end")))))
        yoy = r.get("revenue_yoy")
        if yoy is not None:
            out.append('<text class="tick %s" text-anchor="middle" x="%.1f" y="%d">%s y/y</text>'
                       % ("pos" if yoy >= 0 else "neg", cx, H - 6, pct(yoy)))
    out.append("</svg>")
    return "".join(out)


def stack_bar(parts):
    total = sum(v for _, v, _ in parts) or 1
    segs = []
    for label, v, cls in parts:
        w = v / total * 100
        if w <= 0:
            continue
        segs.append('<div class="seg %s" style="width:%.2f%%" title="%s"><span>%s</span></div>'
                    % (cls, w, esc(label), esc(label) if w >= 14 else ""))
    return '<div class="stack">%s</div>' % "".join(segs)


# ---------------------------------------------------------------- page

CSS = """
:root{--bg:#f4f5f1;--surface:#fff;--sunk:#eceee8;--fg:#18201c;--muted:#5b675f;--rule:#d8ddd6;--accent:#0b6b4c;
--good:#147a4b;--good-bg:#e1f2e8;--warn:#8a5a00;--warn-bg:#fbefd5;--bad:#b0362b;--bad-bg:#f9e2df;--neutral:#3d5a80;--neutral-bg:#e3eaf3;
--up:#1d8a5a;--dn:#c2453a;--fan:#3d5a80;
--display:"Archivo","Arial Narrow",system-ui,sans-serif;--body:"Source Sans 3",system-ui,-apple-system,"Segoe UI",sans-serif;--mono:"JetBrains Mono",ui-monospace,Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0f1412;--surface:#161d1a;--sunk:#1c2420;--fg:#e4ebe7;--muted:#97a59d;--rule:#2b3631;--accent:#4cbf8e;
--good:#5fd09a;--good-bg:#173226;--warn:#f0c766;--warn-bg:#33290f;--bad:#f2897e;--bad-bg:#3a1c19;--neutral:#9db8dc;--neutral-bg:#1c2836;--up:#4cc58b;--dn:#ef7b70;--fan:#8fb0dc;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#0f1412;--surface:#161d1a;--sunk:#1c2420;--fg:#e4ebe7;--muted:#97a59d;--rule:#2b3631;--accent:#4cbf8e;
--good:#5fd09a;--good-bg:#173226;--warn:#f0c766;--warn-bg:#33290f;--bad:#f2897e;--bad-bg:#3a1c19;--neutral:#9db8dc;--neutral-bg:#1c2836;--up:#4cc58b;--dn:#ef7b70;--fan:#8fb0dc;color-scheme:dark}
body{background:var(--bg);color:var(--fg);font-family:var(--body);font-size:16px;line-height:1.5;
padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));padding-block:28px 56px}
main{max-width:980px;margin:0 auto;display:grid;grid-template-columns:minmax(0,1fr);gap:40px}
main>*,.ticker>*{min-width:0}
h1,h2,h3{font-family:var(--display);font-stretch:80%;margin:0;text-wrap:balance;line-height:1.05}
h1{font-size:2.4rem;font-weight:800}h2{font-size:1.9rem;font-weight:800}h3{font-size:1.05rem;font-weight:700;font-stretch:90%;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
a{color:var(--accent)}.muted{color:var(--muted)}.mono{font-family:var(--mono)}
.top{display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px 24px;align-items:end;border-bottom:2px solid var(--fg);padding-bottom:14px}
.top p{margin:4px 0 0;color:var(--muted);font-size:.9rem}
.overview{width:100%;border-collapse:collapse;font-size:.95rem}.overview th,.overview td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--rule)}
.overview th{font-family:var(--display);font-stretch:90%;text-transform:uppercase;letter-spacing:.06em;font-size:.75rem;color:var(--muted)}
.tablewrap{overflow-x:auto}
.ticker{display:grid;gap:22px;scroll-margin-top:16px}
.thead{display:flex;flex-wrap:wrap;gap:6px 18px;align-items:baseline}
.thead .px{font-family:var(--mono);font-size:1.4rem;font-weight:600;font-variant-numeric:tabular-nums}
.chg.pos{color:var(--good)}.chg.neg{color:var(--bad)}
.verdict{display:grid;grid-template-columns:auto 1fr;gap:6px 20px;padding:18px 20px;border-radius:6px;border-left:6px solid}
.verdict.good{background:var(--good-bg);border-color:var(--good)}.verdict.warn{background:var(--warn-bg);border-color:var(--warn)}
.verdict.bad{background:var(--bad-bg);border-color:var(--bad)}.verdict.neutral{background:var(--neutral-bg);border-color:var(--neutral)}
.vlabel{grid-row:span 3;font-family:var(--display);font-stretch:75%;font-weight:800;font-size:2.2rem;line-height:1;text-transform:uppercase;align-self:center}
.verdict.good .vlabel{color:var(--good)}.verdict.warn .vlabel{color:var(--warn)}.verdict.bad .vlabel{color:var(--bad)}.verdict.neutral .vlabel{color:var(--neutral)}
.vhead{font-weight:600;font-size:1.1rem;min-width:0}.vadv{margin:0;min-width:0}.vwhy{margin:4px 0 0;padding-left:18px;font-size:.92rem;min-width:0}
.vnote{grid-column:1/-1;font-size:.78rem;color:var(--muted);margin:6px 0 0}
@media (max-width:560px){.verdict{grid-template-columns:1fr}.vlabel{grid-row:auto}}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px}
.tile{background:var(--surface);border:1px solid var(--rule);border-radius:6px;padding:10px 12px;display:grid;gap:4px;align-content:start;min-width:0}
.tile .k{font-family:var(--display);font-stretch:90%;font-size:.72rem;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);display:flex;align-items:center;gap:6px}
.tile .v{font-weight:600;font-size:1rem;line-height:1.25}.tile .d{font-size:.8rem;color:var(--muted)}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block;flex:none}
.dot.good{background:var(--good)}.dot.warn{background:var(--warn)}.dot.bad{background:var(--bad)}.dot.neutral{background:var(--neutral)}
.panel{background:var(--surface);border:1px solid var(--rule);border-radius:6px;padding:16px;display:grid;gap:10px;min-width:0}
.legend{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:.8rem;color:var(--muted)}
.legend i{display:inline-block;width:14px;height:3px;vertical-align:middle;margin-right:5px}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}
.chart{width:100%;height:auto;display:block}.ladder{width:100%;max-width:300px;height:auto;display:block}
.grid{stroke:var(--rule);stroke-width:1}.tick{fill:var(--muted);font:11px var(--mono)}.tick.pos{fill:var(--good)}.tick.neg{fill:var(--bad)}
.orbox{fill:var(--neutral);opacity:.12}.orline{stroke:var(--neutral);stroke-dasharray:2 4;opacity:.6}
.fan-o{fill:var(--fan);opacity:.12}.fan-i{fill:var(--fan);opacity:.2}.fan-m{fill:none;stroke:var(--fan);stroke-width:1.5;stroke-dasharray:5 4}
.wick{stroke-width:1}.wick.up{stroke:var(--up)}.wick.dn{stroke:var(--dn)}.body.up{fill:var(--up)}.body.dn{fill:var(--dn)}
.lvl{stroke-width:1.5}.lvl.tgt{stroke:var(--good)}.lvl.stp{stroke:var(--bad)}.lvl.ent{stroke:var(--fg);stroke-dasharray:6 4}
.lvltxt{font:600 11px var(--mono)}.lvltxt,.halo{paint-order:stroke;stroke:var(--surface);stroke-width:4px;stroke-linejoin:round}.lvltxt.tgt,.lnum.tgt{fill:var(--good)}.lvltxt.stp,.lnum.stp{fill:var(--bad)}.lvltxt.ent,.lnum.ent{fill:var(--fg)}
.flat{stroke:var(--muted);stroke-dasharray:1 4;stroke-width:1.5}
.entrydot{fill:var(--bg);stroke:var(--fg);stroke-width:2.5}.lastdot{fill:var(--accent)}
.area{fill:var(--accent);opacity:.08}.px{fill:none;stroke:var(--fg);stroke-width:1.6}.sma{fill:none;stroke:var(--fan);stroke-width:1.5}
.hi20{fill:none;stroke:var(--warn);stroke-width:1.2;stroke-dasharray:4 3}
.hb-mid{fill:var(--fan);opacity:.45}.hb-stop{fill:var(--bad);opacity:.7}.hb-tgt{fill:var(--good);opacity:.7}
.zone-gain{fill:var(--good);opacity:.22}.zone-loss{fill:var(--bad);opacity:.22}
.ltxt{fill:var(--muted);font:600 11px var(--display);text-transform:uppercase;letter-spacing:.06em}.lnum{font:600 13px var(--mono)}
.rev{fill:var(--accent);opacity:.75}.rev-d{fill:var(--accent);opacity:.35}
.stack{display:flex;height:30px;border-radius:4px;overflow:hidden;background:var(--sunk)}
.seg{display:flex;align-items:center;justify-content:center;font:600 .75rem var(--mono);white-space:nowrap;overflow:hidden;color:var(--fg)}
.seg.tgt{background:var(--good-bg);box-shadow:inset 0 -3px 0 var(--good)}.seg.stp{background:var(--bad-bg);box-shadow:inset 0 -3px 0 var(--bad)}.seg.mid{background:var(--sunk)}
.barrow{display:grid;grid-template-columns:110px 1fr;gap:10px;align-items:center;font-size:.85rem}
@media (max-width:480px){.barrow{grid-template-columns:1fr}}
.kv{display:grid;grid-template-columns:auto 1fr;gap:6px 16px;margin:0;font-size:.95rem}.kv dt{color:var(--muted)}.kv dd{margin:0;font-family:var(--mono);font-variant-numeric:tabular-nums;text-align:right}
.ticket{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,260px);gap:16px;align-items:center}
@media (max-width:640px){.ticket{grid-template-columns:1fr}}
.news{list-style:none;margin:0;padding:0;display:grid}
.news li{display:grid;grid-template-columns:72px 1fr;gap:4px 12px;padding:9px 0;border-bottom:1px solid var(--rule);font-size:.93rem}
.news time{font-family:var(--mono);font-size:.78rem;color:var(--muted);padding-top:2px}.news .t{min-width:0;overflow-wrap:anywhere}
.chip{display:inline-block;font:600 .68rem var(--mono);text-transform:uppercase;letter-spacing:.04em;padding:1px 6px;border-radius:3px;background:var(--sunk);color:var(--muted);margin-right:4px}
.chip.earnings{background:var(--warn-bg);color:var(--warn)}
.etable{width:100%;border-collapse:collapse;font-size:.88rem;font-variant-numeric:tabular-nums}.etable th,.etable td{padding:6px 8px;border-bottom:1px solid var(--rule);text-align:right;white-space:nowrap}
.etable th:first-child,.etable td:first-child{text-align:left}.etable th{font-weight:600;color:var(--muted)}
ol.steps{margin:0;padding-left:20px;display:grid;gap:4px}
footer{font-size:.8rem;color:var(--muted);border-top:1px solid var(--rule);padding-top:14px}
:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
"""


def render_ticker(b):
    sym = b["symbol"]
    key, label, head, advice, reasons, ind = read_signal(b)
    intraday = b.get("intraday") or {}
    price = intraday.get("price")
    prev = intraday.get("prev_close") or intraday.get("previous_close")
    chg = ((price - prev) / prev * 100) if price and prev else None
    plan, tm, order, risk = b.get("plan") or {}, b.get("timemachine") or {}, b.get("order") or {}, b.get("risk") or {}
    mc, hist = tm.get("mc") or {}, tm.get("history") or {}
    p = ['<section class="ticker" id="%s" aria-labelledby="h-%s">' % (esc(sym), esc(sym))]
    p.append('<div class="thead"><h2 id="h-%s">%s</h2><span class="muted">%s</span>'
             '<span class="px">%s</span><span class="chg %s mono">%s</span></div>'
             % (esc(sym), esc(sym), esc(intraday.get("name") or ""), money(price),
                "pos" if (chg or 0) >= 0 else "neg", pct(chg)))
    p.append('<div class="verdict %s"><div class="vlabel">%s</div><div class="vhead">%s</div><p class="vadv">%s</p>'
             % (key, esc(label), esc(head), esc(advice)))
    if reasons:
        p.append('<ul class="vwhy">%s</ul>' % "".join("<li>%s</li>" % esc(r) for r in reasons))
    else:
        p.append("<div></div>")
    p.append('<p class="vnote">Rules-based read of delayed data from this run. It is not financial advice, and nothing has been ordered.</p></div>')

    p.append('<div class="tiles">')
    for k, v, st, d in ind:
        p.append('<div class="tile"><div class="k"><span class="dot %s"></span>%s</div><div class="v">%s</div><div class="d">%s</div></div>'
                 % (st, esc(k), esc(v), esc(d)))
    p.append("</div>")

    legend = ['<span><i style="background:var(--up)"></i>5-min bars</span>']
    if (plan.get("opening_range") or (b.get("entry") or {}).get("opening_range")):
        legend.append('<span><i style="background:var(--neutral);opacity:.5"></i>Opening range</span>')
    if mc.get("bands"):
        legend.append('<span><i style="background:var(--fan);opacity:.5"></i>Replay range (5–95%, middle 50%, median dashed)</span>')
    if plan:
        legend += ['<span><i style="background:var(--good)"></i>Target</span>',
                   '<span><i style="background:var(--fg)"></i>Entry</span>',
                   '<span><i style="background:var(--bad)"></i>Stop</span>']
    p.append('<div class="panel"><h3>Today, 5-minute bars</h3>%s<div class="legend">%s</div></div>'
             % (intraday_svg(b), "".join(legend)))

    if mc:
        hp = []
        if hist.get("triggered"):
            hp = [("Target %d" % hist.get("target", 0), hist.get("target", 0), "tgt"),
                  ("Neither %d" % hist.get("close", 0), hist.get("close", 0), "mid"),
                  ("Stop %d" % hist.get("stop", 0), hist.get("stop", 0), "stp")]
        p.append('<div class="panel"><h3>Odds from 10,000 replays and the track record</h3>')
        p.append('<div class="barrow"><span>Replays</span>%s</div>' % stack_bar([
            ("Target first %.1f%%" % (mc.get("p_target", 0) * 100), mc.get("p_target", 0), "tgt"),
            ("Neither by %s %.1f%%" % (mc.get("until", plan.get("flat_by", "")), mc.get("p_neither", 0) * 100), mc.get("p_neither", 0), "mid"),
            ("Stop first %.1f%%" % (mc.get("p_stop", 0) * 100), mc.get("p_stop", 0), "stp")]))
        if hp:
            p.append('<div class="barrow"><span>Past %d trades</span>%s</div>' % (hist["triggered"], stack_bar(hp)))
        p.append('<p class="muted" style="margin:0;font-size:.85rem">%s</p>' % esc(tm.get("verdict") or ""))
        p.append("<h3>Where the price ends at %s in the replays</h3>%s" % (esc(mc.get("until", "")), hist_svg(b)))
        p.append('<p class="muted" style="margin:0;font-size:.85rem">Median %s · 90%% of replays end between %s and %s · %d sessions from %s to %s.</p>'
                 % (money(mc.get("median_close")), money(mc.get("p5_close")), money(mc.get("p95_close")),
                    mc.get("pool_sessions", 0), esc(mc.get("pool_from", "")), esc(mc.get("pool_to", ""))))
        p.append("</div>")

    if plan and order:
        qty = int(float(order.get("qty") or 0))
        mp = order.get("plan") or {}
        gain = (plan["target"] - plan["entry"]) * qty
        rows = [("Shares", "%d" % qty), ("Position", money(plan["entry"] * qty)),
                ("Entry", "%s at %s" % (money(plan["entry"]), esc(plan.get("entry_time")))),
                ("Stop", "%s (%s)" % (money(plan["stop"]), esc(plan.get("stop_label", "")))),
                ("Target", "%s (%s)" % (money(plan["target"]), esc(plan.get("target_label", "")))),
                ("Risk per share", money(plan.get("risk_per_share"))),
                ("Max loss at stop", money(mp.get("max_loss"))), ("Gain at target", money(gain)),
                ("Cash after", money(risk.get("cash_after"))), ("Be out by", esc(plan.get("flat_by")))]
        p.append('<div class="panel"><h3>The trade ticket (bracket order, not placed)</h3><div class="ticket"><dl class="kv">%s</dl>%s</div>'
                 % ("".join("<dt>%s</dt><dd>%s</dd>" % (k, v) for k, v in rows), ladder_svg(plan, qty)))
        if order.get("why"):
            p.append('<p class="muted" style="margin:0;font-size:.85rem">%s</p>' % esc(order["why"]))
        p.append("</div>")

    scan = b.get("scan") or {}
    hit = scan.get("hit")
    p.append('<div class="panel"><h3>Six-month trend</h3>%s<div class="legend"><span><i style="background:var(--fg)"></i>Close</span>'
             '<span><i style="background:var(--fan)"></i>20-day average</span><span><i style="background:var(--warn)"></i>20-day closing high</span></div>'
             % daily_svg(b))
    if scan:
        txt = ("Daily scan found: %s." % ", ".join(hit.get("setups") or [])) if hit else \
            "Daily scan (closes through %s) found no breakout, flag or oversold setup." % esc(scan.get("as_of") or "")
        p.append('<p style="margin:0;font-size:.9rem">%s</p>' % txt)
    p.append("</div>")

    facts = b.get("facts")
    if facts and (facts.get("result") or {}).get("rows"):
        res = facts["result"]
        rows = res["rows"]
        p.append('<div class="panel"><h3>Earnings: %s, as filed with the SEC</h3>%s' % (esc(res.get("entity", sym)), rev_svg(rows)))
        p.append('<div class="tablewrap"><table class="etable"><thead><tr><th>Quarter</th><th>Revenue</th><th>y/y</th><th>EPS</th><th>y/y</th>'
                 '<th>Gross</th><th>Operating</th><th>Net</th></tr></thead><tbody>')
        for r in rows[:6]:
            p.append("<tr><td>%s%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                     % (esc(r.get("fiscal")), " *" if r.get("derived") else "", big_money(r.get("revenue")), pct(r.get("revenue_yoy")),
                        "–" if r.get("eps_diluted") is None else "%.2f" % r["eps_diluted"], pct(r.get("eps_yoy")),
                        pct(r.get("gross_margin"), False), pct(r.get("operating_margin"), False), pct(r.get("net_margin"), False)))
        p.append("</tbody></table></div>")
        if facts.get("changes"):
            p.append('<ul style="margin:0;padding-left:18px;font-size:.9rem">%s</ul>' % "".join("<li>%s</li>" % esc(c) for c in facts["changes"]))
        p.append("</div>")

    items = ((b.get("news") or {}).get("items") or [])[:12]
    if items:
        p.append('<div class="panel"><h3>News, last 24 hours</h3><ul class="news">')
        for it in items:
            try:
                t = datetime.fromisoformat(it["time"]).astimezone(timezone.utc)
                when = (t.timestamp() + _ny_offset(t)) if t else 0
                tl = datetime.fromtimestamp(when, tz=timezone.utc).strftime("%-I:%M %p")
            except (KeyError, ValueError, TypeError):
                tl = ""
            chips = "".join('<span class="chip %s">%s</span>' % (esc(tg), esc(tg)) for tg in it.get("tags") or [])
            url = safe_url(it.get("link"))
            title = ('<a href="%s" target="_blank" rel="noopener">%s</a>' % (esc(url), esc(it.get("title")))) if url else esc(it.get("title"))
            p.append('<li><time>%s</time><div class="t">%s %s<div class="muted" style="font-size:.8rem">%s</div></div></li>'
                     % (tl, chips, title, esc(it.get("source"))))
        p.append("</ul></div>")

    p.append('<div class="panel"><h3>Next steps</h3><ol class="steps">%s</ol></div>' % "".join(
        "<li>%s</li>" % esc(s) for s in next_steps(b, key)))
    p.append("</section>")
    return "".join(p), (sym, key, label, price, chg, (b.get("entry") or {}).get("status"), mc, risk.get("verdict"))


def _ny_offset(t):
    """US Eastern offset in seconds for a UTC datetime (DST: 2nd Sun Mar 7:00 UTC to 1st Sun Nov 6:00 UTC)."""
    y = t.year
    mar = datetime(y, 3, 8, 7, tzinfo=timezone.utc)
    mar = mar.replace(day=8 + (6 - mar.weekday()) % 7)
    nov = datetime(y, 11, 1, 6, tzinfo=timezone.utc)
    nov = nov.replace(day=1 + (6 - nov.weekday()) % 7)
    return -4 * 3600 if mar <= t < nov else -5 * 3600


def next_steps(b, key):
    plan = b.get("plan") or {}
    entry = b.get("entry") or {}
    sym = b["symbol"]
    if plan and key in ("good", "warn"):
        return ["Re-check the price: these quotes are delayed. If it has already moved past %s, the plan no longer fits." % money(plan.get("target")),
                "To place it, open a session and run /trader-broker. It shows the bracket ticket and needs your explicit yes.",
                "Set alerts: /trader-alerts add --from-plan (stop, target and flat-by %s)." % plan.get("flat_by", "15:55"),
                "Close anything still open by %s." % plan.get("flat_by", "15:55")]
    if plan and key == "bad":
        return ["No action needed. If you still want it, size down and keep the stop at %s." % money(plan.get("stop")),
                "Run /trader-run %s again later to see if the picture changes." % sym]
    if entry.get("status") == "waiting":
        lvl = entry.get("level") or (entry.get("opening_range") or {}).get("high")
        return ["Watch for a 5-minute close above %s." % money(lvl),
                "Set an alert: /trader-alerts add --symbol %s --above %s." % (sym, "%.2f" % lvl if lvl else "LEVEL"),
                "Run /trader-run %s again once it breaks out." % sym]
    return ["Run /trader-run %s again during market hours, after 9:45 AM New York time." % sym]


def build(syms, out):
    sections, rows, missing = [], [], []
    bundles = []
    for s in syms:
        bd = load(os.path.join(RUNS, "%s.json" % s.upper()))
        if not bd:
            missing.append(s.upper())
            continue
        bundles.append(bd)
    if not bundles:
        print("No collected runs for %s. Run: report.py collect TICKER" % ", ".join(syms), file=sys.stderr)
        return 2
    for bd in bundles:
        sec, row = render_ticker(bd)
        sections.append(sec)
        rows.append(row)
    stamp = datetime.now(timezone.utc)
    ny = datetime.fromtimestamp(stamp.timestamp() + _ny_offset(stamp), tz=timezone.utc)
    names = " ".join(r[0] for r in rows)
    doc = ['<title>Trade Report %s</title>' % esc(names),
           '<meta name="claude:viewport-fit-sides" content="cover">',
           '<link rel="preconnect" href="https://fonts.googleapis.com">',
           '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@75..100,500..800'
           '&family=JetBrains+Mono:wght@400;600&family=Source+Sans+3:wght@400;600&display=swap">',
           "<style>%s</style><main>" % CSS]
    doc.append('<header class="top"><div><h1>Trade Report: %s</h1><p>%s New York time · market %s · free delayed quotes</p></div>'
               '<p>Paper trading rules · nothing ordered</p></header>'
               % (esc(names), ny.strftime("%a %b %-d, %Y, %-I:%M %p"), esc(bundles[0].get("market", ""))))
    if len(rows) > 1:
        doc.append('<section aria-label="Overview"><div class="tablewrap"><table class="overview"><thead><tr><th>Ticker</th><th>Signal</th>'
                   '<th>Price</th><th>Today</th><th>Entry</th><th>Odds (target / stop)</th><th>Risk</th></tr></thead><tbody>')
        for sym, key, label, price, chg, status, mc, rv in rows:
            odds = "%.0f%% / %.0f%%" % (mc["p_target"] * 100, mc["p_stop"] * 100) if mc else "–"
            doc.append('<tr><td><a href="#%s" class="mono">%s</a></td><td><span class="dot %s"></span> %s</td><td class="mono">%s</td>'
                       '<td class="mono">%s</td><td>%s</td><td class="mono">%s</td><td>%s</td></tr>'
                       % (esc(sym), esc(sym), key, esc(label), money(price), pct(chg), esc(status or "–"), odds, esc(rv or "–")))
        doc.append("</tbody></table></div></section>")
    doc += sections
    doc.append('<footer>Sources: Yahoo Finance chart and news feeds (free, delayed, unofficial), SEC EDGAR when an SEC identity was given, '
               'and the day-trader skill pack (scanner, entry, exit, Time Machine, budget, risk). The Time Machine replays the stock\'s own '
               'recent sessions; it cannot foresee earnings, news or halts. Education and tooling, not financial advice.%s</footer>'
               % ((" Not collected: %s." % esc(", ".join(missing))) if missing else ""))
    doc.append("</main>")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(doc))
    print("Wrote %s (%s)" % (out, ", ".join("%s: %s" % (r[0], r[2]) for r in rows)))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help="bundle this ticker's trader/ files and charts")
    c.add_argument("symbol")
    b = sub.add_parser("build", help="render collected tickers into one HTML page")
    b.add_argument("symbols", nargs="+")
    b.add_argument("--out", default="trader/report.html")
    a = ap.parse_args(argv)
    if a.cmd == "collect":
        return collect(a.symbol)
    return build(a.symbols, a.out)


if __name__ == "__main__":
    sys.exit(main())
