-- Stable unit ownership; a product need not have movements to be visible.
ALTER TABLE products ADD COLUMN branch_id INTEGER REFERENCES branches(id) ON DELETE RESTRICT;
CREATE INDEX products_branch_idx ON products(branch_id);
-- Recover only unambiguous existing selections; keep unrelated location text intact.
UPDATE products p SET branch_id=b.id
FROM branches b
WHERE lower(btrim(p.location))=lower(btrim(b.name))
  AND (SELECT count(*) FROM branches other WHERE lower(btrim(other.name))=lower(btrim(p.location)))=1;
