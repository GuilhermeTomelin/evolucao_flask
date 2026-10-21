#CONTEM OS MODELOS QUE REPRESENTAM AS ENTIDADES DO BANCO
#BOOK REPRESENTA A ENTIDADE BOOK

from uuid import uuid4

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import UUID

from db import db

