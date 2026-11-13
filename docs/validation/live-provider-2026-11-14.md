# Live configured-provider check

Date: 14 November 2026, Asia/Kolkata. App revision: `c1a5188`. This check followed the user's request to test the running interface with the configured LLM API.

This is the initial result. The owner subsequently updated the key. The [live retest](live-provider-retest-2026-11-14.md) records a successful connection and two newly observed workflow failures.

**Result: the live connection failed with an authentication/access error. A complete live resume journey was not run.**

| Item | Observation |
| --- | --- |
| Interface | Actual running app, opened in a browser |
| Action | Settings → Re-test |
| App request | `POST /api/settings/test-connection` |
| Provider | Command Code |
| Selected model | `deepseek/deepseek-v4.1-flash` |
| Saved credential | Present; value was not printed or copied into the report |
| Model prompt | `Reply with the single word: OK` |
| Latency | 909 ms |
| Result | `ok: false`, empty reply |
| Displayed guidance | “The model provider rejected the API key. Reconnect in Settings (\"API key\") or re-enter your key.” |

The browser called the real backend. The backend used the configured provider adapter without an injected model or transport. The local endpoint returned HTTP 200 with `ok: false`; this was an unsuccessful model connection, not a successful inference. The exact upstream HTTP status was not captured. The reported category covers authentication or access rejection. It does not establish whether the key expired or which account permission is missing.

The app ran with isolated state. Existing provider/model settings were loaded read-only. Credentials remained in process memory. Personal resumes, jobs and applications were not loaded or sent. No profile, content or PDF approval was issued. No generated document or submission was created. The temporary server was stopped after recording the result.

The first browser click did not execute because the automatic approval service returned an error. A repeat of that same click executed successfully. The observed provider failure came from that executed request, not the approval-service error.

## Required next step

1. Update the Command Code key in the normal application's Settings.
2. Confirm the account can access the selected model.
3. Save the settings.
4. Repeat the connection test.
5. After it succeeds, run a fictional role/profile through the actual model, questions, content review and PDF workflow.

The previous 935-test matrix used controlled model responses. It validates the application behavior covered by those tests. It does not prove that the owner's current API credentials work or that a live model will return valid evidence for a particular role.

The separate Codex host handoff smoke remains a narrower recorded success. It does not establish this configured-provider connection.

Evidence remains in the ignored execution workspace under `live-provider-2026-11-14/`: `connection-response.json`, `connection-result.png`, isolated state and the server log. A check confirmed that neither the saved test configuration nor the recorded response/log contained configured API-key values. No authentication settings were changed in the normal application.
