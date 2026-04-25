# Documentation Agent

An AI-powered documentation generator that analyzes your codebase and produces polished, structured `.docx` documentation through a conversational review loop.

Connect a GitHub repository (public or private via token) or upload a project ZIP, choose a template, preview the draft, suggest edits, and download the final file — all from a single split-screen interface.

## Demo

### 1. Start a session

![Start screen](screenshots/01-start.png)

The agent greets you and explains what it needs. Type **"github"** (or **"zip"** to upload an archive instead) and it immediately asks for your repository URL. Once provided, it confirms whether the repo is public or private and — for private repos — prompts for a personal access token. The right-hand panel shows a placeholder until the first draft is ready.

### 2. Documentation preview loads automatically

![Preview loaded](screenshots/02-preview.png)

After you supply the URL, confirm visibility, and choose a template (or accept the default), the agent fetches the repo, analyzes the codebase, and streams a rendered documentation draft into the right panel. The example here shows a full project documentation for a medical image diagnosis deep-learning project, with an overview, features list, architecture details, and more — all structured and formatted automatically.

### 3. Confirm, save, and download

![Download ready](screenshots/03-download.png)

Reply **"save"** (or **"confirm"**) when you're satisfied. The agent finalizes the `.docx` file and a **Download** button labeled with the filename appears in the preview header. Click it and the file downloads directly to your machine — no extra steps.

---

## Features

- **Split-screen UI** — chat on the left, live document preview on the right
- **GitHub or ZIP input** — works with public repos, private repos (PAT), or uploaded ZIP archives
- **Custom or default template** — upload your own `.docx`/`.md` template or use the built-in one
- **Human review loop** — preview the draft, request revisions in plain English, save only when ready
- **One-click `.docx` download** — final output is a properly formatted Word document
- **Deployed on Cloud Run** — no local setup needed for end users

## Tech Stack

| Layer | Technology |
|---|---|
| Agent framework | [Google ADK](https://github.com/google/adk-python) |
| LLM | Google Gemini (`gemini-2.5-flash`) |
| API server | FastAPI (via `get_fast_api_app`) |
| Frontend | Vanilla JS + marked.js (custom split-screen UI) |
| Deployment | Google Cloud Run + Cloud Build |

## Local Setup

### Prerequisites

- Python 3.11+
- A [Gemini API key](https://aistudio.google.com/app/apikeys)

### 1. Clone and create a virtual environment

```bash
git clone <your-repo-url>
cd documentation_agent_v2
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Edit `documentation_adk/.env`:

```env
GOOGLE_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
USE_LOCAL_STORAGE=true
```

### 4. Run the server

```bash
python main.py
```

Open `http://localhost:8080` in your browser.

## Usage

1. **Start a conversation** — say hello or type `github` / `zip` to begin
2. **Provide your source**:
   - *GitHub*: paste the repository URL, confirm public/private, supply a PAT if needed
   - *ZIP*: upload your project archive when prompted
3. **Choose a template** — upload a custom template or press Enter to use the default
4. **Review the preview** — the draft loads in the right panel; request any revisions in plain English
5. **Save** — reply `save` or `confirm` to generate the final `.docx`
6. **Download** — click the **Download** button that appears in the preview header

## Project Structure

```
documentation_agent_v2/
├── main.py                      # FastAPI entry point + download endpoint
├── requirements.txt
├── cloudbuild.yaml              # Cloud Build CI/CD pipeline
├── Dockerfile
├── static/
│   └── index.html               # Split-screen chat + preview UI
└── documentation_adk/
    ├── __init__.py              # Exports root_agent
    ├── agent.py                 # Root coordinator agent
    ├── config.py                # Env var loading
    ├── callbacks.py             # ADK callback hooks
    ├── tools.py                 # load_project, preview, finalize tools
    ├── project_context.py       # GitHub fetch & ZIP extraction
    ├── prompts/                 # Agent instruction prompts
    └── sub_agents/
        ├── analysis_agent.py    # Drafts documentation from source
        └── template_agent.py   # Fits draft to the chosen template
```

## Deployment (Google Cloud Run)

The repo includes a `cloudbuild.yaml` for automated deployment via Cloud Build triggers.

### Required Cloud Build configuration

1. Grant the Cloud Build service account the **Cloud Run Admin** and **Service Account User** roles
2. Store your Gemini API key as a Secret Manager secret (e.g. `GOOGLE_API_KEY`) and grant the service account access
3. Connect your GitHub repo to a Cloud Build trigger pointing at `cloudbuild.yaml`

### Manual deploy

```bash
gcloud builds submit --config cloudbuild.yaml
```

The build tags the image with `$COMMIT_SHA`, pushes it to Artifact Registry, and deploys to Cloud Run in `australia-southeast1`.

### Environment variables on Cloud Run

| Variable | Value |
|---|---|
| `GEMINI_MODEL` | `gemini-2.5-flash` |
| `USE_LOCAL_STORAGE` | `true` |
| `SERVE_WEB_INTERFACE` | `false` |
| `GOOGLE_API_KEY` | set via Secret Manager |

> **Note:** The service runs with `--max-instances=1` to ensure artifact files are always on the same instance as the download request. For a multi-instance production deployment, swap `USE_LOCAL_STORAGE` for a Cloud Storage–backed artifact service.

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_API_KEY` | required | Gemini API key |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model ID |
| `USE_LOCAL_STORAGE` | `false` | Use disk-based artifact storage |
| `SERVE_WEB_INTERFACE` | `false` | Enable ADK's built-in web UI (disabled — custom UI is used) |
| `PORT` | `8080` | HTTP port |
| `ALLOW_ORIGINS` | (none) | Comma-separated CORS origins |

## License

MIT
