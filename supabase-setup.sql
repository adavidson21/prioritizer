-- Prioritizer cloud sync: run once in the Supabase SQL Editor.
-- One row per account holds that person's whole board as JSON.
-- Row level security means each signed-in user can only see and change their own row.

create table public.boards (
  user_id uuid primary key references auth.users(id) on delete cascade,
  data jsonb not null,
  rev bigint not null default 1,
  updated_at timestamptz not null default now()
);

alter table public.boards enable row level security;

create policy "read own board" on public.boards for select using (auth.uid() = user_id);
create policy "add own board" on public.boards for insert with check (auth.uid() = user_id);
create policy "update own board" on public.boards for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "delete own board" on public.boards for delete using (auth.uid() = user_id);

-- Lets open tabs and phones hear about changes right away.
alter publication supabase_realtime add table public.boards;
