from dataclasses import dataclass
from typing import IO, Dict
import requests

from datamover.protocols import HttpClient, HttpResponse


@dataclass(frozen=True)
class SimpleHttpResponse:
    """
    A minimal, immutable HttpResponse implementation.
    """

    _status_code: int
    _text: str

    @property
    def status_code(self) -> int:
        return self._status_code

    @property
    def text(self) -> str:
        return self._text

    @classmethod
    def from_requests_response(
        cls, response: requests.Response
    ) -> "SimpleHttpResponse":
        return cls(_status_code=response.status_code, _text=response.text)


class RequestsHttpClientAdapter:
    """
    HttpClient implementation backed by 'requests'.
    """

    def post(
        self,
        url: str,
        data: IO[bytes],
        headers: Dict[str, str],
        timeout: float,
        verify: bool,
    ) -> HttpResponse:
        resp = requests.post(
            url=url,
            data=data,
            headers=headers,
            timeout=timeout,
            verify=verify,
        )
        return SimpleHttpResponse.from_requests_response(resp)


# Optional mypy sanity‐checks (won't run at runtime)
_: HttpClient = RequestsHttpClientAdapter()
resp: HttpResponse = SimpleHttpResponse(200, "ok")
