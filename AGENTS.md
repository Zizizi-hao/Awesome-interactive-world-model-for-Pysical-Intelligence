# Purpose
The file is the canonical quick reference for coding agents and contributors.

This project tracks the latest research on interactive world models, summarizes and curates high-quality papers, and covers three areas: autonomous driving, robot learning, and general interactive world models.

## Workflow
This project has three main parts:
1. Track the latest papers: a GitHub Action handles this and is already implemented. It files the papers it finds as issues.
2. Curate the database and update papers: the local agent screens each day's papers in the issues (keeping those from major groups or of high quality), then adds the selected papers to the database in the format described in `CONTRIBUTING.md`.
3. Human review: after each day's issues are processed, do not commit to GitHub right away. A person must review the updates before they are submitted.


## Standard Operating Procedure
1. Follow the existing format for every change so the repository keeps a consistent style.
2. When using `git commit -m`, write a precise message that shows what was updated that day, for example `git commit -m "[update] simscale, worldengine, vira"`.
3. Work one issue at a time. Do not update every issue in a single batch.


## Boundaries
1. Do not delete files casually. Do not use commands such as `rm` or `mv`.
2. Do not run `git commit` or `git push` unless a person explicitly asks for it.


## Four Principles (Karpathy)
- Think Before Coding: Wrong assumptions, hidden confusion, missing tradeoffs;
- Simpliciy First: Overcomplication, bloated abstractions;
- Surgical Changes: Orthogonal edits, touching code you shouldn't
- Goal-Driven Execution: Leverage through tests-first, verifiable success criteria