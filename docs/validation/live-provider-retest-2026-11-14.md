# Live model workflow retest

Date: 14 November 2026, Asia/Kolkata. Application revision: `e5d5d0f`. Provider: Command Code. Model: `deepseek/deepseek-v4.1-flash`.

This report preserves the failed pre-fix run. Both failures were subsequently [fixed and verified](live-fixes-2026-11-14.md). The fresh live workflow passed at `362a3b5`.

**Result at the time:** the updated API connection worked, but the complete live workflow failed on truncated evaluation and a PDF extraction mismatch.

## Method

The normal app at port 18731 used the owner's newly saved settings. Settings → Re-test made a real request and returned `OK` in 5,863 ms.

A separate running instance at port 18732 loaded those settings read-only. Its state, profile, role and outputs were isolated. No model or network transport was substituted. The browser drove upload, review, role evaluation, questions and content confirmation through the actual API.

The fictional candidate was Casey Example. The source specified Python, SQL, PostgreSQL, Docker, Linux, Git, three years of work and a latency improvement from 450 ms to 90 ms. The fictional role was Platform Engineer at Example Cloud. Kubernetes was optional and absent from the profile.

## Observed results

| Stage | Actual result |
| --- | --- |
| Saved API connection | PASS: real reply `OK`, 5,863 ms. |
| Resume import | PASS: real model parsed the TEX source. Dates, original bullets, metrics and skills were retained. The test draft was reviewed and explicitly accepted in isolated state. |
| Role evaluation | FAIL: `truncated_output` at `role_evaluation`, one consumed attempt. No score was produced. Operation duration was about 101 seconds. |
| JD extraction | PASS: real model identified Example Cloud, Platform Engineer, Bengaluru and hybrid work. |
| Questions | PASS: three relevant questions about Git workflows, hybrid availability and automated testing. |
| Proposed edits | PASS: three validated proposals, all initially unselected, with source references. |
| Content selection | PASS: one experience edit selected. The summary rewrite and skill-list append stayed unselected. |
| Complete content preview | PASS: selected edit present; original summary, skills and 450 ms → 90 ms metric retained. No Kubernetes claim was added. |
| Compilation and page rendering | PASS: actual Tectonic/Poppler produced one page with no overflow. |
| Strict PDF content check | FAIL: expected `Tools`, extracted `T ools`, mismatch at token 95. |
| Final PDF approval/export | NOT REACHED. No PDF was released. The final download remained blocked. HR advice was not reached. |

Five structured model tasks each consumed one attempt: import, evaluation, JD extraction, questions and proposals. The separate connection probe made one additional request. No automatic retry was issued for the truncated evaluation.

The explicit fictional answers supplied Git feature-branch/pull-request review and pytest usage. They did not supply Kubernetes or new performance metrics. Only the experience-bullet proposal was selected. These were synthetic QA decisions, not changes to the owner's profile or evidence of a volunteer pilot.

## Issue 1: incomplete evaluation response

Operation: `cbfa65f1-4199-48db-a3a1-968cb6be90d6`.

The live response was classified as `truncated_output`. The configured output ceiling is 16,384 tokens. Raw provider finish metadata and token usage were not retained, so the test does not prove whether the ceiling, reasoning usage or another incomplete-output condition caused it.

The app failed the evaluation without inventing a score. Generation was then tested separately through its existing “Generate without evaluation” action. That does not turn the failed evaluation into a pass.

Required work: inspect provider completion metadata, reproduce the structured evaluation behavior, correct the supported output/model configuration or prompt contract, then repeat the live evaluation. Increasing a budget alone is not a verified remedy.

## Issue 2: kerning creates a false PDF mismatch

Run: `11916def-92cf-4e1a-b967-1e946650d101`. Artifact: `3e66a9fe-7ac3-43cd-a5f2-db8211c20c0f`.

The rendered page was visually inspected. It displays `Tools`, but pypdf extracts `T ools`. All other tokens match the approved stream. The strict guard therefore blocks this otherwise matching document.

A separate diagnostic copy added `Kerning=Off` to the font setup. It used the exact saved manifest and content. The actual compiler produced a one-page PDF whose extracted stream passed the unchanged strict guard. Its expected and actual content hashes both equal `027130109f0e88fda962ea52a583d1d6d8db1b05aa725fe3fe11bcb3bd6c5970`.

**This was an isolated diagnostic, not a production fix or approval.** The repository template and comparison rules were not changed. The original failed run remains failed. The diagnostic PDF was not exported through the application.

Required work: add a real-compiler regression for this case, correct font setup without weakening the guard, then rerun layout/content checks and the live reviewed-export journey.

## Acceptance status at the time

The prior “only external gates remain” status is superseded by this live evidence. The two issues above now require local repair and verification. Five pilots, remote Linux/native Windows checks and authenticated Claude validation also remain open. C4 is not passed.

The normal app on port 18731 remains running. The isolated test server and its browser were stopped after evidence capture. Personal resumes and applications were unchanged. No personal document was sent to the model. Configured API-key values were absent from saved text evidence.

Evidence is retained under the ignored execution workspace's `live-provider-retest-2026-11-14/`: connection response, import/evaluation/run records, checkpoints, approved/extracted text, page image, failure screenshot, model-task summary and the diagnostic source/PDF/check result. No application implementation code changed during this retest.
