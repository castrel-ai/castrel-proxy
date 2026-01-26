"""
Document Operations Module

Provides document reading, writing, and editing functionality
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# File size limit (10MB)
MAX_FILE_SIZE = 10 * 1024 * 1024


class DocumentOperationError(Exception):
    """Document operation exceptions"""

    pass


def _expand_path(file_path: str) -> Path:
    """
    Expand file path, supports ~ and environment variables

    Args:
        file_path: Original file path

    Returns:
        Path: Expanded path object
    """
    expanded = os.path.expanduser(os.path.expandvars(file_path))
    return Path(expanded).resolve()


def _validate_path(file_path: Path) -> None:
    """
    Validate path security

    Args:
        file_path: File path

    Raises:
        DocumentOperationError: Raised when path is unsafe
    """
    # Check if path is absolute
    if not file_path.is_absolute():
        raise DocumentOperationError(f"Path must be absolute: {file_path}")


def _detect_encoding(file_path: Path) -> str:
    """
    Detect file encoding

    Args:
        file_path: File path

    Returns:
        str: Encoding name
    """
    # Try common encodings
    encodings = ["utf-8", "gbk", "gb2312", "latin-1"]

    for encoding in encodings:
        try:
            with open(file_path, "r", encoding=encoding) as f:
                f.read()
            logger.debug(f"Detected encoding: {encoding} for {file_path}")
            return encoding
        except (UnicodeDecodeError, LookupError):
            continue

    # Default to utf-8
    logger.warning(f"Could not detect encoding for {file_path}, using utf-8")
    return "utf-8"


def read_document(file_path: str, encoding: Optional[str] = None) -> Dict[str, Any]:
    """
    Read document content

    Args:
        file_path: File path
        encoding: File encoding, defaults to auto-detect

    Returns:
        Dict[str, Any]: Execution result
            {
                "success": bool,
                "content": str,  # File content
                "encoding": str,  # Encoding used
                "size": int,     # File size (bytes)
                "error": str     # Error message (if failed)
            }
    """
    try:
        # Expand path
        path = _expand_path(file_path)
        logger.info(f"[DOC-READ] Reading document: {path}")

        # Validate path
        _validate_path(path)

        # Check if file exists
        if not path.exists():
            return {"success": False, "error": f"File does not exist: {path}"}

        # Check if it's a file
        if not path.is_file():
            return {"success": False, "error": f"Not a file: {path}"}

        # Check file size
        file_size = path.stat().st_size
        if file_size > MAX_FILE_SIZE:
            return {
                "success": False,
                "error": f"File too large: {file_size} bytes (max: {MAX_FILE_SIZE} bytes)",
            }

        # Check read permission
        if not os.access(path, os.R_OK):
            return {"success": False, "error": f"No read permission: {path}"}

        # Detect encoding
        if encoding is None:
            encoding = _detect_encoding(path)

        # Read file
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
        return {"success": False, "error": f"Failed to read file: {str(e)}"}


def write_document(file_path: str, content: str, encoding: str = "utf-8", create_dirs: bool = True) -> Dict[str, Any]:
    """
    Write document content (overwrite mode)

    Args:
        file_path: File path
        content: File content
        encoding: File encoding, defaults to utf-8
        create_dirs: Whether to automatically create parent directories, defaults to True

    Returns:
        Dict[str, Any]: Execution result
            {
                "success": bool,
                "size": int,     # Number of bytes written
                "path": str,     # File path
                "error": str     # Error message (if failed)
            }
    """
    try:
        # Expand path
        path = _expand_path(file_path)
        logger.info(f"[DOC-WRITE] Writing document: {path}")

        # Validate path
        _validate_path(path)

        # Create parent directories
        if create_dirs:
            path.parent.mkdir(parents=True, exist_ok=True)
        elif not path.parent.exists():
            return {"success": False, "error": f"Parent directory does not exist: {path.parent}"}

        # Check parent directory write permission
        if not os.access(path.parent, os.W_OK):
            return {"success": False, "error": f"No write permission: {path.parent}"}

        # If file exists, check write permission
        if path.exists() and not os.access(path, os.W_OK):
            return {"success": False, "error": f"No write permission: {path}"}

        # Write file
        with open(path, "w", encoding=encoding) as f:
            f.write(content)

        # Get file size after writing
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
        return {"success": False, "error": f"Failed to write file: {str(e)}"}


def edit_document(
    file_path: str,
    operation: str,
    new_content: str,
    old_content: Optional[str] = None,
    encoding: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Edit document content

    Args:
        file_path: File path
        operation: Operation type - "replace" (replace), "append" (append), "prepend" (prepend)
        new_content: New content
        old_content: Old content (only needed for replace operation)
        encoding: File encoding, defaults to auto-detect

    Returns:
        Dict[str, Any]: Execution result
            {
                "success": bool,
                "size": int,        # File size after editing
                "operation": str,   # Operation performed
                "path": str,        # File path
                "error": str        # Error message (if failed)
            }
    """
    try:
        # Expand path
        path = _expand_path(file_path)
        logger.info(f"[DOC-EDIT] Editing document: {path}, operation: {operation}")

        # Validate path
        _validate_path(path)

        # Check operation type
        if operation not in ["replace", "append", "prepend"]:
            return {"success": False, "error": f"Unsupported operation type: {operation}"}

        # Check if file exists
        if not path.exists():
            return {"success": False, "error": f"File does not exist: {path}"}

        # Check if it's a file
        if not path.is_file():
            return {"success": False, "error": f"Not a file: {path}"}

        # Check read/write permissions
        if not os.access(path, os.R_OK):
            return {"success": False, "error": f"No read permission: {path}"}
        if not os.access(path, os.W_OK):
            return {"success": False, "error": f"No write permission: {path}"}

        # Read existing content
        read_result = read_document(str(path), encoding)
        if not read_result["success"]:
            return read_result

        current_content = read_result["content"]
        detected_encoding = read_result["encoding"]

        # Perform edit operation
        if operation == "replace":
            if old_content is None:
                return {"success": False, "error": "replace operation requires old_content parameter"}

            if old_content not in current_content:
                return {"success": False, "error": f"Content to replace not found: {old_content[:50]}..."}

            # Replace content
            new_file_content = current_content.replace(old_content, new_content)

        elif operation == "append":
            # Append to end of file
            new_file_content = current_content + new_content

        elif operation == "prepend":
            # Insert at beginning of file
            new_file_content = new_content + current_content

        # Write edited content
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
        return {"success": False, "error": f"Failed to edit file: {str(e)}"}


def parse_document_args(args: list) -> Dict[str, Any]:
    """
    Parse document operation arguments

    Args:
        args: Argument list, format like ["--file", "/path/to/file", "--content", "..."]

    Returns:
        Dict[str, Any]: Parsed arguments dictionary
    """
    params = {}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--"):
            key = arg[2:]  # Remove "--" prefix
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                params[key] = args[i + 1]
                i += 2
            else:
                params[key] = True
                i += 1
        else:
            i += 1

    return params
