extends Node3D
## Keys: 1 = SDF only, 2 = mesh only, 3 = both.
## Capture from the command line:
##   godot --path . -- --mode=sdf --capture=/abs/path.png

@onready var model: Node3D = $Model
@onready var volume: MeshInstance3D = $SdfVolume
@onready var camera: Camera3D = $Camera3D


func _ready() -> void:
	camera.look_at_from_position(Vector3(1.3, 0.6, 3.6), Vector3.ZERO)
	var args := {}
	for a in OS.get_cmdline_user_args():
		var kv := a.trim_prefix("--").split("=", true, 1)
		args[kv[0]] = kv[1] if kv.size() > 1 else ""
	set_mode(args.get("mode", "both"))
	if args.has("capture"):
		_capture(args["capture"])


func set_mode(mode: String) -> void:
	model.visible = mode != "sdf"
	volume.visible = mode != "mesh"


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed:
		match event.keycode:
			KEY_1:
				set_mode("sdf")
			KEY_2:
				set_mode("mesh")
			KEY_3:
				set_mode("both")


func _capture(path: String) -> void:
	for i in 10:
		await get_tree().process_frame
	get_viewport().get_texture().get_image().save_png(path)
	get_tree().quit()
