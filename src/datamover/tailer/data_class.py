from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True)
class BaseEvent:
    pass


@dataclass(frozen=True)
class InitialFoundEvent(BaseEvent):
    path: str


@dataclass(frozen=True)
class CreatedEvent(BaseEvent):
    path: str


@dataclass(frozen=True)
class ModifiedEvent(BaseEvent):
    path: str


@dataclass(frozen=True)
class DeletedEvent(BaseEvent):
    path: str


@dataclass(frozen=True)
class MovedEvent(BaseEvent):
    src_path: str
    dest_path: str


TailerQueueEvent = Union[
    InitialFoundEvent, CreatedEvent, ModifiedEvent, DeletedEvent, MovedEvent
]
