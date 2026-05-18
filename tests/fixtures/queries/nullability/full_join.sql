-- Full join: both sides nullable.
select u.id, o.name as org_name
from users u
full join orgs o on o.id = u.org_id
