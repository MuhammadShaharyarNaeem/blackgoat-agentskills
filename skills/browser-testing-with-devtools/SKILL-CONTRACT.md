---
name: browser-testing-with-devtools-contract
description: Condensed browser testing contract for workers using Chrome DevTools MCP.
---

# Browser Testing with DevTools — Worker Contract

## Core Principle

Use Chrome DevTools MCP to inspect, debug, and verify web application behavior with real browser data. Never trust assumptions — verify with actual runtime state.

## Available Tools

| Tool | Purpose |
|------|--------|
| `take_screenshot` | Visual verification of page state |
| `take_snapshot` | Get DOM accessibility tree (preferred for assertions) |
| `navigate_page` | Load a URL |
| `click` / `fill` / `type_text` | Interact with elements |
| `evaluate_script` | Run JavaScript in page context |
| `list_console_messages` | Check for runtime errors |
| `list_network_requests` | Verify API calls |
| `wait_for` | Wait for elements/conditions |

## Workflow

1. **NAVIGATE**: Use `navigate_page` to load the target URL.
2. **VERIFY LOAD**: Use `take_snapshot` to confirm the page loaded correctly. Check `list_console_messages` for errors.
3. **INTERACT**: Use `click`, `fill`, `type_text` to drive user flows.
4. **ASSERT**: Use `take_snapshot` for DOM state, `evaluate_script` for computed values, `list_network_requests` for API verification.
5. **DOCUMENT**: Take a `take_screenshot` of the final state for evidence.

## Rules

- Always check `list_console_messages` after page load — runtime errors indicate broken functionality.
- Never execute untrusted code via `evaluate_script` — only run your own verification scripts.
- Use `take_snapshot` (accessibility tree) over `take_screenshot` for assertions — it's deterministic and parseable.
- Verify network requests match expected API contracts using `list_network_requests`.

## Verification Checklist

- [ ] Page loads without console errors
- [ ] All interactive elements are accessible
- [ ] API calls return expected status codes and shapes
- [ ] Visual state matches requirements (screenshot captured)

## Escalate When

- Page returns 4xx/5xx on load → ask manager.
- Console shows unhandled errors on a clean page → ask manager.
- Network requests fail with CORS or auth errors → ask manager.
