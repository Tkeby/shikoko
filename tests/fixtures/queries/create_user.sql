-- Insert a new user.
-- @exec
insert into users (email, name)
values ($1, $2)
