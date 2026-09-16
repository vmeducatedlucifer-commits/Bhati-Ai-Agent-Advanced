# Rawal AI

**Rawal AI** is a self-hosted autonomous AI workspace for building software, researching problems, operating browser and terminal tools, and shipping working results from a controlled project sandbox.

It provides a React/Vite web application, a FastAPI backend, streaming agent runs, project and thread memory, file and terminal tools, browser automation, MCP integrations, provider-agnostic LLM support, PWA installation, Telegram control, Docker deployment, and an optional Capacitor Android shell.

> **Security principle:** Rawal AI is self-hosted software. API keys, workspaces, model traffic, and deployment data remain under the operator's control when the service is deployed on infrastructure owned by the operator.

## What the project includes

| Area | Capability |
|---|---|
| Agent runtime | Autonomous multi-step loop, tool execution, steering, interrupt, permissions, context compaction, repeat-loop protection, and visible failure states |
| Development workspace | Chat, project threads, file tree, editor, terminal, browser preview, artifacts, Git operations, and live activity events |
| Model support | OpenAI-compatible providers, Anthropic-compatible providers, custom proxies, model discovery, streaming, retries, and stall detection |
| Isolation | Docker sandbox when available; path-confined local sandbox for Render and other hosts without a Docker daemon |
| Connectivity | REST, Server-Sent Events (SSE), WebSockets, MCP servers, GitHub, Vercel, Render, Hugging Face, Google Drive, and Telegram |
| Clients | Responsive web UI, installable PWA, Android Capacitor shell, desktop browser, and mobile browser |
| Operations | SQLite by default, optional MongoDB persistence, optional Google Drive archives, health endpoint, structured logs, and deployment blueprints |

## Repository layout

```text
.
├── backend/                  FastAPI API, agent runtime, tools, sandbox, storage, tests
│   ├── app/agent/            Prompts, loop, memory, permissions, compaction, scheduler
│   ├── app/api/v1/           Auth, projects, threads, chat, files, terminal, preview
│   ├── app/llm/              Provider clients, streaming, retries, stall watchdog
│   ├── app/sandbox/          Docker, local, GitHub Actions, and remote sandbox backends
│   ├── app/tools/            Files, shell, browser, web, Git, MCP, tasks, artifacts
│   └── tests/                Backend regression and integration tests
├── frontend/                 React 18 + Vite + TypeScript + Tailwind application
│   ├── src/pages/             Workspace, login, and sharing views
│   ├── src/components/        Chat, layout, terminal, browser, settings, voice, projects
│   ├── src/hooks/             SSE, network adaptation, theme, voice, and device behavior
│   └── android/               Capacitor Android shell
├── cli/                      Private-repository installer CLI source
├── sandbox/                  Docker image used for isolated project execution
├── docs/                     Deployment, configuration, architecture, security, and runbooks
├── Dockerfile                Production image: frontend build + backend runtime
├── docker-compose.yml         Local Docker deployment
├── render.yaml               Render backend blueprint
├── vercel.json                Vercel SPA routing and security headers
├── install.sh                Linux, macOS, and Termux installer
├── install.ps1               Windows PowerShell installer
└── Makefile                  Local development and quality commands
```

## Requirements

For local development, install Python 3.11 or newer, Node.js 20 or newer, npm, and Git. Docker Desktop or Docker Engine is recommended for isolated execution but is not required when using the local sandbox. A MongoDB Atlas database is optional and is strongly recommended for ephemeral hosts such as Render Free. An LLM provider API key is required before the first agent turn.

## Fastest local setup

### Linux, macOS, or Termux

```bash
git clone https://github.com/vmeducatedlucifer-commits/Bhati-Ai-Agent.git
cd Bhati-Ai-Agent
bash install.sh
```

Configure `backend/.env`, then start both services:

```bash
make dev
```

The web client is available at `http://localhost:5173`. The API and interactive documentation are available at `http://localhost:8000/api/docs`.

### Windows PowerShell

```powershell
git clone https://github.com/vmeducatedlucifer-commits/Bhati-Ai-Agent.git
cd Bhati-Ai-Agent
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

Start the backend and frontend in separate terminals:

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

```powershell
npm --prefix frontend run dev
```

### Docker Compose

Docker is the simplest complete local deployment because it builds the web application, backend, and sandbox image together.

```bash
cp backend/.env.example backend/.env
# Edit backend/.env and set DEFAULT_LLM_API_KEY plus production secrets.
docker compose up --build
```

Open `http://localhost:8000`. The production container serves the built frontend and API from one origin. Stop it with `docker compose down`; persistent local data is stored in `./data`.

## Environment configuration

Rawal AI loads variables from `backend/.env` locally and from the hosting provider's secret manager in production. Copy the complete block below when creating a new environment. Blank optional values are valid.

```dotenv
# Application
ENV=dev
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=INFO
CORS_ORIGINS=*

# Authentication and signing; replace both values in production
SECRET_KEY=replace-with-a-long-random-secret
JWT_SECRET=replace-with-a-different-long-random-secret
JWT_ALGORITHM=HS256
JWT_TTL_HOURS=72
AUTH_PASSWORD=
AUTH_USERNAME=rawal
ALLOW_ANONYMOUS=false

# Storage
DATA_DIR=./data
WORKSPACE_ROOT=./data/workspaces
DATABASE_URL=
MONGO_URI=
MONGODB_URI=
DATABASE_NAME=rawal_ai
MONGODB_DB_NAME=
GDRIVE_CREDENTIALS_JSON=
GDRIVE_FOLDER_ID=

# Default LLM provider
DEFAULT_LLM_BASE_URL=https://api.openai.com/v1
DEFAULT_LLM_API_KEY=
DEFAULT_LLM_MODEL=gpt-4o-mini
LLM_TIMEOUT_SECONDS=600
MAX_AGENT_STEPS=80
MAX_CONTEXT_TOKENS=160000
COMPACT_AT_RATIO=0.75

# Sandbox
SANDBOX_BACKEND=auto
SANDBOX_IMAGE=rawal-ai-sandbox:latest
SANDBOX_FALLBACK_IMAGE=python:3.12-slim
SANDBOX_CPUS=1.0
SANDBOX_MEMORY_MB=2048
SANDBOX_IDLE_TIMEOUT_S=1800
SANDBOX_NETWORK=bridge
SANDBOX_COMMAND_TIMEOUT_S=300
SUPERSERVE_API_KEY=
SUPERSERVE_API_URL=https://api.superserve.ai
SUPERSERVE_TEMPLATE=superserve/base
SUPERSERVE_POOL_SIZE=5

# Integrations
GITHUB_TOKEN=
GITHUB_WEBHOOK_SECRET=
VERCEL_TOKEN=
RENDER_TOKEN=
HF_TOKEN=
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_IDS=

# Search
SEARCH_PROVIDER=duckduckgo
TAVILY_API_KEY=
BRAVE_API_KEY=

# Email transcript sharing, optional
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASS=
SMTP_FROM=
```

### Important variables

| Variable | Required | Recommended value | Notes |
|---|---:|---|---|
| `DEFAULT_LLM_API_KEY` | Yes | Provider secret | The fallback model provider used before a provider is configured in the UI |
| `DEFAULT_LLM_BASE_URL` | Yes | `https://api.openai.com/v1` | Any compatible OpenAI-style endpoint is supported |
| `DEFAULT_LLM_MODEL` | Yes | `gpt-4o-mini` | Provider model identifier |
| `AUTH_PASSWORD` | Production | Strong password | Enables the login gate; an empty value is open local mode |
| `ALLOW_ANONYMOUS` | No | `false` | Only set `true` when intentionally exposing an unauthenticated instance |
| `SECRET_KEY` | Production | Random 64+ character value | Application encryption/signing secret |
| `JWT_SECRET` | Production | Different random 64+ character value | Session token signing secret |
| `CORS_ORIGINS` | Split deployment | Exact Vercel origin | Comma-separated origins; avoid `*` in production |
| `MONGO_URI` or `MONGODB_URI` | Render recommended | MongoDB Atlas URI | Preserves data across Render restarts and redeploys |
| `DATABASE_NAME` | Render recommended | `rawal_ai` | MongoDB database name |
| `GDRIVE_CREDENTIALS_JSON` | Optional | Service-account JSON | Workspace archive backup |
| `SANDBOX_BACKEND` | Host-dependent | `local` on Render, `docker` locally | Render does not expose a Docker daemon |
| `BROWSER_CDP_URL` | Render browser mode | Remote Chromium WebSocket | Keeps Chromium outside the Render API process; recommended on Free tier |
| `BROWSER_MAX_SESSIONS` | No | `1` | Limits concurrent browser sessions and memory |
| `BROWSER_IDLE_TIMEOUT_S` | No | `900` | Browser lifecycle idle budget |
| `GITHUB_TOKEN` | Optional | Fine-grained token | Git sync, repository creation, and Actions integrations |
| `TELEGRAM_BOT_TOKEN` | Optional | BotFather token | Telegram control plane |

For individual copying, each variable is defined separately in [`backend/.env.example`](backend/.env.example). Never commit `backend/.env`, provider keys, database credentials, or private tokens.

## Production deployment: Render backend + Vercel frontend

This is the recommended split deployment. Render runs the stateful API and agent runtime. Vercel serves the static React client. The frontend connects to Render through `VITE_API_URL`.

### Step 1: Prepare persistence

Create a MongoDB Atlas database before deploying the backend. Add the Render service's outbound access policy as required by your Atlas configuration. Copy the connection string and database name; do not commit either value.

### Step 2: Deploy the backend to Render

1. Open [Render](https://render.com) and choose **New → Blueprint**.
2. Connect the private GitHub repository.
3. Render detects [`render.yaml`](render.yaml) and builds the production Docker image.
4. Set `DEFAULT_LLM_API_KEY`, `AUTH_PASSWORD`, `MONGO_URI`, and `DATABASE_NAME` in the Render environment dashboard.
5. Set `CORS_ORIGINS` temporarily to `*` during the first boot only, or set it to the final Vercel URL if known.
6. Deploy and verify:

```text
https://YOUR-RENDER-SERVICE.onrender.com/api/v1/health
https://YOUR-RENDER-SERVICE.onrender.com/api/docs
```

Render uses `SANDBOX_BACKEND=local` because a Render web service does not provide the host Docker socket. Set `DATA_DIR=/data` and `WORKSPACE_ROOT=/data/workspaces` as provided by the blueprint. MongoDB is required if workspace and conversation data must survive free-tier spin-downs.

### Browser tools on Render Free

Do not run a local Chromium instance inside a 512 MB Render Free API container for regular browser automation. Configure a managed or separately hosted Chromium CDP endpoint instead:

```dotenv
BROWSER_CDP_URL=wss://YOUR_BROWSER_PROVIDER/playwright?token=YOUR_PROVIDER_TOKEN
BROWSER_MAX_SESSIONS=1
BROWSER_IDLE_TIMEOUT_S=900
```

Set `BROWSER_CDP_URL` only in Render's secret environment. Rawal AI connects to the remote browser with Playwright CDP and keeps browser memory away from the API service. Browserless, Browserbase, a private VPS, or a browser running on an always-on local machine can provide the endpoint. Leave it empty only when the backend host has enough memory for Chromium.

### Step 3: Deploy the frontend to Vercel

1. Open [Vercel](https://vercel.com) and import the same repository.
2. Set **Root Directory** to `frontend`.
3. Use the Vite preset, `npm run build` as the build command, and `dist` as the output directory.
4. Add this Vercel environment variable:

```dotenv
VITE_API_URL=https://YOUR-RENDER-SERVICE.onrender.com
```

5. Deploy the frontend.
6. Return to Render and replace `CORS_ORIGINS` with the exact Vercel origin, for example `https://rawal-ai.vercel.app`.
7. Redeploy the backend and test login, project creation, chat streaming, terminal, and preview.

The frontend internally appends `/api/v1` to `VITE_API_URL`; do not set the variable to `/api/v1` unless the application code is changed accordingly.

Detailed production guidance is in [`docs/deployment.md`](docs/deployment.md).

## Fully local production deployment

Use Docker Compose when frontend and backend should share one origin and the machine has Docker.

```bash
cp backend/.env.example backend/.env
# Set ENV=prod, AUTH_PASSWORD, DEFAULT_LLM_API_KEY, SECRET_KEY, and JWT_SECRET.
docker compose up --build -d
docker compose ps
curl http://localhost:8000/api/v1/health
```

The service binds to port `8000`. Change the host port if necessary:

```bash
APP_PORT=8080 docker compose up --build
```

For a non-Docker development deployment, use `bash install.sh`, set `SANDBOX_BACKEND=local`, and run `make dev`. This mode is suitable for a trusted personal machine; it should not be exposed directly to the public internet without a reverse proxy and authentication.

## Rawal installer and private distribution

The repository contains platform installers:

```bash
bash install.sh       # Linux, macOS, Termux
.\install.ps1         # Windows PowerShell
```

The `cli/` directory contains the private-repository installer logic. It is not published to npm. Authorized operators can run it with a read-only GitHub token supplied through `RAWAL_GITHUB_TOKEN`, `GH_TOKEN`, or `GITHUB_TOKEN`; the token is not written to disk or printed in logs.

```bash
export RAWAL_GITHUB_TOKEN="YOUR_READ_ONLY_TOKEN"
node cli/index.js --mode docker --dir rawal-ai
```

Never place a GitHub token in source code, Dockerfiles, `.env.example`, shell scripts, or public package metadata.

## Client installation

### PWA on Android or desktop

Open the deployed Vercel or local HTTPS URL in Chrome or Edge. Choose **Install app** or **Add to Home screen**. The service worker provides the installable shell and the responsive workspace adapts to mobile screens.

### Native Android shell

The Capacitor project is in `frontend/android/`. From a machine with Android Studio and the Android SDK:

```bash
cd frontend
npm install
npm run cap:build
```

The GitHub Actions workflow can build an APK from the repository. Configure signing secrets in GitHub Actions before distributing a signed release.

## Agent operation

A project contains threads. Each user turn creates a run that streams events over SSE. Agent mode can inspect files, run sandbox commands, use browser tools, call connectors, create artifacts, and update the workspace. Plan mode is read-only and produces a proposal. Chat mode disables tools.

The runtime includes a stall watchdog for silent provider streams, exponential retries for temporary provider errors, repeat-tool-call protection, run interruption, mid-run steering, permission prompts, context compaction, and stale-run recovery after process restarts. The frontend reconnects to SSE with sequence-based resume so a temporary network drop does not silently lose events.

Use **ask** permission mode for shared or production work. Use **auto** only in a trusted isolated workspace. Use **plan** before destructive or unfamiliar operations.

## API and streaming

The API base path is `/api/v1`. Interactive OpenAPI documentation is served at `/api/docs`.

| Area | Representative endpoints |
|---|---|
| Health | `GET /health`, `GET /capabilities`, `GET /tools` |
| Projects | `GET/POST /projects`, `GET/PATCH/DELETE /projects/{id}` |
| Threads | `GET/POST /threads`, `GET/PATCH/DELETE /threads/{id}` |
| Agent runs | `POST /threads/{id}/messages`, `/interrupt`, `/steer`, `/permissions` |
| Events | `GET /threads/{id}/stream?after=<sequence>` using SSE |
| Files | Read, write, list, upload, download, and delete under thread file routes |
| Terminal | WebSocket terminal plus sandbox lifecycle and command execution |
| Preview | `/preview/{thread_id}/{port}/{path}` reverse proxy |
| Integrations | Provider, GitHub, Vercel, Render, Hugging Face, MCP, and Telegram routes |

For endpoint payloads, use the generated API docs rather than copying undocumented request examples.

## Telegram control plane

Create a bot with [BotFather](https://t.me/BotFather), record the bot token, identify allowed Telegram user IDs, and set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_USER_IDS`. The bot can create chats, inspect projects, list files, execute approved commands, and report run status. Keep the allow-list restrictive.

## Quality checks

Run the full checks before deployment:

```bash
# Backend
cd backend
.venv/bin/python -m pytest -q
.venv/bin/ruff check app/ tests/
cd ..

# Frontend
npm --prefix frontend run typecheck
npm --prefix frontend run build

# CLI package without publishing
cd cli
npm pack --dry-run
node --check index.js
```

At the time of this documentation rewrite, the focused agent/API regression suite and frontend production build pass. Review the test output in CI for the complete environment-specific result.

## Security checklist

Before exposing an instance publicly, set strong unique `SECRET_KEY`, `JWT_SECRET`, and `AUTH_PASSWORD` values. Restrict `CORS_ORIGINS` to known frontend origins. Use MongoDB or another durable database for ephemeral hosting. Use Docker isolation locally when untrusted code may run. Limit GitHub and Telegram tokens to the smallest required scope. Put TLS in front of any self-hosted public deployment. Rotate any secret that was pasted into chat, logs, issue trackers, or commits.

See [`docs/security.md`](docs/security.md) for the threat model and deployment hardening checklist.

## Troubleshooting

| Symptom | Resolution |
|---|---|
| `No model configured` | Set `DEFAULT_LLM_API_KEY` and `DEFAULT_LLM_MODEL`, or configure a provider in Settings → Models. |
| Agent appears stuck | Check the event feed and backend logs. The stall watchdog ends silent streams visibly; use Interrupt, then retry with a healthy provider. |
| Chat works locally but not on Vercel | Check `VITE_API_URL`, Render health, browser CORS errors, and exact `CORS_ORIGINS`. |
| Render data disappears | Configure `MONGO_URI` or `MONGODB_URI`; the local filesystem is not durable on ephemeral instances. |
| Sandbox cannot start | Use `SANDBOX_BACKEND=local` on Render, or start Docker and use `SANDBOX_BACKEND=docker` locally. |
| PWA shows an old build | Unregister the service worker or use Settings → Data → clear cache, then reload. |
| Telegram does not respond | Verify the bot token, allow-list user IDs, and send `/start` to the bot. |
| Port is occupied | Change `PORT` for the backend or pass a Vite `--port` value for the frontend. |
| Private installer cannot clone | Supply a read-only token through `RAWAL_GITHUB_TOKEN`, `GH_TOKEN`, or `GITHUB_TOKEN`; never hardcode it. |

## Documentation index

- [`docs/deployment.md`](docs/deployment.md) — Render, Vercel, Docker, local, Termux, and rollback procedures.
- [`docs/configuration.md`](docs/configuration.md) — Environment variables, secrets, providers, persistence, and sandbox settings.
- [`docs/architecture.md`](docs/architecture.md) — Runtime components, event flow, sandbox model, and data boundaries.
- [`docs/security.md`](docs/security.md) — Threat model, authentication, secrets, sandbox, and public deployment hardening.
- [`docs/troubleshooting.md`](docs/troubleshooting.md) — Diagnostic commands, logs, common failures, and recovery runbooks.
- [`docs/browser-automation.md`](docs/browser-automation.md) — Browser runtime and recovery behavior.
- [`docs/manus-connector-catalog.md`](docs/manus-connector-catalog.md) — Connector catalog and MCP setup notes.

## License

This project is distributed under the MIT License. See [`LICENSE`](LICENSE) if present in your checkout.

## References

[1]: https://render.com/docs "Render documentation"
[2]: https://vercel.com/docs "Vercel documentation"
[3]: https://docs.docker.com/compose/ "Docker Compose documentation"
[4]: https://docs.npmjs.com/cli/v10/commands/npm-publish "npm publish documentation"
[5]: https://fastapi.tiangolo.com/ "FastAPI documentation"
[6]: https://vite.dev/guide/ "Vite documentation"
[7]: https://capacitorjs.com/docs "Capacitor documentation"
[8]: https://www.mongodb.com/docs/atlas/ "MongoDB Atlas documentation"
[9]: https://core.telegram.org/bots/api "Telegram Bot API documentation"
[10]: https://docs.github.com/en/actions "GitHub Actions documentation"

<!-- Rawal AI documentation version: 1.0.0 -->
