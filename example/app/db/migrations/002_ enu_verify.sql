--migrate:up
-- Verify that shikoko generates StrEnum classes for Postgres enum types.

create type order_status as enum (
    'pending',
    'confirmed',
    'shipped',
    'delivered',
    'cancelled'
);

create type payment_method as enum (
    'credit_card',
    'bank_transfer',
    'crypto'
);

create table orders (
    id            serial primary key,
    user_id       int not null references users(id),
    total         numeric(10, 2) not null,
    status        order_status not null default 'pending',
    paid_with     payment_method,
    created_at    timestamptz not null default now()
);

-- Seed data.
insert into orders (user_id, total, status, paid_with) values
    (1,  29.99,  'confirmed', 'credit_card'),
    (1,   9.99,  'delivered', 'credit_card'),
    (2, 149.00,  'pending',   null),
    (3,  59.50,  'shipped',   'bank_transfer'),
    (3,  12.00,  'cancelled', 'crypto');

--migrate:down
drop table if exists orders cascade;
drop type if exists payment_method;
drop type if exists order_status;
