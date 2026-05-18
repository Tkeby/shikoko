-- Computed expression with ! override: the alias suffix forces non-null.
-- @one
select count(*) as total!
from users
