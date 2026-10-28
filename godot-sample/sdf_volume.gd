extends MeshInstance3D
## Builds a raymarched SDF volume from a `<name>.sdf.json` sidecar and lines it up
## with the mesh node of the same name under `model`.

@export_file("*.json") var sdf_json := "res://sdf/Suzanne.sdf.json"
@export var model: Node3D


func _ready() -> void:
	var meta: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(sdf_json))
	var bmin := _vec3(meta["bboxMin"])
	var bmax := _vec3(meta["bboxMax"])
	var image_path := sdf_json.get_base_dir().path_join(meta["files"]["godot"])

	var box := BoxMesh.new()
	box.size = bmax - bmin
	mesh = box

	var mat := ShaderMaterial.new()
	mat.shader = preload("res://sdf_raymarch.gdshader")
	mat.set_shader_parameter("sdf", load(image_path))
	mat.set_shader_parameter("bbox_min", bmin)
	mat.set_shader_parameter("bbox_max", bmax)
	mat.set_shader_parameter("voxel_size", float(meta["voxelSize"]))
	mat.set_shader_parameter("decode_scale", float(meta["decode"]["scale"]))
	mat.set_shader_parameter("decode_offset", float(meta["decode"]["offset"]))
	material_override = mat
	cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF

	# The SDF lives in the source mesh's local space; follow that node's transform.
	# source.object is the Blender name; the glTF importer makes it a valid node name.
	var node_name := String(meta["source"]["object"]).validate_node_name()
	var target := _find_mesh(model, node_name) if model else null
	if model and target == null:
		push_warning("no node named %s under %s; the volume stays at the origin" % [node_name, model.name])
	var base := target.global_transform if target else Transform3D.IDENTITY
	global_transform = base * Transform3D(Basis.IDENTITY, (bmin + bmax) * 0.5)


func _find_mesh(root: Node, mesh_name: String) -> Node3D:
	var found := root.find_child(mesh_name, true, false)
	return found as Node3D


func _vec3(a: Array) -> Vector3:
	return Vector3(a[0], a[1], a[2])
