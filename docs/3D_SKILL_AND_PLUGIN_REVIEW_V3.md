# Skill & Plugin Security Review — v3 (2026-09-01)

Scope: the seven repositories named in the v3 polish directive. Nothing was
installed blind: install candidates were shallow-cloned to the session
scratchpad and read; everything else was assessed from remote metadata
(`git ls-remote` + GitHub API) without cloning. Installations are pinned,
project-scoped (`.claude/skills/`), markdown-only, and
carry an in-file provenance block with the removal command.

Duplicate note: the Claude Skill Registry appeared twice in the original
request; treated as one repository.

## 1. emalorenzo/three-agent-skills — INSTALL (one skill)

| | |
|---|---|
| Purpose | Instruction packs for Three.js / React-Three-Fiber best practices |
| Pinned commit | `f950f95ae3b13581546e6d6d8b2f88a08eb3e577` (2026-01-28) |
| License | MIT |
| Install method | extract `skills/three-best-practices.zip` → `.claude/skills/three-best-practices/` |
| Executable surface | none — SKILL.md + 28 rule .md files; zero scripts |
| Network / permissions / deps | none at runtime; no hooks; no global config; no telemetry |
| Benefit | directly applicable: 120+ pinned-version Three.js rules (dispose, draw calls, instancing, lighting/shadow cost, on-demand loops) used for the §11 audit |
| Security / maintenance risk | low / low (static text; version-stamped three 0.182 guidance vs our 0.185 — compatible) |
| Flags in scan | 2, both benign: a documented `npm install -g @gltf-transform/cli` example inside a fenced code block; a GLSL string-replace variable literally named `token` |
| Decision | **INSTALLED**: `three-best-practices` only. **`r3f-best-practices` NOT installed** — JobBot has no React |
| Removal | `rm -rf ~/jobbot/.claude/skills/three-best-practices` |

## 2. Jeffallan/claude-skills — INSTALL (one of 67)

| | |
|---|---|
| Purpose | 67-skill catalog of role/language instruction packs |
| Pinned commit | `882ef55e377dbf9a4dbe496bb41ac6ccd0e555cf` (2026-08-07) |
| License | MIT |
| Executable surface of the repo | Makefile, scripts/, site/ exist at repo level — none are part of a skill install; individual skills are markdown-only |
| Skills inspected (full read + pattern scan) | `javascript-pro` (SKILL.md + 5 refs; sole flag = a class-fields example reading `process.env.API_KEY`) · `playwright-expert` (clean) · `code-reviewer` (clean) |
| Decision | **INSTALLED**: `javascript-pro` (vanilla-ES2023 guidance directly serves this engine work). **REJECTED**: `playwright-expert` (redundant — Playwright already exercised heavily here), `code-reviewer` (duplicates Claude Code's built-in review), and the other 64 (unrelated domains). The complete bundle was **not** installed |
| Removal | `rm -rf ~/jobbot/.claude/skills/javascript-pro` |

## 3. majiayu000/claude-skill-registry — RESEARCH INDEX ONLY

HEAD `3adba96a…`, MIT, **22.6 GB** generated HTML registry. Used only as a
discovery index (its hosted search page); **never cloned** into JobBot and
not installed. Risk of cloning: enormous disk/context waste, generated
content of unvetted provenance. Nothing to remove.

## 4. MonumentalSystems/Atlas-Agent-Teams — INSPECTED, NOT INSTALLED

HEAD `826a409e…`, MIT, 314 KB, Python hooks + markdown teams. Its
`teams/3d-design/` skills (modeling/texturing/animation…) are generic
Blender/Unity reference text; every team ships a `team-logger.py`
PostToolUse hook that writes telemetry JSONL under `~/.claude/team-logs/`
— exactly the class of global hook this directive forbids enabling.
Principle carried over from its hard-surface modeling notes (standard
practice, no attribution-restricted content): man-made equipment reads
through **bevels/chamfers, supporting edges, and material separation** —
applied in §3 of the polish. Decision: **NOT INSTALLED** (marketplace,
telemetry hooks, unrelated agents). Nothing to remove.

## 5. Andrew1326/dominations — REJECTED

HEAD `d3bff0da…`, no license (all-rights-reserved by default), 26 MB,
Python/Phaser strategy game. Unrelated to a Flask/vanilla-Three dashboard;
no-license status alone disqualifies reuse. **NOT CLONED, NOT INSTALLED.**

## 6. phuetz/code-buddy — REJECTED

HEAD `8e2da7d6…`, MIT, **880 MB** TypeScript coding-agent platform (64 LLM
providers, 220+ tools, P2P fleet, desktop app). It is a parallel agent
environment, not a library: installing it would duplicate/replace the
development environment and add an enormous unaudited execution surface.
**NOT CLONED, NOT INSTALLED.**

## 7. Svetlana-DAO-LLC/cad-agent — REJECTED

HEAD `5bbf7168…`, license NOASSERTION, Docker-based CAD/3D-printing MCP
system (build123d). Wrong domain (parametric CAD, not real-time WebGL),
unclear license, Docker daemon requirement. **NOT CLONED, NOT INSTALLED.**

## Continuing capabilities (unchanged)

Stable Taste redesign skill (`redesign-existing-projects` @ ccbc156, pinned,
markdown-only) · Anthropic frontend-design principles · Vercel
web-interface guidelines (guidance only — no Vercel deploy/framework
plugins) · Playwright 1.62 CLI in the project venv · vendored three.js
0.185.1 (checksummed, no CDN) · the existing accessibility/fallback system.

## Post-review state

`~/.claude/skills/` (project scope): `redesign-existing-projects`,
`three-best-practices`, `javascript-pro` — three skills, all pinned,
all markdown-only, each with an embedded provenance + removal block.
No hooks added, no global Claude configuration touched, no telemetry.
