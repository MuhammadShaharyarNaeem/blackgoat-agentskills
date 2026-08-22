extends CharacterBody2D

## Side-view platformer movement with coyote time.

const SPEED := 140.0
const JUMP_VELOCITY := -320.0
const COYOTE_FRAMES := 6

var _coyote := 0

func _physics_process(delta: float) -> void:
	if not is_on_floor():
		velocity += get_gravity() * delta
		_coyote = max(_coyote - 1, 0)
	else:
		_coyote = COYOTE_FRAMES

	if Input.is_action_just_pressed("jump") and _coyote > 0:
		velocity.y = JUMP_VELOCITY
		_coyote = 0

	var direction := Input.get_axis("move_left", "move_right")
	velocity.x = direction * SPEED
	move_and_slide()
