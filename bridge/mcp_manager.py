"""
MCP 管理器模块

负责管理 MCP 客户端连接，获取 tools 信息
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from langchain_mcp_adapters.client import MultiServerMCPClient  

logger = logging.getLogger(__name__)


def convert_config_to_langchain_format(config_data: dict) -> dict:
    """
    将配置转换为 langchain-mcp-adapters 格式
    
    Args:
        config_data: 原始配置数据
    
    Returns:
        dict: langchain 格式的配置
    """
    langchain_config = {}
    
    for name, server_config in config_data.items():
        # 过滤掉无效条目（空名字或空配置）
        if not name or not server_config:
            logger.warning(f"跳过无效的 MCP 配置条目: name={repr(name)}")
            continue

        # 获取 transport 类型，默认为 stdio
        transport = server_config.get('transport', 'stdio')
        
        if transport == 'stdio':
            command = server_config.get('command', '')
            if not command:
                logger.warning(f"MCP 服务 '{name}' 缺少 command 字段，跳过")
                continue
            # stdio 类型：使用 command 和 args
            langchain_config[name] = {
                'transport': 'stdio',
                'command': command,
                'args': server_config.get('args', []),
            }
            # 添加环境变量（如果有）
            if server_config.get('env'):
                langchain_config[name]['env'] = server_config.get('env')
        
        elif transport == 'http':
            url = server_config.get('url', '')
            if not url:
                logger.warning(f"MCP 服务 '{name}' 缺少 url 字段，跳过")
                continue
            # http 类型：使用 url
            langchain_config[name] = {
                'transport': 'http',
                'url': url,
            }
        
        else:
            logger.warning(f"未知的 transport 类型: {transport}，跳过服务 {name}")
            continue
    
    return langchain_config


class MCPManager:
    """MCP 管理器"""
    
    def __init__(self, config_file: Optional[Path] = None):
        """
        初始化 MCP 管理器
        
        Args:
            config_file: 配置文件路径，默认为 ~/.castrel/mcp.json
        """
        if config_file is None:
            self.config_file = Path.home() / '.castrel' / 'mcp.json'
        else:
            self.config_file = Path(config_file)
        
        self.client: Optional[MultiServerMCPClient] = None
        self.server_configs: Dict = {}
    
    def load_config(self) -> Dict:
        """
        加载 MCP 配置
        
        Returns:
            Dict: langchain 格式的配置字典
        """
        if not self.config_file.exists():
            logger.warning(f"MCP 配置文件不存在: {self.config_file}")
            return {}
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            mcpServers = data.get('mcpServers', {})
            
            # 转换为 langchain 格式
            langchain_config = convert_config_to_langchain_format(mcpServers)
            
            logger.info(f"加载了 {len(langchain_config)} 个 MCP 配置")
            return langchain_config
        
        except Exception as e:
            logger.error(f"加载 MCP 配置失败: {e}")
            return {}
    
    def get_server_list(self) -> List[Dict]:
        """
        获取服务器配置列表（用于显示）
        
        Returns:
            List[Dict]: 服务器配置列表
        """
        if not self.config_file.exists():
            return []
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            servers = []
            mcpServers = data.get('mcpServers', {})
            
            for name, config in mcpServers.items():
                servers.append({
                    'name': name,
                    'transport': config.get('transport', 'stdio'),
                    'command': config.get('command', ''),
                    'args': config.get('args', []),
                    'url': config.get('url', ''),
                    'env': config.get('env', {})
                })
            
            return servers
        
        except Exception as e:
            logger.error(f"获取服务器列表失败: {e}")
            return []
    
    async def connect_all(self) -> int:
        """
        连接所有配置的 MCP 服务
        
        Returns:
            int: 成功连接的服务数量
        """
        self.server_configs = self.load_config()
        if not self.server_configs:
            logger.info("没有配置 MCP 服务")
            return 0
        
        try:
            logger.info(f"正在连接 {len(self.server_configs)} 个 MCP 服务...")
            
            # 创建 MultiServerMCPClient
            self.client = MultiServerMCPClient(self.server_configs)
            
            logger.info(f"成功连接 {len(self.server_configs)} 个 MCP 服务")
            return len(self.server_configs)
        
        except Exception as e:
            logger.error(f"连接 MCP 服务失败: {e}")
            return 0
    
    async def get_all_tools(self) -> Dict[str,List[Dict]]:
        """
        获取所有 MCP 服务的 tools
        
        Returns:
            List[Dict]: 所有 tools 列表
        """
        if not self.client:
            logger.debug("没有配置 MCP 服务，跳过工具获取")
            return {}
        
        try:
            # 使用 MultiServerMCPClient 获取所有 tools
            result={}
            count=0
            for server_name in self.server_configs:
                tools = await self.client.get_tools(server_name=server_name)
                # 转换为我们需要的格式
                formatted_tools = []
                for tool in tools:
                    # langchain-mcp-adapters 返回的工具格式
                    tool_info = {
                        'name': tool.name,
                        'description': tool.description or '',
                        'inputSchema': tool.args_schema if hasattr(tool, 'args_schema') else {},
                        'mcp_server': getattr(tool, 'server_name', 'unknown')
                    }
                    formatted_tools.append(tool_info)
                count=count+len(formatted_tools)
                result[server_name] = formatted_tools
            logger.info(f"总共获取到 {count} 个 tools")
            return result
        
        except Exception as e:
            logger.error(f"获取 MCP tools 失败: {e}")
            return {}
    
    async def disconnect_all(self):
        """断开所有 MCP 连接"""
        if self.client:
            try:
                # MultiServerMCPClient 会自动管理连接
                self.client = None
                logger.info("所有 MCP 服务已断开")
            except Exception as e:
                logger.error(f"断开 MCP 服务失败: {e}")

    def _read_raw_config(self) -> dict:
        """读取 mcp.json 原始内容"""
        if not self.config_file.exists():
            return {"mcpServers": {}}
        with open(self.config_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_raw_config(self, data: dict) -> None:
        """写入 mcp.json"""
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def install_server(self, name: str, config: dict) -> bool:
        """
        安装（新增或更新）一个 MCP Server 配置到 mcp.json。
        
        Args:
            name: MCP Server 名称（唯一标识）
            config: 配置字典，含 transport/command/args/url/env 等字段
        Returns:
            True 表示成功
        """
        try:
            data = self._read_raw_config()
            data.setdefault("mcpServers", {})[name] = config
            self._write_raw_config(data)
            # 重置客户端，下次 tool_call 时重连
            self.client = None
            logger.info(f"[MCP-INSTALL] Installed MCP server: {name}")
            return True
        except Exception as e:
            logger.error(f"[MCP-INSTALL] Failed to install {name}: {e}")
            return False

    def remove_server(self, name: str) -> bool:
        """
        从 mcp.json 移除一个 MCP Server 配置。
        
        Args:
            name: MCP Server 名称
        Returns:
            True 表示成功（即使 name 不存在也返回 True）
        """
        try:
            data = self._read_raw_config()
            servers = data.get("mcpServers", {})
            if name in servers:
                del servers[name]
                data["mcpServers"] = servers
                self._write_raw_config(data)
                self.client = None
                logger.info(f"[MCP-REMOVE] Removed MCP server: {name}")
            else:
                logger.warning(f"[MCP-REMOVE] Server not found: {name}")
            return True
        except Exception as e:
            logger.error(f"[MCP-REMOVE] Failed to remove {name}: {e}")
            return False


# 全局 MCP 管理器实例
_mcp_manager = MCPManager()


def get_mcp_manager() -> MCPManager:
    """获取全局 MCP 管理器实例"""
    return _mcp_manager

