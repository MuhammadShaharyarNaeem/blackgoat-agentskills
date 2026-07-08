---
name: godot-gdscript-patterns
description: "Master Godot 4 GDScript patterns including signals, scenes, state machines, and optimization. Use when building Godot games, implementing game systems, or learning GDScript best practices."
risk: safe
source: community
date_added: "2026-02-27"
---

# Godot GDScript Patterns

Production patterns for Godot 4.x game development with GDScript, covering architecture, signals, scenes, and optimization.

## Use this skill when

- Building games with Godot 4
- Implementing game systems in GDScript
- Designing scene architecture
- Managing game state
- Optimizing GDScript performance
- Learning Godot best practices

## Do not use this skill when

- The task is unrelated to godot gdscript patterns
- You need a different domain or tool outside this scope

## Instructions

- Clarify goals, constraints, and required inputs.
- Apply relevant best practices and validate outcomes.
- Provide actionable steps and verification.
- If detailed examples are required, open `resources/implementation-playbook.md`.

## Resources

- `resources/implementation-playbook.md` for detailed patterns and examples.

## Limitations
- Use this skill only when the task clearly matches the scope described above.
- Do not treat the output as a substitute for environment-specific validation, testing, or expert review.
- Stop and ask for clarification if required inputs, permissions, safety boundaries, or success criteria are missing.

## Procedural Memories (Learned Lessons)

- **[2026-06-27] (Object Pool Invalidation & Dangling Pointers):** When returning a node to a pool, always call `remove_child()` if it has a parent to avoid parent-hierarchy bugs. Guard all pop loops with `is_instance_valid(node)` to filter out nodes freed externally or automatically by Godot.
- **[2026-06-27] (Ghost Processing):** Components inside pooled nodes must check parent activity (e.g. `if not parent.get("is_active"): return`) at the start of process/physics ticks to prevent background processing of inactive entities.
- **[2026-06-27] (Safe I/O Overwrite Guard):** If loading save files fails (corrupt JSON, decryption errors), immediately set a `save_failed_no_overwrite` flag to `true`. Block all subsequent `save_game()` attempts to prevent overwriting the user's corrupt save with a blank default template.
- **[2026-06-27] (Atomic Two-Step Write):** When writing save state, always write first to a temporary file (`.tmp`), verify it exists, move the old save to a backup (`.bak`), and finally rename the `.tmp` to the target path.
- **[2026-06-27] (Device-Unique Encryption Keys):** Never hardcode static passwords or keys in code. Construct keys dynamically at runtime using `OS.get_unique_id()` concatenated with a static salt and MD5 hashed. Provide a secure fallback key string if `get_unique_id()` returns empty.
- **[2026-06-28] (UI Navigation Orchestration):** When implementing persistent navigation systems (e.g. bottom Navigation Bars, tab bars), always implement the top-level MainScreen/MainMenu UI orchestration container that manages and coordinates the visibility of the sub-screen panels (Dashboard, Map, Upgrades, Shop) in response to navigation events. Do not deploy loose panels without a central container.
