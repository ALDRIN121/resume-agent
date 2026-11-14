# Use Resume Agent from an agent host

Install the application from the reviewed checkout first. Python 3.12 or 3.13, Tectonic and Poppler are required for PDF generation.

The current upgrades are a local candidate. The public `main` installer does not contain unpushed changes.

## Codex

1. Open the project where you want to use the skill.
2. Export the skill into that project's skill directory.

```bash
resume-generator skill export --destination .agents/skills/resume-agent
```

3. Start a new Codex session in that project.
4. Ask `$resume-agent` to import or tailor a fictional resume first.
5. Review the source, content and PDF when requested.

Codex discovers repository skills in `.agents/skills`. See [official skill documentation](https://learn.chatgpt.com/docs/build-skills).

Codex CLI **0.153.4** passed the exported-skill review-handoff smoke check on 13 November 2026. It inspected a real saved run, presented the proposed change, and waited. No approval, submission or injected shell command occurred. The host's actual model name was not reported. This smoke check does not cover every Codex interface or model.

## Claude Code

1. Export the same package into your project's Claude skill directory.

```bash
resume-generator skill export --destination .claude/skills/resume-agent
```

2. Start Claude Code in that project.
3. Ask `/resume-agent` to inspect a fictional saved review.
4. Review each source, content and PDF decision yourself.

Claude Code supports project skills in `.claude/skills`. See [official skill documentation](https://code.claude.com/docs/en/skills).

Claude Code **2.1.285** was detected. Its smoke check stopped before inference because its OAuth session expired. This host integration is **unverified and unsupported in this candidate** until its required smoke check passes. No authentication settings were changed. Sign in through the host's own flow before rerunning the check.

## Modes and billing

`configured_provider` is the default. It uses the backend provider configured in Resume Agent. Provider charges and limits apply. Local Ollama needs no cloud API key; local compute is still required.

`external_agent` returns structured model requests to the calling agent. It makes no configured-backend model calls. Your host subscription, credits or API charges can still apply. No universal free allowance is promised.

The same skill and JSON protocol serve both hosts. The installed package includes its complete protocol reference. Export refuses an existing destination so local changes survive. Choose a new destination when testing an update.

Host model results cannot accept an import or approve content or PDF bytes. The skill shows the current review and asks for a decision. Use current review IDs and hashes from inspection. Do not approve an unseen PDF.

Read [the JSON protocol](../skills/resume-agent/references/protocol.md) for commands, schemas, exit codes and recovery. Detailed local evidence is in [the host validation record](validation/agent-hosts-2026-11-13.md).
