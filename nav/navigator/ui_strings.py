"""The canonical English text for every user-facing UI string.

This module is the source of truth. On startup, main.py calls
_sync_ui_strings() which upserts missing keys and — if a string's
English text has changed — deletes every existing translation for
that key. The admin panel sees an empty cell and re-runs translation.

Keys follow `<surface>.<purpose>`. Placeholders use `{name}` syntax;
the translator preserves them verbatim (see translator.py prompt).

Categories at the bottom mirror interviews._category_of() and are
translated for display, not as identifiers — the backend continues
to send SHELTER/FOOD/... in the card payload.
"""

ENGLISH_STRINGS: dict[str, str] = {
    # ── Welcome page ─────────────────────────────────────
    "welcome.title": "Welcome",
    "welcome.subtitle": "Talk through your situation, upload documents, and get a personalized plan.",
    "welcome.where_are_you": "Where are you located?",
    "welcome.location_hint": "We use this to find services near you. Not all addresses are in the map — if you can't find yours, pick one close by (e.g. the odd house across the street). Precise location is not required.",
    "welcome.address_placeholder": "e.g. M5V 2T6 or 123 Queen St W",
    "welcome.start": "Start Session",
    "welcome.privacy_note": "Sessions time out after 15 minutes of inactivity during chat or upload. Everything is wiped when the session ends.",
    "welcome.choose_language": "Choose your language",
    "welcome.change_language": "← Change language",

    # ── Location gate ────────────────────────────────────
    "location.title": "Where are you located?",
    "location.subtitle": "Start typing a postal code or address — pick a suggestion to continue.",
    "location.continue": "Continue",
    "location.looking_up": "Looking up…",
    "location.back": "← Back",
    "location.cancel": "← Cancel",

    # ── Interview header ─────────────────────────────────
    "interview.starting_session": "Starting a session…",
    "interview.change_location": "← Change location",
    "interview.location_label": "Location:",
    "interview.end_session": "End session",
    "interview.finish": "Finish",
    "interview.finishing": "Finishing…",

    # ── Chat ─────────────────────────────────────────────
    "chat.empty_prompt": "Ask about the customer's situation, or upload a document on the right.",
    "chat.assistant_responding": "Assistant is responding…",
    "chat.type_message": "Type a message…",
    "chat.send": "Send",

    # ── Action plan ──────────────────────────────────────
    "plan.title": "Action plan",
    "plan.generating": "Generating…",
    "plan.copy": "Copy",
    "plan.copied": "Copied!",
    "plan.download_markdown": "📄 Markdown",
    "plan.download_office": "📄 Office",
    "plan.download_office_working": "📄 Preparing…",
    "plan.regenerate": "Regenerate",
    "plan.back_to_chat": "Back to chat",
    "plan.no_content": "No content generated.",

    # ── Documents panel ──────────────────────────────────
    "documents.title": "Documents",
    "documents.dropzone": "Drop files here, or click to browse.",
    "documents.empty": "No documents yet.",
    "documents.remove": "remove",
    "documents.uploading": "Uploading · {pct}%",
    "documents.processing": "Uploaded — processing…",
    "documents.status_processing": "processing",
    "documents.status_uploading": "uploading",
    "documents.status_ready": "ready · {k}k tok",
    "documents.status_ready_skipped": "ready · skipped (budget)",
    "documents.status_skipped_too_large": "skipped — too large",
    "documents.status_quarantine": "quarantine",
    "documents.status_failed": "failed",
    "documents.error_unsupported_type": "Unsupported file type. Accepted: PDF, Office (OOXML), images, plain text.",
    "documents.error_skipped_count": "{n} file(s) skipped — unsupported type",
    "documents.error_legacy_office": "{filename}: {ext} (Office 97-2003) is not supported — re-save as {replacement} and re-upload.",

    # ── Context budget ───────────────────────────────────
    "context.title": "Context budget",
    "context.tokens_composed": "{used} / {total} tokens",
    "context.docs_included": "{n} document{s} included",
    "context.docs_skipped_suffix": "{n} skipped",
    "context.reserved_for_reply": "{n} reserved for reply",

    # ── Session expired ──────────────────────────────────
    "session.expired_title": "Session expired",
    "session.expired_body": "This session ended after 15 minutes of inactivity. Uploaded documents and the chat transcript have been discarded.",
    "session.expired_return": "Return to Welcome",

    # ── Session clock ────────────────────────────────────
    "clock.session": "session",
    "clock.session_ending": "session ending",
    "clock.minutes_left": "{n}m",
    "clock.less_than_minute": "<1m",

    # ── Service card ─────────────────────────────────────
    "card.global": "Global",
    "card.distance_km": "{d}km",
    "card.expand": "Expand details",
    "card.collapse": "Collapse details",
    "card.eligibility": "Eligibility:",
    "card.application": "How to apply:",
    "card.fees": "Fees:",
    "card.email": "Email:",
    "card.url": "URL:",

    # ── Confirmations ────────────────────────────────────
    "confirm.end_session": "End this session? Documents and chat history will be discarded.",
    "confirm.end_session_yes": "End session",
    "confirm.cancel": "Cancel",

    # ── Categories (from interviews._category_of) ────────
    "category.SHELTER": "SHELTER",
    "category.FOOD": "FOOD",
    "category.HEALTH": "HEALTH",
    "category.LEGAL": "LEGAL",
    "category.EMPLOYMENT": "EMPLOYMENT",
    "category.EDUCATION": "EDUCATION",
    "category.COUNSEL": "COUNSEL",
    "category.FINANCE": "FINANCE",
    "category.CHILD": "CHILD",
    "category.TRANSPORT": "TRANSPORT",
    "category.OTHER": "OTHER",
}


# Optional context hints — the translator uses these to pick register.
# Only populated for strings where the meaning is genuinely ambiguous.
#
# INVARIANT: every value must fit in VARCHAR(50) — the UiString.context
# column limit. A longer value fails at startup, since _sync_ui_strings()
# runs inside the FastAPI lifespan handler before the app serves traffic.
# create_all() does not ALTER existing tables, so raising the model column
# to VARCHAR(255) would require an explicit ALTER TABLE against the live
# schema. Keep the hints terse. (Current longest: 49 chars.)
CONTEXTS: dict[str, str] = {
    "welcome.title":           "page heading",
    "welcome.start":           "button label, primary action",
    "welcome.choose_language": "page heading on the kiosk language picker",
    "welcome.change_language": "small inline link, returns to the language picker",
    "location.continue":       "button label",
    "interview.finish":        "button label, ends session with a plan",
    "interview.end_session":   "button label, abandons session",
    "chat.send":               "button label",
    "chat.type_message":       "form input placeholder",
    "plan.copy":               "button label",
    "plan.copied":             "confirmation after action, keep exclamation",
    "plan.regenerate":         "button label, produces a fresh plan",
    "confirm.end_session":     "modal body, destructive action, warning tone",
    "confirm.end_session_yes": "destructive confirmation button, names the action",
    "confirm.cancel":          "button label, dismisses the modal",
    "documents.remove":        "small inline link, verb",
    "session.expired_title":   "page heading, status not imperative",
    "clock.session":           "label on a status badge",
    "clock.session_ending":    "label on a status badge, urgent tone",
    "card.eligibility":        "field label before a value",
    "card.application":        "field label before a value",
}