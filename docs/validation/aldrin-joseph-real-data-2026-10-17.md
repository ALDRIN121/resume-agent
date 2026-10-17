# Aldrin Joseph — real-data browser retest

This retest replaces the earlier Jane Doe sample as the verification of the user's actual profile.

## Inputs

- Source: the newer `Aldrin_Joseph_Resume(20261016-082636).pdf` from Downloads, dated 16 October 2026. It includes Pine Labs from July 2026, CogniCor, three Gapblue roles, newer projects, and open-source contributions.
- Target: the Senior AIML Engineer posting recovered from the user's earlier failed run. The posting does not name an employer; no company was invented.
- Provider/model: Command Code, `deepseek/deepseek-v4.1-flash`.
- The PDF was uploaded and parsed through the browser. The structured profile contains all five roles and thirteen project/contribution entries; approximately 13,600 characters of JSON.
- Updated the normal app's base profile with the October resume and preserved the older cached profile at `~/.resume_generator/backups/base_resume-before-2026-10-17-update.yaml`. The original Downloads PDF remains unchanged.

## Additional defects found with real data

1. Analysis and answer enrichment sliced resume JSON at 6,000 characters, losing later projects or producing malformed JSON. Both now receive complete JSON. HR review also receives the complete LaTeX instead of the first 8,000 characters.
2. An HR-driven correction added unsupported metrics (including a 30% Pine Labs improvement and invented accuracy/user counts). That run was cancelled and its output is not the deliverable. The generator now rejects added or removed numeric occurrences, including common spelled quantities, and falls back to the source-backed template. Prompt rules explicitly prohibit changing supplied metrics, including when review feedback requests more quantification. Regressions cover novel claims, duplicate additions/removals, lost baselines, legitimate wording changes, and layout spacing.
3. Parser-generated project descriptions duplicated existing bullets or merely repeated the project name. Rendering now omits those redundant descriptions while retaining distinct descriptions. The complete reference resume fits two pages rather than three.

The numeric guard is deliberately conservative. It does not prove every semantic claim or the association of a number with an employer; the final PDF still requires a factual review against the supplied source.

## Final verification

- Full Python suite: 246 passed; three pre-existing dependency/test-marker warnings.
- Frontend socket tests: 3 passed; production UI build remains valid (no frontend changes in this retest).
- Source and new-test lint checks pass; diff whitespace check passes.
- Independent review verified the full-input fix and numeric-occurrence comparison after replacing a set with a Counter.
- Unconfirmed gap questions were skipped. In the final verification run, all suggested factual rewrites were rejected; job-specific polish ran using the supplied facts under numeric-occurrence protection.

## Date-review correction

HR review lacked the current date and incorrectly called the July 2026 Pine Labs start date future-dated. It now receives the current date explicitly. Metric-density preferences are advisory and no longer contribute to rewrite thresholds; two substantive quality failures can still trigger a retry.

## Completed real-data result

- Final run: `04119e4a-53df-4afa-a432-42d51854d215`, Complete in the normal app; one generation attempt, approximately 167 seconds including the interaction phases.
- Downloaded the result through the browser without errors to `output/aldrin-joseph-validation/aldrin-joseph-senior-aiml-engineer.pdf`.
- Two pages, visually inspected: no clipped text, overlap, or orphaned sections.
- Verified current Pine Labs role and July 2026 start, all five role histories/dates, all thirteen project/contribution names, education, benchmark figures, and selected contribution PR references against the supplied resume.
- Read the final persisted checkpoint and compared numeric Counters: every numeric occurrence in the generated LaTeX matches the source-backed template. No added or removed numeric facts.
- Explicitly checked that the unsupported 30%, 90%, 500+, 35%, and 25% claims from the rejected pass are absent. The 4+ years qualifier remains unchanged; unconfirmed diffusion/reinforcement-learning claims are absent.
- Final HR scores: metric density 0.75; buzzword density, action verbs, tense, and title plausibility 1.00 each. No date or quality rewrite loop.
- Browser console: no errors. The completed run and PDF are filed in the normal app library, with Command Code and DeepSeek V4.1 Flash active.
- Final factual wording still merits user review: numeric occurrence preservation does not establish every semantic claim or metric-to-role association.

