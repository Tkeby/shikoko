-- List orders for a user with a specific payment method.
--
select
  o.id,
  o.user_id,
  o.total,
  o.status,
  o.paid_with,
  o.created_at
from orders o
where o.user_id = $1
  and o.paid_with = $2::payment_method
order by o.created_at desc
