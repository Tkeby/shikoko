-- Insert a new user and return the generated row.
--
-- @one
insert into users (email, name, org_id)
values ($1, $2, $3)
returning id, email, name, org_id, created_at
