"""Sphinx configuration; build the offline interactive lab alongside the gallery."""

from pathlib import Path

from datacenter_simulator.cli import generate_reference

project = "Data Center Simulator"
author = "ASVA Consulting"
release = "0.1.0"
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.mathjax",
    "sphinx_gallery.gen_gallery",
]
html_theme = "pydata_sphinx_theme"
html_theme_options = {"github_url": "https://github.com/julianascencio/datacenter-simulator"}
html_static_path = ["_static"]
exclude_patterns = ["_build"]
sphinx_gallery_conf = {
    "examples_dirs": "../examples",
    "gallery_dirs": "auto_examples",
    "filename_pattern": r"plot_",
    "download_all_examples": True,
    "abort_on_example_error": True,
    "remove_config_comments": True,
}
generate_reference(Path(__file__).parent / "_static" / "lab")
