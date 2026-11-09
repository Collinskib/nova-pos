-- Web-till checkout fields: who a credit sale belongs to, and an
-- idempotency key so a double-tapped or retried charge can't double-book.
alter table sales add column if not exists customer_name text;
alter table sales add column if not exists client_ref text;

create unique index if not exists sales_branch_client_ref
    on sales (branch_id, client_ref)
    where client_ref is not null;
