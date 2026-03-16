#!/bin/bash
# PyInstaller 打包脚本 for castrel-proxy
# 兼容 CentOS 7 / 极简环境 (移除 which 依赖)

set -e

echo "=== 清理旧的构建文件 ==="
rm -rf build dist *.spec

echo "=== 确认 Python 环境 ==="
# 使用 command -v (Bash 内置) 替代 which
PYTHON_BIN=$(command -v python3)

if [ -z "$PYTHON_BIN" ]; then
    echo "❌ 错误：未找到 python3 命令!"
    exit 1
fi

echo "当前使用 Python: $PYTHON_BIN"
$PYTHON_BIN --version

# 检查是否指向预期的路径 (可选检查)
# 注意：这里使用字符串匹配，不依赖外部命令
if [[ "$PYTHON_BIN" != *"/usr/local/bin/python3.11"* ]]; then
    echo "⚠️ 警告：当前 Python 路径 ($PYTHON_BIN) 似乎不是 /usr/local/bin/python3.11"
    echo "   如果这是你手动编译的版本，请忽略此警告。"
    echo "   如果不是，请检查 PATH 环境变量。"
fi

echo "=== 安装核心依赖 ==="
# 1. 强制安装 certifi (作为 SSL 证书的备用方案)
# 2. 安装项目依赖
echo "正在安装 certifi..."
uv pip install --system certifi

echo "正在安装项目依赖..."
uv pip install --system -e .

echo "=== 安装/升级 PyInstaller ==="
pip3 install pyinstaller --upgrade

echo "=== 开始打包 ==="
# 显式使用 python3 调用 PyInstaller 模块，确保环境一致
python3 -m PyInstaller \
    --name castrel-proxy \
    --onefile \
    -p src \
    --collect-all=castrel_proxy \
    --collect-all=typer \
    --collect-all=click \
    --collect-all=aiohttp \
    --collect-all=yaml \
    --collect-all=mcp \
    --collect-all=langchain_mcp_adapters \
    --collect-all=file_read_backwards \
    --collect-all=certifi \
    --hidden-import=typer \
    --hidden-import=click \
    --hidden-import=aiohttp \
    --hidden-import=yaml \
    --hidden-import=mcp \
    --hidden-import=langchain_mcp_adapters \
    --hidden-import=file_read_backwards \
    --hidden-import=certifi \
    --hidden-import=ssl \
    --hidden-import=_ssl \
    main.py

echo "=== 打包完成 ==="
DIST_FILE="dist/castrel-proxy"

if [ -f "$DIST_FILE" ]; then
    chmod +x "$DIST_FILE"
    echo "✅ 可执行文件已生成：$DIST_FILE"
    ls -lh "$DIST_FILE"

    echo ""
    echo "=== 快速测试 (仅检查能否启动) ==="
    # 尝试运行 --help，如果是因为缺少配置文件报错是正常的
    # 我们主要关注是否出现 "SSL" 相关的报错
    if ./dist/castrel-proxy --help 2>&1 | grep -i "ssl"; then
        echo "⚠️ 检测到输出中包含 SSL 相关字样，请仔细检查上方日志是否有证书错误。"
    else
        echo "✅ 初步测试通过 (未发现明显的 SSL 启动错误)。"
    fi
else
    echo "❌ 打包失败：未找到生成文件 $DIST_FILE"
    exit 1
fi