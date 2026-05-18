drop table if exists posts cascade;
drop table if exists users cascade;
drop table if exists orgs  cascade;

create table orgs (
    id   serial primary key,
    name text not null
);

create table users (
    id         serial primary key,
    email      text not null,
    name       text,
    org_id     int references orgs(id),    -- nullable FK
    created_at timestamptz not null default now()
);

create table posts (
    id      serial primary key,
    user_id int not null references users(id),
    title   text not null,
    body    text
);
