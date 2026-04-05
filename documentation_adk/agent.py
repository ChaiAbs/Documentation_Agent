from __future__ import annotations

from google.adk.agents import LlmAgent

from documentation_adk.callbacks import maybe_handle_pending_preview_follow_up
from documentation_adk.callbacks import respond_after_documentation_tool
from documentation_adk.callbacks import scrub_uploaded_files_from_llm_request
from documentation_adk.config import MODEL
from documentation_adk.prompts import MAIN_AGENT_PROMPT
from documentation_adk.tools import finalize_documentation
from documentation_adk.tools import prepare_documentation_preview


root_agent = LlmAgent(
    name="documentation_agent",
    model=MODEL,
    description="Generates project documentation from an uploaded zip file and a documentation template, with a human review step before saving.",
    instruction=MAIN_AGENT_PROMPT,
    before_model_callback=[
        maybe_handle_pending_preview_follow_up,
        respond_after_documentation_tool,
        scrub_uploaded_files_from_llm_request,
    ],
    tools=[
        prepare_documentation_preview,
        finalize_documentation,
    ],
)

__all__ = ["root_agent"]
