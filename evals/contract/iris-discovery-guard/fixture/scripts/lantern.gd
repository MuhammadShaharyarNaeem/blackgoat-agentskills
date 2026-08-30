extends PointLight2D

## The lantern dims as the player stands still and recovers while moving -
## the game's core pressure mechanic.

const DIM_PER_SECOND := 0.08
const RECOVER_PER_SECOND := 0.20
const MIN_ENERGY := 0.15

func _process(delta: float) -> void:
	var body := get_parent() as CharacterBody2D
	if body and body.velocity.length() > 4.0:
		energy = minf(energy + RECOVER_PER_SECOND * delta, 1.0)
	else:
		energy = maxf(energy - DIM_PER_SECOND * delta, MIN_ENERGY)
