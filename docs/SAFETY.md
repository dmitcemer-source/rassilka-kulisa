# Safety, permissions and compliance

## Sending gates (two independent locks)

1. **Human approval in the database.** A campaign can only reach status `approved` through
   `kulisa approve --campaign N --by "Human name"`. The approver and timestamp are stored in
   `campaigns` and in the `action_log` audit trail.
2. **Environment switch.** `KULISA_SENDING_ENABLED` must be `true` on the machine that starts
   the campaign. It defaults to `false` everywhere (`.env.example`, `Settings`).

`ListmonkClient.start_campaign` and `campaigns.start` both refuse to proceed unless **both**
conditions hold. There is no bypass path, and every refusal is visible in the CLI output.

## Unsubscribe / suppression guarantees

- `suppression_list` is checked at import, at segmentation, and before any recipient is pushed
  to Listmonk.
- Unsubscribes reported by Listmonk are mirrored into the suppression list by `monitor.sync_unsubscribes`.
- Hard bounces are suppressed automatically (`bounce:hard`) to protect sender reputation.
- Unsubscribe links are injected in the Listmonk template (`{{ UnsubscribeURL }}`).
- Invalid addresses are suppressed at import time and never re-entered.

## Lawful, permission-based use

- Only import lists you are lawfully allowed to use for B2B outreach (legitimate interest /
  consent as applicable in the recipient's jurisdiction, e.g. GDPR/ePrivacy, CAN-SPAM, CASL).
- Every email identifies the sender and includes a working unsubscribe path.
- Complaints are tracked per campaign; addresses that complain are suppressed (`complaint`).
- Keep evidence of list provenance alongside the import files.

## Credentials and secrets

- All secrets live in environment variables (`.env`, git-ignored) — never in code or the DB.
- `.env.example` documents every variable without real values.
- Listmonk API token / basic auth and the Mistral API key are read only by `config.py`.
- The dashboard binds to `127.0.0.1` by default; if you expose it, put it behind authentication.

## Audit trail

Every campaign action — imports, validations, segment changes, draft creation, approvals,
starts, stat syncs, suppressions, replies, reports — is written to `action_log` with actor,
timestamp and JSON details. The daily report includes the recent audit trail.

## Test discipline

- `KULISA_TEST_MODE=true` marks campaigns as test-mode in the database.
- The offline demo (`python -m kulisa.demo`) uses a mock Listmonk and `example.com` test
  recipients only; no packet leaves the machine.
- Do not set `KULISA_SENDING_ENABLED=true` until the owner has approved the campaign content
  and the audience.
