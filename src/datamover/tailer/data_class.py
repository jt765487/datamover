from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True, slots=True)
class BaseEvent:
    pass


@dataclass(frozen=True, slots=True)
class InitialFoundEvent(BaseEvent):
    path: str


@dataclass(frozen=True, slots=True)
class CreatedEvent(BaseEvent):
    path: str


@dataclass(frozen=True, slots=True)
class ModifiedEvent(BaseEvent):
    path: str


@dataclass(frozen=True, slots=True)
class DeletedEvent(BaseEvent):
    path: str


@dataclass(frozen=True, slots=True)
class MovedEvent(BaseEvent):
    src_path: str
    dest_path: str


TailerQueueEvent = Union[
    InitialFoundEvent, CreatedEvent, ModifiedEvent, DeletedEvent, MovedEvent
]
