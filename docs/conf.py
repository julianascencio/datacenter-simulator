"""Sphinx configuration; build the offline interactive lab alongside the gallery."""

import tomllib
from pathlib import Path

from sphinx_gallery.sorting import ExplicitOrder

from datacenter_simulator.analysis.engineering import export_engineering_study
from datacenter_simulator.cli import generate_reference

project = "Data Center Simulator"
author = "ASVA Consulting"
ROOT = Path(__file__).resolve().parents[1]
release = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
version = release
copyright = "2026, ASVA Consulting"
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.mathjax",
    "sphinx.ext.viewcode",
    "sphinx_gallery.gen_gallery",
]
html_theme = "pydata_sphinx_theme"
html_title = "Data Center Simulator"
html_show_sourcelink = False
html_theme_options = {
    "github_url": "https://github.com/julianascencio/datacenter-simulator",
    "use_edit_page_button": True,
    "show_toc_level": 2,
    "show_prev_next": False,
    "navbar_align": "left",
}
html_context = {
    "github_user": "julianascencio",
    "github_repo": "datacenter-simulator",
    "github_version": "main",
    "doc_path": "docs",
}
autosummary_generate = True
autodoc_typehints = "description"
autodoc_member_order = "bysource"
napoleon_google_docstring = True
napoleon_numpy_docstring = True
html_static_path = ["_static"]
html_css_files = ["datacenter.css"]
exclude_patterns = ["_build", "auto_examples"]
sphinx_gallery_conf = {
    "examples_dirs": str(ROOT / "examples"),
    "gallery_dirs": "gallery",
    "filename_pattern": r"plot_",
    "subsection_order": ExplicitOrder(
        [
            "../examples/methods",
            "../examples/connectors",
            "../examples/analysis",
        ]
    ),
    "within_subsection_order": "ExampleTitleSortKey",
    "download_all_examples": False,
    "abort_on_example_error": True,
    "remove_config_comments": True,
    "matplotlib_animations": False,
}
generate_reference(Path(__file__).parent / "_static" / "lab")

export_engineering_study(str(Path(__file__).parent / "_static" / "lab"))
