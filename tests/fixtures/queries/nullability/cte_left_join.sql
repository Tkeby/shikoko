-- CTE with left join: nullability should propagate through the CTE.
with x as (
    select u.id, o.name as org_name
    from users u
    left join orgs o on o.id = u.org_id
)
select id, org_name from x
