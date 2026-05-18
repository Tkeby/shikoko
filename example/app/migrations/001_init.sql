-- Example app schema for shikoko demo.
-- Run this against the demo database before starting the app.

drop table if exists posts cascade;
drop table if exists users cascade;
drop table if exists orgs  cascade;

create table orgs (
    id   serial primary key,
    name text not null
);

create table users (
    id         serial primary key,
    email      text not null unique,
    name       text,
    org_id     int references orgs(id),
    created_at timestamptz not null default now()
);

create table posts (
    id         serial primary key,
    user_id    int not null references users(id),
    title      text not null,
    body       text,
    created_at timestamptz not null default now()
);

-- Seed data.
insert into orgs (name) values
    ('Acme Corp'),
    ('Globex Inc');

insert into users (email, name, org_id) values
    ('alice@example.com', 'Alice', 1),
    ('bob@example.com', 'Bob', null),
    ('carol@example.com', 'Carol', 2);

insert into posts (user_id, title, body) values
    (1, 'Hello World', 'My first post!'),
    (1, 'Second post', 'More content here.'),
    (3, 'Globex News', 'Welcome to Globex.');
