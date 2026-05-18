-- Override bang + left join: created_at! is forced non-null, org_name is nullable.
select u.created_at!, o.name as org_name
from users u
left join orgs o on o.id = u.org_id
