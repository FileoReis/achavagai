from .base import Vaga
from .linkedin import buscar_vagas_linkedin
from .indeed import buscar_vagas_indeed
from .generic_wordpress import buscar_vagas_todos_wordpress
from .vagas_com import buscar_vagas_vagas_com
from .infojobs import buscar_vagas_infojobs
from .empregare import buscar_vagas_empregare
from .empregando_brasil import buscar_vagas_empregando_brasil
from .jooble import buscar_vagas_jooble
from .gupy import buscar_vagas_gupy

__all__ = [
    "Vaga",
    "buscar_vagas_linkedin",
    "buscar_vagas_indeed",
    "buscar_vagas_todos_wordpress",
    "buscar_vagas_vagas_com",
    "buscar_vagas_infojobs",
    "buscar_vagas_empregare",
    "buscar_vagas_empregando_brasil",
    "buscar_vagas_jooble",
    "buscar_vagas_gupy",
]
