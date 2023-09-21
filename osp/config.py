from starlette.datastructures import Secret

from quirck.core.config import config

GITHUB_BOT_TOKEN = config("GITHUB_BOT_TOKEN", cast=Secret)
GITHUB_CLIENT_ID = config("GITHUB_CLIENT_ID", cast=str)
GITHUB_CLIENT_SECRET = config("GITHUB_CLIENT_SECRET", cast=Secret)
GITHUB_TEAM = config("GITHUB_TEAM", cast=str)

GSPREAD_CREDS_FILE = config("GSPREAD_CREDS_FILE", cast=str)
GSPREAD_SPREADSHEET = config("GSPREAD_SPREADSHEET", cast=str)
GSPREAD_WS_GID = config("GSPREAD_WS_GID", cast=int)
