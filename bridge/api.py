"""
API 客户端模块

处理与服务端的 HTTP 通信
"""

import asyncio
from typing import Any, Dict, Optional

import aiohttp

from .client_id import get_machine_metadata


class APIError(Exception):
    """API 相关错误"""
    pass


class PairingError(APIError):
    """配对验证错误"""
    pass


class NetworkError(APIError):
    """网络连接错误"""
    pass


class APIClient:
    """API 客户端类"""
    
    def __init__(self, timeout: float = 10.0):
        """
        初始化 API 客户端
        
        Args:
            timeout: 请求超时时间（秒）
        """
        self.timeout = aiohttp.ClientTimeout(total=timeout)
    
    async def _verify_pairing_async(
        self, 
        server_url: str, 
        verification_code: str, 
        client_id: str,
        workspace_id: str
    ) -> Dict[str, any]:
        """
        异步向服务端验证配对信息
        
        Args:
            server_url: 服务端 URL
            verification_code: 验证码
            client_id: 客户端唯一标识
            workspace_id: 工作区ID
        
        Returns:
            dict: 服务端响应数据
        
        Raises:
            NetworkError: 网络连接失败
            PairingError: 验证失败（验证码无效等）
            APIError: 其他 API 错误
        """
        # 确保 URL 格式正确
        if not server_url.startswith(('http://', 'https://')):
            server_url = f'https://{server_url}'
        
        # 移除末尾的斜杠
        server_url = server_url.rstrip('/')
        
        # 构建配对端点
        endpoint = f'{server_url}/api/v1/bridge/pair/verify_code'
        
        # 请求数据
        payload = {
            'verification_code': verification_code,
            'workspace_id': workspace_id
        }
        
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(endpoint, json=payload) as response:
                    # 获取响应数据
                    try:
                        response_data = await response.json()
                    except Exception:
                        response_data = None
                    
                    # 处理响应状态码
                    if response.status == 200:
                        return response_data
                    
                    # 处理错误响应
                    error_msg = "配对验证失败"
                    if response_data:
                        # 从响应中提取错误消息
                        if 'message' in response_data:
                            error_msg = response_data['message']
                        elif 'error' in response_data:
                            error_msg = response_data['error']
                        elif 'data' in response_data and isinstance(response_data['data'], dict):
                            if 'error' in response_data['data']:
                                error_msg = response_data['data']['error']
                    
                    # 根据状态码抛出相应的错误
                    if response.status == 404:
                        raise PairingError(f"服务端配对接口不存在: {endpoint}")
                    elif response.status >= 500:
                        raise APIError(f"服务端错误: {error_msg}")
                    elif response.status in [400, 401]:
                        raise PairingError(error_msg)
                    else:
                        raise APIError(f"{error_msg} (HTTP {response.status})")
        
        except aiohttp.ClientConnectorError as e:
            raise NetworkError(f"无法连接到服务端: {server_url}") from e
        except asyncio.TimeoutError as e:
            raise NetworkError(f"连接超时: {server_url}") from e
        except (PairingError, APIError):
            # 重新抛出已知错误
            raise
        except Exception as e:
            raise APIError(f"请求失败: {e}") from e
    
    def verify_pairing(
        self, 
        server_url: str, 
        verification_code: str, 
        client_id: str,
        workspace_id: str
    ) -> Dict[str, any]:
        """
        向服务端验证配对信息（同步包装）
        
        Args:
            server_url: 服务端 URL
            verification_code: 验证码
            client_id: 客户端唯一标识
            workspace_id: 工作区ID
        
        Returns:
            dict: 服务端响应数据
        
        Raises:
            NetworkError: 网络连接失败
            PairingError: 验证失败（验证码无效等）
            APIError: 其他 API 错误
        """
        return asyncio.run(self._verify_pairing_async(server_url, verification_code, client_id, workspace_id))
    
    async def _test_connection_async(self, server_url: str) -> bool:
        """
        异步测试与服务端的连接
        
        Args:
            server_url: 服务端 URL
        
        Returns:
            bool: 连接成功返回 True，否则返回 False
        """
        # 确保 URL 格式正确
        if not server_url.startswith(('http://', 'https://')):
            server_url = f'https://{server_url}'
        
        server_url = server_url.rstrip('/')
        
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(f'{server_url}/api/v1/bridge/health') as response:
                    return response.status == 200
        except Exception:
            return False
    
    def test_connection(self, server_url: str) -> bool:
        """
        测试与服务端的连接（同步包装）
        
        Args:
            server_url: 服务端 URL
        
        Returns:
            bool: 连接成功返回 True，否则返回 False
        """
        return asyncio.run(self._test_connection_async(server_url))
    
    async def _send_client_info(
        self,
        server_url: str,
        client_id: str,
        verification_code: str,
        workspace_id: str,
        tools: Dict[str, Any],
        skills: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        异步发送 MCP tools 和 Skills 信息到服务端

        Args:
            server_url: 服务端 URL
            client_id: 客户端唯一标识
            verification_code: 验证码
            tools: MCP tools 列表
            skills: Skills 元数据字典（可选）

        Returns:
            bool: 发送成功返回 True

        Raises:
            NetworkError: 网络连接失败
            APIError: API 错误
        """
        # 确保 URL 格式正确
        if not server_url.startswith(('http://', 'https://')):
            server_url = f'https://{server_url}'

        server_url = server_url.rstrip('/')
        endpoint = f'{server_url}/api/v1/bridge/pair/client_info'

        # 请求数据
        payload = {
            'client_id': client_id,
            'verification_code': verification_code,
            'workspace_id': workspace_id,
            'mcp_tools': tools,
            'metadata': get_machine_metadata()
        }

        # 添加 Skills 信息（如果有）
        if skills is not None:
            payload['skills'] = skills
        
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(endpoint, json=payload) as response:
                    # 获取响应数据
                    try:
                        response_data = await response.json()
                    except Exception:
                        response_data = None
                    
                    # 处理响应状态码
                    if response.status == 200:
                        return True
                    
                    # 处理错误响应
                    error_msg = "发送 MCP tools 失败"
                    if response_data:
                        # 从响应中提取错误消息
                        if 'message' in response_data:
                            error_msg = response_data['message']
                        elif 'error' in response_data:
                            error_msg = response_data['error']
                        elif 'data' in response_data and isinstance(response_data['data'], dict):
                            if 'error' in response_data['data']:
                                error_msg = response_data['data']['error']
                    
                    # 根据状态码抛出相应的错误
                    if response.status == 404:
                        raise APIError(f"MCP tools 接口不存在: {endpoint}")
                    elif response.status >= 500:
                        raise APIError(f"服务端错误: {error_msg}")
                    else:
                        raise APIError(f"{error_msg} (HTTP {response.status})")
        
        except aiohttp.ClientConnectorError as e:
            raise NetworkError(f"无法连接到服务端: {server_url}") from e
        except asyncio.TimeoutError as e:
            raise NetworkError(f"连接超时: {server_url}") from e
        except (APIError, NetworkError):
            raise
        except Exception as e:
            raise APIError(f"请求失败: {e}") from e
    
    def send_mcp_tools(
        self,
        server_url: str,
        client_id: str,
        verification_code: str,
        tools: list
    ) -> bool:
        """
        发送 MCP tools 信息到服务端（同步包装）
        
        Args:
            server_url: 服务端 URL
            client_id: 客户端唯一标识
            verification_code: 验证码
            tools: MCP tools 列表
        
        Returns:
            bool: 发送成功返回 True
        
        Raises:
            NetworkError: 网络连接失败
            APIError: API 错误
        """
        return asyncio.run(self._send_mcp_tools_async(
            server_url, client_id, verification_code, tools
        ))


# 全局 API 客户端实例
_api_client = APIClient()


def get_api_client() -> APIClient:
    """获取全局 API 客户端实例"""
    return _api_client
