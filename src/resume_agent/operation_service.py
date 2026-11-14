"""Private import/evaluation lifecycle; processing is supplied by later tasks."""
from __future__ import annotations

from collections.abc import AsyncIterator

from .contracts import Event, OperationAction, OperationRequest, OperationView
from .run_service import ActionValidator, Driver, _Lifecycle
from .run_store import RunStore


class OperationService:
    def __init__(self, store: RunStore, *, driver: Driver | None = None,
                 action_validator: ActionValidator | None = None):
        self.store = store
        self._lifecycle = _Lifecycle(store, "operation", driver, action_validator)

    def create(self, request: OperationRequest) -> OperationView:
        request = OperationRequest.model_validate(request.model_dump(mode="json"))
        owner_id = self.store.create_operation(request.kind, request.input)
        return self.get(owner_id)

    def get(self, operation_id: str) -> OperationView:
        return self._lifecycle.get(operation_id)

    async def drive(self, operation_id: str, action: OperationAction | None = None) -> OperationView:
        return await self._lifecycle.drive(operation_id, action)

    def cancel(self, operation_id: str) -> OperationView:
        return self._lifecycle.cancel(operation_id)

    def subscribe(self, operation_id: str) -> AsyncIterator[Event]:
        return self._lifecycle.subscribe(operation_id)
