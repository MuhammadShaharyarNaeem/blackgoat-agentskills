# Global Context — Lantern Hollow

## Target Scope
- Repo: lantern-hollow (single repo)
- Branch: main
- Local path: .

## Tech Stack
- Godot 4.2, GL Compatibility renderer, GDScript throughout.
- 2D side-view platformer; 640x360 canvas, canvas_items stretch.

## Architecture Notes
- One main scene (`scenes/main.tscn`); player is a `CharacterBody2D` with
  coyote-time movement (`scripts/player.gd`).
- Core mechanic: the lantern (`PointLight2D`) dims when idle and recovers in
  motion (`scripts/lantern.gd`).

## Recorded
Discovery run of 2026-08-15, branch `main`. Curated - downstream agents rely
on this file's stability.
