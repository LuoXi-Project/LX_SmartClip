from pydantic import BaseModel


class RenamePayload(BaseModel):
    name: str

