-- 0004_adjust_stock_balance.sql — atomic stock_balances += delta.
-- Read-modify-write through PostgREST loses updates under concurrent sales;
-- a single upsert inside one statement is the atomic form (§6.2).
create or replace function adjust_stock_balance(
    p_business uuid, p_branch uuid, p_product uuid, p_delta numeric
)
returns void
language sql
as $$
    insert into stock_balances (business_id, branch_id, product_id, on_hand, rebuilt_at)
    values (p_business, p_branch, p_product, p_delta, now())
    on conflict (business_id, branch_id, product_id)
    do update set on_hand = stock_balances.on_hand + excluded.on_hand,
                  rebuilt_at = now();
$$;
