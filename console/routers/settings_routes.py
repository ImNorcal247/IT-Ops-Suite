from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from console.deps import get_sink_config, require_user_api
from modules.ticket_sinks import SinkConfig, test_clickup_connection, test_servicenow_connection

router = APIRouter(prefix="/api/settings", tags=["settings"])

CLICKUP_CATEGORIES = ["Application", "Network", "Hardware", "Access", "Database", "Security"]


class SettingsBody(BaseModel):
    mode: str
    dry_run: bool
    clickup_token: str = ""
    clickup_default_list: str = ""
    clickup_lists: dict = {}
    servicenow_instance: str = ""
    servicenow_username: str = ""
    servicenow_password: str = ""


class TestClickUpBody(BaseModel):
    token: str


class TestServiceNowBody(BaseModel):
    instance: str
    username: str
    password: str


@router.get("")
def get_settings(user=Depends(require_user_api), config: SinkConfig = Depends(get_sink_config)):
    return {
        "mode": config.mode,
        "dry_run": config.dry_run,
        "has_clickup_token": bool(config.clickup_token),
        "clickup_default_list": config.clickup_default_list,
        "clickup_lists": config.clickup_lists,
        "servicenow_instance": config.servicenow_instance,
        "servicenow_username": config.servicenow_username,
        "has_servicenow_password": bool(config.servicenow_password),
    }


@router.post("")
def save_settings(body: SettingsBody, request: Request, user=Depends(require_user_api)):
    current: SinkConfig = request.app.state.sink_config
    new_config = SinkConfig(
        mode=body.mode,
        dry_run=body.dry_run,
        # Blank credential fields keep whatever was already saved, so
        # reopening Settings and clicking Save doesn't wipe out a token
        # that isn't re-typed every time.
        clickup_token=body.clickup_token or current.clickup_token,
        clickup_default_list=body.clickup_default_list or current.clickup_default_list,
        clickup_lists={**current.clickup_lists, **{k: v for k, v in body.clickup_lists.items() if v}},
        servicenow_instance=body.servicenow_instance or current.servicenow_instance,
        servicenow_username=body.servicenow_username or current.servicenow_username,
        servicenow_password=body.servicenow_password or current.servicenow_password,
    )
    request.app.state.sink_config = new_config
    return {"ok": True, "mode": new_config.mode, "dry_run": new_config.dry_run}


@router.post("/test-clickup")
def test_clickup(body: TestClickUpBody, user=Depends(require_user_api)):
    if not body.token:
        return {"ok": False, "message": "Enter an API token first."}
    ok, message = test_clickup_connection(body.token)
    return {"ok": ok, "message": message}


@router.post("/test-servicenow")
def test_servicenow(body: TestServiceNowBody, user=Depends(require_user_api)):
    if not (body.instance and body.username and body.password):
        return {"ok": False, "message": "Fill in instance, username, and password first."}
    ok, message = test_servicenow_connection(body.instance, body.username, body.password)
    return {"ok": ok, "message": message}
