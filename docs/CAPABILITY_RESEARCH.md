# Capability research — futuristic redesign (2026-08-31)

Method: the harness provides an authoritative live inventory of every installed
skill, plugin, agent and MCP tool (superior to any directory search); each
external candidate below was additionally verified against its primary source
by direct fetch. Nothing was installed or enabled. Per the brief, anything
missing is listed with an exact command and waits for operator approval.

## Requested `find-skills` step

`find-skills` (vercel-labs/skills) is **not installed** in this environment, so
it cannot be "invoked first". Its function — enumerating available skills — is
covered here by the harness's own authoritative inventory (below), which is
complete rather than search-based. Installing it would add nothing for this
task. **Decision: do not install; equivalent inventory performed.**

## Installed inventory (harness-authoritative)

| Capability | Source / maintainer | State | Decision for this redesign |
| :--- | :--- | :--- | :--- |
| `dataviz` skill | Anthropic (bundled) | installed | **USE** — governs every chart: form choice, mark specs, validated palette; its validator was run for the dark chart palette (all sets PASS) and stays authoritative |
| `superpowers` plugin (brainstorming, TDD, worktrees, verification, …) | superpowers-marketplace 6.3.0 | installed | **USE** — `using-git-worktrees` (this worktree), `test-driven-development` (backend), `verification-before-completion` (final gate). `brainstorming` deliberately skipped: the operator supplied a complete spec and forbade stopping at research/planning |
| `vercel` plugin | Vercel (claude-plugins-official) | installed | **INVENTORIED — mostly N/A.** Its actual skills are: bootstrap, deploy, env(+vars), status, ai-gateway, ai-sdk, auth, cdn-caching, chat-sdk, deployments-cicd, eve, knowledge-update, marketplace, microfrontends, next-*, nextjs, react-best-practices, routing-middleware, runtime-cache, shadcn, turbopack, vercel-agent, vercel-cli, vercel-connect, vercel-firewall, vercel-functions, vercel-sandbox, vercel-storage, verification, workflow. **`web-design-guidelines` is NOT among them** — it ships in a different package (vercel-labs/agent-skills). No React/Next/deploy skill applies to this Flask + vanilla-JS app; none will be used |
| Playwright (Python) | Microsoft, in `venv` | installed | **USE** — real-browser verification; already drives 17 existing repo tests. This is the project's established browser tool |
| `design`, `artifact-*` skills | Anthropic (bundled) | installed | not used — they target claude.ai Artifacts / mockup canvases, not this app's own codebase |
| `code-review`, `simplify`, `security-review` | Anthropic (bundled) | installed | available for post-slice review if requested |
| Connectors (Gmail, Drive, Canva, Indeed, ZipRecruiter, Lucid, …) | claude.ai | installed | **not used** — per brief, no connector is required for a local redesign; per CLAUDE.md they can never serve the pipeline anyway |

## External candidates (verified at source; NOT installed)

| Candidate | Source verified | Fit for Flask + vanilla JS | Concerns | Decision |
| :--- | :--- | :--- | :--- | :--- |
| **Vercel `web-design-guidelines`** | vercel-labs/agent-skills → the skill is a thin trigger that fetches `vercel-labs/web-interface-guidelines/main/command.md` | Yes — framework-neutral checklist | none (public checklist) | **USE THE SOURCE DIRECTLY, no install**: the full checklist was fetched from the primary repo this session and is applied as the final audit pass (results in `docs/PLAYWRIGHT_VISUAL_QA.md`). Installing the wrapper adds nothing. To install anyway: `npx skills add vercel-labs/agent-skills/web-design-guidelines` — awaiting approval, not required |
| **Anthropic `frontend-design`** | anthropics/skills → `skills/frontend-design/SKILL.md` fetched | Yes — process + principles, stack-agnostic | none | **PRINCIPLES ADOPTED from the fetched source** (thesis-driven hero, one signature element, structure-encodes-meaning, subject-grounding, and its named AI-default clusters to avoid — see design direction doc). To install the skill itself: `npx skills add anthropics/skills/frontend-design` — optional, awaiting approval |
| **Taste-Skill (`design-taste-frontend`)** | github.com/leonxlnx/taste-skill fetched | Partial — v2 (default) is **experimental**, ships GSAP skeletons and greenfield/aesthetic-brief workflows | brief forbids GSAP; repo's own positioning is not dashboards/multi-step product UIs; third-party maintainer, active rewrite | **DO NOT USE.** Its anti-generic goals are covered by the adopted frontend-design principles + this brief's own anti-patterns |
| **Microsoft Playwright CLI** (`playwright-cli`) | github.com/microsoft/playwright-cli | n/a (tooling) | **binary not installed** (`which playwright-cli` → none; no npm package present) | **NOT INSTALLED — venv Playwright used instead** (same engine, already trusted by the repo's test suite; zero new dependencies). If the standalone CLI is wanted: `npm i -g @playwright/cli` (or per its README) — awaiting approval; the redesign does not need it |
| Figma connector | — | n/a | not needed; no mockup workflow requested | **DO NOT ADD** |
| Vercel deployment connector / MCP auth | plugin's `authenticate` tools | n/a | JobBot is not deployed to Vercel | **DO NOT ADD / DO NOT AUTHENTICATE** |

## ACTION REQUIRED (optional installs, work is NOT blocked)

Nothing blocks the redesign. If you want the optional skills installed for
future sessions, say so and I'll run exactly:

1. `npx skills add anthropics/skills/frontend-design` — official Anthropic design-direction skill (its principles are already applied this session from source).
2. `npx skills add vercel-labs/agent-skills/web-design-guidelines` — wrapper for the checklist already being applied from its primary source.
3. Playwright CLI per microsoft/playwright-cli README — redundant with the venv Playwright the repo already uses.

No other capability, package, connector, or service is proposed.
