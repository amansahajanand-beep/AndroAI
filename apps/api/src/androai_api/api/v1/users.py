from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from ...db import get_db
from ...deps import AuthContext, current_auth
from ...models import User
from ...schemas import UserOut, UserPatchIn
from ...services import auth as auth_svc
from ...services import rbac

router = APIRouter(tags=["users"])


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id, email=user.email, display_name=user.display_name, is_active=user.is_active,
        email_verified=user.email_verified_at is not None, roles=sorted(r.name for r in user.roles),
        permissions=sorted(rbac.permissions_of(user.roles)), created_at=user.created_at,
    )


@router.get("/me", response_model=UserOut)
def me(ctx: AuthContext = Depends(current_auth)):
    return user_out(ctx.user)


@router.patch("/me", response_model=UserOut)
def update_me(body: UserPatchIn, ctx: AuthContext = Depends(current_auth), db: Session = Depends(get_db)):
    if "display_name" in body.model_fields_set:
        ctx.user.display_name = (body.display_name or "").strip() or None
    db.commit()
    return user_out(ctx.user)


@router.post("/me/logout-all", status_code=204)
def logout_all(ctx: AuthContext = Depends(current_auth), db: Session = Depends(get_db)) -> Response:
    auth_svc.revoke_all_sessions(db, ctx.user_id)
    db.commit()
    return Response(status_code=204)
