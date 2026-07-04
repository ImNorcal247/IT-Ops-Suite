from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from console.deps import get_policy_collection, require_user_api
from modules.policy_qa import query_policies

router = APIRouter(prefix="/api", tags=["policy-qa"])


class PolicyQABody(BaseModel):
    question: str


@router.post("/policy-qa")
def policy_qa(body: PolicyQABody, user=Depends(require_user_api), collection=Depends(get_policy_collection)):
    if collection is None:
        raise HTTPException(status_code=503, detail="No policy documents found in docs/policies/.")
    try:
        return query_policies(collection, body.question)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Policy lookup failed: {e}")
