# AGENTS.md

Guidelines for anyone working in this repo, human or agent. Four people are building in parallel, so these rules exist mainly to keep us from stepping on each other.

## Start here

- **`PLAN.md` is the design doc.** Read it before starting non-trivial work. It covers the architecture, the phases, and who owns what.
- When a design decision changes, update `PLAN.md` in the same PR. Keep it matching reality.
- Everyone is on macOS. Don't add Windows or Linux workarounds.

## Layout

| Path | What | Stack |
|---|---|---|
| `app/` | Tauri shell plus React UI (console and projector windows) | TypeScript, React, Vite, Tailwind, WebGL |
| `engine/` | Vision, sim, forecasting, routing, commander | Python, OpenCV, NumPy |
| `assets/` | Scenarios, heightmaps, STLs, marker sheets | — |
| `tools/` | One-off scripts (e.g. DEM → assets) | Python |

## Ownership

Each area has an owner (see the Ownership section of `PLAN.md`). You can work anywhere, but **before making significant changes in someone else's area, tell them.** Small fixes are fine; just mention them in the PR.

## Shared contracts

A few things touch everyone. Treat them carefully:

- **The WebSocket protocol** (`engine/protocol.py`). Change the Pydantic models and regenerate the TS types in the *same* commit. Never hand-edit the generated types. Announce protocol changes to the team.
- **The map-grid coordinate frame.** Every module speaks map coordinates. Only vision and the projector shader deal with camera or projector space.
- **Scenario assets.** `heightmap.npy` and the STLs both come from `tools/dem_to_assets.py`. Don't edit either one by hand, or the sim and the print will drift apart.
- **Tauri APIs are only called from `app/src/platform/`.** The app must always run in a plain browser too.
- **Virtual table mode must always work.** It's how anyone can develop without the physical setup.

## Track work in GitHub issues

Four people (and their agents) work in parallel. To keep anyone from duplicating or clobbering work, every non-trivial task gets a GitHub issue. **Agents should do this on their own, without being asked.**

1. **Check first.** Before starting, look for an existing issue: `gh issue list --state open`, or `gh issue list --search "<keywords>"`. If someone else is assigned to overlapping work, stop and tell the user instead of starting a parallel version.
2. **Claim it.** If no issue exists, create one and assign yourself. Prefix the title with the area, matching the branch name:
   `gh issue create --title "sim: wind and slope spread" --body "<what and why, files likely touched>" --assignee @me`
   If an issue exists and nobody has it, assign yourself: `gh issue edit <N> --add-assignee @me`.
3. **Keep it current.** If the plan or scope changes, or you hit a blocker, comment: `gh issue comment <N> --body "..."`.
4. **Close the loop.** Put `Closes #<N>` in the PR description. If you abandon the work, unassign yourself and comment on where it stopped.

Keep each issue to roughly one PR's worth of work. Small fixes (typos, one-line changes) don't need an issue.

## Git workflow

- `main` should always run. Don't push directly to it; work on branches named like `sim/wind-slope` or `app/calibration-wizard`, prefixed with your area.
- Keep PRs small and focused, and merge often. Long-lived branches cause painful conflicts.
- Pull `main` before starting new work.
- Never commit secrets. API keys go in `.env` (gitignored), with names listed in `.env.example`.
- No AI attribution anywhere: no `Co-Authored-By` trailers for Claude or other agents, no "Generated with Claude Code" lines, and no mentions of being AI-generated in commits, PRs, issues, or comments.

## Code

- Match the style of the surrounding code. Keep it simple; this is a hackathon, not a framework.
- Don't add dependencies casually. If you do, add them to the lockfile and mention it in the PR.
- Keep sim and forecasting code vectorized (NumPy). Avoid Python loops over grid cells.
- Never block the engine's main loop. Slow work (rollouts, LLM calls) goes in its own process or async task.

## Claude skills

We keep project skills in `.claude/skills/` so every teammate's agent learns the workflows we figure out. **Agents should create and maintain these as they work.**

**Create a skill when** you work out a repeatable workflow that someone else will need again, such as:
- running the engine and app together
- calibrating the projector and camera
- regenerating protocol types
- adding a new token type or scenario
- debugging marker detection

**Keep skills current.** If you change how something works and a skill describes it, update the skill in the same PR. A stale skill is worse than none. Delete skills that are no longer relevant.

**Format:** one directory per skill, containing `SKILL.md`:

```markdown
---
name: run-dev
description: Start the Python engine and the Tauri app together for local development. Use when asked to run, start, or test the app.
---

Steps, commands, and gotchas go here. Keep it short and concrete.
```

- Make the `description` say *when* to use the skill. That's what agents match on.
- Keep skills short and actionable: commands, file paths, gotchas. Don't copy what's already in `PLAN.md`; link to it instead.
- Check `.claude/skills/` before inventing a process from scratch.

## Commands

Prereqs: `uv`, `pnpm`, Node, and the Rust toolchain. Everything runs from the repo root via `make`:

| Command | What |
|---|---|
| `make install` | `uv sync` the engine and `pnpm install` the app |
| `make engine` | Python engine on `ws://localhost:8765` |
| `make app` | Tauri app (console window; open the projector from the console) |
| `make web` | UI in a plain browser: `http://localhost:1420/?view=console` and `?view=projector` |
| `make dev` | Engine + Tauri app together |
| `make types` | Regenerate `app/src/shared/protocol.ts` from `engine/protocol.py` |
| `make test` | Engine pytest + app typecheck |

Engine modules use flat imports (`from protocol import ...`) and are run from `engine/`. Config lives in a root `.env` (see `.env.example`), read by both `make` and Vite.
