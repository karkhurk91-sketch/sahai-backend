from pydantic import BaseModel
from typing import Optional

class IncomingMessage(BaseModel):
    from_number: str
    text: str
    timestamp: int

class OutgoingMessage(BaseModel):
    to_number: str
    text: str
