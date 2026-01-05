"""
客户端唯一标识生成模块

基于机器特征（hostname + MAC地址）生成稳定的客户端ID
"""

import hashlib
import platform
import socket
import uuid
from typing import Dict


def get_client_id() -> str:
    """
    生成基于机器特征的唯一客户端标识
    
    使用 hostname 和 MAC 地址的组合生成 SHA256 哈希值，
    确保同一台机器始终生成相同的 ID。
    
    Returns:
        str: 16字符的客户端唯一标识
    """
    # 获取主机名
    hostname = socket.gethostname()
    
    # 获取 MAC 地址（作为整数）
    mac = uuid.getnode()
    
    # 组合机器特征
    identifier = f"{hostname}:{mac}"
    
    # 生成 SHA256 哈希并截取前16位
    hash_value = hashlib.sha256(identifier.encode()).hexdigest()[:16]
    
    return hash_value


def get_machine_metadata() -> Dict[str, str]:
    """
    获取当前机器的元数据信息，用于发送到服务端
    
    Returns:
        dict: 包含机器详细信息的字典
    """
    metadata = {}
    
    try:
        # 获取机器名
        metadata['hostname'] = socket.gethostname()
    except Exception:
        metadata['hostname'] = 'unknown'
    
    try:
        # 获取 MAC 地址
        mac = uuid.getnode()
        mac_address = ':'.join(['{:02x}'.format((mac >> elements) & 0xff) 
                                for elements in range(0, 48, 8)][::-1])
        metadata['mac_address'] = mac_address
    except Exception:
        pass
    
    try:
        # 获取操作系统信息
        metadata['os'] = platform.system()  # Windows, Linux, Darwin
        metadata['os_version'] = platform.version()
        metadata['os_release'] = platform.release()
    except Exception:
        pass
    
    try:
        # 获取机器架构
        metadata['architecture'] = platform.machine()  # x86_64, arm64, etc.
    except Exception:
        pass
    
    try:
        # 获取 Python 版本
        metadata['python_version'] = platform.python_version()
    except Exception:
        pass
    
    try:
        # 获取处理器信息
        metadata['processor'] = platform.processor()
    except Exception:
        pass
    
    try:
        # 获取平台信息
        metadata['platform'] = platform.platform()
    except Exception:
        pass
    
    return metadata

