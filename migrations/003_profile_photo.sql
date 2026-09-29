ALTER TABLE users ADD COLUMN avatar bytea;
ALTER TABLE users ADD COLUMN avatar_revision integer NOT NULL DEFAULT 0;
ALTER TABLE users ADD CONSTRAINT avatar_size CHECK (octet_length(avatar) <= 262144);
