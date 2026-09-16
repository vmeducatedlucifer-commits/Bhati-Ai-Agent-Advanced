# Rawal CLI

Install the private self-hosted Rawal AI autonomous workspace with one command:

```bash
RAWAL_GITHUB_TOKEN=ghp_... node cli/index.js
```

Local development instead of Docker:

```bash
RAWAL_GITHUB_TOKEN=ghp_... node cli/index.js --mode local --dir rawal-ai
```

The installer accepts `RAWAL_GITHUB_TOKEN`, `GH_TOKEN`, or `GITHUB_TOKEN` from the environment. It uses the token only for the Git operation, redacts it from logs, and never writes it into the checkout or package. The repository remains private and every installer user must have an authorized GitHub token with read access.

PowerShell:

```powershell
$env:RAWAL_GITHUB_TOKEN = "ghp_..."
node cli/index.js --mode docker
```

Configure `backend/.env` after installation. Never commit tokens or put them in shell history.

The `rawal` npm package is intentionally **not published**. For controlled distribution, share this private repository or distribute the CLI through a private artifact registry with its own authentication.
