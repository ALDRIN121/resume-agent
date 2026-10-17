# Command Code integration verification — 17 October 2026

This records the initial sample test. The subsequent [Aldrin Joseph real-data retest](aldrin-joseph-real-data-2026-10-17.md) is the current result and includes additional fixes for full-profile context, factual numbers, and review date grounding.

The app now supports Command Code in Settings, onboarding, the CLI wizard, provider detection, and connection testing. It uses the documented OpenAI-compatible Chat Completions endpoint at `https://api.commandcode.ai/provider/v1`, with `deepseek/deepseek-v4.1-flash` as its catalog default. The live public models endpoint confirmed this exact ID. Credentials use `COMMAND_CODE_API_KEY`, are excluded from config YAML/API responses, and are saved in the existing private secrets file.

References: [Provider API](https://commandcode.ai/docs/provider), [API keys](https://commandcode.ai/docs/studio#api-keys).

## Live browser verification

- Selected Command Code in Settings, entered the supplied key, saved, and received OK from the connection test (about 2.8 seconds).
- Uploaded `examples/sample_resume.tex`; DeepSeek parsed Jane Doe's resume in about 8 seconds.
- Tested both pasted job text and uploading `examples/sample_jd.txt` (TechCorp's senior platform engineering role).
- The final run asked five relevant questions. Test answers declined unconfirmed Kubernetes/EKS production scope, on-call/SLO ownership, testing/documentation examples, production Go, and additional architecture ownership.
- Reviewed eight suggestions; retained the original summary and approved seven rewrites.
- Left the run, reloaded the browser, reopened it, and continued successfully.
- Generated a one-page PDF, ran HR review, filed it in the TechCorp library, and downloaded it through the UI. All five HR criteria scored 1.00. Generation processing was about 168 seconds; interactive pauses are additional.
- Restarted the backend, reopened the saved run, and verified Complete status and Download PDF remain available.
- Inspected the rendered PDF: no visible clipping, overlap, orphan sections, or extra pages.

Sample output: `output/commandcode-validation/techcorp-sample.pdf`. The generated file and preview are ignored runtime artifacts, not source files.

## Defects reproduced and fixed

1. Saving provider settings left the global header/sidebar and doctor banner stale. Settings changes now propagate to the app immediately.
2. Vision was disabled in Settings but the backend still requested an empty vision model and entered unnecessary rewrite retries. Disabled vision now skips the model call. Provider switching and detected-provider setup clear stale vision settings for Command Code.
3. Live question statistics and run options displayed demo values and an old vision model. They now use available run/settings data.
4. Live runs kept the initial Unknown company/role. They now receive the current run summary.
5. Checkpoint reads warned about unregistered application schemas. Sync and async serializers now explicitly allow the application's saved schema types.
6. Browser navigation caused a second socket close after disconnection, raising a server error. Disconnect handling no longer closes an already closed socket.
7. Finished streams kept reconnecting. Terminal events now stop reconnection; unexpected disconnects during active runs still retry.
8. Restored history lacked a terminal event, so completed runs appeared to run forever after a server restart. History loading now reconstructs completion/failure events.
9. Configuration readiness accepted keys belonging to another provider. It now checks the selected provider's credential.
10. API errors always directed users to OpenRouter. Credit/authentication/rate-limit messages now refer to the selected provider, with Command Code plan-access guidance.

## Output accuracy assessment

The sample preserved identity, contact details, employers, role dates, education, the Go learning qualifier, and major facts such as 2M requests/day, 90ms latency, 60% deployment-time reduction, 50+ customers, and 800+ stars. No unconfirmed on-call, SLO, EKS, or Helm claims appeared.

It is not a verbatim transformation: the existing polishing policy changes phrasing and metric density. The result omitted the 450ms latency baseline and 10x deployment claim and generalized adoption at three companies to multiple companies. Human review remains necessary when exact factual/metric preservation is required; this work does not claim lossless generation or benchmark performance beyond this sample.

## Final checks

- Python suite: **232 passed**, including real PDF compilation and restoration tests.
- Frontend socket tests: **3 passed**.
- Production frontend build: passed.
- Source and new-test lint checks: passed; diff whitespace check: passed.
- Independent review: no unresolved actionable findings after fixing detected-provider vision setup.
- Three pre-existing test warnings remain (Starlette HTTPX deprecation, LangGraph default serializer warning, unregistered slow-test marker). Broad lint over all legacy tests reports existing style/unused-variable findings; changed source and new tests pass.
- First-run Tectonic package downloads initially exceeded one test's 60-second timeout; PDF tests passed after resources finished downloading. The app's configured compile timeout is 180 seconds.

## Local state

The browser test server is at `http://127.0.0.1:8000` with isolated sample state under `/tmp/resume-agent-commandcode-runtime`; the launcher is `/tmp/resume-agent-ui-server.py`. This avoids overwriting the user's base resume. The requested provider/model and supplied key were also saved in the normal `~/.resume_generator` private settings, preserving existing resume data and other provider credentials. No supplied credential was added to tracked source or validation logs.
