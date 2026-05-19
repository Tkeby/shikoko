-- Delete a user by id.
--
-- @exec
delete from users
where id = $1
