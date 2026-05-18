-- Inner join: both sides non-null.
select u.id, o.name as org_name
from users u
join orgs o on o.id = u.org_id
