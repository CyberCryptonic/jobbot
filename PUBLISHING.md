# How this repository was published

jobbot ran on a private container with real credentials, a real resume, and a filled answer bank in its git history. The public repository was produced from it the following way, and the same steps apply if you fork this and later want to publish your own changes.

1. **Private backup first.** The original tree, with full history, was pushed to a private repository. It is never made public; the history contains personal files.
2. **Clean copy, kit on top.** A fresh clone of this public repository received the documentation kit (README, LICENSE, SECURITY.md, .gitignore, .env.example, the example answer bank, the diagrams, BUILD-GUIDE.md, REPRODUCTION.md, the PR template), then the code was copied in with `rsync --ignore-existing`, excluding `.env`, databases, exports, screenshots, letters, logs, the resume, the filled answer bank, and the master prompt.
3. **Scrub.** Every hit for a name, mailbox, private IP, ntfy topic, Tailscale hostname, reference, employer name in fixtures, or key pattern was listed and removed. Host-specific values moved into `.env` or config with documented defaults. Test fixtures with real employer mail were replaced with synthetic ones.
4. **Safety defaults confirmed in code.** `DRY_RUN` true, verify-first-20 on, quota 10, native job-board forms never scripted, CAPTCHAs never attempted, exact-match export-control and clearance answers, resume never written.
5. **Secrets scan.** `gitleaks detect --no-git` on the tree, plus a grep for the personal patterns. Zero findings before the first push.
6. **Push, then lock the door.** Secret scanning and push protection were enabled on the repository.

If you publish a fork, keep the order: backup, clean copy, scrub, verify defaults, scan, push. The `.gitignore` here already refuses the files that matter most, but a `.gitignore` is not a substitute for reading `git status` before you commit.
