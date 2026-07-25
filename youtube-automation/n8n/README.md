# n8n orchestration

`workflow.json` is an **importable scaffold** of the full pipeline. It chains the six stages
and pauses at the two approval gates. Import it (n8n → ⋮ → Import from File), then finish the
wiring below — a few fields depend on your environment and can't be baked in.

## The flow
```
Schedule Trigger → Set Job → Research Trends → Generate Script
   → 🔔 Approve Script  (Send and Wait)
   → Voiceover → Images → Assemble
   → 🔔 Approve Video   (Send and Wait)
   → Upload
```
**Research Trends** researches currently-viral, kid-safe topics (Claude + web search) and writes
`topics.json`; **Generate Script** then builds the story from the top-ranked topic
(`--from-research`). Want to approve the *topic* too? Drop a third "Send and Wait" node between
Research Trends and Generate Script and have it show `topics.json`.

## After importing — wiring checklist

1. **Make the scripts reachable from n8n.** The Execute Command nodes run shell commands.
   If you run n8n in Docker, mount this repo (`-v $(pwd):/workspace`) and make sure Python +
   `requirements.txt` + `ffmpeg` are available *inside that container* (or run n8n natively).
   Edit each Execute Command node's `command` so the path and Python invocation match your setup.
   The default assumes `/workspace/youtube-automation` with deps installed.

2. **Set the topic source.** The **Set Job** node hard-codes a sample topic and derives a numeric
   `job` id from the timestamp. Replace the topic with:
   - a rotating list (a Google Sheet / n8n Data Table you pull from), or
   - a Claude "ideas" call, or
   - a manual field you fill each run.

3. **Configure the two approval nodes.** They use Telegram "Send and Wait for Approval".
   - Add Telegram credentials (bot token from @BotFather) and your chat id, **or**
   - swap them for the **Email** or **Slack** node's "Send and Wait" operation.
   - **Approve Script** should include the generated `script.json` so you can read it before approving.
     Point it at `output/<job>/script.json`.
   - **Approve Video** should attach or link `output/<job>/video.mp4`.

4. **Handle "disapprove".** For a first pass the scaffold continues linearly. Add an **IF** node
   after each approval that checks `{{ $json.approved }}` and stops (or loops back to regenerate)
   when you reject.

5. **Set the schedule.** The Schedule Trigger defaults to disabled/manual. Set your cadence
   (e.g. every 8 hours) once you trust the output. Start by running it manually.

6. **Env vars.** The scripts read keys from `.env` in the repo. Make sure that file exists in the
   working directory the commands run from (or export the vars into the n8n environment).

## Tip
Run the whole thing **manually** from n8n a handful of times, approving each step, before you
enable the schedule. That's the safest way to catch a bad path or missing key.
