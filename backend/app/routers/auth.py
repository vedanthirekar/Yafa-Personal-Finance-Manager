from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, schemas, security
from ..database import get_db
from ..services import demo_seed

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=schemas.TokenResponse)
def register(payload: schemas.RegisterRequest, db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.username == payload.username).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Username already registered")
    if db.query(models.User).filter(models.User.email == payload.email).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email already registered")

    user = models.User(
        username=payload.username,
        email=payload.email,
        name=payload.name,
        hashed_password=security.hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = security.create_access_token(user.username)
    return schemas.TokenResponse(access_token=token, username=user.username, name=user.name)


@router.post("/login", response_model=schemas.TokenResponse)
def login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == payload.username).first()
    if not user or not security.verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect username or password")

    token = security.create_access_token(user.username)
    return schemas.TokenResponse(access_token=token, username=user.username, name=user.name)


@router.post("/demo-login", response_model=schemas.TokenResponse)
def demo_login(db: Session = Depends(get_db)):
    """No credentials needed -- one-click "Try Demo" entry point. Wipes and
    reseeds the demo user's transactions on every call so each demo session
    starts pristine, regardless of what an earlier visitor added or deleted.
    """
    user = demo_seed.get_or_create_demo_user(db)
    demo_seed.reset_and_seed(db, user)

    token = security.create_access_token(user.username)
    return schemas.TokenResponse(access_token=token, username=user.username, name=user.name)


@router.get("/me", response_model=schemas.UserOut)
def me(current_user: models.User = Depends(security.get_current_user)):
    return current_user
