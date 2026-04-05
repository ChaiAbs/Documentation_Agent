# Documentation Agent

This repo runs as a Google ADK documentation workflow in `adk web`.

The flow is built around:

- a project `.zip` file
- a documentation template (`.md` or `.txt`)

They then run a two-agent workflow:

1. `code_analysis_writer` reads the uploaded codebase and drafts documentation text.
2. `template_fitter` reshapes that draft to fit the uploaded documentation template.

The result is a generated Markdown file saved as an ADK artifact for download.

## ADK Web Mode

The ADK agent lives in [documentation_adk/agent.py](/Users/chai/Documents/documentation_agent/documentation_adk/agent.py).

ADK expects you to run `adk web` from the parent directory that contains the agent folder. In this repo, that means running the command from the repo root.

### Run with ADK Web

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Set your Gemini key:

```bash
export GOOGLE_API_KEY=your_key_here
```

4. Start the ADK web UI from this repo root:

```bash
adk web --port 8000
```

5. Open `http://localhost:8000`
6. Select `documentation_adk` or `documentation_agent` in the ADK UI
7. Upload:
   - one project `.zip`
   - one template `.md` or `.txt`
8. Ask the agent to generate the documentation

The agent will read uploaded artifacts, run the two worker agents, and save the final Markdown back as an ADK artifact for download.

## Files

- `documentation_adk/agent.py`: ADK Web coordinator and entrypoint
- `documentation_adk/sub_agents/`: worker agents
- `documentation_adk/prompts/`: prompt text split by agent
- `documentation_adk/tools.py`: ADK artifact loading and generated-file saving
- `documentation_adk/project_context.py`: repository summarization helpers

## Setup

1. Create a virtual environment and activate it.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Set your Gemini key:

```bash
export GOOGLE_API_KEY=your_key_here
```

4. Run ADK Web:

```bash
adk web --port 8000
```

5. Open `http://localhost:8000`

## Architecture

- `Google ADK` powers the worker-agent workflow
- `documentation_adk/tools.py` reads uploaded ADK artifacts and saves the generated document back to artifacts
- `build_project_context()` extracts a lightweight repository tree plus representative file excerpts from the uploaded zip

## Template Expectations

The uploaded template can be:

- a Markdown file with placeholders like `{{project_name}}`, `{{overview}}`, `{{setup}}`
- a Markdown outline with headings that should be filled in
- a plain-text documentation skeleton

## Notes

- The generated output is saved as a Markdown artifact in ADK Web.
- This scaffold assumes UTF-8 templates.
- For production use, you would likely add persistent artifact storage, background jobs, richer project parsing, and stronger validation.
