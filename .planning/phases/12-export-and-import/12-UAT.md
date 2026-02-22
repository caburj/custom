---
status: complete
phase: 12-export-and-import
source: 12-01-SUMMARY.md, 12-02-SUMMARY.md
started: 2026-02-22T18:00:00Z
updated: 2026-02-22T18:08:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Export Button Presence & Position
expected: In the sidebar header action bar, an export button (⤓ downwards arrow icon) appears BEFORE the delete button. The import button (⤒ upwards arrow icon) appears between export and delete.
result: pass

### 2. Export Disabled When Nothing Checked
expected: With no traces checked, the export button is visually disabled and not clickable. The import button remains enabled regardless.
result: pass

### 3. Export Downloads JSON File
expected: Check one or more traces, click export. Browser downloads a file named `ai-debug-traces-YYYY-MM-DD.json` (today's date). The file contains a JSON array of trace objects.
result: pass

### 4. Import File Picker Opens
expected: Click the import button. A file picker dialog opens allowing you to select a file.
result: pass

### 5. Import Preview Dialog (Valid File)
expected: Select a previously exported JSON file. A preview dialog appears showing the number of traces to import and how many are duplicates. Dialog has Import and Cancel buttons.
result: pass

### 6. Import Merges Traces Into Sidebar
expected: In the preview dialog, click Import. The dialog closes and the imported traces appear in the sidebar trace list. No success toast — the sidebar updating is the feedback.
result: pass

### 7. Import Invalid File Shows Error
expected: Select a non-JSON file or a malformed JSON file. The dialog shows an error message. Only a Cancel button is available (no Import button).
result: pass

### 8. Import Round-Trip Integrity
expected: Export some traces, delete them, then import the exported file. The re-imported traces appear identical to the originals (same trace IDs, same iteration data).
result: pass

## Summary

total: 8
passed: 8
issues: 0
pending: 0
skipped: 0

## Gaps

[none yet]
