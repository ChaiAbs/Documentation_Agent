from __future__ import annotations

from google.adk.agents import LlmAgent

from documentation_adk.config import MODEL
from documentation_adk.prompts import TEMPLATE_AGENT_PROMPT


template_agent = LlmAgent(
    name="template_fitter",
    model=MODEL,
    description="Fits drafted documentation into the uploaded documentation template.",
    instruction=TEMPLATE_AGENT_PROMPT,
)
