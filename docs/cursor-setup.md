# Cursor setup -- Blackgoat Agent Skills

This repo is a **dual package**: Claude Code uses `.claude-plugin/` + `.mcp.json`; Cursor uses `.cursor-plugin/` + root `mcp.json` + `rules/`. Both share the same `agents/` and `skills/` trees. No fork, no second copy of persona *content* (see hardlink install below).

## Local install (dev / smoke)

### Critical: no out-of-tree junctions for the plugin root

Cursor **rejects** a local plugin whose install path is a symlink/junction whose target is outside `~/.cursor/plugins/local`.

Observed log (Cursor 3.15.x):

```text
loadUserLocalPlugin blackgoat-agentskills rejected: symlink target C:\Users\<you>\.claude\skills\blackgoat-agentskills is outside C:\Users\<you>\.cursor\plugins\local
loadUserLocalPlugins completed … (0 plugins loaded)
```

If that happens, Customize still shows **Skills** via Claude-compat discovery (`claude=true`), but the Cursor plugin never loads — so **Agents / Rules / plugin MCP from this package do not appear**.

Do **not** use:

```powershell
# REJECTED by Cursor — do not use
New-Item -ItemType Junction -Path "$env:USERPROFILE\.cursor\plugins\local\blackgoat-agentskills" -Target "<repo>"
```

### Recommended: real directory + hardlinks (Windows, same volume)

Keeps one authoritative checkout (this repo) while placing a Cursor-legal tree under `plugins/local`. File hardlinks share inode with the repo — edit either path, both see the change. New files need a re-run of the install script.

**PowerShell (Windows):**

```powershell
$repo  = "C:\Users\user\.claude\skills\blackgoat-agentskills"   # or your clone path
$local = "$env:USERPROFILE\.cursor\plugins\local\blackgoat-agentskills"

function Remove-Tree($path) {
  if (-not (Test-Path $path)) { return }
  $item = Get-Item $path -Force
  if ($item.LinkType -eq 'Junction' -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    cmd /c "rmdir `"$path`""
  } else {
    Remove-Item $path -Recurse -Force
  }
}

function Mirror-HardlinkTree($srcRoot, $dstRoot) {
  New-Item -ItemType Directory -Force -Path $dstRoot | Out-Null
  Get-ChildItem $srcRoot -Force | ForEach-Object {
    $dst = Join-Path $dstRoot $_.Name
    if ($_.PSIsContainer) { Mirror-HardlinkTree $_.FullName $dst }
    else { cmd /c "mklink /H `"$dst`" `"$($_.FullName)`"" | Out-Null }
  }
}

Remove-Tree $local
New-Item -ItemType Directory -Force -Path $local | Out-Null
Mirror-HardlinkTree (Join-Path $repo '.cursor-plugin') (Join-Path $local '.cursor-plugin')
Mirror-HardlinkTree (Join-Path $repo 'agents')         (Join-Path $local 'agents')
Mirror-HardlinkTree (Join-Path $repo 'skills')         (Join-Path $local 'skills')
Mirror-HardlinkTree (Join-Path $repo 'rules')          (Join-Path $local 'rules')
cmd /c "mklink /H `"$(Join-Path $local 'mcp.json')`" `"$(Join-Path $repo 'mcp.json')`""
# Do NOT hardlink/copy root plugin.json into local — that is Agent Plugins format (skills+MCP only).
```

**macOS / Linux** (same idea with hardlinks; replace `mklink /H` with `ln`):

```bash
REPO=/absolute/path/to/blackgoat-agentskills
LOCAL=~/.cursor/plugins/local/blackgoat-agentskills
rm -rf "$LOCAL"
mkdir -p "$LOCAL"
hardlink_tree() { # $1 src $2 dst
  mkdir -p "$2"
  for p in "$1"/* "$1"/.[!.]*; do
    [ -e "$p" ] || continue
    base=$(basename "$p")
    if [ -d "$p" ]; then hardlink_tree "$p" "$2/$base"
    else ln "$p" "$2/$base"
    fi
  done
}
hardlink_tree "$REPO/.cursor-plugin" "$LOCAL/.cursor-plugin"
hardlink_tree "$REPO/agents" "$LOCAL/agents"
hardlink_tree "$REPO/skills" "$LOCAL/skills"
hardlink_tree "$REPO/rules" "$LOCAL/rules"
ln "$REPO/mcp.json" "$LOCAL/mcp.json"
```

### Alternative: relocate the checkout under `plugins/local`

Move the git tree to `~/.cursor/plugins/local/blackgoat-agentskills` and junction Claude’s path *to* that location. Cursor then loads a normal directory; Claude Code still opens the old path. Use this if you prefer zero hardlink re-sync.

### After install

1. **Developer: Reload Window**
2. Confirm in **Output → Cursor Plugins** (or `Cursor Plugins.log`):
   - `loadUserLocalPlugins … (1 plugins loaded)` (not `0`)
   - **no** `symlink target … is outside …` warning for `blackgoat-agentskills`
3. Open **Customize** and confirm:
   - **Skills** — squad / `bgpdd-*` from the **plugin** (not only Claude-compat)
   - **Subagents / Agents** — Rex, Aria, Mason, … from `agents/`
   - **MCP** — chrome-devtools, playwright, linear, github from `mcp.json`
4. If GitHub MCP is enabled, set `GITHUB_PERSONAL_ACCESS_TOKEN` under **Plugins → Configure**.

## Claude Code (unchanged)

Leave the existing Claude checkout / Claude Marketplace (or local) install alone. `.claude-plugin/` and `.mcp.json` are untouched by the Cursor packaging files. Agents should still appear as `blackgoat-agentskills:*`.

Root `plugin.json` (`{"name":"blackgoat-agentskills"}`) is the Agent Plugins / hub stub — **skills + MCP only**. Cursor Agents require the Cursor Plugin format (`.cursor-plugin/plugin.json`). Keep root `plugin.json` for Claude/hub if needed; do not rely on it for squad agents in Cursor.

## Marketplace publish

1. Submit at [cursor.com/marketplace/publish](https://cursor.com/marketplace/publish) with this Git repo (manifest at `.cursor-plugin/plugin.json`).
2. After the listing is live, install from **Customize**.
3. **Remove** the local hardlink tree (`~/.cursor/plugins/local/blackgoat-agentskills`) so Cursor does not double-load the same plugin.

## Smoke checklist

| Check | Expected |
| --- | --- |
| `Cursor Plugins.log` | `1 plugins loaded`; no out-of-tree symlink rejection |
| Customize → Skills | Plugin skills, including `bgpdd-*` and `agent-squad` |
| Customize → Subagents | Squad personas from `agents/` |
| Customize → MCP | Four servers from root `mcp.json` when the plugin is enabled |
| `/bgpdd-lite` or "delegate to Mason" | Orchestrator reads `skills/agent-squad/*`; delegates via custom agent **name** |
| Claude Code | Still loads via `.claude-plugin`; no persona/skill body changes required |

## Out of scope notes

- Do not replace `AGENTS.md` (Antigravity). Cursor uses `rules/cursor-runtime.mdc` instead.
- Do not symlink the **plugin root** to a path outside `~/.cursor/plugins/local`.
- User-level `~/.cursor/agents/` is a separate surface (works without plugins); prefer the plugin install once local loading succeeds.
