from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from console.auth import SESSION_COOKIE_NAME, create_session_token, verify_password
from console.db import get_connection
from console.templating import templates

router = APIRouter()


@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    finally:
        conn.close()

    if not row or not verify_password(password, row["password_hash"]):
        return templates.TemplateResponse(
            request, "login.html", {"error": "Incorrect email or password."}, status_code=401
        )

    token = create_session_token(row["id"], row["email"])
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(SESSION_COOKIE_NAME, token, httponly=True, samesite="lax", max_age=12 * 60 * 60)
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response
