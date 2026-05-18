-- Override bang: force non-null despite nullable FK.
select u.id, u.org_id as org_id!
from users u
left join orgs o on o.id = u.org_id
