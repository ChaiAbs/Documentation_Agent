# Documentation Agent v2

An AI-powered documentation generation system that automatically creates software project documentation from source code repositories. Upload a project ZIP and a documentation template — the agent analyzes your codebase and produces polished, structured documentation with a human review loop.

## Features

- **Two-agent pipeline**: a Code Analysis Agent drafts documentation from your codebase, then a Template Fitter Agent reshapes it to match your template
- **Flexible templates**: supports Markdown files with placeholders (`{{overview}}`, `{{setup}}`), heading-based outlines, or plain-text skeletons
- **Human review loop**: generates a draft preview, accepts natural-language revision requests, and saves only when you confirm
- **Intelligent file analysis**: prioritizes key files (README, package.json, requirements.txt, etc.), skips build artifacts, and respects token/size limits
- **ADK Web UI**: full browser-based interface with file upload and artifact download

## Tech Stack

- **Python 3.x** with async/await
- **[Google ADK](https://github.com/google/adk-python)** — agent orchestration framework
- **Google Gemini** — LLM backend (default: `gemini-2.0-flash`)
- **python-dotenv** — environment configuration

## Project Structure

```
documentation_agent_v2/
├── requirements.txt
├── .env.example
└── documentation_adk/
    ├── __init__.py          # Exports root_agent
    ├── agent.py             # Root coordinator agent
    ├── config.py            # Loads env vars
    ├── callbacks.py         # ADK callback hooks
    ├── tools.py             # ADK tools (load, preview, finalize)
    ├── project_context.py   # ZIP extraction & file analysis
    ├── prompts/             # Agent instruction prompts
    └── sub_agents/
        ├── analysis_agent.py
        └── template_agent.py
```

## Setup

### 1. Clone and create a virtual environment

```bash
git clone <your-repo-url>
cd documentation_agent_v2
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
export GOOGLE_API_KEY=your_gemini_api_key_here
export GEMINI_MODEL=gemini-2.0-flash  # optional, this is the default
```

Or create a `.env` file in the repo root:

```
GOOGLE_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.0-flash
```

You can get a Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikeys).

### 4. Start the ADK web server

```bash
adk web --port 8000
```

Then open `http://localhost:8000` and select `documentation_adk` from the agent list.

## Usage

1. **Upload your project** as a `.zip` file via the ADK Web UI
2. **Upload a documentation template** (`.md` or `.txt`)
3. **Ask the agent** to generate documentation (e.g. _"Generate documentation for this project"_)
4. **Review the draft** — request revisions in plain English if needed:
   - _"Make the overview shorter"_
   - _"Remove the setup section"_
   - _"Add a section about configuration"_
5. **Confirm** to save — say _"confirm"_, _"looks good"_, _"save it"_, etc.
6. **Download** the generated file from the artifacts area

## Template Format

The uploaded template can be:

- A Markdown file with placeholders like `{{project_name}}`, `{{overview}}`, `{{setup}}`
- A Markdown outline with headings to be filled in
- A plain-text documentation skeleton

The generated output is saved as a Markdown artifact (filename: `{project_name}-documentation.md`).

## Configuration

| Variable | Default | Description |
|---|---|---|
| `GOOGLE_API_KEY` | required | Gemini API key |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Model to use (e.g. `gemini-2.5-flash`) |

### Analysis limits (`project_context.py`)

| Setting | Value | Description |
|---|---|---|
| `MAX_FILE_BYTES` | 24,000 | Max bytes read per file |
| `MAX_TEXT_FILES` | 18 | Max files included in context |
| `MAX_TOTAL_CHARS` | 80,000 | Total character budget for excerpts |

Ignored directories: `.git`, `node_modules`, `.venv`, `dist`, `build`, `__pycache__`, `.next`, `coverage`

## How It Works

```
User uploads ZIP + template
         ↓
Root Agent (coordinator)
         ↓
prepare_documentation_preview()
    ├── Analysis Agent
    │     ├── Extracts file tree & key excerpts from ZIP
    │     └── Drafts documentation
    └── Template Agent
          └── Fits draft to the provided template
         ↓
Preview shown to user
         ↓
   ┌─────┴──────┐
Revision     Confirmation
   │               │
Re-draft     finalize_documentation()
                   │
             Artifact saved & ready for download
```

## Notes

- This project assumes UTF-8 templates.
- For production use you would likely add persistent artifact storage, background job queues, richer AST-based project parsing, rate limiting, and user authentication.

## License

MIT
