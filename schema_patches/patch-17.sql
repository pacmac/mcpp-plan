-- patch-17: class and priority on areas for roadmap ordering
-- class: 'product' (ships) or 'tooling' (builds/proves/reaches the product, never ships)
-- priority: integer, lower = higher priority within class; NULL sorts last
ALTER TABLE areas ADD COLUMN class TEXT CHECK(class IN ('product','tooling'));
ALTER TABLE areas ADD COLUMN priority INTEGER;
