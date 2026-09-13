-- Areas gain `type`: HOW the area can be PROVEN.
-- `class` (product|tooling) answers who gets it and cannot answer this; across
-- every project 87% of classed rows were 'product', so it could not discriminate.
-- Nullable, no default: a guessed backfill would assert a proof nobody chose.
ALTER TABLE areas ADD COLUMN type TEXT CHECK(type IN
  ('firmware','service','library','contract','tool','gate','doc'));
