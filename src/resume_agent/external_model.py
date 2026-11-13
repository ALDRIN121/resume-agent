"""Lookup index for checkpoint-owned external model requests."""
from uuid import uuid4

from .contracts import ModelRequest, utc_now
from .run_store import Conflict


class ExternalModelPauseError(BaseException):
    """Control flow, not provider failure; broad model exception handlers skip it."""
    def __init__(self, request: ModelRequest):
        self.request = request
        super().__init__('external_model_response_required')


def register_request(context, key, preferred_id=None):
    store = context.control.store
    with store.connection(immediate=True) as conn:
        conn.execute('INSERT OR IGNORE INTO external_model_requests VALUES (?,?,?,?,?,?)',
            (preferred_id or str(uuid4()), context.owner_kind, context.owner_id, key, key, utc_now()))
        row = conn.execute('SELECT * FROM external_model_requests WHERE owner_kind=? AND owner_id=? AND task_key=?',
                           (context.owner_kind, context.owner_id, key)).fetchone()
        if row is None or row['input_hash'] != key or (preferred_id and row['request_id'] != preferred_id):
            raise Conflict('external_task_identity_conflict')
        return row['request_id']


def request_owner(store, request_id):
    with store.connection() as conn:
        row = conn.execute('SELECT owner_kind,owner_id FROM external_model_requests WHERE request_id=?', (request_id,)).fetchone()
        if row is None:
            raise KeyError(request_id)
        return row['owner_kind'], row['owner_id']
