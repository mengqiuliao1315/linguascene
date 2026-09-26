from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.social import (
    ChatMessageCreate,
    ChatMessageOut,
    ChatThreadOut,
    FriendOut,
    FriendRequestOut,
    FriendStatusOut,
)
from app.services import social_service

router = APIRouter(prefix="/api", tags=["friends"])


@router.get("/friends", response_model=list[FriendOut])
def list_friends(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[FriendOut]:
    return [FriendOut.model_validate(f) for f in social_service.list_friends(db, user)]


@router.get("/friends/requests")
def list_requests(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    incoming, outgoing = social_service.list_friend_requests(db, user)
    return {
        "incoming": [FriendRequestOut.model_validate(r) for r in incoming],
        "outgoing": [FriendRequestOut.model_validate(r) for r in outgoing],
    }


@router.get("/friends/status/{user_id}", response_model=FriendStatusOut)
def friend_status(
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FriendStatusOut:
    return FriendStatusOut.model_validate(social_service.friend_state(db, user, user_id))


@router.post("/friends/{user_id}", response_model=FriendStatusOut)
def add_friend(
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FriendStatusOut:
    try:
        social_service.request_friend(db, user, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return FriendStatusOut.model_validate(social_service.friend_state(db, user, user_id))


@router.post(
    "/friends/requests/{friendship_id}/accept", status_code=status.HTTP_204_NO_CONTENT
)
def accept_request(
    friendship_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    try:
        social_service.respond_friend(db, user, friendship_id, accept=True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()


@router.post(
    "/friends/requests/{friendship_id}/decline", status_code=status.HTTP_204_NO_CONTENT
)
def decline_request(
    friendship_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    try:
        social_service.respond_friend(db, user, friendship_id, accept=False)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()


@router.delete("/friends/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_friend(
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    try:
        social_service.remove_friend(db, user, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()


@router.get("/chat/threads", response_model=list[ChatThreadOut])
def chat_threads(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ChatThreadOut]:
    return [
        ChatThreadOut.model_validate(t) for t in social_service.chat_threads(db, user)
    ]


@router.get("/chat/unread")
def unread(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return {"unread": social_service.unread_total(db, user)}


@router.get("/chat/{user_id}", response_model=list[ChatMessageOut])
def messages(
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ChatMessageOut]:
    try:
        rows = social_service.list_messages(db, user, user_id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    db.commit()

    return [
        ChatMessageOut.model_validate(
            {
                "id": row.id,
                "sender_id": row.sender_id,
                "recipient_id": row.recipient_id,
                "content": row.content,
                "created_at": row.created_at,
                "mine": row.sender_id == user.id,
            }
        )
        for row in rows
    ]


@router.post(
    "/chat/{user_id}", response_model=ChatMessageOut, status_code=status.HTTP_201_CREATED
)
def send(
    user_id: int,
    payload: ChatMessageCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ChatMessageOut:
    try:
        row = social_service.send_message(db, user, user_id, payload.content)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    db.commit()

    return ChatMessageOut.model_validate(
        {
            "id": row.id,
            "sender_id": row.sender_id,
            "recipient_id": row.recipient_id,
            "content": row.content,
            "created_at": row.created_at,
            "mine": True,
        }
    )
