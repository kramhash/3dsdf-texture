// Sphere-traces a baked SDF Texture3D inside a box mesh.
// The box is centered on the SDF bbox; marching happens in the SDF's local (Y-up) space.
// Godot lights and shadows the box fragment's VERTEX, not the marched point, so
// shadow lookups would land on the box; shadows are off for the volume.
shader_type spatial;
render_mode cull_front, depth_draw_always, shadows_disabled;

uniform sampler3D sdf : filter_linear, repeat_disable;
uniform vec3 bbox_min;
uniform vec3 bbox_max;
uniform float voxel_size;
// distance = sampled value * decode_scale + decode_offset (the sidecar's `decode`).
uniform float decode_scale = 1.0;
uniform float decode_offset = 0.0;
uniform vec3 albedo : source_color = vec3(0.8, 0.55, 0.35);

varying vec3 box_pos;
varying vec3 cam_box;

float sample_sdf(vec3 p) {
	vec3 uvw = (p - bbox_min) / (bbox_max - bbox_min);
	return texture(sdf, uvw).r * decode_scale + decode_offset;
}

vec3 sdf_normal(vec3 p) {
	vec2 e = vec2(voxel_size, 0.0);
	return normalize(vec3(
		sample_sdf(p + e.xyy) - sample_sdf(p - e.xyy),
		sample_sdf(p + e.yxy) - sample_sdf(p - e.yxy),
		sample_sdf(p + e.yyx) - sample_sdf(p - e.yyx)));
}

void vertex() {
	box_pos = VERTEX;
	cam_box = (inverse(MODEL_MATRIX) * vec4(CAMERA_POSITION_WORLD, 1.0)).xyz;
}

void fragment() {
	vec3 center = (bbox_min + bbox_max) * 0.5;
	vec3 ro = cam_box + center;
	vec3 rd = normalize(box_pos - cam_box);

	vec3 inv = 1.0 / rd;
	vec3 t0 = (bbox_min - ro) * inv;
	vec3 t1 = (bbox_max - ro) * inv;
	float t_near = max(max(min(t0.x, t1.x), min(t0.y, t1.y)), min(t0.z, t1.z));
	float t_far = min(min(max(t0.x, t1.x), max(t0.y, t1.y)), max(t0.z, t1.z));

	float t = max(t_near, 0.0);
	bool hit = false;
	for (int i = 0; i < 256 && t < t_far; i++) {
		float d = sample_sdf(ro + rd * t);
		if (d < voxel_size * 0.02) {
			hit = true;
			break;
		}
		t += max(d, voxel_size * 0.05);
	}
	if (!hit) {
		discard;
	}

	vec3 p = ro + rd * t;
	vec3 n = sdf_normal(p);
	NORMAL = normalize((VIEW_MATRIX * MODEL_MATRIX * vec4(n, 0.0)).xyz);
	ALBEDO = albedo;
	ROUGHNESS = 0.6;
	// Writing ALPHA moves this to the transparent pass, skipping the opaque depth
	// prepass. With the prepass, the prepass and color pass DEPTH values differ
	// slightly and the depth test drops random pixels (speckle).
	ALPHA = 1.0;

	vec4 clip = PROJECTION_MATRIX * VIEW_MATRIX * MODEL_MATRIX * vec4(p - center, 1.0);
	DEPTH = clip.z / clip.w;
}
