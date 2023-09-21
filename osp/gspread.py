import asyncio
import logging

import gspread_asyncio
from gspread.worksheet import ValueRange
from google.oauth2.service_account import Credentials

from osp.config import GSPREAD_CREDS_FILE, GSPREAD_SPREADSHEET, GSPREAD_WS_GID
from osp.model import Repository

logger = logging.getLogger(__name__)


def get_creds():
    creds = Credentials.from_service_account_file(GSPREAD_CREDS_FILE)
    scoped = creds.with_scopes([
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ])
    return scoped


agcm = gspread_asyncio.AsyncioGspreadClientManager(get_creds)


async def update_repo(repository: Repository) -> None:
    # The first task goes to H, second to K, ...
    target_column = 5 + repository.assignment.order * 3

    agc = await agcm.authorize()

    spreadsheet = await agc.open_by_key(GSPREAD_SPREADSHEET)
    worksheet = await spreadsheet.get_worksheet_by_id(GSPREAD_WS_GID)

    users, = await worksheet.get("A:A", major_dimension="COLUMNS")

    try:
        row = users.index(str(repository.user_id)) + 1
    except ValueError:
        logger.info("User not found in spreadsheet: %s", repository.user_id)
        return

    await worksheet.update_cell(
        row, target_column,
        f"""=HYPERLINK("https://github.com/{repository.assignment.owner}/{repository.repo_name}/pulls"; "PR")"""
    )
