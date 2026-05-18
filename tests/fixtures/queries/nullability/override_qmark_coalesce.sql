-- Override qmark on coalesce: coalesce is NOT NULL, but ? forces nullable.
select coalesce(name, 'anon') as name?
from users
