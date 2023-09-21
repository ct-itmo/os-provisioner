from pathlib import Path

from osp.github import api_client
from osp.router import get_mount


static_path = Path(__file__).parent / "static"
template_path = Path(__file__).parent / "templates"
main_route = "osp:main"
mount = get_mount()
shutdown = api_client.aclose

__all__ = ["main_route", "mount", "static_path", "template_path"]
