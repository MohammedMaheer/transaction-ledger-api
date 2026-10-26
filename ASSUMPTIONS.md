# Assumptions and scope

1. **Currency and precision.** The ledger represents one currency with two fractional
   digits. No currency conversion or multi-currency accounting is supported. Amounts and
   balances use PostgreSQL `NUMERIC(18,2)` and Python `Decimal`; the maximum is
   `9999999999999999.99`. Credits that would overflow the balance return 400 before any
   write commits. No rounding is performed on input.

2. **Monetary JSON contract.** Clients submit amounts as decimal strings such as `"100"`,
   `"100.0"`, or `"100.00"`. JSON numbers, scientific notation, signs, leading zeros (other
   than `0`), surrounding whitespace, non-finite values, and more than two fractional digits
   are rejected with 422. In particular, `"1.000"` is rejected even though it equals one.
   All monetary responses contain exactly two fractional digits.

3. **Account creation.** Names are trimmed, nonblank strings of at most 200 characters.
   Duplicate names are allowed. Account IDs are server-generated UUIDv4 values. Accounts
   always start at zero. Extra body fields, including balance, ID, and timestamp, are
   rejected rather than silently ignored.

4. **Descriptions and text.** Description is optional and defaults to an empty string;
   it is limited to 2,000 characters and is otherwise preserved. References are trimmed,
   nonblank strings of at most 100 characters. Names, references, and descriptions reject
   null characters, which PostgreSQL text cannot store. All body strings require string
   inputs; numbers and booleans are not coerced into text.

5. **Immutability.** Transactions can only be created and listed through the API. No
   account deletion, transaction editing/deletion, or balance-setting endpoint exists.
   Corrections require a new compensating credit/debit with a new reference. Database
   administrator access is trusted; direct SQL mutations are outside the API contract.

6. **Reference uniqueness and duplicates.** `(account_id, reference_id)` is the uniqueness
   scope across standalone transactions and transfer legs together. References are
   case-sensitive after trimming. Identical references on different accounts are permitted.
   A repeated reference returns 409 even if the payload is identical; the original result
   is not replayed. A duplicate check precedes sufficient-funds checks, so retrying a fully
   spent debit is still reported as a duplicate. Clients must retain a reference across
   network/timeout retries, and use a new reference for an intentionally new operation.

7. **Transfer idempotency.** A transfer stores the exact supplied reference on its source
   debit and destination credit. There is no separate transfer table or globally unique
   transfer reference. Both accounts are locked in ascending UUID order before examining
   either reference. A reference already used on either account rejects the entire
   operation with 409, including a changed amount, changed counterpart, reverse direction,
   or a collision with a standalone entry. The same reference can be used by transfers
   between entirely disjoint account pairs. Thus idempotency is scoped to participating
   accounts, rather than globally across the system.

8. **Failed transfer retries.** Failed operations do not reserve references. A failed
   insufficient-funds transfer can be retried after funding the source, provided neither
   account has since used that reference. Two legs and both balance changes commit or
   roll back together. If a response is lost after a successful commit, retrying the same
   request returns 409 and cannot move the money twice; history shows the original entries.

9. **Pagination.** Default `page=1`, `limit=20`; maximum limit is 100 and maximum page is
   1,000,000. Both must be positive integers. Unknown history query fields are rejected.
   Total records count the filtered result. Empty histories have zero total pages; pages
   beyond the end return an empty data array with the actual totals. Ordering is
   `created_at DESC, id DESC`; UUID order only breaks timestamp ties. Offset pagination
   is deterministic for a fixed ledger, but new entries between separate page requests
   can shift offsets. One response's count and records are consistent with each other.

10. **Timestamps.** PostgreSQL generates timezone-aware timestamps using `now()` (the
    database transaction start time). Application connections use UTC and serialize ISO
    8601 timestamps with a UTC offset or `Z`. Two transfer legs share a transaction timestamp.
    Clients cannot set timestamps.

11. **Concurrency and errors.** PostgreSQL's default READ COMMITTED isolation is used with
    account row locks. All supported writers follow the same lock ordering. Lock/statement
    timeout and deadlock/serialization conflicts return 409 and can be retried by the client
    with the same reference. The service does not automatically retry transactions. Standard
    validation errors (including self-transfers) return 422; insufficient funds and balance
    overflow return 400. Missing accounts return 404, uniqueness conflicts 409, database
    unavailability 503 where identified, and unexpected failures a sanitized 500.

12. **Security and scope.** Authentication, per-account authorization, TLS termination,
    rate limiting, audit export, reversals, exchange rates, and regulatory workflows are
    outside the assessment. The local Compose ports are loopback-only. A shared deployment
    needs its own secrets and access controls. API writes maintain ledger reconciliation;
    database checks guard individual rows and references, with no database triggers for
    cross-table aggregate equality. The assessment application is deliberately one service
    and one relational database.

13. **Health and deployment.** `/health` checks database connectivity and presence of the
    account/transaction tables. It is a readiness check, not a complete migration-version
    audit. Alembic must run before serving requests; Compose enforces that ordering. Schema
    downgrade deletes the ledger and is only appropriate for disposable development data.
