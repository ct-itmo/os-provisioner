import datetime
import logging
import enum

import gspread_asyncio
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


class Column(enum.Enum):
    LINK = 1
    DATE = 2
    BONUS = 3


def get_column(order: int, column: Column):
    return 4 + order * 3 + column.value


async def get_worksheet() -> gspread_asyncio.AsyncioGspreadWorksheet:
    agc = await agcm.authorize()

    spreadsheet = await agc.open_by_key(GSPREAD_SPREADSHEET)
    return await spreadsheet.get_worksheet_by_id(GSPREAD_WS_GID)


async def get_row(worksheet: gspread_asyncio.AsyncioGspreadWorksheet, user_id: int) -> int | None:
    users, = await worksheet.get("A:A", major_dimension="COLUMNS")

    try:
        return users.index(str(user_id)) + 1
    except ValueError:
        logger.info("User not found in spreadsheet: %s", user_id)


async def add_repo_link(repository: Repository) -> None:
    worksheet = await get_worksheet()

    row = await get_row(worksheet, repository.user_id)
    if row == None:
        return

    column = get_column(repository.assignment.order, Column.LINK)
    
    await worksheet.update_cell(
        row, column,
        f"""=HYPERLINK("https://github.com/{repository.assignment.owner}/{repository.repo_name}/pulls"; "PR")"""
    )


async def add_score(repository: Repository, bonus: int) -> None:
    worksheet = await get_worksheet()

    row = await get_row(worksheet, repository.user_id)
    if row == None:
        return

    date_column = get_column(repository.assignment.order, Column.DATE)
    await worksheet.update_cell(row, date_column, datetime.date.today().strftime("%d.%m"))

    bonus_column = get_column(repository.assignment.order, Column.BONUS)
    await worksheet.update_cell(row, bonus_column, bonus)
