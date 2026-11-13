# Definition of Done

A task is complete only when **all** applicable boxes are ticked:

- [ ] Problem + expected behaviour documented in the audit/backlog with severity
- [ ] Root cause fixed (not symptom-suppressed)
- [ ] A regression test exists that **fails on the old code** and passes on the new
- [ ] Full suite green: `uv run --with pytest --with flask --with "qrcode[pil]" python -m pytest tests/ -q`
- [ ] Edge cases exercised (empty/invalid input, duplicates, expired auth, concurrent ops where relevant)
- [ ] Cross-platform consumers checked (mobile engine, web till, cloud projector)
- [ ] Security implications reviewed (authz, secrets, injection, RLS)
- [ ] Audit table + docs updated
- [ ] Independent verification pass re-ran the reproduction and reviewed the diff

**Extra gates**

- UI changes → inspected rendered output (screenshot), not just code
- Sync changes → verified persisted DB state, not just API 200s
- Financial changes → totals checked against independently computed expected values
- Schema changes → migration tested against a clean `init_db()` **and** the existing `pos.db`
