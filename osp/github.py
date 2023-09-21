import asyncio
import hmac
import tempfile
from typing import Any

import httpx

from quirck.auth.oauth import StaticOAuthConfiguration, OAuthClient

from osp.config import GITHUB_BOT_TOKEN, GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, GITHUB_WEBHOOK_SECRET


BASE_URL = "https://api.github.com"

github_configuration = StaticOAuthConfiguration(
    "https://github.com/login/oauth/access_token",
    "https://github.com/login/oauth/authorize",
    "github"
)

github_client = OAuthClient(
    configuration=github_configuration,
    client_id=GITHUB_CLIENT_ID,
    client_secret=str(GITHUB_CLIENT_SECRET)
)

api_client = httpx.AsyncClient(headers={
    "Accept": "application/vnd.github.v3+json"
})

import logging
logging.basicConfig(level="DEBUG")


class GithubError(Exception):
    def __init__(self, response: httpx.Response, *args):
        self.response = response
        super().__init__(*args)


class RepoExistsError(GithubError): ...

class AccountRestrictedError(GithubError): ...

class CloneError(Exception): ...


async def get_user_login(token: str) -> str:
    response = await api_client.get(
        f"{BASE_URL}/user",
        headers={
            "Authorization": f"token {token}"
        }
    )

    response.raise_for_status()

    return response.json()["login"]


async def create_repository(owner: str, repo: str) -> None:
    response = await api_client.post(
        f"{BASE_URL}/orgs/{owner}/repos",
        headers={
            "Authorization": f"token {GITHUB_BOT_TOKEN}"
        },
        json={
            "name": repo,
            "visibility": "private",
            "has_issues": False,
            "has_wiki": False,
            "has_downloads": False
        }
    )

    if response.status_code == 422 and any(
        error["message"] == "name already exists on this account"
        for error in response.json()["errors"]
    ):
        raise RepoExistsError(response)

    response.raise_for_status()


async def add_team(owner: str, repo: str, team: str, role: str) -> None:
    response = await api_client.put(
        f"{BASE_URL}/orgs/{owner}/teams/{team}/repos/{owner}/{repo}",
        headers={
            "Authorization": f"token {GITHUB_BOT_TOKEN}"
        },
        json={
            "permission": role
        }
    )

    response.raise_for_status()


async def add_collaborator(owner: str, repo: str, login: str, permission: str) -> dict[str, Any] | None:
    retries = 0

    while True:
        response = await api_client.put(
            f"{BASE_URL}/repos/{owner}/{repo}/collaborators/{login}",
            headers={
                "Authorization": f"token {GITHUB_BOT_TOKEN}"
            },
            json={
                "permission": "push"
            }
        )

        if response.status_code != 404:
            break

        if retries == 3:
            response.raise_for_status()
        
        await asyncio.sleep(0.3 * retries)
        retries += 1
    
    if response.status_code == 422 and any(
        error["message"] == "User could not be added"
        for error in response.json()["errors"]
    ):
        raise AccountRestrictedError(response)
    
    response.raise_for_status()

    if response.status_code == 204:
        return None

    return response.json()
            

async def accept_invitation(token: str, invitation_id: str) -> None:
    response = await api_client.patch(
        f"{BASE_URL}/user/repository_invitations/{invitation_id}",
        headers={
            "Authorization": f"token {token}"
        }
    )

    response.raise_for_status()


async def protect_branch(owner: str, repo: str, branch: str) -> None:
    response = await api_client.put(
        f"{BASE_URL}/repos/{owner}/{repo}/branches/{branch}/protection",
        headers={
            "Authorization": f"token {GITHUB_BOT_TOKEN}"
        },
        json={
            "required_pull_request_reviews": {
                "required_approving_review_count": 1
            },
            "required_status_checks": None,
            "enforce_admins": None,
            "restrictions": {
                "users": [],
                "teams": ["os"]
            }
        }
    )

    response.raise_for_status()


async def user_in_team(org: str, team_name: str, username: str) -> bool:
    response = await api_client.get(
        f"{BASE_URL}/orgs/{org}/teams/{team_name}/memberships/{username}",
        headers={
            "Authorization": f"token {GITHUB_BOT_TOKEN}"
        }
    )

    if response.status_code == 404:
        return False
    
    response.raise_for_status()

    return response.json()["state"] == "active"


async def close_pr(owner: str, repo: str, pr_number: int) -> None:
    response = await api_client.patch(
        f"{BASE_URL}/repos/{owner}/{repo}/pulls/{pr_number}",
        headers={
            "Authorization": f"token {GITHUB_BOT_TOKEN}"
        },
        json={
            "state": "closed"
        }
    )

    response.raise_for_status()


async def clone_repo(owner: str, source_repo: str, target_repo: str) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        process = await asyncio.create_subprocess_exec(
            "git", "clone", f"https://{GITHUB_BOT_TOKEN}@github.com/{owner}/{source_repo}.git", "repo",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=None,
            stderr=None,
            cwd=temp_dir
        )

        try:
            await asyncio.wait_for(process.wait(), timeout=30)
        except TimeoutError:
            process.kill()
            raise CloneError("git clone timed out")

        if process.returncode != 0:
            raise CloneError(f"git clone failed with code {process.returncode}")

        process = await asyncio.create_subprocess_exec(
            "git", "remote", "set-url", "origin", f"https://{GITHUB_BOT_TOKEN}@github.com/{owner}/{target_repo}.git",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=None,
            stderr=None,
            cwd=f"{temp_dir}/repo"
        )

        await process.wait()

        if process.returncode != 0:
            raise CloneError(f"git remote set-url failed with code {process.returncode}")

        process = await asyncio.create_subprocess_exec(
            "git", "push", "-f", "origin", "master",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=None,
            stderr=None,
            cwd=f"{temp_dir}/repo"
        )

        try:
            await asyncio.wait_for(process.wait(), timeout=30)
        except TimeoutError:
            process.kill()
            raise CloneError("git push timed out")
        
        if process.returncode != 0:
            raise CloneError(f"git push failed with code {process.returncode}")


SIGNATURE_256_PREFIX = "sha256="


def verify_signature(data: bytes, signature: str | None) -> bool:
    if signature is None or not signature.startswith(SIGNATURE_256_PREFIX):
        return False

    signature_hex = signature[len(SIGNATURE_256_PREFIX):]

    return hmac.compare_digest(
        signature_hex,
        hmac.new(
            str(GITHUB_WEBHOOK_SECRET).encode(),
            data,
            "sha256"
        ).hexdigest()
    )


__all__ = [
    "github_configuration", "github_client",
    "GithubError" , "RepoExistsError", "AccountRestrictedError",
    "get_user_login", "create_repository", "add_team", "add_collaborator",
    "accept_invitation", "protect_branch", "user_in_team", "close_pr",
    "clone_repo",
    "verify_signature"
]
