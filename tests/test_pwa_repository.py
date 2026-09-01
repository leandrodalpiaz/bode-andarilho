from types import SimpleNamespace

from src.pwa.repository import SupabaseRepository


class Query:
    def __init__(self, row):
        self.row = row

    def select(self, *_args):
        return self

    def eq(self, *_args):
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        return SimpleNamespace(data=[self.row] if self.row else [], error=None)


def repository_for_public_event(store):
    event = {
        "id": 10,
        "loja_id": 1,
        "status": "published",
        "visibilidade": "public",
        "public_token_hash": "token-hash",
    }
    repository = object.__new__(SupabaseRepository)
    repository._table = lambda _table: Query(event)
    repository.get_store = lambda _store_id: store
    return repository


def test_public_event_is_hidden_when_its_store_is_archived():
    repository = repository_for_public_event({"id": 1, "status": "archived"})

    assert repository.get_public_event("token-hash") is None


def test_public_event_includes_only_an_active_store():
    repository = repository_for_public_event({"id": 1, "nome": "Loja Piloto", "status": "active"})

    event = repository.get_public_event("token-hash")

    assert event is not None
    assert event["loja"]["nome"] == "Loja Piloto"
