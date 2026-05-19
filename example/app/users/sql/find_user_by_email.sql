-- Find a single user by email address.
-- Returns None if the user does not exist.
--
-- @one
select
  u.id,
  u.email,
  u.name,
  u.created_at!,
  o.name as org_name
from users u
left join orgs o on o.id = u.org_id
where u.email = $1
