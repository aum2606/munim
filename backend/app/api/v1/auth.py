from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response, status

from app.core.deps import SessionDep, SettingsDep
from app.core.errors import UnauthorizedError
from app.core.ratelimit import limited
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.services.auth import AuthService, IssuedTokens
from app.services.password_reset import request_reset, reset_password

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "munim_refresh"
COOKIE_PATH = "/api/v1/auth"


def _respond(response: Response, tokens: IssuedTokens, settings: SettingsDep) -> TokenResponse:
    # The refresh token lives only in an httpOnly, SameSite=Strict cookie scoped to /auth, so
    # page JavaScript (XSS) can't read it and other sites can't make the browser send it.
    response.set_cookie(
        COOKIE_NAME,
        tokens.refresh_token,
        max_age=settings.refresh_token_days * 86400,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
        path=COOKIE_PATH,
    )
    return TokenResponse(access_token=tokens.access_token, expires_in=tokens.expires_in)


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limited("register"))],
)
async def register(
    body: RegisterRequest, response: Response, session: SessionDep, settings: SettingsDep
) -> TokenResponse:
    return _respond(response, await AuthService(session, settings).register(body), settings)


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(limited("login"))])
async def login(
    body: LoginRequest, response: Response, session: SessionDep, settings: SettingsDep
) -> TokenResponse:
    tokens = await AuthService(session, settings).login(body.email, body.password)
    return _respond(response, tokens, settings)


@router.post("/refresh", response_model=TokenResponse, dependencies=[Depends(limited("refresh"))])
async def refresh(
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    munim_refresh: Annotated[str | None, Cookie()] = None,
) -> TokenResponse:
    if munim_refresh is None:
        raise UnauthorizedError("Not authenticated")
    return _respond(response, await AuthService(session, settings).refresh(munim_refresh), settings)


@router.post(
    "/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(limited("forgot_password"))],
)
async def forgot_password(
    body: ForgotPasswordRequest, session: SessionDep, settings: SettingsDep
) -> dict[str, str]:
    await request_reset(session, settings, body.email)
    return {"detail": "If that address has an account, a reset link is on its way."}


@router.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(limited("reset_password"))],
)
async def reset_password_with_link(body: ResetPasswordRequest, session: SessionDep) -> None:
    await reset_password(session, body.token, body.password)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    munim_refresh: Annotated[str | None, Cookie()] = None,
) -> None:
    if munim_refresh is not None:
        await AuthService(session, settings).logout(munim_refresh)
    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH)
