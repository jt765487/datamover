import io
import pytest
import requests
from unittest.mock import MagicMock, patch

from datamover.protocols import HttpResponse, HttpClient
from datamover.uploader.http_adapters import (
    SimpleHttpResponse,
    RequestsHttpClientAdapter,
)


# --- Tests for SimpleHttpResponse ---


class TestSimpleHttpResponse:
    def test_creation_and_property_access(self):
        """Test basic object creation and property getters."""
        status = 200
        text_content = "Success"
        response = SimpleHttpResponse(_status_code=status, _text=text_content)

        assert response.status_code == status
        assert response.text == text_content

    def test_immutability_frozen(self):
        """Test that the dataclass is frozen (immutable)."""
        response = SimpleHttpResponse(_status_code=200, _text="Initial")
        with pytest.raises(
            AttributeError
        ):  # More specific: dataclasses.FrozenInstanceError in Python 3.7+
            response.status_code = 404
        with pytest.raises(AttributeError):
            response.text = "Changed"

    def test_from_requests_response(self):
        """Test the class method that converts a requests.Response object."""
        mock_req_response = MagicMock(spec=requests.Response)
        mock_req_response.status_code = 201
        mock_req_response.text = "Created successfully"

        simple_response = SimpleHttpResponse.from_requests_response(mock_req_response)

        assert isinstance(simple_response, SimpleHttpResponse)
        assert simple_response.status_code == 201
        assert simple_response.text == "Created successfully"

    def test_protocol_conformance(self):
        """Test that SimpleHttpResponse conforms to the HttpResponse protocol."""
        response: HttpResponse = SimpleHttpResponse(_status_code=200, _text="OK")
        assert response.status_code == 200
        assert response.text == "OK"


# --- Tests for RequestsHttpClientAdapter ---


class TestRequestsHttpClientAdapter:
    @pytest.fixture
    def adapter(self) -> RequestsHttpClientAdapter:
        """Fixture to provide a RequestsHttpClientAdapter instance."""
        return RequestsHttpClientAdapter()

    @pytest.fixture
    def mock_requests_response(self) -> MagicMock:
        """Fixture to provide a mock requests.Response object."""
        response = MagicMock(spec=requests.Response)
        response.status_code = 200
        response.text = "Mocked Response OK"
        return response

    @patch("datamover.uploader.http_adapters.requests.post")
    def test_post_successful_call_and_conversion(
        self,
        mock_post_method: MagicMock,
        adapter: RequestsHttpClientAdapter,
        mock_requests_response: MagicMock,
    ):
        """
        Test that post() calls requests.post with correct parameters
        and correctly converts the response.
        """
        mock_post_method.return_value = mock_requests_response

        url = "http://test.com/api"
        # For IO[bytes], we need a file-like object in binary mode
        data_bytes = b"key=value&another=key"
        data_io = io.BytesIO(data_bytes)
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Custom": "Test",
        }
        timeout_seconds = 10.5
        verify_ssl = False

        response = adapter.post(
            url=url,
            data=data_io,
            headers=headers,
            timeout=timeout_seconds,
            verify=verify_ssl,
        )

        # 1. Verify requests.post was called correctly
        mock_post_method.assert_called_once_with(
            url=url,
            data=data_io,  # Ensure the same IO object is passed
            headers=headers,
            timeout=timeout_seconds,
            verify=verify_ssl,
        )

        # 2. Verify the response is a correctly converted SimpleHttpResponse
        assert isinstance(response, SimpleHttpResponse)
        assert response.status_code == mock_requests_response.status_code  # e.g., 200
        assert (
            response.text == mock_requests_response.text
        )  # e.g., "Mocked Response OK"

    @patch("datamover.uploader.http_adapters.requests.post")
    def test_post_handles_requests_exception_propagation(
        self, mock_post_method: MagicMock, adapter: RequestsHttpClientAdapter
    ):
        """
        Test that exceptions from requests.post (like Timeout) propagate up.
        """
        url = "http://timeout.com/api"
        data_io = io.BytesIO(b"data")
        headers = {"Content-Type": "text/plain"}

        # Configure the mock to raise a requests-specific exception
        mock_post_method.side_effect = requests.exceptions.Timeout(
            "Connection timed out"
        )

        with pytest.raises(requests.exceptions.Timeout) as excinfo:
            adapter.post(
                url=url, data=data_io, headers=headers, timeout=5.0, verify=True
            )

        assert "Connection timed out" in str(excinfo.value)
        mock_post_method.assert_called_once()  # Ensure it was still called

    def test_protocol_conformance(self):
        """Test that RequestsHttpClientAdapter conforms to the HttpClient protocol."""
        # This is more of a type system check, but we can instantiate.
        # The protocol requires a post method, which this class has.
        client: HttpClient = RequestsHttpClientAdapter()
        assert hasattr(client, "post")
        assert callable(client.post)
