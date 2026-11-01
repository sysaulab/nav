"""app.handlers — per-format document handlers.

Each handler is a pure function of (path, raw, doc_id, declared, sniffed)
returning a Document. Handlers never raise; failures return a quarantined
Document via quarantine(). router.py is the only caller and selects which
handler to invoke.

Blank pages (zero blocks, quality.status == "pass") are valid output.
Absence of text is a property of the input, not a sanitizer failure.
"""