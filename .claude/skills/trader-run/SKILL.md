---
name: trader-run
description: >-
  One-shot trade check for one or more tickers: market clock, news, earnings,
  daily setup, entry signal, and if the entry triggered, the exit plan, the
  Time Machine odds, position size and the risk check. Publishes a visual
  trade report (signal, indicators, charts, ticket) and ends with a short
  summary and its link. Never places an order. Use when the user says
  "/trader-run TSLA", "run the automation for NVDA", "check AAPL end to end",
  or starts a session with only ticker symbols.
argument-hint: "TICKER [TICKER...] [sec=\"Name email\"]"
---

# trader-run

Input: `$ARGUMENTS`. The tickers are the uppercase words. An optional
`sec="Name email"` part is the SEC User-Agent; without it, skip the SEC parts
and say so in the summary.

Run every command from the repository root, exactly as written (relative
paths), one ticker at a time; `T` below is the ticker. Config: use
`trader/config.json` if it exists, otherwise pass
`--config .claude/skills/trader-budget/config.example.json` to the scripts
that take `--config`, and say the example budget was used.

If a command fails because a host is unreachable (403, tunnel or URL error),
stop calling that source, name the host in the summary, and carry on with the
steps that do not need it. Never invent prices, headlines or results.

## Steps for each ticker

1. `python3 .claude/skills/trader-alerts/alerts.py clock`
2. `python3 .claude/skills/trader-news/news.py --tickers T --hours 24 --json --user-agent "Name email" > trader/news-T.json`
   (with `--no-sec` instead of `--user-agent` when no SEC identity was given).
   Read that file for the summary; do not run news.py a second time, it only
   shows headlines once.
3. Only with an SEC User-Agent:
   `python3 .claude/skills/trader-analyst/facts.py T --user-agent "Name email" --json > trader/facts-T.json`
4. `python3 .claude/skills/trader-scanner/scan.py daily --symbols T`
5. If the market is open and at least 15 minutes past the open:
   `python3 .claude/skills/trader-entry/entry.py check T --write`
   Otherwise skip to step 7.
6. Only if step 5 says TRIGGERED, in order:
   - `python3 .claude/skills/trader-exit/exit.py plan --write`
   - `python3 .claude/skills/trader-timemachine/timemachine.py run --write --until 15:55`
   - `python3 .claude/skills/trader-budget/size.py --write` (plus `--config` as above)
   - `python3 .claude/skills/trader-risk/check.py --json > trader/risk-T.json` (plus `--config` as above), then read it
7. `python3 .claude/skills/trader-report/report.py collect T`
   Always run this, whatever happened above: it saves this ticker's results
   before the next ticker overwrites them.

## The report

After the last ticker:

1. `python3 .claude/skills/trader-report/report.py build T1 T2 ... --out trader/report.html`
   (every ticker, in the order given).
2. Publish it with the Artifact tool: `file_path` is the absolute path of
   `trader/report.html`, `icon` "chart", and a one-sentence `description`
   naming the tickers and each one's signal. Do not edit the file first: the
   script already writes a complete page. If the Artifact tool is not
   available, say so and give the file path instead.

## Summary

Start with the report link. Then, per ticker, in plain words and real numbers:

- Signal: the report's label (Favorable, Mixed, Unfavorable, Skip, Wait, No
  trade, Not checked, Market closed) and the one-line reason.
- Market: open or closed, next open.
- News: the newest items that matter, or "nothing new".
- Earnings (if run): last quarter's revenue, EPS and growth; whether a report is near.
- Setup: what the daily scan found.
- Entry: waiting (and the level), triggered (time and price), or not open yet.
- If triggered: stop, target, Time Machine odds, shares and max loss, and the
  risk verdict (PASS or BLOCK and why).
- What failed or was skipped.

## Never

- Never place, approve, cancel or change an order, and never run
  `trader-broker` or any broker tool. If the risk check passes, say: "To
  place it, open a session and run /trader-broker, which needs your explicit yes."
- Never present a delayed quote as live, and never call it financial advice.
  The signal is a rules-based read of the data, and the report says so.
