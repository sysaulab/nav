"""System prompt assembly for the interview flow.

Each document is rendered as a compact, human-readable fragment (not raw
JSON) — ~2–3× cheaper than JSON and easier for the LLM to cite. Block IDs
(``p1_b2``) are preserved as citation handles.
"""
from __future__ import annotations

import json


BASE_SYSTEM_PROMPT = (
    "You are a caseworker assistant for a local resource navigator. "
    "Help the user understand their situation and connect them with "
    "appropriate local services. The user may have uploaded documents; "
    "their extracted contents appear below under '## Attached documents'. "
    "Each content block carries an ID like `p1_b2` — cite these when "
    "referencing specifics. A block tagged `minconf=<0.65` means OCR may "
    "be unreliable; hedge accordingly. If a document was quarantined or "
    "excluded for size, tell the user explicitly. You have no tools: "
    "everything you know about the documents is in this prompt."
)


def render_document(doc: dict) -> str:
    lines = [f"### {doc['filename']} — {doc['page_count']} page(s), quality={doc['quality']}"]
    for page in doc["pages"]:
        lines.append(f"\nPage {page['page_number']}:")
        for b in page["blocks"]:
            tag = b["type"]
            if b.get("min_confidence") is not None:
                tag += f", minconf={b['min_confidence']:.2f}"
            bid = b.get("block_id") or "?"
            lines.append(f"  {bid} [{tag}]: {b['text']}")
            if b.get("table_data"):
                lines.append(
                    f"    table: {json.dumps(b['table_data'], separators=(',', ':'))}"
                )
    return "\n".join(lines)


def assemble_prompt(base: str, rendered_docs: list[str]) -> str:
    if not rendered_docs:
        return base
    return base + "\n\n## Attached documents\n\n" + "\n\n".join(rendered_docs)