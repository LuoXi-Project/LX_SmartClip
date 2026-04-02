from pydantic import BaseModel

class ConfigUpdate(BaseModel):
    key: str
    value: str


class ModelsRequest(BaseModel):
    base_url: str
    api_key: str

