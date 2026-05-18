-- Right join: left side should be nullable.
select u.id, o.name as org_name
from users u
right join orgs o on o.id = u.org_id
