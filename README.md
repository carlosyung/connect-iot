# Connect-IoT

Homepage for [connect-iot.com](https://connect-iot.com): Hong Kong news, AI/LLM, IoT, tech, finance, HKO weather and markets, in an MSN-style layout.

## How it updates

`.github/workflows/update.yml` runs `build.py` every day at 06:00 HKT (22:00 UTC). The script fetches the news feeds, weather and market data, writes `dist/`, and force-pushes it as a single commit to the `site` branch. Cloudflare Pages deploys `site` to connect-iot.com. If a build fails (e.g. feeds down), nothing is pushed and yesterday's page stays live.

- **Change the schedule:** edit the `cron:` line in `.github/workflows/update.yml` (e.g. `"0 */6 * * *"` for every 6 hours).
- **Update now:** Actions tab → *Daily update* → *Run workflow*.
- **Daily briefing (今日重點):** `briefing.py` asks Gemini (`gemini-3.8-flash`, free tier) to write an original analysis of the day's headlines once per HK day, falling back to Cloudflare Workers AI (DeepSeek V4 Flash) if Gemini fails. Saved to `content/briefings/YYYY-MM-DD.json` and published at `/briefing/`. Needs the `GEMINI_API_KEY` and/or `CLOUDFLARE_API_TOKEN` secrets plus the `CLOUDFLARE_ACCOUNT_ID` variable; without them the rest of the site still updates.
- **Add or remove sources:** edit `FEEDS` / `MARKETS` at the top of `build.py`.
- **Change the design:** edit `template.html`.

Run locally: `python3 build.py` then open `dist/index.html`. Standard library only, no dependencies.
