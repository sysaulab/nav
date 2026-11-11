/**
 * English source strings. Mirrors navigator/ui_strings.py.
 *
 * Used as:
 *   - the full dictionary when locale === 'en' (no API call)
 *   - the fallback for any key missing from a translation payload,
 *     or every key if the /api/ui/strings fetch fails
 *
 * If a string changes in ui_strings.py, update it here too. Stale
 * English is caught by eyeball (the backend also invalidates
 * translations on a text change, so the picker will show the new
 * English immediately after a redeploy).
 */
export const ENGLISH_STRINGS: Record<string, string> = {
  // ── Welcome page ─────────────────────────────────────
  'welcome.title': 'Welcome',
  'welcome.subtitle': 'Talk through your situation, upload documents, and get a personalized plan.',
  'welcome.where_are_you': 'Where are you located?',
  'welcome.location_hint': "We use this to find services near you. Not all addresses are in the map — if you can't find yours, pick one close by (e.g. the odd house across the street). Precise location is not required.",
  'welcome.address_placeholder': 'e.g. M5V 2T6 or 123 Queen St W',
  'welcome.start': 'Start Session',
  'welcome.privacy_note': 'Sessions time out after 15 minutes of inactivity during chat or upload. Everything is wiped when the session ends.',
  'welcome.choose_language': 'Choose your language',
  'welcome.change_language': '← Change language',

  // ── Location gate ────────────────────────────────────
  'location.title': 'Where are you located?',
  'location.subtitle': 'Start typing a postal code or address — pick a suggestion to continue.',
  'location.continue': 'Continue',
  'location.looking_up': 'Looking up…',
  'location.back': '← Back',
  'location.cancel': '← Cancel',

  // ── Interview header ─────────────────────────────────
  'interview.starting_session': 'Starting a session…',
  'interview.change_location': '← Change location',
  'interview.location_label': 'Location:',
  'interview.end_session': 'End session',
  'interview.finish': 'Finish',
  'interview.finishing': 'Finishing…',

  // ── Chat ─────────────────────────────────────────────
  'chat.empty_prompt': "Ask about the customer's situation, or upload a document on the right.",
  'chat.assistant_responding': 'Assistant is responding…',
  'chat.type_message': 'Type a message…',
  'chat.send': 'Send',

  // ── Action plan ──────────────────────────────────────
  'plan.title': 'Action plan',
  'plan.generating': 'Generating…',
  'plan.copy': 'Copy',
  'plan.copied': 'Copied!',
  'plan.download_markdown': '📄 Markdown',
  'plan.download_office': '📄 Office',
  'plan.download_office_working': '📄 Preparing…',
  'plan.regenerate': 'Regenerate',
  'plan.back_to_chat': 'Back to chat',
  'plan.no_content': 'No content generated.',

  // ── Documents panel ──────────────────────────────────
  'documents.title': 'Documents',
  'documents.dropzone': 'Drop files here, or click to browse.',
  'documents.empty': 'No documents yet.',
  'documents.remove': 'remove',
  'documents.uploading': 'Uploading · {pct}%',
  'documents.processing': 'Uploaded — processing…',
  'documents.status_processing': 'processing',
  'documents.status_uploading': 'uploading',
  'documents.status_ready': 'ready · {k}k tok',
  'documents.status_ready_skipped': 'ready · skipped (budget)',
  'documents.status_skipped_too_large': 'skipped — too large',

  // ── Context budget ───────────────────────────────────
  'context.title': 'Context budget',
  'context.tokens_composed': '{used} / {total} tokens',
  'context.docs_included': '{n} document{s} included',
  'context.docs_skipped_suffix': '{n} skipped',
  'context.reserved_for_reply': '{n} reserved for reply',

  // ── Session expired ──────────────────────────────────
  'session.expired_title': 'Session expired',
  'session.expired_body': 'This session ended after 15 minutes of inactivity. Uploaded documents and the chat transcript have been discarded.',
  'session.expired_return': 'Return to Welcome',

  // ── Session clock ────────────────────────────────────
  'clock.session': 'session',
  'clock.session_ending': 'session ending',
  'clock.minutes_left': '{n}m',
  'clock.less_than_minute': '<1m',

  // ── Service card ─────────────────────────────────────
  'card.global': 'Global',
  'card.distance_km': '{d}km',
  'card.expand': 'Expand details',
  'card.collapse': 'Collapse details',
  'card.eligibility': 'Eligibility:',
  'card.application': 'How to apply:',
  'card.fees': 'Fees:',
  'card.email': 'Email:',
  'card.url': 'URL:',

  // ── Confirmations ────────────────────────────────────
  'confirm.end_session': 'End this session? Documents and chat history will be discarded.',

  // ── Categories (from interviews._category_of) ────────
  'category.SHELTER': 'SHELTER',
  'category.FOOD': 'FOOD',
  'category.HEALTH': 'HEALTH',
  'category.LEGAL': 'LEGAL',
  'category.EMPLOYMENT': 'EMPLOYMENT',
  'category.EDUCATION': 'EDUCATION',
  'category.COUNSEL': 'COUNSEL',
  'category.FINANCE': 'FINANCE',
  'category.CHILD': 'CHILD',
  'category.TRANSPORT': 'TRANSPORT',
  'category.OTHER': 'OTHER',
}