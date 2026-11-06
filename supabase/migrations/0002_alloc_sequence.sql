-- 0002_alloc_sequence.sql — atomic per-branch stream counter (BUILD.md §8.3).
-- A single UPDATE inside a function takes the row lock, allocates the next
-- value, and commits with the event write — the safe commit-order cursor.
create or replace function alloc_sequence(p_branch uuid)
returns bigint
language plpgsql
as $$
declare
    n bigint;
begin
    insert into sync_stream_counters (branch_id, next_sequence)
    values (p_branch, 2)
    on conflict (branch_id) do nothing;

    update sync_stream_counters
    set next_sequence = next_sequence + 1
    where branch_id = p_branch
    returning next_sequence - 1 into n;

    return n;
end;
$$;
