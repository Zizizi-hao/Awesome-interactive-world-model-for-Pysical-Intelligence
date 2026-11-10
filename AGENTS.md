# Purpose
The file is the canonical quick reference for coding agents and contributors.

This project tracks the latest research on interactive world models, summarizes and curates high-quality papers, and covers three areas: autonomous driving, robot learning, and general interactive world models.

## Workflow

This project has three main parts:

1. **Track:** the existing GitHub Action files new candidate papers as issues. Candidates are search results, not verified recommendations.
2. **Curate locally:** process one issue at a time; verify primary sources, select relevant high-quality work, update the bilingual database, and regenerate and validate its outputs according to `CONTRIBUTING.md`.
3. **Human review and publication:** leave the changes local for review. Commit/push only when explicitly authorized; close the issue only when closure is requested and publication succeeds.

## Standard Operating Procedure

1. **Scope and deduplicate:** inspect `git status`, `CONTRIBUTING.md`, and the requested issue/comments. Deduplicate arXiv IDs/titles against `data/*.yaml`; `seen_arxiv_ids.txt` only records scanning. Preserve unrelated changes and process no other issues.
2. **Verify quality:** read current primary-source methods, experiments, limitations, and official project/code pages. Verify title, first-publication year, affiliations, venue, and links. Use arXiv unless acceptance is verified; omit unknown optional fields and placeholder links. Judge comparisons, ablations, and downstream evidence, not institution reputation alone.
3. **Apply scope:** require learned world prediction/dynamics or its application to driving, robotics, or physical/game interaction. Prioritize action-conditioned work; explain prediction-only relevance. Pure VLA planning, generic video benchmarks, rule-only transitions, and unrelated time-series work do not automatically qualify. Distinguish new dynamics from reuse for policy learning.
4. **Record and edit:** in `curation/YYYY-MM-DD.md`, group by issue and record every candidate's include/defer/exclude decision, reason, and primary-source URLs. Edit `data/<category>.yaml` in existing format, choosing the actual application category. Match `note`/`note_en` claims, numbers, and limitations; supply required translations. Set `meta.updated` to the curation date when papers change.
5. **Generate and validate:** run `python3 scripts/generate_readme.py`, `python3 scripts/generate_monthly_chart.py`, `python3 -m unittest discover -s tests`, and `git diff --check`. Verify bilingual sync, unique new IDs, counts, no unintended existing-entry edits, and both chart renderings. Do not hand-edit READMEs or change generators for routine dependency/font issues; report incomplete checks.
6. **Hand off:** report decision counts, key limitations, changed files, and validation. Leave changes local and issues open unless the corresponding publication/closure actions are explicitly authorized.

## Capability Evidence

Set `features` only when the paper demonstrates the corresponding capability; use `{}` when none is verified.

- `action`: externally specified actions condition future-state prediction; joint action/future output alone is insufficient.
- `realtime`: measured world-model throughput with hardware/resolution context; few sampling steps or policy speed alone is insufficient.
- `closedloop`: demonstrated feedback-based execution, evaluation, or policy learning. Identify controller/planner feedback; batch generation plus offline DPO alone does not establish online closed-loop control.
- `longhorizon`: evaluated coherent long rollouts; long tasks, subgoal plans, or selected demos alone are insufficient.

## Authorized Publication

1. Honor existing explicit authorization without asking again. Check branch/remote and fetch; preserve remote changes, never force-push. Stage only reviewed files, including audit/generated outputs. Name added work precisely, e.g. `git commit -m "[update] simscale, worldengine, vira"`.
2. Update the audit's authorization status before committing. Push and verify the remote commit and CI; close the issue as completed only when requested and publication succeeds. Verify the final issue state; report commit URL, CI result, and closure status.
3. Check `gh auth status` for GitHub writes: Git/SSH authentication does not imply gh/API login. If a connector lacks permissions, use authenticated `gh`; if needed, use the official `gh auth login` flow.

## Boundaries

1. Do not delete files casually. Do not use commands such as `rm` or `mv`.
2. Do not run `git commit` or `git push` unless a person explicitly asks for it.
3. Do not close issues or post comments without explicit authorization; successful local curation does not authorize publication.

## Four Principles (Karpathy)

- Think Before Coding: Wrong assumptions, hidden confusion, missing tradeoffs;
- Simpliciy First: Overcomplication, bloated abstractions;
- Surgical Changes: Orthogonal edits, touching code you shouldn't
- Goal-Driven Execution: Leverage through tests-first, verifiable success criteria
