-- Prevent duplicate clause rows per catalog standard (Phase A QA).
-- Safe to run multiple times.

CREATE UNIQUE INDEX IF NOT EXISTS uq_standard_clauses_standard_clause
  ON standard_clauses (standard_id, clause_number);
