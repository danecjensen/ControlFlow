import abc
import datetime
import json
import math
from pathlib import Path
from typing import ClassVar

from litellm.utils import trim_messages
from pydantic import Field, field_validator

import controlflow
from controlflow.llm.messages import MessageType
from controlflow.utilities.types import ControlFlowModel


def get_default_history() -> "History":
    return controlflow.default_history


class History(ControlFlowModel, abc.ABC):
    @abc.abstractmethod
    def load_messages(
        self,
        thread_id: str,
        limit: int = None,
        before: datetime.datetime = None,
        after: datetime.datetime = None,
    ) -> list[MessageType]:
        raise NotImplementedError()

    def load_messages_to_token_limit(
        self, thread_id: str, model: str = None
    ) -> list[MessageType]:
        messages = []
        # as long as the messages are not trimmed, keep loading more
        while messages == (trim := trim_messages(messages, model=model)):
            batch = self.load_messages(
                thread_id,
                limit=50,
                before=None if not messages else messages[-1].timestamp,
            )
            messages.extend(batch)
        return trim

    @abc.abstractmethod
    def save_messages(self, thread_id: str, messages: list[MessageType]):
        raise NotImplementedError()


class InMemoryHistory(History):
    _history: ClassVar[dict[str, list[MessageType]]] = {}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def load_messages(
        self,
        thread_id: str,
        limit: int = None,
        before: datetime.datetime = None,
        after: datetime.datetime = None,
    ) -> list[MessageType]:
        messages = InMemoryHistory._history.get(thread_id, [])
        filtered_messages = [
            msg
            for i, msg in enumerate(reversed(messages))
            if (before is None or msg.timestamp < before)
            and (after is None or msg.timestamp > after)
            and i < (limit or math.inf)
        ]
        return list(reversed(filtered_messages))

    def save_messages(self, thread_id: str, messages: list[MessageType]):
        InMemoryHistory._history.setdefault(thread_id, []).extend(messages)


class FileHistory(History):
    base_path: Path = Field(
        default_factory=lambda: controlflow.settings.home_path / "history"
    )

    def path(self, thread_id: str) -> Path:
        return self.base_path / f"{thread_id}.json"

    @field_validator("base_path", mode="before")
    def _validate_path(cls, v):
        v = Path(v).expanduser()
        if not v.exists():
            v.mkdir(parents=True, exist_ok=True)
        return v

    def load_messages(
        self,
        thread_id: str,
        limit: int = None,
        before: datetime.datetime = None,
        after: datetime.datetime = None,
    ) -> list[MessageType]:
        if not self.path(thread_id).exists():
            return []

        with open(self.path(thread_id), "r") as f:
            all_messages = json.load(f)

        messages = []
        for msg in reversed(all_messages):
            message = MessageType.model_validate(msg)
            if before is None or message.timestamp < before:
                if after is None or message.timestamp > after:
                    messages.append(message)
                    if len(messages) >= limit or math.inf:
                        break

        return list(reversed(messages))

    def save_messages(self, thread_id: str, messages: list[MessageType]):
        if self.path(thread_id).exists():
            with open(self.path(thread_id), "r") as f:
                all_messages = json.load(f)
        else:
            all_messages = []
        all_messages.extend([msg.model_dump(mode="json") for msg in messages])
        with open(self.path(thread_id), "w") as f:
            json.dump(all_messages, f)


DEFAULT_HISTORY = InMemoryHistory()
