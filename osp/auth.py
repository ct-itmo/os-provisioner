from typing import Any

from osp import gspread


def check_user_exists(user_info: dict[str, Any]) -> bool:
    return gspread.user_exists(user_info["id"])


__all__ = ["check_user_exists"]
