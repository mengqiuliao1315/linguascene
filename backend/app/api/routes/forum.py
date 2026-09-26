"""论坛：经验帖、点赞、评论。"""

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.storage import (
    AVATAR_EXTENSIONS,
    MAX_FORUM_IMAGE_BYTES,
    forum_image_path,
    save_forum_image,
)
from app.core.uploads import read_limited
from app.models.social import ForumComment
from app.models.user import User
from app.schemas.social import (
    CommentCreate,
    CommentOut,
    PostCardOut,
    PostCreate,
    PostDetailOut,
    PostPageOut,
    PostUpdate,
    PopularTag,
)
from app.services import social_service, wordbook_service

router = APIRouter(prefix="/api/forum", tags=["forum"])


@router.get("/posts", response_model=PostPageOut)
def list_posts(
    tag: str = "",
    q: str = "",
    sort: str = "new",
    offset: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PostPageOut:
    if sort not in social_service.POST_SORTS:
        sort = "new"
    limit = max(1, min(limit, 50))
    offset = max(0, offset)

    rows = social_service.list_posts(
        db, user, tag=tag, keyword=q, sort=sort, offset=offset, limit=limit
    )
    total = social_service.count_posts(db, tag=tag, keyword=q)
    return PostPageOut(
        items=[PostCardOut.model_validate(r) for r in rows],
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(rows) < total,
    )


@router.get("/tags", response_model=list[PopularTag])
def list_tags(
    limit: int = 12,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PopularTag]:
    """热门标签，供列表页快捷筛选。"""
    return [
        PopularTag.model_validate(row)
        for row in social_service.popular_tags(db, limit=max(1, min(limit, 30)))
    ]


@router.get("/images/{name}")
def serve_image(name: str) -> FileResponse:
    """论坛配图接口。

    与头像同理不校验登录：<img> 无法附带 Authorization 头，而帖子正文
    需要展示图片。文件名含时间戳与内容哈希，不可枚举。
    """
    path = forum_image_path(name)
    if not path:
        raise HTTPException(status_code=404, detail="图片不存在")
    media = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media)


@router.post("/images", status_code=status.HTTP_201_CREATED)
async def upload_image(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> dict:
    """发帖时上传配图，返回可直接写进 Markdown 的 URL。"""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in AVATAR_EXTENSIONS:
        raise HTTPException(status_code=400, detail="只支持 png/jpg/webp/gif 图片")
    raw = await read_limited(file, MAX_FORUM_IMAGE_BYTES, too_large="图片不能超过 5MB")
    if not raw:
        raise HTTPException(status_code=400, detail="文件为空")
    return {"url": save_forum_image(file.filename or f"image{suffix}", raw)}


@router.post("/posts", response_model=PostDetailOut, status_code=status.HTTP_201_CREATED)
def create_post(
    payload: PostCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PostDetailOut:
    post = social_service.create_post(db, user, payload)
    wordbook_service.award_contribution(
        db, user, wordbook_service.CONTRIBUTION_RULES["forum_post"],
        "forum_post", ref_type="forum_post", ref_id=post.id,
    )
    db.commit()
    return PostDetailOut.model_validate(social_service.post_detail(db, user, post))


@router.get("/posts/{post_id}", response_model=PostDetailOut)
def get_post(
    post_id: int,
    count_view: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PostDetailOut:
    # 列表页就地展开正文时传 count_view=false，避免把展开算成一次阅读
    post = social_service.get_post(db, user, post_id, count_view=count_view)
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")
    db.commit()
    return PostDetailOut.model_validate(social_service.post_detail(db, user, post))


@router.patch("/posts/{post_id}", response_model=PostDetailOut)
def update_post(
    post_id: int,
    payload: PostUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PostDetailOut:
    post = social_service.get_post(db, user, post_id, count_view=False)
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")
    if post.user_id != user.id and user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="只能编辑自己的帖子")

    social_service.update_post(db, post, payload)
    db.commit()
    return PostDetailOut.model_validate(social_service.post_detail(db, user, post))


@router.delete("/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(
    post_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    post = social_service.get_post(db, user, post_id, count_view=False)
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")
    if post.user_id != user.id and user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="只能删除自己的帖子")

    social_service.delete_post(db, post)
    db.commit()


@router.post("/posts/{post_id}/like")
def like_post(
    post_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    post = social_service.get_post(db, user, post_id, count_view=False)
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")

    liked = social_service.toggle_like(db, user, post)
    db.commit()
    return {"liked": liked, "like_count": post.like_count}


@router.post("/posts/{post_id}/pin", response_model=PostDetailOut)
def pin_post(
    post_id: int,
    pinned: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PostDetailOut:
    """置顶由管理员操作，避免首页被刷。"""
    if user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="需要管理员权限")

    post = social_service.get_post(db, user, post_id, count_view=False)
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")

    post.is_pinned = 1 if pinned else 0
    db.commit()
    return PostDetailOut.model_validate(social_service.post_detail(db, user, post))


@router.get("/posts/{post_id}/comments", response_model=list[CommentOut])
def list_comments(
    post_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CommentOut]:
    post = social_service.get_post(db, user, post_id, count_view=False)
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")
    return [
        CommentOut.model_validate(c)
        for c in social_service.list_comments(db, user, post_id)
    ]


@router.post(
    "/posts/{post_id}/comments",
    response_model=CommentOut,
    status_code=status.HTTP_201_CREATED,
)
def add_comment(
    post_id: int,
    payload: CommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CommentOut:
    post = social_service.get_post(db, user, post_id, count_view=False)
    if not post:
        raise HTTPException(status_code=404, detail="帖子不存在")

    comment = social_service.add_comment(db, user, post, payload.content)
    wordbook_service.award_contribution(
        db, user, wordbook_service.CONTRIBUTION_RULES["forum_reply"],
        "forum_reply", ref_type="forum_comment", ref_id=comment.id,
    )
    db.commit()
    return CommentOut.model_validate(
        {
            "id": comment.id,
            "content": comment.content,
            "author": social_service._author(db, user.id),
            "is_mine": True,
            "created_at": comment.created_at,
        }
    )


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    comment = db.get(ForumComment, comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="评论不存在")
    if comment.user_id != user.id and user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="只能删除自己的评论")

    social_service.delete_comment(db, comment)
    db.commit()
