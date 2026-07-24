# Himanshu Malhotra — Personal Portfolio

An interactive, single-page portfolio for **Himanshu Malhotra** — Data & Analytics Leader
(Manager, Data Analytics & Reporting). Built as a self-contained site: elegant dark/light
"dossier" design, animated KPI counters, an interactive career journey, filterable work,
and an expertise panel — all in one file, no build step, no dependencies.

## Files

| Path | Purpose |
|------|---------|
| `index.html` | The complete website (HTML + CSS + JS, fully self-contained). |
| `assets/Himanshu_Malhotra_Resume.pdf` | Résumé served by the **Download résumé** button. |

## Preview locally

Just open `index.html` in any browser — or serve the folder:

```bash
python3 -m http.server 8080
# then visit http://localhost:8080
```

## Publish a shareable link (free options)

**GitHub Pages** — easiest, gives `https://<username>.github.io/<repo>/`:
1. Push this repo to GitHub.
2. Repo **Settings → Pages → Build and deployment → Source: Deploy from a branch**.
3. Select this branch and `/ (root)`, then **Save**. Live in ~1 minute.

**Vercel / Netlify** — for a custom domain:
1. Import the GitHub repo (no framework / static site).
2. Output directory: root. Deploy. Add your own domain in the dashboard.

## Editing content

Everything lives in `index.html`:
- **Text & sections** — plain HTML, clearly commented (`HERO`, `IMPACT`, `ABOUT`,
  `JOURNEY`, `WORK`, `EXPERTISE`, `CONTACT`).
- **Colours & fonts** — CSS custom properties in the `:root` block at the top of `<style>`.
- **KPI numbers** — the `data-to` attributes on `.kpi .num`.
- **Skill levels** — the `data-w` attributes on `.fill` bars.
- **Projects** — the `.card` articles in the `WORK` section (`data-cat` controls filtering).

To replace the résumé, drop a new PDF at `assets/Himanshu_Malhotra_Resume.pdf`.
