"""Agent Skills: installed list, marketplace, and installers (paste/URL/GitHub)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import Auth, DB, get_project
from app.core.audit import record
from app.skills import manager as skills

router = APIRouter(tags=["skills"])


async def _workspace(db: DB, project_id: str) -> str:
    project = await get_project(db, project_id)
    return project.workspace_path


@router.get("/projects/{project_id}/skills")
async def list_skills(project_id: str, db: DB, _: Auth):
    workspace = await _workspace(db, project_id)
    return [s.to_dict() for s in skills.discover_skills(workspace)]


@router.get("/projects/{project_id}/skills/{name}")
async def get_skill(project_id: str, name: str, db: DB, _: Auth):
    workspace = await _workspace(db, project_id)
    return skills.read_skill(workspace, name)


@router.patch("/projects/{project_id}/skills/{name}")
async def toggle_skill(project_id: str, name: str, body: dict, db: DB, _: Auth):
    workspace = await _workspace(db, project_id)
    enabled = bool(body.get("enabled", True))
    return skills.set_skill_enabled(workspace, name, enabled).to_dict()


@router.delete("/projects/{project_id}/skills/{name}")
async def remove_skill(project_id: str, name: str, db: DB, auth: Auth):
    workspace = await _workspace(db, project_id)
    skills.delete_skill(workspace, name)
    await record(db, "skill.delete", {"project_id": project_id, "name": name}, actor=auth)
    return {"deleted": name}


class PasteIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1)
    hint: str = ""


@router.post("/projects/{project_id}/skills/paste", status_code=201)
async def install_paste(project_id: str, body: PasteIn, db: DB, auth: Auth):
    workspace = await _workspace(db, project_id)
    skill = skills.install_from_paste(workspace, body.name, body.content, body.hint)
    await record(db, "skill.install", {"project_id": project_id, "name": skill.name, "via": "paste"}, actor=auth)
    return skill.to_dict()


class UrlIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


@router.post("/projects/{project_id}/skills/from-url", status_code=201)
async def install_url(project_id: str, body: UrlIn, db: DB, auth: Auth):
    workspace = await _workspace(db, project_id)
    installed = skills.install_from_url(workspace, body.url)
    await record(
        db, "skill.install",
        {"project_id": project_id, "names": [s.name for s in installed], "via": "url"},
        actor=auth,
    )
    return [s.to_dict() for s in installed]


class GithubIn(BaseModel):
    repo: str = Field(min_length=3, max_length=200, description="owner/repo[@ref][/subpath]")
    only: list[str] = Field(default_factory=list, description="Install just these paths/names")


@router.post("/projects/{project_id}/skills/scan")
async def scan_github(project_id: str, body: GithubIn, db: DB, _: Auth):
    await _workspace(db, project_id)
    return skills.browse_github_repo(body.repo)


@router.post("/projects/{project_id}/skills/from-github", status_code=201)
async def install_github(project_id: str, body: GithubIn, db: DB, auth: Auth):
    workspace = await _workspace(db, project_id)
    installed = skills.install_from_github(workspace, body.repo, body.only or None)
    await record(
        db, "skill.install",
        {"project_id": project_id, "names": [s.name for s in installed], "via": "github"},
        actor=auth,
    )
    return [s.to_dict() for s in installed]


@router.get("/skills/marketplace")
async def marketplace(_: Auth, q: str = ""):
    return skills.marketplace_live(q)


class MarketplaceIn(BaseModel):
    project_id: str
    skill_id: str


@router.post("/skills/marketplace/install", status_code=201)
async def install_marketplace(body: MarketplaceIn, db: DB, auth: Auth):
    workspace = await _workspace(db, body.project_id)
    skill = skills.install_from_marketplace(workspace, body.skill_id)
    await record(
        db, "skill.install",
        {"project_id": body.project_id, "name": skill.name, "via": "marketplace"},
        actor=auth,
    )
    return skill.to_dict()
