"""
文档操作模块

提供文档的读取、写入和编辑功能
"""

import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# 文件大小限制 (10MB)
MAX_FILE_SIZE = 10 * 1024 * 1024


class DocumentOperationError(Exception):
    """文档操作异常"""

    pass


def _expand_path(file_path: str) -> Path:
    """
    展开文件路径，支持 ~ 和环境变量

    Args:
        file_path: 原始文件路径

    Returns:
        Path: 展开后的路径对象
    """
    expanded = os.path.expanduser(os.path.expandvars(file_path))
    return Path(expanded).resolve()


def _validate_path(file_path: Path) -> None:
    """
    验证路径安全性

    Args:
        file_path: 文件路径

    Raises:
        DocumentOperationError: 路径不安全时抛出异常
    """
    # 检查路径是否为绝对路径
    if not file_path.is_absolute():
        raise DocumentOperationError(f"路径必须是绝对路径: {file_path}")


def _detect_encoding(file_path: Path) -> str:
    """
    检测文件编码

    Args:
        file_path: 文件路径

    Returns:
        str: 编码名称
    """
    # 尝试常见编码
    encodings = ["utf-8", "gbk", "gb2312", "latin-1"]

    for encoding in encodings:
        try:
            with open(file_path, "r", encoding=encoding) as f:
                f.read()
            logger.debug(f"Detected encoding: {encoding} for {file_path}")
            return encoding
        except (UnicodeDecodeError, LookupError):
            continue

    # 默认使用 utf-8
    logger.warning(f"Could not detect encoding for {file_path}, using utf-8")
    return "utf-8"


def read_document(file_path: str, encoding: Optional[str] = None) -> Dict[str, Any]:
    """
    读取文档内容

    Args:
        file_path: 文件路径
        encoding: 文件编码，默认自动检测

    Returns:
        Dict[str, Any]: 执行结果
            {
                "success": bool,
                "content": str,  # 文件内容
                "encoding": str,  # 使用的编码
                "size": int,     # 文件大小（字节）
                "error": str     # 错误信息（如果失败）
            }
    """
    try:
        # 展开路径
        path = _expand_path(file_path)
        logger.info(f"[DOC-READ] Reading document: {path}")

        # 验证路径
        _validate_path(path)

        # 检查文件是否存在
        if not path.exists():
            return {"success": False, "error": f"文件不存在: {path}"}

        # 检查是否为文件
        if not path.is_file():
            return {"success": False, "error": f"不是文件: {path}"}

        # 检查文件大小
        file_size = path.stat().st_size
        if file_size > MAX_FILE_SIZE:
            return {
                "success": False,
                "error": f"文件过大: {file_size} 字节 (最大: {MAX_FILE_SIZE} 字节)",
            }

        # 检查读取权限
        if not os.access(path, os.R_OK):
            return {"success": False, "error": f"无读取权限: {path}"}

        # 检测编码
        if encoding is None:
            encoding = _detect_encoding(path)

        # 读取文件
        try:
            with open(path, "r", encoding=encoding) as f:
                content = f.read()
        except UnicodeDecodeError:
            logger.warning(f"Failed to decode with {encoding}, trying utf-8 with errors='replace'")
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            encoding = "utf-8 (with replacements)"

        logger.info(f"[DOC-READ-SUCCESS] Read {file_size} bytes from {path}")

        return {
            "success": True,
            "content": content,
            "encoding": encoding,
            "size": file_size,
        }

    except DocumentOperationError as e:
        logger.error(f"[DOC-READ-ERROR] Validation error: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(f"[DOC-READ-ERROR] Unexpected error: {e}", exc_info=True)
        return {"success": False, "error": f"读取文件失败: {str(e)}"}


def write_document(file_path: str, content: str, encoding: str = "utf-8", create_dirs: bool = True) -> Dict[str, Any]:
    """
    写入文档内容（覆盖模式）

    Args:
        file_path: 文件路径
        content: 文件内容
        encoding: 文件编码，默认 utf-8
        create_dirs: 是否自动创建父目录，默认 True

    Returns:
        Dict[str, Any]: 执行结果
            {
                "success": bool,
                "size": int,     # 写入的字节数
                "path": str,     # 文件路径
                "error": str     # 错误信息（如果失败）
            }
    """
    try:
        # 展开路径
        path = _expand_path(file_path)
        logger.info(f"[DOC-WRITE] Writing document: {path}")

        # 验证路径
        _validate_path(path)

        # 创建父目录
        if create_dirs:
            path.parent.mkdir(parents=True, exist_ok=True)
        elif not path.parent.exists():
            return {"success": False, "error": f"父目录不存在: {path.parent}"}

        # 检查父目录写入权限
        if not os.access(path.parent, os.W_OK):
            return {"success": False, "error": f"无写入权限: {path.parent}"}

        # 如果文件已存在，检查写入权限
        if path.exists() and not os.access(path, os.W_OK):
            return {"success": False, "error": f"无写入权限: {path}"}

        # 写入文件
        with open(path, "w", encoding=encoding) as f:
            f.write(content)

        # 获取写入后的文件大小
        file_size = path.stat().st_size

        logger.info(f"[DOC-WRITE-SUCCESS] Wrote {file_size} bytes to {path}")

        return {
            "success": True,
            "size": file_size,
            "path": str(path),
        }

    except DocumentOperationError as e:
        logger.error(f"[DOC-WRITE-ERROR] Validation error: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(f"[DOC-WRITE-ERROR] Unexpected error: {e}", exc_info=True)
        return {"success": False, "error": f"写入文件失败: {str(e)}"}


def edit_document(
    file_path: str,
    operation: str,
    new_content: str,
    old_content: Optional[str] = None,
    encoding: Optional[str] = None,
) -> Dict[str, Any]:
    """
    编辑文档内容

    Args:
        file_path: 文件路径
        operation: 操作类型 - "replace" (替换), "append" (追加), "prepend" (前置)
        new_content: 新内容
        old_content: 旧内容（仅 replace 操作需要）
        encoding: 文件编码，默认自动检测

    Returns:
        Dict[str, Any]: 执行结果
            {
                "success": bool,
                "size": int,        # 编辑后的文件大小
                "operation": str,   # 执行的操作
                "error": str        # 错误信息（如果失败）
            }
    """
    try:
        # 展开路径
        path = _expand_path(file_path)
        logger.info(f"[DOC-EDIT] Editing document: {path}, operation: {operation}")

        # 验证路径
        _validate_path(path)

        # 检查操作类型
        if operation not in ["replace", "append", "prepend"]:
            return {"success": False, "error": f"不支持的操作类型: {operation}"}

        # 检查文件是否存在
        if not path.exists():
            return {"success": False, "error": f"文件不存在: {path}"}

        # 检查是否为文件
        if not path.is_file():
            return {"success": False, "error": f"不是文件: {path}"}

        # 检查读写权限
        if not os.access(path, os.R_OK):
            return {"success": False, "error": f"无读取权限: {path}"}
        if not os.access(path, os.W_OK):
            return {"success": False, "error": f"无写入权限: {path}"}

        # 读取现有内容
        read_result = read_document(str(path), encoding)
        if not read_result["success"]:
            return read_result

        current_content = read_result["content"]
        detected_encoding = read_result["encoding"]

        # 执行编辑操作
        if operation == "replace":
            if old_content is None:
                return {"success": False, "error": "replace 操作需要提供 old_content 参数"}

            if old_content not in current_content:
                return {"success": False, "error": f"未找到要替换的内容: {old_content[:50]}..."}

            # 替换内容
            new_file_content = current_content.replace(old_content, new_content)

        elif operation == "append":
            # 追加到文件末尾
            new_file_content = current_content + new_content

        elif operation == "prepend":
            # 插入到文件开头
            new_file_content = new_content + current_content

        # 写入编辑后的内容
        write_result = write_document(str(path), new_file_content, detected_encoding.split()[0], create_dirs=False)

        if write_result["success"]:
            write_result["operation"] = operation
            logger.info(f"[DOC-EDIT-SUCCESS] Edited {path} with {operation} operation")

        return write_result

    except DocumentOperationError as e:
        logger.error(f"[DOC-EDIT-ERROR] Validation error: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error(f"[DOC-EDIT-ERROR] Unexpected error: {e}", exc_info=True)
        return {"success": False, "error": f"编辑文件失败: {str(e)}"}


def parse_document_args(args: list) -> Dict[str, Any]:
    """
    解析文档操作参数

    Args:
        args: 参数列表，格式如 ["--file", "/path/to/file", "--content", "..."]

    Returns:
        Dict[str, Any]: 解析后的参数字典
    """
    params = {}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--"):
            key = arg[2:]  # 移除 "--" 前缀
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                params[key] = args[i + 1]
                i += 2
            else:
                params[key] = True
                i += 1
        else:
            i += 1

    return params
