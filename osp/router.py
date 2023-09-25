import logging
from typing import Sequence

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager, joinedload
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import Mount, Route

from quirck.auth.middleware import AdminMiddleware, AuthenticationMiddleware
from quirck.auth.model import User
from quirck.auth.oauth import OAuthException
from quirck.web.template import TemplateResponse

from osp import github, gspread
from osp.config import GITHUB_TEAM
from osp.form import PasswordLoginForm
from osp.model import Assignment, RepoStatus, Repository


logger = logging.getLogger(__name__)


async def list_assignments(request: Request) -> Response:
    session: AsyncSession = request.scope["db"]
    user: User = request.scope["user"]

    assignments = (await session.scalars(select(Assignment))).all()
    repositories = (await session.scalars(select(Repository).where(Repository.user_id == user.id))).all()

    context = [
        (
            assignment,
            next(
                (repo for repo in repositories if repo.assignment_id == assignment.id),
                None
            )
        )
        for assignment in assignments
    ]

    return TemplateResponse(
        request, "main.html",
        {"context": context}
    )


async def issue_github_auth(request: Request) -> Response:
    return await github.github_client.authorize_redirect(
        request,
        redirect_uri=str(request.url_for("osp:issue_process", id=request.path_params["id"])),
        scope="repo:invite"
    )


async def process_repo(session: AsyncSession, repository: Repository) -> None:
    try:
        await gspread.add_repo_link(repository)
        await github.clone_repo(repository.assignment.owner, repository.assignment.repo, repository.repo_name)

        await github.protect_branch(repository.assignment.owner, repository.repo_name, "master")

        repository.status = RepoStatus.FINISHED
        await session.commit()
    except:
        logger.exception("Could not clone repository")
        repository.status = RepoStatus.FAILED
        await session.commit()


async def issue_assignment(request: Request) -> Response:
    session: AsyncSession = request.scope["db"]
    user: User = request.scope["user"]

    assignment = (await session.scalars(select(Assignment).where(Assignment.id == request.path_params["id"]))).one_or_none()
    if assignment is None:
        raise HTTPException(404, "Задание не найдено")

    try:
        token: str = (await github.github_client.process_code_flow(
            request,
            redirect_uri=str(request.url_for("osp:issue_process", id=request.path_params["id"]))
        ))["access_token"]
    except (OAuthException, KeyError) as exc:
        logger.info("OAuth failed: %s: %s", type(exc), exc)
        raise HTTPException(403, "Не удалось войти в GitHub")
    
    try:
        login = await github.get_user_login(token)

        repo_name = f"{assignment.repo}-{user.id}"

        try:
            await github.create_repository(
                assignment.owner,
                repo_name
            )
        except github.RepoExistsError:
            # Just force push here.
            pass

        await github.add_team(
            assignment.owner,
            repo_name,
            GITHUB_TEAM,
            "maintain"
        )

        try:
            invitation = await github.add_collaborator(
                assignment.owner,
                repo_name,
                login,
                "push"
            )
        except github.AccountRestrictedError:
            raise HTTPException(
                403,
                "Ваш аккаунт ограничен на GitHub. Смените аккаунт и повторите попытку."
            )

        if invitation is not None:
            await github.accept_invitation(token, invitation["id"])

        await session.execute(
            insert(Repository)
                .values(
                    user_id=user.id,
                    assignment_id=assignment.id,
                    repo_name=repo_name
                )
                .on_conflict_do_update(
                    index_elements=[Repository.user_id, Repository.assignment_id],
                    set_={
                        Repository.status: RepoStatus.IN_PROGRESS
                    }
                )
        )

        await session.commit()

        repository = (await session.scalars(
            select(Repository)
                .where((Repository.user_id == user.id) & (Repository.assignment_id == assignment.id))
                .options(joinedload(Repository.assignment))
        )).one()
        
        return RedirectResponse(
            request.url_for("osp:main"),
            status_code=303,
            background=BackgroundTask(process_repo, session, repository)
        )
    except httpx.HTTPStatusError as exc:
        logger.exception("GitHub request failed: %s", exc.response.text)
        raise HTTPException(500, "Произошла ошибка на стороне GitHub")


async def sync_in_background(repositories: Sequence[Repository]) -> None:
    for repository in repositories:
        try:
            await github.clone_repo(repository.assignment.owner, repository.assignment.repo, repository.repo_name)
        except github.CloneError:
            logger.exception("Can't clone %s", repository.repo_name)


async def sync_assignment(request: Request) -> Response:
    session: AsyncSession = request.scope["db"]

    repositories = (await session.scalars(
        select(Repository).where(Repository.assignment_id == request.path_params["id"]).options(joinedload(Repository.assignment))
    )).all()

    return RedirectResponse(
        request.url_for("osp:main"),
        status_code=303,
        background=BackgroundTask(sync_in_background, repositories)
    )


async def github_webhook(request: Request) -> Response:
    session: AsyncSession = request.scope["db"]

    event = request.headers.get("X-GitHub-Event")
    if event != "pull_request_review":
        return PlainTextResponse("Unknown event")

    if not github.verify_signature(
        await request.body(),
        request.headers.get("X-Hub-Signature-256")
    ):
        return PlainTextResponse("Bad signature", status_code=403)

    payload = await request.json()

    try:
        state = payload["review"]["state"]
        owner = payload["repository"]["owner"]["login"]
        repo_name = payload["repository"]["name"]
        reviewer = payload["review"]["user"]["login"]
        comment = payload["review"]["body"]
        pr_number = payload["pull_request"]["number"]
        pr_branch = payload["pull_request"]["head"]["ref"]
    except KeyError:
        return PlainTextResponse("Invalid payload", status_code=400)
    
    repository = (await session.scalars(
        select(Repository)
        .join(Assignment, Repository.assignment_id == Assignment.id)
        .where((Repository.repo_name == repo_name) & (Assignment.owner == owner))
        .options(contains_eager(Repository.assignment))
    )).one_or_none()

    if repository is None:
        return PlainTextResponse("Unknown repository")

    if not await github.user_in_team(owner, GITHUB_TEAM, reviewer):
        return PlainTextResponse("Unknown reviewer")

    if state != "approved":
        return PlainTextResponse("No approval")

    try:
        bonus = int(comment)
    except ValueError:
        bonus = 0

    await gspread.add_score(repository, bonus)
    await github.close_pr(owner, repo_name, pr_number)
    await github.protect_branch(owner, repo_name, pr_branch)

    return PlainTextResponse("OK")


async def password_login(request: Request) -> Response:
    form = await PasswordLoginForm.from_formdata(request)

    if await form.validate_on_submit():
        request.session["user_id"] = form.login.data

        return RedirectResponse(request.url_for("osp:main"), status_code=303)

    return TemplateResponse(request, "password_login.html", {"form": form})


def get_mount():
    admin_mount = Mount(
        path="/admin",
        routes=[
            Route("/assignment/{id:int}/sync", sync_assignment, methods=["POST"], name="sync")
        ],
        middleware=[
            Middleware(AdminMiddleware)
        ],
        name="admin"
    )

    authenticated_mount = Mount(
        path="/",
        routes=[
            Route("/", list_assignments, name="main"),
            Route("/assignment/{id:int}", issue_github_auth, methods=["POST"], name="issue_start"),
            Route("/assignment/{id:int}/process", issue_assignment, name="issue_process"),
            admin_mount
        ],
        middleware=[
            Middleware(AuthenticationMiddleware)
        ]
    )
    return Mount(
        path="/",
        routes=[
            Route("/password-login", password_login, methods=["GET", "POST"], name="password_login"),
            Route("/github/webhook", github_webhook, methods=["POST"], name="github_webhook"),
            authenticated_mount,
        ],
        name="osp"
    )


__all__ = ["get_mount"]
