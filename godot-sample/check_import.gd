extends SceneTree
## Import check: the slice atlas loads as a Texture3D whose size matches the sidecar
## and whose center voxel decodes to inside (negative). Needs a real renderer (not --headless)
## because the dummy renderer returns no texture data.

func _init() -> void:
	var meta: Dictionary = JSON.parse_string(FileAccess.get_file_as_string("res://sdf/Suzanne.sdf.json"))
	var tex := load("res://sdf/" + String(meta["files"]["godot"])) as Texture3D
	var dims: Array = meta["dims"]
	if tex == null:
		push_error("not a Texture3D")
		quit(1)
		return
	var size_ok := tex.get_width() == int(dims[0]) and tex.get_height() == int(dims[1]) and tex.get_depth() == int(dims[2])
	var layers: Array[Image] = tex.get_data()
	var mid: Image = layers[int(dims[2]) / 2]
	var scale := float(meta["decode"]["scale"])
	var offset := float(meta["decode"]["offset"])
	var center := mid.get_pixel(int(dims[0]) / 2, int(dims[1]) / 2).r * scale + offset
	var corner := mid.get_pixel(0, 0).r * scale + offset
	print("size %dx%dx%d format %d center %.4f corner %.4f" % [tex.get_width(), tex.get_height(), tex.get_depth(), tex.get_format(), center, corner])
	quit(0 if size_ok and center < 0.0 and corner > 0.0 else 1)
