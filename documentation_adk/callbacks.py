from __future__ import annotations

import re

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse
from google.adk.models.llm_request import LlmRequest
from google.genai import types

PENDING_DOCUMENT_CONTENT_KEY = "pending_document_content"
REVISION_VERBS = (
    "change",
    "update",
    "remove",
    "delete",
    "drop",
    "omit",
    "add",
    "revise",
    "edit",
    "rewrite",
    "regenerate",
    "shorten",
    "expand",
    "replace",
    "rename",
    "reword",
)


def _latest_user_text(callback_context: CallbackContext) -> str:
    texts: list[str] = []
    for part in callback_context.user_content.parts or []:
        if part.text:
            texts.append(part.text)
    return "\n".join(texts).strip()


def _describe_part(part: types.Part) -> str | None:
    if part.inline_data:
        name = part.inline_data.display_name or "uploaded file"
        mime_type = part.inline_data.mime_type or "unknown mime type"
        return f"[Uploaded file available to tools: {name} ({mime_type})]"
    if part.file_data:
        name = part.file_data.display_name or part.file_data.file_uri or "uploaded file"
        mime_type = part.file_data.mime_type or "unknown mime type"
        return f"[Uploaded file available to tools: {name} ({mime_type})]"
    return None


def _looks_like_confirmation(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    if not normalized:
        return False

    explicit_phrases = {
        "confirm",
        "confirmed",
        "approve",
        "approved",
        "save",
        "save it",
        "finalize",
        "finalise",
        "looks good",
        "this looks good",
        "ship it",
    }
    if normalized in explicit_phrases:
        return True

    return any(
        phrase in normalized
        for phrase in (
            "confirm and save",
            "save the file",
            "save the draft",
            "finalize the draft",
            "finalise the draft",
            "go ahead and save",
            "approved to save",
        )
    )


def _looks_like_revision_request(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    if not normalized or _looks_like_confirmation(normalized):
        return False

    if normalized in {
        "changes",
        "change it",
        "update it",
        "revise it",
        "edit it",
    }:
        return True

    direct_request_patterns = (
        rf"^(?:please\s+)?(?:{'|'.join(REVISION_VERBS)})\b",
        rf"^(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:{'|'.join(REVISION_VERBS)})\b",
        rf"^(?:i\s+want|i\s+would\s+like|i'd\s+like|let's)\s+(?:to\s+)?(?:{'|'.join(REVISION_VERBS)})\b",
        r"^(?:please\s+)?make\s+(?:the\s+)?(?:draft|preview|document|doc|intro|introduction|overview|summary|title|heading)\b",
    )
    if any(re.search(pattern, normalized) for pattern in direct_request_patterns):
        return True

    if re.search(
        r"\b(?:draft|preview|document|doc|intro|introduction|overview|summary|title|heading|section)\b.*\bshould be\b",
        normalized,
    ):
        return True

    if re.search(
        rf"\b(?:{'|'.join(REVISION_VERBS)})\b.*\b(?:section|intro|introduction|overview|summary|title|heading|draft|preview|document|doc)\b",
        normalized,
    ):
        return True

    return False


def _format_preview_response(response: dict, *, is_follow_up: bool = False) -> str:
    if response.get("status") != "preview_ready":
        return response.get(
            "message",
            "I couldn't generate a documentation preview from the uploaded files.",
        )

    filename = response.get("filename", "generated-documentation.md")
    preview_markdown = (response.get("preview_markdown") or "").strip()
    next_step_message = response.get(
        "next_step_message",
        "Reply with any changes you want, or confirm when you want me to save the final file.",
    )
    if is_follow_up:
        return f"{preview_markdown}\n\n{next_step_message}"

    return f"Here is the draft preview for `{filename}`:\n\n{preview_markdown}\n\n{next_step_message}"


def scrub_uploaded_files_from_llm_request(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> None:
    """Replace uploaded file parts with plain text so Gemini never receives raw zip bytes.

    The original uploaded parts remain available in the invocation/session
    context, which allows function tools to recover the actual file contents.
    """
    del callback_context

    sanitized_contents: list[types.Content] = []
    for content in llm_request.contents:
        sanitized_parts: list[types.Part] = []
        for part in content.parts or []:
            if part.text:
                sanitized_parts.append(types.Part.from_text(text=part.text))
                continue

            description = _describe_part(part)
            if description:
                sanitized_parts.append(types.Part.from_text(text=description))

        if sanitized_parts:
            sanitized_contents.append(
                types.Content(role=content.role, parts=sanitized_parts)
            )

    llm_request.contents = sanitized_contents


async def maybe_handle_pending_preview_follow_up(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> LlmResponse | None:
    """Handle preview revisions and confirmations deterministically."""
    del llm_request

    pending_preview = (callback_context.state.get(PENDING_DOCUMENT_CONTENT_KEY) or "").strip()
    if not pending_preview:
        return None

    message = _latest_user_text(callback_context)
    if not message:
        return None

    if _looks_like_confirmation(message):
        from documentation_adk.tools import finalize_documentation

        result = await finalize_documentation(callback_context)
        response_text = result.get(
            "message",
            "I couldn't save the documentation file.",
        )
    elif _looks_like_revision_request(message):
        from documentation_adk.tools import prepare_documentation_preview

        result = await prepare_documentation_preview(
            callback_context,
            revision_instructions=message,
        )
        response_text = _format_preview_response(result, is_follow_up=True)
    else:
        return None

    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=response_text)],
        )
    )


def respond_after_documentation_tool(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> LlmResponse | None:
    """Return plain-text responses after preview/finalize tools complete."""
    del callback_context

    if not llm_request.contents:
        return None

    latest_content = llm_request.contents[-1]
    for part in latest_content.parts or []:
        function_response = part.function_response
        if not function_response:
            continue

        response = function_response.response or {}
        if function_response.name == "prepare_documentation_preview":
            message = _format_preview_response(response, is_follow_up=False)
            return LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=message)],
                )
            )

        if function_response.name == "finalize_documentation":
            message = response.get(
                "message",
                "I couldn't save the documentation file.",
            )
            return LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=message)],
                )
            )

        if function_response.name != "generate_documentation_from_uploads":
            continue

        if response.get("status") != "success":
            message = response.get(
                "message",
                "I couldn't generate the documentation from the uploaded files.",
            )
            return LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=message)],
                )
            )

        filename = response.get("filename", "generated-documentation.md")
        message = (
            f"Your documentation is ready. The generated file is `{filename}` "
            "and it is available in the ADK Web artifacts/download area."
        )
        return LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=message)],
            )
        )

    return None
