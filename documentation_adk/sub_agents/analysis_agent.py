from __future__ import annotations

from google.adk.agents import LlmAgent

from documentation_adk.config import MODEL
from documentation_adk.prompts import ANALYSIS_AGENT_PROMPT


analysis_agent = LlmAgent(
    name="code_analysis_writer",
    model=MODEL,
    description="Analyzes repository context and drafts software documentation text.",
    instruction=ANALYSIS_AGENT_PROMPT,
)
