-- The shelf is a shelf of references. Nothing here can hold a book: the widest
-- text column a reader can fill is one corrected sentence they wrote themselves,
-- and the paragraph it replaces is present only as a hash.

create table if not exists account (
    id          bigserial primary key,
    provider    text        not null,
    subject     text        not null,
    handle      text,
    created_at  timestamptz not null default now(),
    seen_at     timestamptz not null default now(),
    unique (provider, subject)
);

create table if not exists session (
    token       text        primary key,
    account_id  bigint      not null references account(id) on delete cascade,
    created_at  timestamptz not null default now(),
    expires_at  timestamptz not null
);

create index if not exists session_account on session (account_id);
create index if not exists session_expiry  on session (expires_at);

create table if not exists shelf_entry (
    account_id  bigint      not null references account(id) on delete cascade,
    book_id     text        not null,
    title       text,
    author      text,
    lang        text,
    -- {"h": "<paragraph hash>", "frac": 0.42} — a content anchor, because the
    -- book re-paginates to every screen and a spread index means nothing across
    -- devices.
    position    jsonb,
    updated_at  timestamptz not null default now(),
    primary key (account_id, book_id)
);

create table if not exists edit (
    account_id  bigint      not null,
    book_id     text        not null,
    para_hash   text        not null,
    base_hash   text        not null,
    text        text        not null,
    updated_at  timestamptz not null,
    primary key (account_id, book_id, para_hash),
    foreign key (account_id, book_id)
        references shelf_entry (account_id, book_id) on delete cascade
);
