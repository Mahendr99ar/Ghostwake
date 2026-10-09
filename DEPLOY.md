# Deploying GhostWake for free

Four free services, about 45 minutes the first time:

| Piece | Service | What it costs |
| --- | --- | --- |
| Code and CI | GitHub | Free for public repos |
| Database | Neon (Postgres) | Free tier, 0.5 GB |
| API | Render (web service) | Free tier, sleeps after 15 min idle |
| Web app | Vercel (Hobby) | Free for non-commercial use |

Free-tier limits change. Check each pricing page before you start.

## 0. Before you start

Install Git, Python 3.11 or newer, and Node 20. Run the project locally once (see the README) so you know what "working" looks like before you deploy it.

## 1. Put the code on GitHub

1. Create an empty public repository called `ghostwake` on github.com. Don't add a README; this project has one.
2. From the project folder:

   ```bash
   git init
   git add .
   git commit -m "GhostWake: first version"
   git branch -M main
   git remote add origin https://github.com/<your-username>/ghostwake.git
   git push -u origin main
   ```

3. Open the **Actions** tab. The `CI` workflow should run and go green within a few minutes. If it fails, fix that first; everything below assumes the tests pass.

## 2. Create the database on Neon

1. Sign up at neon.tech and create a project. Pick the region closest to your Render region (Singapore works well for India).
2. On the project dashboard, copy the connection string. It looks like:

   ```
   postgresql://USER:PASSWORD@ep-something.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   ```

3. Change the start from `postgresql://` to `postgresql+psycopg://`. That tells SQLAlchemy which driver to use:

   ```
   postgresql+psycopg://USER:PASSWORD@ep-something.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   ```

   This is your `GW_DATABASE_URL`. Treat it like a password.

4. Optional check from your laptop:

   ```bash
   cd backend
   GW_DATABASE_URL="postgresql+psycopg://..." python -m ghostwake.pipeline
   ```

   It should print `"alerts": 15`. The tables are created on first run, so there is no migration step.

## 3. Deploy the API on Render

1. Sign up at render.com with your GitHub account.
2. Click **New** then **Blueprint**, and pick the `ghostwake` repository. Render reads `render.yaml` and proposes one web service, `ghostwake-api`.
3. Fill the values it asks for:

   | Variable | Value |
   | --- | --- |
   | `GW_DATABASE_URL` | the Neon string from step 2 |
   | `GW_CORS_ORIGINS` | `http://localhost:5173` for now; you'll add the Vercel URL in step 5 |
   | `GW_LLM_BASE_URL`, `GW_LLM_API_KEY`, `GW_LLM_MODEL` | leave empty for now (step 7) |

   `GW_ANALYST_TOKEN` is generated for you. Open the service's **Environment** tab later to copy it.

4. Click **Apply**. The first build takes a few minutes. The start command runs the pipeline, then starts the server.
5. When it shows **Live**, open `https://ghostwake-api.onrender.com/api/health` (your URL may differ). You should see `"ok": true` and `"open_alerts": 15`. The interactive API docs are at `/docs`.

The free service sleeps after 15 minutes without traffic, and the first request after that takes up to a minute while it wakes. That's expected. Mention it in your README so nobody thinks the site is broken.

## 4. Deploy the web app on Vercel

1. Sign up at vercel.com with GitHub. Click **Add New** then **Project**, and import `ghostwake`.
2. Set:

   | Setting | Value |
   | --- | --- |
   | Root Directory | `web` |
   | Framework Preset | Vite |
   | Build Command | `npm run build` (default) |
   | Output Directory | `dist` (default) |
   | Environment variable `VITE_API_URL` | your Render URL, e.g. `https://ghostwake-api.onrender.com` (no trailing slash) |

3. Click **Deploy**. You get a URL like `https://ghostwake.vercel.app`.

`VITE_API_URL` is baked in at build time. If you change it later, redeploy.

## 5. Connect the two

1. Back on Render, open `ghostwake-api`, then **Environment**.
2. Set `GW_CORS_ORIGINS` to your Vercel URL. Keep localhost if you still develop locally:

   ```
   https://ghostwake.vercel.app,http://localhost:5173
   ```

3. Save. Render redeploys by itself.
4. Open the Vercel URL. The queue should list 15 alerts and the map should show tracks.

## 6. Turn on the daily refresh

1. In the GitHub repo, open **Settings**, **Secrets and variables**, **Actions**.
2. Add a repository secret named `GW_DATABASE_URL` with the Neon string.
3. Open **Actions**, pick **Refresh data**, and click **Run workflow** once by hand. From then on it runs every morning at 05:47 IST.

The scenario is fixed, so a daily run changes nothing visible. It proves the pipeline runs unattended and stays idempotent, and it's where real data feeds would plug in.

## 7. Optional: a real language model for the copilot

Without these variables the copilot uses its offline writer, which is what the evals check. To use a model, pick any provider with an OpenAI-compatible chat endpoint that supports tool calling, and set three variables on Render:

| Provider | `GW_LLM_BASE_URL` |
| --- | --- |
| Groq | `https://api.groq.com/openai/v1` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` |
| Ollama on your own machine | `http://localhost:11434/v1` (local only, not from Render) |

Set `GW_LLM_API_KEY` to the provider's key and `GW_LLM_MODEL` to a model from its console that lists tool or function calling support. Model names change often, so copy the current one rather than trusting a name from a tutorial.

Then run the evals against the model from your laptop:

```bash
cd backend
GW_DATABASE_URL=... GW_LLM_BASE_URL=... GW_LLM_API_KEY=... GW_LLM_MODEL=... PYTHONPATH=. python evals/run_evals.py
```

If it scores below the offline writer, leave the model off. If the provider is down or the quota runs out, the copilot falls back to offline mode and says so in its answer.

## 8. Check the deployment end to end

Do this once after every big change:

- [ ] `/api/health` returns `ok: true` and a `last_run` from today or the latest deploy
- [ ] The site loads, the queue shows alerts, the map shows tracks and the dashed red IMBL
- [ ] Click SEA FALCON: the dashed amber line shows its silent stretch
- [ ] Click the top dark vessel: the radar chip appears and "Could be" names SEA FALCON
- [ ] Press play on the timeline: ships move, trails fade
- [ ] Ask the copilot "Brief me": an answer with no warning about unverified figures
- [ ] Ask it "Escalate this": it refuses
- [ ] Escalate an alert with the analyst token and a note; reload; it is still escalated
- [ ] "Open case file" opens a printable page
- [ ] On a phone, the Alerts / Map switch works
- [ ] The GitHub **Refresh data** workflow ran green

## Troubleshooting

| What you see | Likely cause | Fix |
| --- | --- | --- |
| Site says it can't reach the API | `VITE_API_URL` wrong or missing, or Render asleep | Open the health URL directly, wait for it to wake, check the variable on Vercel, redeploy |
| Browser console shows a CORS error | Vercel URL not in `GW_CORS_ORIGINS` | Add it exactly, with `https://` and no trailing slash |
| Render log: `could not translate host name` | Connection string pasted wrong | Copy it again from Neon and keep `?sslmode=require` |
| Render log: `No module named psycopg` | Old build cache | Clear build cache and deploy |
| Escalate says "Analyst token required" | Token not entered, or wrong | Copy `GW_ANALYST_TOKEN` from Render's Environment tab |
| Map is one flat colour with no coastline | Basemap tiles blocked on that network | Data still works; check that tiles.openfreemap.org is reachable |
| Copilot answers end with "LLM unavailable" | Model name, key or quota | Check the three LLM variables; offline mode keeps working meanwhile |
| Neon project paused | Free tier suspends idle compute | It resumes on the next connection; the first request is slower |

## Custom domain (optional)

A `.vercel.app` address is fine for a portfolio. If you buy a domain, add it under the Vercel project's **Domains** tab, then add the new address to `GW_CORS_ORIGINS` on Render.
