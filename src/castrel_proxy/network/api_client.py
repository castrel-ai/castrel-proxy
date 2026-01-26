"""
API Client Module

Handles HTTP communication with the server
"""

import asyncio
from typing import Dict

import aiohttp

from ..core.client_id import get_machine_metadata


class APIError(Exception):
    """API-related errors"""

    pass


class PairingError(APIError):
    """Pairing verification errors"""

    pass


class NetworkError(APIError):
    """Network connection errors"""

    pass


class APIClient:
    """API client class"""

    def __init__(self, timeout: float = 10.0):
        """
        Initialize API client

        Args:
            timeout: Request timeout (seconds)
        """
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    async def _verify_pairing_async(
        self, server_url: str, verification_code: str, client_id: str, workspace_id: str
    ) -> Dict[str, any]:
        """
        Asynchronously verify pairing information with server

        Args:
            server_url: Server URL
            verification_code: Verification code
            client_id: Client unique identifier
            workspace_id: Workspace ID

        Returns:
            dict: Server response data

        Raises:
            NetworkError: Network connection failure
            PairingError: Verification failure (invalid verification code, etc.)
            APIError: Other API errors
        """
        # Ensure URL format is correct
        if not server_url.startswith(("http://", "https://")):
            server_url = f"https://{server_url}"

        # Remove trailing slash
        server_url = server_url.rstrip("/")

        # Build pairing endpoint
        endpoint = f"{server_url}/api/v1/bridge/pair/verify_code"

        # Request payload
        payload = {"verification_code": verification_code, "client_id": client_id, "workspace_id": workspace_id}

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(endpoint, json=payload) as response:
                    # Get response data
                    try:
                        response_data = await response.json()
                    except Exception:
                        response_data = None

                    # Handle response status code
                    if response.status == 200:
                        return response_data

                    # Handle error responses
                    error_msg = "Pairing verification failed"
                    if response_data:
                        # Extract error message from response
                        if "message" in response_data:
                            error_msg = response_data["message"]
                        elif "error" in response_data:
                            error_msg = response_data["error"]
                        elif "data" in response_data and isinstance(response_data["data"], dict):
                            if "error" in response_data["data"]:
                                error_msg = response_data["data"]["error"]

                    # Raise appropriate error based on status code
                    if response.status == 404:
                        raise PairingError(f"Server pairing endpoint does not exist: {endpoint}")
                    elif response.status >= 500:
                        raise APIError(f"Server error: {error_msg}")
                    elif response.status in [400, 401]:
                        raise PairingError(error_msg)
                    else:
                        raise APIError(f"{error_msg} (HTTP {response.status})")

        except aiohttp.ClientConnectorError as e:
            raise NetworkError(f"Unable to connect to server: {server_url}") from e
        except asyncio.TimeoutError as e:
            raise NetworkError(f"Connection timeout: {server_url}") from e
        except (PairingError, APIError):
            # Re-raise known errors
            raise
        except Exception as e:
            raise APIError(f"Request failed: {e}") from e

    def verify_pairing(
        self, server_url: str, verification_code: str, client_id: str, workspace_id: str
    ) -> Dict[str, any]:
        """
        Verify pairing information with server (synchronous wrapper)

        Args:
            server_url: Server URL
            verification_code: Verification code
            client_id: Client unique identifier
            workspace_id: Workspace ID

        Returns:
            dict: Server response data

        Raises:
            NetworkError: Network connection failure
            PairingError: Verification failure (invalid verification code, etc.)
            APIError: Other API errors
        """
        return asyncio.run(self._verify_pairing_async(server_url, verification_code, client_id, workspace_id))

    async def _test_connection_async(self, server_url: str) -> bool:
        """
        Asynchronously test connection to server

        Args:
            server_url: Server URL

        Returns:
            bool: True if connection successful, False otherwise
        """
        # Ensure URL format is correct
        if not server_url.startswith(("http://", "https://")):
            server_url = f"https://{server_url}"

        server_url = server_url.rstrip("/")

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(f"{server_url}/api/v1/bridge/health") as response:
                    return response.status == 200
        except Exception:
            return False

    def test_connection(self, server_url: str) -> bool:
        """
        Test connection to server (synchronous wrapper)

        Args:
            server_url: Server URL

        Returns:
            bool: True if connection successful, False otherwise
        """
        return asyncio.run(self._test_connection_async(server_url))

    async def _send_client_info(
        self, server_url: str, client_id: str, verification_code: str, workspace_id: str, tools: Dict[str, list]
    ) -> bool:
        """
        Asynchronously send MCP tools information to server

        Args:
            server_url: Server URL
            client_id: Client unique identifier
            verification_code: Verification code
            workspace_id: Workspace ID
            tools: MCP tools list, format: {server_name: [tool_name, ...]}

        Returns:
            bool: True if send successful

        Raises:
            NetworkError: Network connection failure
            APIError: API error
        """
        # Ensure URL format is correct
        if not server_url.startswith(("http://", "https://")):
            server_url = f"https://{server_url}"

        server_url = server_url.rstrip("/")
        endpoint = f"{server_url}/api/v1/bridge/pair/client_info"

        # Request payload
        payload = {
            "client_id": client_id,
            "verification_code": verification_code,
            "workspace_id": workspace_id,
            "mcp_tools": tools,
            "metadata": get_machine_metadata(),
        }

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(endpoint, json=payload) as response:
                    # Get response data
                    try:
                        response_data = await response.json()
                    except Exception:
                        response_data = None

                    # Handle response status code
                    if response.status == 200:
                        return True

                    # Handle error responses
                    error_msg = "Failed to send MCP tools"
                    if response_data:
                        # Extract error message from response
                        if "message" in response_data:
                            error_msg = response_data["message"]
                        elif "error" in response_data:
                            error_msg = response_data["error"]
                        elif "data" in response_data and isinstance(response_data["data"], dict):
                            if "error" in response_data["data"]:
                                error_msg = response_data["data"]["error"]

                    # Raise appropriate error based on status code
                    if response.status == 404:
                        raise APIError(f"MCP tools endpoint does not exist: {endpoint}")
                    elif response.status >= 500:
                        raise APIError(f"Server error: {error_msg}")
                    else:
                        raise APIError(f"{error_msg} (HTTP {response.status})")

        except aiohttp.ClientConnectorError as e:
            raise NetworkError(f"Unable to connect to server: {server_url}") from e
        except asyncio.TimeoutError as e:
            raise NetworkError(f"Connection timeout: {server_url}") from e
        except (APIError, NetworkError):
            raise
        except Exception as e:
            raise APIError(f"Request failed: {e}") from e

    def send_mcp_tools(self, server_url: str, client_id: str, verification_code: str, tools: list) -> bool:
        """
        Send MCP tools information to server (synchronous wrapper)

        Args:
            server_url: Server URL
            client_id: Client unique identifier
            verification_code: Verification code
            tools: MCP tools list

        Returns:
            bool: True if send successful

        Raises:
            NetworkError: Network connection failure
            APIError: API error
        """
        return asyncio.run(self._send_mcp_tools_async(server_url, client_id, verification_code, tools))


# Global API client instance
_api_client = APIClient()


def get_api_client() -> APIClient:
    """Get global API client instance"""
    return _api_client
