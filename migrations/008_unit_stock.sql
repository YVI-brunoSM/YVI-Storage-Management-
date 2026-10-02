CREATE TABLE product_stocks (
 product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
 branch_id INTEGER NOT NULL REFERENCES branches(id) ON DELETE RESTRICT,
 quantity NUMERIC(14,3) NOT NULL DEFAULT 0 CHECK(quantity>=0 AND quantity<100000000000),
 min_stock NUMERIC(14,3) NOT NULL DEFAULT 0 CHECK(min_stock>=0 AND min_stock<100000000000),
 opening_quantity NUMERIC(14,3) NOT NULL DEFAULT 0 CHECK(opening_quantity>=0),
 enabled BOOLEAN NOT NULL DEFAULT true,
 version INTEGER NOT NULL DEFAULT 1,
 PRIMARY KEY(product_id,branch_id)
);
CREATE INDEX product_stocks_branch_idx ON product_stocks(branch_id,product_id);
ALTER TABLE products ADD COLUMN stock_allocation_pending BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE products ADD COLUMN unallocated_stock NUMERIC(14,3) NOT NULL DEFAULT 0 CHECK(unallocated_stock>=0);
-- Old central quantities cannot be inferred from historical destination fields.
-- Keep them intact until an administrator explicitly allocates the opening stock.
UPDATE products SET unallocated_stock=current_stock,stock_allocation_pending=(current_stock>0);
INSERT INTO product_stocks(product_id,branch_id,min_stock)
 SELECT id,branch_id,min_stock FROM products WHERE branch_id IS NOT NULL;
INSERT INTO product_stocks(product_id,branch_id,min_stock)
 SELECT DISTINCT p.id,m.branch_id,p.min_stock FROM products p JOIN movements m ON m.product_id=p.id
 WHERE p.branch_id IS NULL AND m.branch_id IS NOT NULL ON CONFLICT DO NOTHING;
ALTER TABLE movements ADD COLUMN stock_model INTEGER NOT NULL DEFAULT 1 CHECK(stock_model IN (1,2));
ALTER TABLE movements ALTER COLUMN stock_model SET DEFAULT 2;
CREATE TABLE stock_transfers (
 id UUID PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id),
 source_id INTEGER NOT NULL REFERENCES branches(id), destination_id INTEGER NOT NULL REFERENCES branches(id),
 quantity NUMERIC(14,3) NOT NULL CHECK(quantity>0 AND quantity<100000000000),
 user_id INTEGER NOT NULL REFERENCES users(id), notes TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), CHECK(source_id<>destination_id)
);
ALTER TABLE movements ADD COLUMN transfer_id UUID REFERENCES stock_transfers(id);
CREATE TRIGGER transfers_immutable BEFORE UPDATE OR DELETE ON stock_transfers FOR EACH ROW EXECUTE FUNCTION prevent_history_mutation();

CREATE FUNCTION inventory_products(unit_scope INTEGER[]) RETURNS TABLE (
 id INTEGER,code TEXT,name TEXT,category_id INTEGER,unit TEXT,current_stock NUMERIC,min_stock NUMERIC,
 purchase_price NUMERIC,sale_price NUMERIC,location TEXT,created_at TIMESTAMPTZ,version INTEGER,active INTEGER,
 default_min_stock NUMERIC,branch_ids INTEGER[],unit_stocks JSONB,low_unit_count BIGINT,
 stock_allocation_pending BOOLEAN,unallocated_stock NUMERIC
) LANGUAGE sql STABLE AS $$
 SELECT p.id,p.code,p.name,p.category_id,p.unit,coalesce(s.qty,0),coalesce(s.minimum,0),
 p.purchase_price,p.sale_price,coalesce(s.names,''),p.created_at,p.version,p.active,p.min_stock,
 coalesce(s.ids,ARRAY[]::INTEGER[]),coalesce(s.details,'[]'::JSONB),coalesce(s.low_count,0),
 p.stock_allocation_pending,CASE WHEN unit_scope IS NULL THEN p.unallocated_stock ELSE 0 END
 FROM products p LEFT JOIN LATERAL (
   SELECT sum(ps.quantity) qty,sum(ps.min_stock) minimum,array_agg(ps.branch_id ORDER BY b.name) ids,
   string_agg(b.name,', ' ORDER BY b.name) names,count(*) FILTER(WHERE ps.quantity<=ps.min_stock) low_count,
   jsonb_agg(jsonb_build_object('branch_id',ps.branch_id,'branch_name',b.name,'quantity',ps.quantity,
     'min_stock',ps.min_stock,'version',ps.version) ORDER BY b.name) details
   FROM product_stocks ps JOIN branches b ON b.id=ps.branch_id
   WHERE ps.product_id=p.id AND ps.enabled AND (unit_scope IS NULL OR ps.branch_id=ANY(unit_scope))
 ) s ON true WHERE unit_scope IS NULL OR cardinality(s.ids)>0;
$$;
