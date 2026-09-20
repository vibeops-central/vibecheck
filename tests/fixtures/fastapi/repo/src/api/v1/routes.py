from fastapi import APIRouter, Depends

router = APIRouter(prefix="/api/v1")


@router.get("/users")
async def list_users(service=Depends(lambda: None)):
    return await service.list()
