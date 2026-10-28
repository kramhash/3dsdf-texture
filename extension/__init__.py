"""Bake meshes into 3D signed distance field textures for Three.js and Godot."""

from . import ui


def register():
    ui.register()


def unregister():
    ui.unregister()
