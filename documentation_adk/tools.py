from __future__ import annotations

import tempfile
import zipfile
from base64 import b64decode, urlsafe_b64decode
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from google.adk.tools import ToolContext
from google.genai import types

from documentation_adk.project_context import build_project_context


TEMPLATE_SUFFIXES = {".md", ".txt"}
PENDING_DOCUMENT_CONTENT_KEY = "pending_document_content"
PENDING_DOCUMENT_FILENAME_KEY = "pending_document_filename"
PENDING_ANALYSIS_RESULT_KEY = "pending_analysis_result"


def _looks_like_template_name(name: str) -> bool:
    lower_name = name.lower()
    return any(lower_name.endswith(suffix) for suffix in TEMPLATE_SUFFIXES)


def _looks_like_zip_bytes(data: bytes) -> bool:
    return data.startswith(b"PK\x03\x04") or data.startswith(b"PK\x05\x06") or data.startswith(b"PK\x07\x08")


def _looks_like_text(data: bytes) -> bool:
    if not data:
        return False
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


async def _pick_artifacts(
    artifact_names: list[str],
    tool_context: ToolContext,
) -> tuple[str | None, str | None]:
    project_zip = None
    template_file = None

    for name in artifact_names:
        lower_name = name.lower()
        if lower_name.endswith(".zip") and project_zip is None:
            project_zip = name
        elif _looks_like_template_name(name) and template_file is None:
            template_file = name

    if project_zip and template_file:
        return project_zip, template_file

    for name in artifact_names:
        artifact = await tool_context.load_artifact(name)
        if not artifact or not artifact.inline_data:
            continue

        blob = artifact.inline_data
        data = blob.data or b""
        mime_type = (blob.mime_type or "").lower()

        if project_zip is None and (
            _looks_like_zip_bytes(data)
            or mime_type == "application/zip"
            or mime_type == "application/x-zip-compressed"
        ):
            project_zip = name
            continue

        if template_file is None and (
            _looks_like_template_name(name)
            or mime_type.startswith("text/")
            or mime_type == "application/octet-stream" and _looks_like_text(data)
            or _looks_like_text(data)
        ):
            template_file = name

    return project_zip, template_file


def _safe_artifact_filename(name: str, fallback: str) -> str:
    cleaned = Path(name).name.strip()
    return cleaned or fallback


def _extract_suggested_filename(analysis_result: str, fallback: str) -> str:
    match = re.search(
        r"^SUGGESTED_FILENAME:\s*(.+)$",
        analysis_result,
        flags=re.MULTILINE,
    )
    if not match:
        return fallback
    return _safe_artifact_filename(match.group(1).strip(), fallback)


def _normalize_for_comparison(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _normalize_heading_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _remove_requested_markdown_sections(
    markdown: str,
    revision_instructions: str,
) -> tuple[str, bool]:
    targets: list[str] = []
    for match in re.finditer(
        r"(?:remove|delete|drop|omit)\s+(?:the\s+)?(.+?)\s+section\b",
        revision_instructions,
        flags=re.IGNORECASE,
    ):
        target = _normalize_heading_name(match.group(1).replace(" section", ""))
        if target:
            targets.append(target)

    if not targets:
        return markdown, False

    lines = markdown.splitlines()
    headings: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
        if not match:
            continue
        headings.append((index, len(match.group(1)), _normalize_heading_name(match.group(2))))

    if not headings:
        return markdown, False

    ranges_to_remove: list[tuple[int, int]] = []
    for heading_index, heading_level, heading_title in headings:
        if not any(
            target in heading_title or heading_title in target
            for target in targets
        ):
            continue

        end_index = len(lines)
        for next_heading_index, next_heading_level, _ in headings:
            if next_heading_index <= heading_index:
                continue
            if next_heading_level <= heading_level:
                end_index = next_heading_index
                break
        ranges_to_remove.append((heading_index, end_index))

    if not ranges_to_remove:
        return markdown, False

    kept_lines: list[str] = []
    current_index = 0
    for start_index, end_index in sorted(ranges_to_remove):
        if current_index < start_index:
            kept_lines.extend(lines[current_index:start_index])
        current_index = max(current_index, end_index)
    if current_index < len(lines):
        kept_lines.extend(lines[current_index:])

    revised_markdown = "\n".join(kept_lines).strip()
    return revised_markdown or markdown, revised_markdown.strip() != markdown.strip()


def _latest_user_text_from_tool_context(tool_context: ToolContext) -> str:
    texts: list[str] = []
    user_content = getattr(tool_context, "user_content", None)
    for part in getattr(user_content, "parts", None) or []:
        text = getattr(part, "text", None)
        if text:
            texts.append(text)
    return "\n".join(texts).strip()


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


def _resolve_revision_instructions(
    tool_context: ToolContext,
    revision_instructions: str,
) -> str:
    if revision_instructions.strip():
        return revision_instructions.strip()

    existing_preview = tool_context.state.get(PENDING_DOCUMENT_CONTENT_KEY)
    latest_user_text = _latest_user_text_from_tool_context(tool_context)
    if existing_preview and latest_user_text and not _looks_like_confirmation(latest_user_text):
        return latest_user_text
    return ""


def _clear_pending_document_state(tool_context: ToolContext) -> None:
    for key in (
        PENDING_DOCUMENT_CONTENT_KEY,
        PENDING_DOCUMENT_FILENAME_KEY,
        PENDING_ANALYSIS_RESULT_KEY,
    ):
        if key in tool_context.state:
            tool_context.state[key] = ""


async def _run_template_agent(
    template_request: str,
    tool_context: ToolContext,
) -> str | None:
    from google.adk.tools.agent_tool import AgentTool

    from documentation_adk.sub_agents import template_agent

    final_document = await AgentTool(agent=template_agent).run_async(
        args={"request": template_request},
        tool_context=tool_context,
    )
    if not isinstance(final_document, str) or not final_document.strip():
        return None
    return final_document.strip()


def _decode_blob_data(raw_data: bytes | str) -> bytes:
    if isinstance(raw_data, bytes):
        return raw_data

    if not isinstance(raw_data, str):
        return bytes(raw_data)

    candidates = [raw_data, raw_data + ("=" * (-len(raw_data) % 4))]
    for candidate in candidates:
        try:
            return urlsafe_b64decode(candidate)
        except Exception:
            pass
        try:
            return b64decode(candidate)
        except Exception:
            pass

    return raw_data.encode("utf-8", errors="ignore")


def _extract_part_blob(part: Any) -> tuple[bytes, str, str] | None:
    if isinstance(part, dict):
        inline_data = part.get("inline_data")
        if inline_data:
            raw_data = _decode_blob_data(inline_data.get("data") or b"")
            mime_type = (inline_data.get("mime_type") or "").lower()
            display_name = inline_data.get("display_name") or ""
            return raw_data, mime_type, display_name

        file_data = part.get("file_data")
        if file_data:
            mime_type = (file_data.get("mime_type") or "").lower()
            display_name = file_data.get("display_name") or ""
            return b"", mime_type, display_name

        return None

    inline_data = getattr(part, "inline_data", None)
    if inline_data:
        raw_data = _decode_blob_data(inline_data.data or b"")
        mime_type = (inline_data.mime_type or "").lower()
        display_name = getattr(inline_data, "display_name", "") or ""
        return raw_data, mime_type, display_name

    file_data = getattr(part, "file_data", None)
    if file_data:
        mime_type = (getattr(file_data, "mime_type", "") or "").lower()
        display_name = getattr(file_data, "display_name", "") or ""
        return b"", mime_type, display_name

    return None


def _classify_blob(data: bytes, mime_type: str, display_name: str) -> str | None:
    if _looks_like_template_name(display_name):
        return "template"
    if display_name.lower().endswith(".zip"):
        return "zip"
    if _looks_like_zip_bytes(data) or mime_type in {
        "application/zip",
        "application/x-zip-compressed",
    }:
        return "zip"
    if mime_type.startswith("text/") or _looks_like_text(data):
        return "template"
    return None


def _extract_inline_uploads_from_parts(parts: list[Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    project_zip = None
    template_file = None

    for part in parts:
        blob = _extract_part_blob(part)
        if not blob:
            continue
        data, mime_type, display_name = blob
        kind = _classify_blob(data, mime_type, display_name)
        if kind == "zip" and project_zip is None:
            project_zip = {
                "name": _safe_artifact_filename(display_name, "project.zip"),
                "data": data,
                "mime_type": mime_type or "application/zip",
            }
        elif kind == "template" and template_file is None:
            template_file = {
                "name": _safe_artifact_filename(display_name, "template.txt"),
                "data": data,
                "mime_type": mime_type or "text/plain",
            }

    return project_zip, template_file


def _find_inline_uploads(tool_context: ToolContext) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    current_parts = list((tool_context.user_content.parts if tool_context.user_content and tool_context.user_content.parts else []))
    project_zip, template_file = _extract_inline_uploads_from_parts(current_parts)
    if project_zip and template_file:
        return project_zip, template_file

    session_events = list(getattr(tool_context.session, "events", []) or [])
    for event in reversed(session_events):
        content = getattr(event, "content", None)
        parts = list((content.parts if content and content.parts else []))
        if not parts:
            continue
        found_zip, found_template = _extract_inline_uploads_from_parts(parts)
        if project_zip is None and found_zip is not None:
            project_zip = found_zip
        if template_file is None and found_template is not None:
            template_file = found_template
        if project_zip and template_file:
            return project_zip, template_file

    return project_zip, template_file


def _find_recent_inline_uploads_from_local_session_db(
    tool_context: ToolContext,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    db_path = Path(__file__).resolve().parent / ".adk" / "session.db"
    if not db_path.exists():
        return None, None

    app_name = getattr(tool_context.session, "app_name", None) or "documentation_adk"
    user_id = getattr(tool_context, "user_id", None) or "user"

    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                """
                select event_data
                from events
                where app_name = ? and user_id = ?
                order by timestamp desc
                limit 100
                """,
                (app_name, user_id),
            ).fetchall()
    except sqlite3.Error:
        return None, None

    project_zip = None
    template_file = None
    for (event_data,) in rows:
        try:
            payload = json.loads(event_data)
        except json.JSONDecodeError:
            continue
        parts = ((payload.get("content") or {}).get("parts") or [])
        found_zip, found_template = _extract_inline_uploads_from_parts(parts)
        if project_zip is None and found_zip is not None:
            project_zip = found_zip
        if template_file is None and found_template is not None:
            template_file = found_template
        if project_zip and template_file:
            return project_zip, template_file

    return project_zip, template_file


async def load_uploaded_inputs(tool_context: ToolContext) -> dict:
    """Loads the uploaded project zip and documentation template from ADK artifacts.

    Returns:
        dict: Status plus extracted `project_context` and `template_text` when both files are available.
    """
    inline_project_zip, inline_template_file = _find_inline_uploads(tool_context)
    if inline_project_zip is None or inline_template_file is None:
        db_project_zip, db_template_file = _find_recent_inline_uploads_from_local_session_db(
            tool_context
        )
        if inline_project_zip is None:
            inline_project_zip = db_project_zip
        if inline_template_file is None:
            inline_template_file = db_template_file

    artifact_names = await tool_context.list_artifacts()
    project_zip = inline_project_zip
    template_file = inline_template_file

    if project_zip is None or template_file is None:
        artifact_project_zip, artifact_template_file = await _pick_artifacts(
            list(artifact_names or []), tool_context
        )
        if project_zip is None and artifact_project_zip is not None:
            project_zip = {"name": artifact_project_zip, "source": "artifact"}
        if template_file is None and artifact_template_file is not None:
            template_file = {"name": artifact_template_file, "source": "artifact"}

    if not project_zip or not template_file:
        missing = []
        if not project_zip:
            missing.append("a project .zip file")
        if not template_file:
            missing.append("a documentation template (.md or .txt)")
        return {
            "status": "missing_uploads",
            "message": "Please upload " + " and ".join(missing) + " in the ADK web UI, then ask me to generate the documentation again.",
            "available_artifacts": list(artifact_names or []),
        }

    if project_zip.get("source") == "artifact":
        project_artifact = await tool_context.load_artifact(project_zip["name"])
        if not project_artifact or not project_artifact.inline_data:
            return {
                "status": "error",
                "message": f"I found `{project_zip['name']}` but could not read its binary contents.",
            }
        project_zip_data = project_artifact.inline_data.data
    else:
        project_zip_data = project_zip["data"]

    if template_file.get("source") == "artifact":
        template_artifact = await tool_context.load_artifact(template_file["name"])
        if not template_artifact or not template_artifact.inline_data:
            return {
                "status": "error",
                "message": f"I found `{template_file['name']}` but could not read its contents.",
            }
        template_data = template_artifact.inline_data.data
    else:
        template_data = template_file["data"]

    try:
        template_text = template_data.decode("utf-8", errors="ignore")
    except Exception as exc:  # pragma: no cover
        return {
            "status": "error",
            "message": f"Failed to decode the uploaded template: {exc}",
        }

    with tempfile.TemporaryDirectory(prefix="doc-agent-") as temp_dir:
        temp_root = Path(temp_dir)
        zip_path = temp_root / _safe_artifact_filename(project_zip["name"], "project.zip")
        zip_path.write_bytes(project_zip_data)

        extract_dir = temp_root / "project"
        extract_dir.mkdir(parents=True, exist_ok=True)

        try:
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(extract_dir)
        except zipfile.BadZipFile:
            return {
                "status": "error",
                "message": f"`{project_zip['name']}` is not a valid zip archive.",
            }

        extracted_items = [item for item in extract_dir.iterdir()]
        project_dir = extracted_items[0] if len(extracted_items) == 1 and extracted_items[0].is_dir() else extract_dir
        project_context = build_project_context(project_dir)

    tool_context.state["project_zip_name"] = project_zip["name"]
    tool_context.state["template_file_name"] = template_file["name"]
    tool_context.state["project_context"] = project_context
    tool_context.state["template_text"] = template_text

    return {
        "status": "success",
        "message": "Uploaded files were loaded successfully.",
        "project_zip_name": project_zip["name"],
        "template_file_name": template_file["name"],
        "project_context_preview": project_context[:1500],
    }


async def save_generated_document(
    filename: str,
    content: str,
    tool_context: ToolContext,
) -> dict:
    """Saves the generated documentation as a downloadable Markdown artifact.

    Args:
        filename (str): Output filename for the generated documentation.
        content (str): Final Markdown document body.

    Returns:
        dict: Status plus artifact filename and version.
    """
    safe_name = filename.strip() or "generated-documentation.md"
    safe_name = re.sub(r"\.[A-Za-z0-9]+$", "", safe_name)
    safe_name = f"{safe_name}.md"

    artifact = types.Part.from_bytes(
        data=content.encode("utf-8"),
        mime_type="text/markdown",
    )
    version = await tool_context.save_artifact(filename=safe_name, artifact=artifact)
    tool_context.state["generated_document_name"] = safe_name

    return {
        "status": "success",
        "filename": safe_name,
        "version": version,
        "message": f"Saved the generated documentation as `{safe_name}`.",
    }


async def _build_documentation_preview(
    tool_context: ToolContext,
    revision_instructions: str = "",
) -> dict:
    """Runs the documentation workflow and returns a preview without saving it."""
    from google.adk.tools.agent_tool import AgentTool

    from documentation_adk.sub_agents import analysis_agent

    load_result = await load_uploaded_inputs(tool_context)
    if load_result.get("status") != "success":
        return load_result

    project_context = tool_context.state["project_context"]
    template_text = tool_context.state["template_text"]
    project_zip_name = tool_context.state["project_zip_name"]
    resolved_revision_instructions = _resolve_revision_instructions(
        tool_context=tool_context,
        revision_instructions=revision_instructions,
    )

    existing_preview = tool_context.state.get(PENDING_DOCUMENT_CONTENT_KEY, "").strip()

    if resolved_revision_instructions and existing_preview:
        analysis_result = tool_context.state.get(PENDING_ANALYSIS_RESULT_KEY, "").strip()
        if not analysis_result:
            analysis_result = (
                "## Documentation Draft\n"
                "Use the current preview as the primary source document for revision."
            )

        template_request = (
            "Revise the current documentation preview.\n\n"
            "You must apply the user's requested changes. Do not simply repeat the "
            "existing preview. Update the document so the requested differences are "
            "visible in the returned Markdown while preserving the template structure.\n\n"
            f"Uploaded template:\n{template_text}\n\n"
            f"Current documentation preview:\n{existing_preview}\n\n"
            f"Supporting documentation draft:\n{analysis_result}\n\n"
            f"User revision instructions:\n{resolved_revision_instructions}"
        )
        final_document = await _run_template_agent(
            template_request=template_request,
            tool_context=tool_context,
        )
        if (
            final_document
            and _normalize_for_comparison(final_document) == _normalize_for_comparison(existing_preview)
        ):
            retry_request = (
                f"{template_request}\n\n"
                "IMPORTANT: Your previous attempt repeated the same preview. "
                "This time, return a revised document that clearly reflects the "
                "requested edits. If the user asked to remove a section, the "
                "section must not appear in the output."
            )
            final_document = await _run_template_agent(
                template_request=retry_request,
                tool_context=tool_context,
            )
        if (
            final_document
            and _normalize_for_comparison(final_document) == _normalize_for_comparison(existing_preview)
        ):
            fallback_document, changed = _remove_requested_markdown_sections(
                markdown=existing_preview,
                revision_instructions=resolved_revision_instructions,
            )
            if changed:
                final_document = fallback_document
    else:
        analysis_request = (
            "Draft software documentation for the uploaded project.\n\n"
            f"Project zip name:\n{project_zip_name}\n\n"
            f"Project context:\n{project_context}\n\n"
            f"Uploaded template:\n{template_text}"
        )
        analysis_result = await AgentTool(agent=analysis_agent).run_async(
            args={"request": analysis_request},
            tool_context=tool_context,
        )

        if not isinstance(analysis_result, str) or not analysis_result.strip():
            return {
                "status": "error",
                "message": "The analysis agent did not return any documentation draft.",
            }

        template_request = (
            "Fit the following documentation draft into the uploaded template.\n\n"
            f"Uploaded template:\n{template_text}\n\n"
            f"Documentation draft:\n{analysis_result}"
        )
        final_document = await _run_template_agent(
            template_request=template_request,
            tool_context=tool_context,
        )

    if not isinstance(final_document, str) or not final_document.strip():
        return {
            "status": "error",
            "message": "The template-fitting agent did not return a final document.",
        }

    fallback_name = project_zip_name.removesuffix(".zip") + "-documentation.md"
    suggested_filename = _extract_suggested_filename(analysis_result, fallback_name)
    return {
        "status": "preview_ready",
        "filename": suggested_filename,
        "preview_markdown": final_document.strip(),
        "analysis_result": analysis_result,
        "revision_instructions_applied": resolved_revision_instructions,
        "message": "Draft preview generated successfully.",
    }


async def prepare_documentation_preview(
    tool_context: ToolContext,
    revision_instructions: str = "",
) -> dict:
    """Generates a documentation draft preview and stores it for confirmation."""
    preview_result = await _build_documentation_preview(
        tool_context=tool_context,
        revision_instructions=revision_instructions,
    )
    if preview_result.get("status") != "preview_ready":
        return preview_result

    tool_context.state[PENDING_DOCUMENT_CONTENT_KEY] = preview_result["preview_markdown"]
    tool_context.state[PENDING_DOCUMENT_FILENAME_KEY] = preview_result["filename"]
    tool_context.state[PENDING_ANALYSIS_RESULT_KEY] = preview_result["analysis_result"]

    return {
        "status": "preview_ready",
        "filename": preview_result["filename"],
        "preview_markdown": preview_result["preview_markdown"],
        "revision_instructions_applied": preview_result["revision_instructions_applied"],
        "message": (
            f"Draft preview is ready for review as `{preview_result['filename']}`."
        ),
        "next_step_message": (
            "Review the draft below and reply with any changes you want. "
            "When it looks right, reply with an explicit confirmation such as "
            "`confirm` or `save` and I will generate the final file."
        ),
    }


async def finalize_documentation(
    tool_context: ToolContext,
    filename: str = "",
) -> dict:
    """Saves the current approved preview as a downloadable Markdown artifact."""
    pending_content = tool_context.state.get(PENDING_DOCUMENT_CONTENT_KEY, "").strip()
    pending_filename = tool_context.state.get(
        PENDING_DOCUMENT_FILENAME_KEY,
        "generated-documentation.md",
    )

    if not pending_content:
        return {
            "status": "missing_preview",
            "message": (
                "There is no pending draft to save yet. Generate a documentation "
                "preview first, review it, and then confirm when you're ready."
            ),
        }

    save_result = await save_generated_document(
        filename=filename.strip() or pending_filename,
        content=pending_content,
        tool_context=tool_context,
    )
    _clear_pending_document_state(tool_context)

    return {
        "status": "success",
        "filename": save_result["filename"],
        "version": save_result["version"],
        "message": (
            f"Documentation approved and saved as `{save_result['filename']}`. "
            "It is available in the ADK Web artifacts/download area."
        ),
    }


async def generate_documentation_from_uploads(tool_context: ToolContext) -> dict:
    """Backwards-compatible helper that still supports one-shot generation."""
    preview_result = await prepare_documentation_preview(tool_context=tool_context)
    if preview_result.get("status") != "preview_ready":
        return preview_result

    return await finalize_documentation(
        tool_context=tool_context,
        filename=preview_result["filename"],
    )
