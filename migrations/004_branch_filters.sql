-- Destination filters use EXISTS so repeated movements never duplicate catalog rows.
CREATE INDEX movements_branch_product_idx ON movements(branch_id,product_id);
CREATE INDEX movements_branch_user_idx ON movements(branch_id,user_id);
