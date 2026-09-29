-- Old timestamps are interpreted using LEGACY_TIMEZONE, set by migrate.py.
ALTER TABLE users ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE role_permissions ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE categories ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE branches ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE products ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE products ADD COLUMN active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1));
ALTER TABLE products ALTER COLUMN current_stock TYPE NUMERIC(14,3) USING current_stock::numeric;
ALTER TABLE products ALTER COLUMN min_stock TYPE NUMERIC(14,3) USING min_stock::numeric;
ALTER TABLE products ALTER COLUMN purchase_price TYPE NUMERIC(14,2) USING round(purchase_price::numeric,2);
ALTER TABLE products ALTER COLUMN sale_price TYPE NUMERIC(14,2) USING round(sale_price::numeric,2);
ALTER TABLE products ALTER COLUMN current_stock SET NOT NULL;
ALTER TABLE products ALTER COLUMN min_stock SET NOT NULL;
ALTER TABLE products ALTER COLUMN purchase_price SET NOT NULL;
ALTER TABLE products ALTER COLUMN sale_price SET NOT NULL;
ALTER TABLE products ADD CONSTRAINT products_valid_balances CHECK(current_stock>=0 AND min_stock>=0 AND purchase_price>=0 AND sale_price>=0 AND current_stock<100000000000 AND min_stock<100000000000 AND purchase_price<100000000000 AND sale_price<100000000000);
ALTER TABLE products ADD CONSTRAINT products_unit CHECK(unit IN ('un','m','par','cx','kg'));
ALTER TABLE products ADD CONSTRAINT products_whole_units CHECK(unit IN ('m','kg') OR (current_stock=trunc(current_stock) AND min_stock=trunc(min_stock)));
ALTER TABLE users ADD CONSTRAINT users_role CHECK(role IN ('ADMIN','MANAGER','OPERATOR'));
ALTER TABLE users ADD CONSTRAINT users_active CHECK(active IN (0,1));
CREATE UNIQUE INDEX users_username_lower_idx ON users(lower(username));
ALTER TABLE movements ALTER COLUMN quantity TYPE NUMERIC(14,3) USING quantity::numeric;
ALTER TABLE movements ALTER COLUMN unit_price TYPE NUMERIC(14,2) USING round(unit_price::numeric,2);
ALTER TABLE movements ALTER COLUMN total_price TYPE NUMERIC(17,2) USING round(total_price::numeric,2);
ALTER TABLE movements ADD COLUMN legacy BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE movements ADD COLUMN legacy_product_id INTEGER;
UPDATE movements SET legacy_product_id=product_id;
ALTER TABLE movements ADD COLUMN reversal_of INTEGER UNIQUE REFERENCES movements(id);
ALTER TABLE movements ADD COLUMN product_code TEXT;
ALTER TABLE movements ADD COLUMN product_name TEXT;
ALTER TABLE movements ADD COLUMN product_unit TEXT;
ALTER TABLE movements ADD COLUMN actor_name TEXT;
ALTER TABLE movements ADD COLUMN branch_name_snapshot TEXT;
ALTER TABLE movements ADD COLUMN stock_after NUMERIC(14,3);
UPDATE movements m SET legacy=true, product_code=COALESCE(p.code, dp.code), product_name=COALESCE(p.name,dp.name), product_unit=p.unit
 FROM (SELECT id FROM movements) ids LEFT JOIN movements ref ON ref.id=ids.id
 LEFT JOIN products p ON ref.product_id=p.id LEFT JOIN deleted_products dp ON ref.product_id=dp.id WHERE m.id=ids.id;
UPDATE movements m SET actor_name=u.name FROM users u WHERE m.user_id=u.id;
UPDATE movements m SET branch_name_snapshot=b.name FROM branches b WHERE m.branch_id=b.id;
-- Missing historical product links are preserved as snapshots, not invented active products.
ALTER TABLE movements DROP CONSTRAINT IF EXISTS movements_product_id_fkey;
ALTER TABLE movements ALTER COLUMN product_id DROP NOT NULL;
UPDATE movements SET product_id=NULL WHERE product_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM products p WHERE p.id=movements.product_id);
ALTER TABLE movements ADD CONSTRAINT movements_product_id_fkey FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT;
ALTER TABLE movements DROP CONSTRAINT IF EXISTS movements_user_id_fkey;
ALTER TABLE movements ADD CONSTRAINT movements_user_id_fkey FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE RESTRICT;
ALTER TABLE movements ADD CONSTRAINT movements_valid CHECK(quantity>0 AND quantity<100000000000 AND unit_price>=0 AND unit_price<100000000000 AND total_price>=0 AND total_price<1000000000000000);
ALTER TABLE movements ADD CONSTRAINT movements_new_links CHECK(legacy OR (product_id IS NOT NULL AND user_id IS NOT NULL AND stock_after IS NOT NULL));
ALTER TABLE movements ADD CONSTRAINT movements_stock_after CHECK(stock_after IS NULL OR stock_after>=0);
ALTER TABLE users ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE current_setting('app.legacy_timezone');
ALTER TABLE products ALTER COLUMN created_at TYPE TIMESTAMPTZ USING created_at AT TIME ZONE current_setting('app.legacy_timezone');
ALTER TABLE movements ALTER COLUMN timestamp TYPE TIMESTAMPTZ USING timestamp AT TIME ZONE current_setting('app.legacy_timezone');
CREATE TABLE product_baselines(product_id INTEGER PRIMARY KEY REFERENCES products(id), quantity NUMERIC(14,3) NOT NULL CHECK(quantity>=0), captured_at TIMESTAMPTZ NOT NULL DEFAULT now());
INSERT INTO product_baselines(product_id,quantity) SELECT id,current_stock FROM products;
CREATE TABLE operation_keys (
 user_id INTEGER NOT NULL REFERENCES users(id), key TEXT NOT NULL, payload_hash TEXT NOT NULL,
 result JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(user_id,key)
);
CREATE TABLE login_limits (key TEXT PRIMARY KEY, attempts INTEGER NOT NULL, window_start TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE audit_events(id BIGSERIAL PRIMARY KEY, actor_id INTEGER REFERENCES users(id), action TEXT NOT NULL, target_id INTEGER, details JSONB NOT NULL DEFAULT '{}', timestamp TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX movements_time_idx ON movements(timestamp DESC,id DESC);
CREATE INDEX movements_product_time_idx ON movements(product_id,timestamp DESC,id DESC);
CREATE INDEX movements_branch_time_idx ON movements(branch_id,timestamp DESC,id DESC);
CREATE INDEX movements_user_idx ON movements(user_id);
CREATE INDEX products_category_idx ON products(category_id);
CREATE FUNCTION prevent_history_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'History is immutable; register a reversal' USING ERRCODE='23514'; END; $$;
CREATE TRIGGER movements_immutable BEFORE UPDATE OR DELETE ON movements FOR EACH ROW EXECUTE FUNCTION prevent_history_mutation();
CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE ON audit_events FOR EACH ROW EXECUTE FUNCTION prevent_history_mutation();
INSERT INTO role_permissions(role,role_name,dashboard,products_view,products_manage,costs_view,categories_manage,movements_in,movements_out,alerts_view,branches_manage,users_manage,reports_export)
VALUES ('ADMIN','Administrador',1,1,1,1,1,1,1,1,1,1,1),('MANAGER','Gerente',1,1,1,1,1,1,1,1,0,0,1),('OPERATOR','Operador',1,1,0,0,0,0,1,1,0,0,0)
ON CONFLICT(role) DO NOTHING;
