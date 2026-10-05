from __future__ import annotations
from contextlib import contextmanager
from typing import Any, Iterator
import psycopg
from psycopg.rows import dict_row

class Database:
    def __init__(self, url: str): self._url = url
    @contextmanager
    def transaction(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self._url, row_factory=dict_row) as connection:
            with connection.transaction(): yield connection
    @contextmanager
    def cursor(self) -> Iterator[Any]:
        with psycopg.connect(self._url, row_factory=dict_row) as connection:
            with connection.cursor() as cursor: yield cursor
    def fetchone(self, query: str, params: tuple[Any, ...] = ()) -> Any:
        with self.cursor() as cursor:
            cursor.execute(query, params); return cursor.fetchone()
    def fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[Any]:
        with self.cursor() as cursor:
            cursor.execute(query, params); return cursor.fetchall()
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        with self.cursor() as cursor: cursor.execute(query, params)
