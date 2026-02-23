from fastapi import Header, HTTPException
from app.core.security import decode_token

def get_current_tenant(authorization: str = Header(...)):
    token = authorization.replace("Bearer ", "")
    payload = decode_token(token)

    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="Tenant ID missing")

    return payload