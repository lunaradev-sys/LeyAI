from pydantic import BaseModel


class AnalisisLey(BaseModel):
    pais: str
    tema: str
    articulos_clave: list[str]