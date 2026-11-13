-- Members can read their own business row (mobile/web show the business name).
-- businesses.id is the tenant key; is_member() resolves membership for auth.uid().
create policy tenant_read_businesses on businesses
    for select using (is_member(id));
