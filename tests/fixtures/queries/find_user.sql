-- Find a user by email.
-- @one
select id, email, name
from users
where email = $1
