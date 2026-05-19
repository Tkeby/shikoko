-- List orders filtered by status.
--
select
  o.id,
  o.user_id,
  o.total,
  o.status,
  o.paid_with,
  o.created_at
from orders o
where o.status = $1::order_status
order by o.created_at desc
