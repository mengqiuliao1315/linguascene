from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.pet import PetOut, UpdatePetRequest
from app.services import pet_service

router = APIRouter(prefix="/api/pet", tags=["pet"])


@router.get("", response_model=PetOut)
def get_pet(user: User = Depends(get_current_user)) -> PetOut:
    """只读：重复请求结果一致，可安全重放。

    连续陪伴天数按「今天已到访」投影，所以打开首页就能看到它见到你
    之后的样子；真正的落库在 /visit。
    """
    return PetOut.model_validate(pet_service.payload(user, pet_service.snapshot(user)))


@router.post("/visit", response_model=PetOut)
def visit_pet(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PetOut:
    """记录今天来看过宠物。幂等，同一天重复调用只算一次。"""
    pet_service.record_visit(db, user)
    db.commit()
    db.refresh(user)
    return PetOut.model_validate(pet_service.payload(user))


@router.patch("", response_model=PetOut)
def update_pet(
    payload: UpdatePetRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PetOut:
    if payload.species is not None:
        user.pet_species = pet_service.normalize_species(payload.species)
    if payload.name is not None:
        user.pet_name = payload.name.strip()[: pet_service.MAX_NAME_LENGTH]
    db.commit()
    db.refresh(user)
    return PetOut.model_validate(pet_service.payload(user))
