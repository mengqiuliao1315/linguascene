"""有界读取上传文件，避免先把整份内容读进内存再检查大小。"""

from fastapi import HTTPException, UploadFile, status


async def read_limited(
    file: UploadFile | None,
    limit: int,
    *,
    too_large: str,
) -> bytes | None:
    """最多读 limit 字节；超出立刻 400，不把超大文件完整缓冲。"""
    if file is None:
        return None
    raw = await file.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=too_large)
    return raw
