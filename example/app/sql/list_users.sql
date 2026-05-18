-- List all users with their org name.
-- Left join ensures users without an org are still included.
select
  u.id,
  u.email,
  u.name,
  o.name as org_name
from users u
left join orgs o on o.id = u.org_id
order by u.id
