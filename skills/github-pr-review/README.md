# GitHub PR Review Skill

This skill automates the process of orchestrating a code review on a GitHub Pull Request using the **Luna** persona.

## Features
- Automatically fetches PR file changes via your configured GitHub MCP server.
- Discovers companion PRs across repositories through the linked Linear issue, for a holistic review.
- Adopts Luna's strict, deficit-focused review persona: only points out what is **wrong** (defects, security, performance) and suggests **future considerations** without fluffy praise.
- Posts the final review to the GitHub PR as a standard comment — only after explicit user approval.

## Requirements
- A **GitHub MCP server** connected and authorized in Claude, with `repo` scope or fine-grained access to the target Pull Requests.
- A **Linear MCP server** connected and authorized in Claude.

## Usage
Simply ask Claude to review a PR and provide the link.

**Example Prompt:**
> "Please review this PR: https://github.com/owner-name/repo-name/pull/123"

Claude will handle the rest: fetching the diff, discovering any linked companion PRs, drafting Luna's review, and — after you approve — posting the review comment.
