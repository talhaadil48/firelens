# Source-table column maps

Map exact source headers and explicit unit conversions. Every nonblank source row
and every original cell is retained, including partial records, ranges, lists,
qualitative values and source notes. Never invent independent tests from groups.

Use record_kind to distinguish individual_test, grouped_summary, session,
reference and source_note. skip_rows retains those entries as source_note rather
than deleting them. Numeric fields stay null where no exact scalar is available;
the source_cells values remain unchanged. Hashes and physical source rows travel
with each record. The system has no review-status flags or approval workflow.
