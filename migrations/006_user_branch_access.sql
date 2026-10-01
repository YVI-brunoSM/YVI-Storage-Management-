ALTER TABLE users ADD COLUMN branch_restricted BOOLEAN NOT NULL DEFAULT false;
CREATE TABLE user_branches (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 branch_id INTEGER NOT NULL REFERENCES branches(id) ON DELETE RESTRICT,
 PRIMARY KEY(user_id,branch_id)
);
CREATE INDEX user_branches_branch_idx ON user_branches(branch_id,user_id);
ALTER TABLE users ADD CONSTRAINT admin_unrestricted CHECK(role<>'ADMIN' OR NOT branch_restricted);
