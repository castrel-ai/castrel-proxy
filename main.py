#!/usr/bin/env python3
"""
PyInstaller 入口文件

使用绝对导入避免相对导入问题
并在程序启动初期修复 SSL 证书验证问题
"""

import os
import sys


def fix_ssl_certificates():
    """
    自动检测并设置 SSL 证书路径，解决 'unable to get local issuer certificate' 错误。
    必须在导入任何网络库 (如 aiohttp, requests) 之前调用。
    """
    # 常见 Linux 系统的 CA 证书路径
    possible_paths = [
        "/etc/pki/tls/certs/ca-bundle.crt",  # CentOS 7/8/9, RHEL, Fedora
        "/etc/pki/tls/certs/ca-bundle.trust.crt",  # CentOS/RHEL (备用)
        "/etc/ssl/certs/ca-certificates.crt",  # Debian, Ubuntu, Alpine
        "/etc/ssl/certs/ca-bundle.crt",  # OpenSUSE, SLES
        "/etc/openssl/certs/ca-certificates.crt",  # 某些定制系统
    ]

    cert_path = None

    # 1. 优先查找系统自带的证书
    for path in possible_paths:
        if os.path.exists(path):
            cert_path = path
            break

    # 2. 如果系统没找到，尝试使用 certifi 包自带的证书
    if not cert_path:
        try:
            import certifi
            cert_path = certifi.where()
            # print(f"[SSL Fix] Using certifi bundle: {cert_path}")
        except ImportError:
            # 如果连 certifi 都没装，那就没办法了，只能打印警告
            # print("[SSL Fix] Warning: No CA certificates found and certifi not installed.")
            pass

    # 3. 如果找到了有效路径，设置环境变量
    if cert_path and os.path.exists(cert_path):
        os.environ["SSL_CERT_FILE"] = cert_path
        os.environ["REQUESTS_CA_BUNDLE"] = cert_path
        # 对于 aiohttp 和原生 ssl 模块，这通常就足够了
        # print(f"[SSL Fix] Successfully set SSL_CERT_FILE to: {cert_path}")

        # 额外措施：如果 ssl 模块已经加载，尝试重新加载默认路径（通常不需要，但以防万一）
        # 注意：如果在 import ssl 之后才调用此函数，主要靠环境变量生效
    else:
        # 实在找不到，至少让程序知道出错了，而不是报神秘的 SSL 错误
        print("[SSL Fix] Error: Could not locate any CA certificate bundle.", file=sys.stderr)


# 【关键】在任何业务逻辑导入之前执行修复
fix_ssl_certificates()

# 现在再导入你的业务逻辑
from castrel_proxy.cli.commands import run

if __name__ == "__main__":
    run()