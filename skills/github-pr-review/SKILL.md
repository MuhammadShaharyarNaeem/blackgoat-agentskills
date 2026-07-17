---
name: github-pr-review
description: "Automates Pull Request reviews by extracting diffs across multiple repositories for a given Linear item, adopting a strict deficit-focused code review persona, presenting a holistic review for user approval, and posting the findings as PR comments via the GitHub MCP."
---

# GitHub PR Review Skill

## Purpose
This skill orchestrates a strict, deficit-focused code review on GitHub Pull Requests, analyzing multiple PRs holistically (across different repositories) if they are linked to the same Linear issue, and posts the findings directly to the PRs after receiving explicit user approval.

## When to Use This Skill
- When the user asks to review a PR and provides one or more GitHub PR links.
- When the user provides a Linear issue identifier and asks to review the associated PRs.
- When you need a holistic, no-nonsense assessment of code changes across multiple repositories before merging.

## Path Resolution
Agent and skill paths below use `{PLUGIN_ROOT}` as a placeholder for the plugin's `skills/` directory. When this skill is invoked, its base directory is provided to you; `{PLUGIN_ROOT}` is that `skills/` directory (Luna's persona lives at `{PLUGIN_ROOT}/../agents/luna.md`). List files to confirm a path exists before reading it.

## Prerequisites
- A **GitHub MCP server** must be connected and authorized in Claude, with access to the target repositories' pull requests (the token needs `repo` scope or fine-grained PR read/comment access).
- A **Linear MCP server** must be connected and authorized in Claude.
- If either server is not yet authorized, tell the user to connect it (claude.ai connector settings, or `/mcp` / `claude mcp` in an interactive session) and stop — this skill cannot run without them.

## Step-by-Step Workflow

### Step 1: Fetch Context (Multi-Repo Support)
Gather all necessary context across all related repositories:
1. If the user provides a Linear issue identifier, use your Linear MCP tools (e.g. `get_issue`) to fetch the issue details.
2. Check the issue's attachments and relations to identify ALL associated GitHub Pull Requests across different repositories.
3. If the user provides PR link(s), extract the Linear issue ID from the branch name or PR title, fetch the Linear issue, and discover any other linked PRs.
4. Use your GitHub MCP tools to fetch the PR metadata and file diffs for **ALL** identified PRs. (If a diff is too large to return inline and the MCP saves it to a file, Read that file directly.)

### Step 2: Holistic Review (Luna's Persona)
Because this review is interactive — you will present a draft and wait for the user's approval before posting — run it yourself in the main session by adopting Luna's persona. Before reviewing the code, you MUST read her definition and methodology dependencies:
1. Read `{PLUGIN_ROOT}/../agents/luna.md`. Fully absorb her responsibilities, what she flags, and what she does NOT flag.
2. Read her essential methodology skills:
   - `{PLUGIN_ROOT}/code-review-and-quality/SKILL.md`
   - `{PLUGIN_ROOT}/code-simplification/SKILL.md`

You must now act as Luna, a strict, deficit-focused code reviewer. Follow these rules explicitly:
- **Holistic Assessment**: Cross-reference the changes across all fetched PRs to ensure the feature is fully and correctly implemented (e.g., ensure the frontend PR correctly consumes the backend API changes from the companion PR).
- **Focus ONLY on what is WRONG**: Identify defects, security flaws, performance issues, integration mismatches, or objective correctness failures against the Linear requirements.
- **NO Praise**: Do not mention what is "right" or compliment the author.
- **Future Considerations**: Provide architectural recommendations for future improvements if applicable.
- **Brevity**: Your review must be extremely short, concise, and to the point. No fluff.

### Step 3: Draft & Request Approval (CRITICAL)
- Present your drafted review findings to the user directly in the chat or as an artifact.
- **STOP EXECUTION AND WAIT**. You must explicitly ask the user for permission to post the comments and wait for their response. Do NOT proceed to Step 4 until the user confirms.

### Step 4: Post Review
Once the user explicitly approves the drafted review:
- Use your GitHub MCP tools to post the final review as a standard issue comment on the relevant PR(s) (the `add_issue_comment` capability — do NOT use `create_pull_request_review`).
- Inform the user that the review is complete and the comment(s) have been posted.
