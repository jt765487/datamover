import os
import shutil
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import (
    Union,
    Callable,
    IO,
    ContextManager,
    Iterator,
    Protocol,
    Optional,
)

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]


class MkdirCallable(Protocol):
    def __call__(
        self, path: PathLike, *, parents: bool = True, exist_ok: bool = True
    ) -> None: ...


class ResolveCallable(Protocol):
    def __call__(self, path: PathLike, *, strict: bool = False) -> Path: ...


class OpenFileCallable(Protocol):
    def __call__(
        self, path: PathLike, mode: str, *, encoding: Optional[str] = None
    ) -> ContextManager[IO]: ...


def _default_os_stat(path: PathLike) -> os.stat_result:
    return os.stat(str(path))


def _default_os_lstat(path: PathLike) -> os.stat_result:
    return os.lstat(str(path))


def _default_exists(path: PathLike) -> bool:
    return os.path.exists(str(path))


# MODIFIED _default_open
def _default_open(
    path: PathLike, mode: str, *, encoding: Optional[str] = None
) -> ContextManager[IO]:
    """
    Default implementation for opening a file.
    Matches the built-in open() signature for mode and encoding.
    """
    return open(str(path), mode, encoding=encoding)


def _default_listdir(path: PathLike) -> list[str]:
    return os.listdir(str(path))


def _default_abspath(path: PathLike) -> str:
    return os.path.abspath(str(path))


def _default_isdir(path: PathLike) -> bool:
    return os.path.isdir(str(path))


def _default_makedirs(
    path: PathLike, *, parents: bool = True, exist_ok: bool = True
) -> None:
    """
    Default implementation for creating a directory.
    Mirrors pathlib.Path.mkdir behavior: creates all missing parents
    and does not error if the target already exists.
    """
    Path(path).mkdir(parents=parents, exist_ok=exist_ok)


def _default_resolve(path: PathLike, *, strict: bool = False) -> Path:
    p = Path(path)
    try:
        return p.resolve(strict=strict)
    except FileNotFoundError:
        if strict:
            raise
        return p.absolute()


def _default_access(path: PathLike, mode: int) -> bool:
    return os.access(str(path), mode)


def _default_move(src: PathLike, dst: PathLike) -> None:
    try:
        shutil.move(str(src), str(dst))
    except Exception as e:
        logger.debug("FS.move failed (%s -> %s): %s", src, dst, e)
        raise


def _default_isfile(path: PathLike) -> bool:
    return os.path.isfile(str(path))


def _default_scandir(path: PathLike) -> ContextManager[Iterator[os.DirEntry]]:
    return os.scandir(str(path))


def _default_relative_to(path: PathLike, other: PathLike) -> Path:
    return Path(path).relative_to(Path(other))


@dataclass(frozen=True)
class FS:
    stat: Callable[[PathLike], os.stat_result] = field(default=_default_os_stat)
    lstat: Callable[[PathLike], os.stat_result] = field(default=_default_os_lstat)
    exists: Callable[[PathLike], bool] = field(default=_default_exists)
    # MODIFIED FS.open field to use the new Protocol
    open: OpenFileCallable = field(default=_default_open)
    listdir: Callable[[PathLike], list[str]] = field(default=_default_listdir)
    path_abspath: Callable[[PathLike], str] = field(default=_default_abspath)
    is_dir: Callable[[PathLike], bool] = field(default=_default_isdir)
    mkdir: MkdirCallable = field(default=_default_makedirs)
    resolve: ResolveCallable = field(default=_default_resolve)
    access: Callable[[PathLike, int], bool] = field(default=_default_access)
    move: Callable[[PathLike, PathLike], None] = field(default=_default_move)
    is_file: Callable[[PathLike], bool] = field(default=_default_isfile)
    scandir: Callable[[PathLike], ContextManager[Iterator[os.DirEntry]]] = field(
        default=_default_scandir
    )
    relative_to: Callable[[PathLike, PathLike], Path] = field(
        default=_default_relative_to
    )
