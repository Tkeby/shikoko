-- List all posts by a given user, newest first.
select
  p.id,
  p.title,
  p.body,
  p.created_at
from posts p
where p.user_id = $1
order by p.created_at desc
