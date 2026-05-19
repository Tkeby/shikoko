-- Change an order's status (e.g. confirm, ship, cancel).
--
-- @one
update orders
set status = $2::order_status
where id = $1
returning id, user_id, total, status, paid_with, created_at
