from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

from console.deps import require_user_page
from console.templating import templates

router = APIRouter()


@router.get("/")
def root(user=Depends(require_user_page)):
    return RedirectResponse(url="/dashboard")


@router.get("/dashboard")
def dashboard_page(request: Request, user=Depends(require_user_page)):
    return templates.TemplateResponse(request, "dashboard.html", {
        "active": "dashboard", "header_title": "Ticket Dashboard",
        "header_status": "Data refreshed every 30s", "user": user,
    })


@router.get("/ask-data")
def ask_data_page(request: Request, user=Depends(require_user_page)):
    return templates.TemplateResponse(request, "ask_data.html", {
        "active": "ask-data", "header_title": "Ask Your Data",
        "header_status": "", "user": user, "narrow": True,
    })


@router.get("/policy-qa")
def policy_qa_page(request: Request, user=Depends(require_user_page)):
    return templates.TemplateResponse(request, "policy_qa.html", {
        "active": "policy-qa", "header_title": "Policy Q&A",
        "header_status": "", "user": user, "narrow": True,
    })


@router.get("/classifier")
def classifier_page(request: Request, user=Depends(require_user_page)):
    return templates.TemplateResponse(request, "classifier.html", {
        "active": "classifier", "header_title": "Incident Classifier",
        "header_status": "Few-shot structured output", "user": user, "narrow": True,
    })


@router.get("/orchestrator")
def orchestrator_page(request: Request, user=Depends(require_user_page)):
    return templates.TemplateResponse(request, "orchestrator.html", {
        "active": "orchestrator", "header_title": "Ticket Orchestrator",
        "header_status": "", "user": user, "narrow": True,
    })


@router.get("/settings")
def settings_page(request: Request, user=Depends(require_user_page)):
    return templates.TemplateResponse(request, "settings.html", {
        "active": "settings", "header_title": "Settings",
        "header_status": "Session-only — not written to disk", "user": user,
    })
