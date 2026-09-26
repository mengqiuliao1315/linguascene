from fastapi import HTTPException, UploadFile, status


async def read_limited(
    file: UploadFile | None,
    limit: int,
    *,
    too_large: str,
) -> bytes | None:
    if file is None:
        return None
    raw = await file.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=too_large)
    return raw
