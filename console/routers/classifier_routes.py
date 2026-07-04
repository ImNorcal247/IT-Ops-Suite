from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from console.deps import require_user_api
from modules.incident_classifier import classify_incident

router = APIRouter(prefix="/api", tags=["classifier"])


class ClassifyBody(BaseModel):
    description: str
    context: str = ""


@router.post("/classify")
def classify(body: ClassifyBody, user=Depends(require_user_api)):
    try:
        return classify_incident(body.description, body.context)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Classification failed: {e}")
