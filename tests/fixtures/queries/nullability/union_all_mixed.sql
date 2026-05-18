-- UNION ALL with mixed nullability: one branch has NOT NULL, the other nullable.
-- Append node has no root Output → all columns default to nullable.
select id, email as name from users
union all
select id, name from users
