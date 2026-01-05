"""
配置文件管理模块

处理 ~/.castrel/config.yaml 配置文件的读取、写入和验证
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml


class ConfigError(Exception):
    """配置相关错误"""
    pass


class Config:
    """配置管理类"""
    
    def __init__(self, config_dir: Optional[Path] = None):
        """
        初始化配置管理器
        
        Args:
            config_dir: 配置目录路径，默认为 ~/.castrel
        """
        if config_dir is None:
            self.config_dir = Path.home() / '.castrel'
        else:
            self.config_dir = Path(config_dir)
        
        self.config_file = self.config_dir / 'config.yaml'
    
    def _ensure_config_dir(self):
        """确保配置目录存在"""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise ConfigError(f"无法创建配置目录 {self.config_dir}: {e}")
    
    def save(self, server_url: str, verification_code: str, client_id: str, workspace_id: str) -> None:
        """
        保存配置到文件
        
        Args:
            server_url: 服务端URL
            verification_code: 验证码
            client_id: 客户端唯一标识
            workspace_id: 工作区ID
        
        Raises:
            ConfigError: 保存配置失败时抛出
        """
        self._ensure_config_dir()
        
        config_data = {
            'server_url': server_url,
            'verification_code': verification_code,
            'client_id': client_id,
            'workspace_id': workspace_id,
            'paired_at': datetime.utcnow().isoformat() + 'Z'
        }
        
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                yaml.safe_dump(config_data, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            raise ConfigError(f"保存配置失败: {e}")
    
    def load(self) -> dict:
        """
        从文件加载配置
        
        Returns:
            dict: 配置字典
        
        Raises:
            ConfigError: 配置文件不存在或加载失败时抛出
        """
        if not self.config_file.exists():
            raise ConfigError("配置文件不存在，请先使用 'pair' 命令进行配对")
        
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
            
            if not config_data:
                raise ConfigError("配置文件为空")
            
            # 验证必需字段
            required_fields = ['server_url', 'verification_code', 'client_id', 'workspace_id']
            for field in required_fields:
                if field not in config_data:
                    raise ConfigError(f"配置文件缺少必需字段: {field}")
            
            return config_data
        
        except yaml.YAMLError as e:
            raise ConfigError(f"配置文件格式错误: {e}")
        except Exception as e:
            raise ConfigError(f"加载配置失败: {e}")
    
    def exists(self) -> bool:
        """
        检查配置文件是否存在
        
        Returns:
            bool: 配置文件存在返回 True，否则返回 False
        """
        return self.config_file.exists()
    
    def delete(self) -> None:
        """
        删除配置文件
        
        Raises:
            ConfigError: 删除失败时抛出
        """
        if not self.config_file.exists():
            raise ConfigError("配置文件不存在")
        
        try:
            self.config_file.unlink()
        except Exception as e:
            raise ConfigError(f"删除配置文件失败: {e}")
    
    def get_server_url(self) -> str:
        """获取服务端URL"""
        return self.load()['server_url']
    
    def get_verification_code(self) -> str:
        """获取验证码"""
        return self.load()['verification_code']
    
    def get_client_id(self) -> str:
        """获取客户端ID"""
        return self.load()['client_id']
    
    def get_paired_at(self) -> Optional[str]:
        """获取配对时间"""
        config = self.load()
        return config.get('paired_at')
    
    def get_workspace_id(self) -> str:
        """获取工作区ID"""
        return self.load()['workspace_id']


# 全局配置实例
_config = Config()


def get_config() -> Config:
    """获取全局配置实例"""
    return _config

