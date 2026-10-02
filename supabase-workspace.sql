create table if not exists public.predash_workspace (
  id text primary key,
  payload jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

alter table public.predash_workspace enable row level security;

revoke all on table public.predash_workspace from anon, authenticated;

insert into public.predash_workspace (id, payload)
values ('personal', '{"version":1,"watch_codes":[],"watch_names":{},"industry_notes":{}}'::jsonb)
on conflict (id) do nothing;
