-- 0001_foundation.sql — tenant model + event store (BUILD.md §5.3, extended)
-- Apply via `supabase db push`. Requires a Supabase project (see .env.example).
create extension if not exists pgcrypto;

create table businesses (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    status text not null default 'active',
    created_at timestamptz not null default now()
);

create table branches (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null references businesses(id),
    name text not null,
    address text,
    status text not null default 'active',
    created_at timestamptz not null default now(),
    unique (business_id, id)
);

create table profiles (
    id uuid primary key references auth.users(id),
    display_name text,
    created_at timestamptz not null default now()
);

create table business_memberships (
    business_id uuid not null references businesses(id),
    user_id uuid not null references profiles(id),
    role text not null default 'cashier',
    created_at timestamptz not null default now(),
    primary key (business_id, user_id)
);

create table branch_memberships (
    business_id uuid not null,
    branch_id uuid not null,
    user_id uuid not null references profiles(id),
    primary key (business_id, branch_id, user_id),
    foreign key (business_id, branch_id) references branches (business_id, id)
);

create table devices (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null,
    branch_id uuid not null,
    device_name text not null,
    device_type text not null,
    api_key_hash text,
    active boolean not null default true,
    last_seen_at timestamptz,
    created_at timestamptz not null default now(),
    unique (id, business_id, branch_id),
    foreign key (business_id, branch_id)
        references branches (business_id, id)
);

create table products (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null references businesses(id),
    sku text,
    barcode text,
    name text not null,
    selling_price numeric(14, 2) not null default 0,
    cost_price numeric(14, 2) not null default 0,
    active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (business_id, sku),
    unique (business_id, barcode),
    unique (id, business_id)
);

create table sales (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null,
    branch_id uuid not null,
    device_id uuid not null,
    receipt_number text not null,
    subtotal numeric(14, 2) not null,
    discount_total numeric(14, 2) not null default 0,
    tax_total numeric(14, 2) not null default 0,
    total numeric(14, 2) not null,
    status text not null default 'completed',
    created_at timestamptz not null,
    unique (id, business_id),
    unique (branch_id, receipt_number),
    foreign key (business_id, branch_id)
        references branches (business_id, id),
    foreign key (device_id, business_id, branch_id)
        references devices (id, business_id, branch_id)
);

create table sale_items (
    id uuid primary key default gen_random_uuid(),
    sale_id uuid not null,
    business_id uuid not null,
    product_id uuid not null,
    quantity numeric(14, 3) not null,
    unit_price numeric(14, 2) not null,
    line_total numeric(14, 2) not null,
    foreign key (sale_id, business_id)
        references sales (id, business_id),
    foreign key (product_id, business_id)
        references products (id, business_id)
);

create table payments (
    id uuid primary key default gen_random_uuid(),
    sale_id uuid not null,
    business_id uuid not null,
    method text not null default 'cash',
    amount numeric(14, 2) not null,
    created_at timestamptz not null default now(),
    foreign key (sale_id, business_id) references sales (id, business_id)
);

create table stock_movements (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null,
    branch_id uuid not null,
    product_id uuid not null,
    movement_type text not null,
    quantity_delta numeric(14, 3) not null,
    reference_id uuid,
    device_id uuid,
    note text,
    created_at timestamptz not null,
    foreign key (business_id, branch_id)
        references branches (business_id, id),
    foreign key (product_id, business_id)
        references products (id, business_id)
);

create index stock_movements_branch_product_idx
    on stock_movements (business_id, branch_id, product_id);

-- stock_balances is a rebuildable projection of stock_movements (§6.2)
create table stock_balances (
    business_id uuid not null,
    branch_id uuid not null,
    product_id uuid not null,
    on_hand numeric(14, 3) not null default 0,
    rebuilt_at timestamptz not null default now(),
    primary key (business_id, branch_id, product_id),
    foreign key (business_id, branch_id) references branches (business_id, id),
    foreign key (product_id, business_id) references products (id, business_id)
);

create table stock_transfers (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null references businesses(id),
    from_branch_id uuid not null,
    to_branch_id uuid not null,
    status text not null default 'DRAFT'
        check (status in ('DRAFT','DISPATCHED','IN_TRANSIT','RECEIVED','CANCELLED')),
    note text,
    created_at timestamptz not null default now(),
    dispatched_at timestamptz,
    received_at timestamptz
);

create table stock_transfer_items (
    id uuid primary key default gen_random_uuid(),
    transfer_id uuid not null references stock_transfers(id) on delete cascade,
    product_id uuid not null references products(id),
    qty_sent numeric(14, 3) not null,
    qty_received numeric(14, 3) not null default 0,
    qty_damaged numeric(14, 3) not null default 0
);

-- Event ingestion: dedupe by event_id; per-branch stream counter (§8.2, §8.3)
create table sync_events (
    id bigint generated always as identity,
    event_id uuid not null unique,
    business_id uuid not null,
    branch_id uuid not null,
    device_id uuid not null,
    device_sequence bigint,
    event_type text not null,
    schema_version int not null default 1,
    entity_id uuid,
    device_created_at timestamptz,
    payload jsonb not null default '{}',
    server_received_at timestamptz not null default now(),
    server_sequence bigint,
    status text not null default 'accepted',
    foreign key (business_id, branch_id) references branches (business_id, id)
);

create table sync_stream_counters (
    branch_id uuid primary key references branches(id),
    next_sequence bigint not null default 1
);

create table sync_device_cursors (
    device_id uuid primary key references devices(id),
    last_sequence bigint not null default 0,
    updated_at timestamptz not null default now()
);

create table sync_conflicts (
    id bigint generated always as identity primary key,
    event_id uuid,
    device_id uuid,
    reason text not null,
    detail jsonb,
    resolved boolean not null default false,
    created_at timestamptz not null default now()
);

create table audit_logs (
    id bigint generated always as identity primary key,
    at timestamptz not null default now(),
    actor text,
    action text not null,
    detail text
);

create table subscriptions (
    id uuid primary key default gen_random_uuid(),
    business_id uuid not null references businesses(id),
    plan text not null,
    status text not null default 'trialing',
    seats int,
    created_at timestamptz not null default now(),
    current_period_end timestamptz
);

create index sales_business_created_idx on sales (business_id, created_at);
create index sync_events_branch_seq_idx on sync_events (branch_id, server_sequence);

-- RLS (§4.3, §5.2): every tenant-owned table. Business membership gates access.
alter table branches enable row level security;
alter table business_memberships enable row level security;
alter table branch_memberships enable row level security;
alter table devices enable row level security;
alter table products enable row level security;
alter table sales enable row level security;
alter table sale_items enable row level security;
alter table payments enable row level security;
alter table stock_movements enable row level security;
alter table stock_balances enable row level security;
alter table stock_transfers enable row level security;
alter table sync_events enable row level security;
alter table subscriptions enable row level security;

create or replace function is_member(b uuid) returns boolean language sql stable as
$$ select exists (select 1 from business_memberships
   where business_id = b and user_id = auth.uid()) $$;

create policy tenant_read_branches on branches
    for select using (is_member(business_id));
create policy tenant_read_products on products
    for select using (is_member(business_id));
create policy tenant_read_sales on sales
    for select using (is_member(business_id));
create policy tenant_read_sale_items on sale_items
    for select using (is_member(business_id));
create policy tenant_read_payments on payments
    for select using (is_member(business_id));
create policy tenant_read_movements on stock_movements
    for select using (is_member(business_id));
create policy tenant_read_balances on stock_balances
    for select using (is_member(business_id));
create policy tenant_read_devices on devices
    for select using (is_member(business_id));
create policy tenant_read_memberships on business_memberships
    for select using (user_id = auth.uid());
create policy tenant_read_branch_memberships on branch_memberships
    for select using (user_id = auth.uid());
create policy tenant_read_transfers on stock_transfers
    for select using (is_member(business_id));
create policy tenant_read_events on sync_events
    for select using (is_member(business_id));
create policy tenant_read_subs on subscriptions
    for select using (is_member(business_id));
-- writes go through the cloud API (service role), not client SDKs (§4.3)
