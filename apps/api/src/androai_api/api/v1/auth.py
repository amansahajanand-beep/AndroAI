from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from sqlalchemy.orm import Session

from ...db import get_db
from ...deps import ACCESS_COOKIE, REFRESH_COOKIE, AuthContext, check_origin, current_auth
from ...errors import AppError
from ...mail import Mailer, get_mailer
from ...rate_limit import client_ip, hit, limit_by_ip
from ...config import get_settings
from ...schemas import (ChangePasswordIn, EmailTokenIn, ForgotPasswordIn, LoginIn, MessageOut,
                        RefreshIn, RegisterIn, ResetPasswordIn, TokenOut)
from ...services import auth as svc
from .users import user_out
from ...schemas import AuthOut, SessionOut, UserOut

router = APIRouter(tags=["auth"])
_ip_limit = Depends(limit_by_ip("auth"))


def _set_session_cookies(response: Response, pair: svc.TokenPair, *, remember: bool) -> None:
    """httpOnly cookies for the browser app (JS cannot read them). The refresh cookie is
    scoped to /api/v1/auth so it is only sent to the endpoints that need it."""
    s = get_settings()
    common = dict(httponly=True, secure=s.cookies_secure, samesite="lax", domain=s.cookie_domain)
    response.set_cookie(ACCESS_COOKIE, pair.access_token, max_age=s.jwt_access_ttl_minutes * 60, path="/", **common)
    response.set_cookie(REFRESH_COOKIE, pair.refresh_token, max_age=s.refresh_ttl_days * 86400 if remember else None,
                        path="/api/v1/auth", **common)


def _clear_session_cookies(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(ACCESS_COOKIE, path="/", domain=s.cookie_domain)
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth", domain=s.cookie_domain)


def _tokens(pair: svc.TokenPair) -> TokenOut:
    return TokenOut(access_token=pair.access_token, access_expires_at=pair.access_expires_at,
                    refresh_token=pair.refresh_token, refresh_expires_at=pair.refresh_expires_at)


@router.post("/register", response_model=UserOut, status_code=201, dependencies=[_ip_limit])
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db),
             mailer: Mailer = Depends(get_mailer)):
    user = svc.register(db, mailer, email=body.email, password=body.password,
                        display_name=body.display_name, ip=client_ip(request))
    return user_out(user)


@router.post("/login", response_model=AuthOut, dependencies=[_ip_limit])
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    # Per-account throttle blunts credential stuffing that rotates source IPs.
    hit("login_acct", svc.normalize_email(body.email), get_settings().rate_limit_login_per_account_per_minute)
    user, pair = svc.login(db, email=body.email, password=body.password,
                           user_agent=request.headers.get("user-agent"), ip=client_ip(request))
    check_origin(request, require=False)  # login CSRF: refuse a foreign Origin if one is sent
    _set_session_cookies(response, pair, remember=body.remember)
    return AuthOut(user=user_out(user), tokens=_tokens(pair))


@router.post("/refresh", response_model=TokenOut, dependencies=[_ip_limit])
def refresh(request: Request, response: Response, body: RefreshIn | None = None,
            cookie_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE), db: Session = Depends(get_db)):
    """Body token (API clients) or the httpOnly refresh cookie (browser). Rotates both."""
    token = body.refresh_token if body else cookie_token
    if not token:
        raise AppError(401, "invalid_refresh_token", "Session expired, please sign in again")
    if body is None:
        check_origin(request, require=True)  # cookie flow: CSRF check
    try:
        pair = svc.refresh(db, refresh_token=token, user_agent=request.headers.get("user-agent"), ip=client_ip(request))
    except AppError:
        if body is None:
            _clear_session_cookies(response)
        raise
    if body is None:
        _set_session_cookies(response, pair, remember=True)
    return _tokens(pair)


@router.post("/logout", status_code=204)
def logout(request: Request, body: RefreshIn | None = None,
           cookie_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE), db: Session = Depends(get_db)) -> Response:
    """Revokes the session (all tokens issued from the same login) and clears the cookies. Idempotent."""
    token = body.refresh_token if body else cookie_token
    if body is None and cookie_token:
        check_origin(request, require=True)
    if token:
        svc.logout_by_refresh_token(db, token)
    resp = Response(status_code=204)
    _clear_session_cookies(resp)
    return resp


@router.get("/session", response_model=SessionOut)
def session(ctx: AuthContext = Depends(current_auth)):
    """Who am I + when does the current access token expire (the web app polls this)."""
    return SessionOut(user=user_out(ctx.user), expires_at=ctx.expires_at)


@router.post("/verify-email", response_model=MessageOut, dependencies=[_ip_limit])
def verify_email(body: EmailTokenIn, db: Session = Depends(get_db)):
    svc.verify_email(db, body.token)
    return MessageOut(message="Email verified")


@router.post("/resend-verification", response_model=MessageOut, dependencies=[_ip_limit])
def resend_verification(ctx: AuthContext = Depends(current_auth), db: Session = Depends(get_db),
                        mailer: Mailer = Depends(get_mailer)):
    svc.resend_verification(db, mailer, ctx.user)
    return MessageOut(message="If your email is unverified, a new link has been sent")


@router.post("/forgot-password", response_model=MessageOut, status_code=202, dependencies=[_ip_limit])
def forgot_password(body: ForgotPasswordIn, request: Request, db: Session = Depends(get_db),
                    mailer: Mailer = Depends(get_mailer)):
    hit("forgot_acct", svc.normalize_email(body.email), 3)
    svc.request_password_reset(db, mailer, email=body.email, ip=client_ip(request))
    return MessageOut(message="If that account exists, a reset link has been sent")


@router.post("/reset-password", response_model=MessageOut, dependencies=[_ip_limit])
def reset_password(body: ResetPasswordIn, request: Request, db: Session = Depends(get_db)):
    svc.reset_password(db, token=body.token, new_password=body.new_password, ip=client_ip(request))
    return MessageOut(message="Password updated; please sign in")


@router.post("/change-password", response_model=MessageOut, status_code=status.HTTP_200_OK)
def change_password(body: ChangePasswordIn, ctx: AuthContext = Depends(current_auth),
                    db: Session = Depends(get_db)):
    if body.current_password == body.new_password:
        raise AppError(422, "weak_password", "New password must differ from the current one")
    svc.change_password(db, ctx.user, current=body.current_password, new=body.new_password,
                        keep_session_id=ctx.session_id)
    return MessageOut(message="Password changed; other sessions were signed out")
