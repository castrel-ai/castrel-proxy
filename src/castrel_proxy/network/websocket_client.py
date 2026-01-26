"""
WebSocket Client Module

Establishes WebSocket connection with server, receives commands and returns execution results
"""

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Optional

import aiohttp

from ..operations import document
from ..core.executor import CommandExecutor
from ..mcp.manager import get_mcp_manager
from ..security.whitelist import get_whitelist_file_path, is_command_allowed

# Configure logging
logger = logging.getLogger(__name__)


class WebSocketClient:
    """WebSocket client"""

    def __init__(
        self,
        server_url: str,
        client_id: str,
        verification_code: str,
        workspace_id: str,
        reconnect_interval: float = 5.0,
    ):
        """
        初始化 WebSocket client

        Args:
            server_url: Server URL
            client_id: Client unique identifier
            verification_code: Verification code
            workspace_id: Workspace ID
            reconnect_interval: Reconnect interval (seconds)
        """
        self.server_url = server_url
        self.client_id = client_id
        self.verification_code = verification_code
        self.workspace_id = workspace_id
        self.reconnect_interval = reconnect_interval
        self.mcp_manager = get_mcp_manager()
        self.running = False
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.heartbeat_interval = 30.0  # 30seconds，Ensure enough heartbeats before server timeout

    def _get_ws_url(self) -> str:
        """Get WebSocket URL"""
        # Convert http/https to ws/wss
        ws_url = self.server_url.replace("https://", "wss://").replace("http://", "ws://")
        ws_url = ws_url.rstrip("/")

        # Add client authentication parameters
        return f"{ws_url}/api/v1/bridge/ws?client_id={self.client_id}&workspace_id={self.workspace_id}&verification_code={self.verification_code}"

    def _log_operation(
        self,
        session_id: str,
        operation_type: str,
        operation: str,
        arguments: any = None,
        result: any = None,
        success: bool = True,
        elapsed: float = 0.0,
        error: str = None,
    ):
        """
        Log operation to terminal.log

        Args:
            session_id: Session ID
            operation_type: Operation type（MCP_TOOL, DOC_READ, DOC_WRITE, DOC_EDIT）
            operation: Operation name
            arguments: Arguments
            result: Result
            success: Whether successful
            elapsed: Execution time
            error: Error message
        """
        from datetime import datetime

        try:
            # Create session directory
            home_dir = os.path.expanduser("~")
            session_dir = os.path.join(home_dir, ".castrel", session_id)
            os.makedirs(session_dir, exist_ok=True)
            log_file = os.path.join(session_dir, "terminal.log")

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            log_entry = f"""[{timestamp}] {operation_type}: {operation}
  SUCCESS: {success}
  DURATION: {elapsed:.2f}s
"""

            if arguments:
                import json

                log_entry += f"  ARGUMENTS:\n    {json.dumps(arguments, ensure_ascii=False, indent=2).replace(chr(10), chr(10) + '    ')}\n"

            if result:
                import json

                result_str = json.dumps(result, ensure_ascii=False, indent=2)[:500]  # Limit length
                log_entry += f"  RESULT:\n    {result_str.replace(chr(10), chr(10) + '    ')}\n"

            if error:
                log_entry += f"  ERROR:\n    {error}\n"

            log_entry += "---\n\n"

            # Append to log file
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(log_entry)

        except Exception as e:
            # Logging failure should not affect operation execution
            logger.warning(f"Failed to log operation: {e}")

    async def _handle_command(self, message: dict) -> Optional[dict]:
        """
        Handle server commands

        Args:
            message: Server message

        Returns:
            Optional[dict]: Response message, return None if no response needed None
        """
        message_id = message.get("id")
        message_type = message.get("type")
        timestamp = message.get("timestamp")

        logger.info(
            f"[CLIENT-MSG-RECV] Received message: message_id={message_id}, "
            f"message_type={message_type}, timestamp={timestamp}, client_id={self.client_id}"
        )

        if message_type == "connected":
            # Connection success message
            session_id = message.get("session_id", "")
            msg = message.get("message", "")
            logger.info(
                f"[CLIENT-CONNECTED] Connection established: session_id={session_id}, "
                f"message={msg}, client_id={self.client_id}"
            )
            # No response needed
            return None

        elif message_type == "local_tool_call":
            # Handle local command call
            data = message.get("data", {})
            command = data.get("command", "")
            args = data.get("args", [])
            cwd = data.get("cwd")
            timeout = data.get("timeout", 300)
            session_id = data.get("session_id", "")

            logger.info(
                f"[CLIENT-LOCAL-CALL] Local tool call received: message_id={message_id}, "
                f"command={command}, args={args}, cwd={cwd}, session_id={session_id}, timeout={timeout}s, "
                f"client_id={self.client_id}"
            )

            return await self._execute_local_command(
                message_id=message_id,
                command=command,
                args=args,
                cwd=cwd,
                session_id=session_id,
                timeout=timeout,
            )

        elif message_type == "mcp_tool_call":
            # Handle MCP tool call
            data = message.get("data", {})
            server_name = data.get("server_name", "")
            tool_name = data.get("tool_name", "")
            arguments = data.get("arguments", {})
            session_id = data.get("session_id", "")

            logger.info(
                f"[CLIENT-MCP-CALL] MCP tool call received: message_id={message_id}, "
                f"server={server_name}, tool={tool_name}, session_id={session_id}, arguments={arguments}, "
                f"client_id={self.client_id}"
            )

            return await self._execute_mcp_tool(
                message_id=message_id,
                server_name=server_name,
                tool_name=tool_name,
                session_id=session_id,
                arguments=arguments,
            )

        elif message_type == "doc_read_call":
            # Handle document read call
            data = message.get("data", {})
            file_path = data.get("file_path", "")
            encoding = data.get("encoding")
            session_id = data.get("session_id", "")

            logger.info(
                f"[CLIENT-DOC-READ-CALL] Doc read call received: message_id={message_id}, "
                f"file_path={file_path}, session_id={session_id}, encoding={encoding}, client_id={self.client_id}"
            )

            return await self._execute_doc_read(
                message_id=message_id,
                file_path=file_path,
                session_id=session_id,
                encoding=encoding,
            )

        elif message_type == "doc_write_call":
            # Handle document write call
            data = message.get("data", {})
            file_path = data.get("file_path", "")
            content = data.get("content", "")
            encoding = data.get("encoding", "utf-8")
            create_dirs = data.get("create_dirs", True)
            session_id = data.get("session_id", "")

            logger.info(
                f"[CLIENT-DOC-WRITE-CALL] Doc write call received: message_id={message_id}, "
                f"file_path={file_path}, content_len={len(content)}, session_id={session_id}, encoding={encoding}, "
                f"create_dirs={create_dirs}, client_id={self.client_id}"
            )

            return await self._execute_doc_write(
                message_id=message_id,
                file_path=file_path,
                session_id=session_id,
                content=content,
                encoding=encoding,
                create_dirs=create_dirs,
            )

        elif message_type == "doc_edit_call":
            # Handle document edit call
            data = message.get("data", {})
            file_path = data.get("file_path", "")
            operation = data.get("operation", "")
            new_content = data.get("new_content", "")
            old_content = data.get("old_content")
            encoding = data.get("encoding")
            session_id = data.get("session_id", "")

            logger.info(
                f"[CLIENT-DOC-EDIT-CALL] Doc edit call received: message_id={message_id}, "
                f"file_path={file_path}, operation={operation}, session_id={session_id}, encoding={encoding}, client_id={self.client_id}"
            )

            return await self._execute_doc_edit(
                message_id=message_id,
                file_path=file_path,
                session_id=session_id,
                operation=operation,
                new_content=new_content,
                old_content=old_content,
                encoding=encoding,
            )

        elif message_type == "ping":
            # Heartbeat from server, response needed
            logger.debug(f"[CLIENT-PING-RECV] Received ping: message_id={message_id}, client_id={self.client_id}")
            return {"id": message_id, "type": "pong"}

        elif message_type == "pong":
            # Server response to client heartbeat
            logger.debug(f"[CLIENT-PONG-RECV] Received pong: message_id={message_id}, client_id={self.client_id}")
            # No response needed
            return None

        else:
            # Unknown command type
            logger.warning(
                f"[CLIENT-MSG-UNKNOWN] Unknown message type: message_id={message_id}, "
                f"message_type={message_type}, client_id={self.client_id}"
            )
            return {
                "id": message_id,
                "type": "error",
                "error": f"Unknown message type: {message_type}",
            }

    async def _send_heartbeat(self):
        """Send heartbeat periodically"""
        logger.info(
            f"[CLIENT-HEARTBEAT-START] Heartbeat task started: interval={self.heartbeat_interval}s, "
            f"client_id={self.client_id}"
        )

        while self.running and self.ws and not self.ws.closed:
            try:
                # Send heartbeat message
                heartbeat_msg = {
                    "id": str(uuid.uuid4()),
                    "type": "ping",
                    "timestamp": int(time.time() * 1000),
                }
                logger.debug(
                    f"[CLIENT-HEARTBEAT-SEND] Sending heartbeat: message_id={heartbeat_msg['id']}, "
                    f"client_id={self.client_id}"
                )
                await self.ws.send_json(heartbeat_msg)
                logger.debug(
                    f"[CLIENT-HEARTBEAT-SENT] Heartbeat sent: message_id={heartbeat_msg['id']}, "
                    f"client_id={self.client_id}"
                )

                # Wait for next heartbeat
                await asyncio.sleep(self.heartbeat_interval)

            except Exception as e:
                logger.error(
                    f"[CLIENT-HEARTBEAT-ERROR] Failed to send heartbeat: error={e}, client_id={self.client_id}",
                    exc_info=True,
                )
                break

        logger.info(f"[CLIENT-HEARTBEAT-STOP] Heartbeat task stopped: client_id={self.client_id}")

    async def _execute_local_command(
        self,
        message_id: str,
        command: str,
        session_id: str,
        args: list = None,
        cwd: Optional[str] = None,
        timeout: int = 300,
    ) -> dict:
        """
        Execute local command

        Args:
            message_id: 消息ID
            command: 命令名称
            session_id: 聊天Session ID（required）
            args: 命令Arguments列表
            cwd: 工作目录
            timeout: 超时时间（seconds）

        Returns:
            dict: 响应消息
        """
        start_time = time.time()
        try:
            # 验证 session_id
            if not session_id:
                logger.error(f"[CLIENT-LOCAL-EXEC-ERROR] session_id is required: message_id={message_id}")
                return {
                    "id": message_id,
                    "type": "local_tool_result",
                    "success": False,
                    "data": {
                        "exit_code": -1,
                        "stdout": "",
                        "stderr": "session_id is required for command execution",
                        "execution_time": 0.0,
                    },
                }

            if args is None:
                args = []

            # 展开Arguments中的 ~ 路径和环境变量
            expanded_args = []
            for arg in args:
                # 只对看起来像路径的Arguments进行展开（包含 ~ 或 $）
                if "~" in arg or "$" in arg:
                    expanded_args.append(os.path.expanduser(os.path.expandvars(arg)))
                else:
                    expanded_args.append(arg)

            # 构建完整命令
            if expanded_args:
                full_command = f"{command} {' '.join(expanded_args)}"
            else:
                full_command = command

            # Whitelist check
            is_allowed, blocked_commands = is_command_allowed(full_command)
            if not is_allowed:
                whitelist_path = get_whitelist_file_path()
                blocked_list = ", ".join(blocked_commands) if blocked_commands else command
                error_msg = (
                    f"Command execution rejected。Following commands not in whitelist: {blocked_list}\n"
                    f"Please add required commands to whitelist configuration file: {whitelist_path}"
                )
                logger.warning(
                    f"[CLIENT-LOCAL-EXEC-BLOCKED] Commands not in whitelist: message_id={message_id}, "
                    f"blocked_commands={blocked_commands}, full_command={full_command[:200]}, "
                    f"whitelist_path={whitelist_path}, client_id={self.client_id}"
                )
                return {
                    "id": message_id,
                    "type": "local_tool_result",
                    "success": False,
                    "data": {
                        "exit_code": -3,
                        "stdout": "",
                        "stderr": error_msg,
                        "execution_time": 0.0,
                    },
                }

            logger.info(
                f"[CLIENT-LOCAL-EXEC-START] Executing local command: message_id={message_id}, "
                f"command={full_command}, session_id={session_id}, cwd={cwd}, timeout={timeout}s, "
                f"client_id={self.client_id}"
            )

            # Create session-specific executor
            executor = CommandExecutor(session_id=session_id, timeout=timeout)

            # Execute command（Pass cwd to execute method if specified）
            result = await executor.execute(full_command, cwd=cwd)

            elapsed = time.time() - start_time
            logger.info(
                f"[CLIENT-LOCAL-EXEC-SUCCESS] Local command completed: message_id={message_id}, "
                f"exit_code={result.exit_code}, elapsed={elapsed:.2f}s, "
                f"stdout_len={len(result.stdout)}, stderr_len={len(result.stderr)}, client_id={self.client_id}"
            )

            return {
                "id": message_id,
                "type": "local_tool_result",
                "success": result.exit_code == 0,
                "data": result.to_dict(),
            }

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                f"[CLIENT-LOCAL-EXEC-ERROR] Local command execution failed: message_id={message_id}, "
                f"error={e}, elapsed={elapsed:.2f}s, client_id={self.client_id}",
                exc_info=True,
            )
            return {
                "id": message_id,
                "type": "local_tool_result",
                "success": False,
                "data": {
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": f"Execute local command失败: {str(e)}",
                    "execution_time": 0.0,
                },
            }

    async def _execute_mcp_tool(
        self,
        message_id: str,
        server_name: str,
        tool_name: str,
        session_id: str,
        arguments: dict,
    ) -> dict:
        """
        Execute MCP tool

        Args:
            message_id: 消息ID
            server_name: MCP 服务器名称
            tool_name: 工具名称
            session_id: 聊天Session ID（required）
            arguments: 工具Arguments

        Returns:
            dict: 响应消息
        """
        start_time = time.time()
        try:
            # 验证 session_id
            if not session_id:
                logger.error(f"[CLIENT-MCP-EXEC-ERROR] session_id is required: message_id={message_id}")
                return {
                    "id": message_id,
                    "type": "mcp_tool_result",
                    "success": False,
                    "data": {
                        "server_name": server_name,
                        "tool_name": tool_name,
                        "result": None,
                        "error": "session_id is required for MCP tool execution",
                    },
                }

            logger.info(
                f"[CLIENT-MCP-EXEC-START] Executing MCP tool: message_id={message_id}, "
                f"server={server_name}, tool={tool_name}, session_id={session_id}, arguments={arguments}, "
                f"client_id={self.client_id}"
            )

            # Call MCP tool
            if not self.mcp_manager.client:
                logger.error(
                    f"[CLIENT-MCP-EXEC-ERROR] MCP client not initialized: message_id={message_id}, "
                    f"client_id={self.client_id}"
                )
                return {
                    "id": message_id,
                    "type": "mcp_tool_result",
                    "success": False,
                    "data": {
                        "server_name": server_name,
                        "tool_name": tool_name,
                        "result": None,
                        "error": "MCP 客户端未初始化",
                    },
                }

            # 执行工具
            tools = await self.mcp_manager.client.get_tools(server_name=server_name)
            current_tool = None
            # Iterate through tool_name to get corresponding tool
            for tool in tools:
                if tool.name == tool_name:
                    current_tool = tool
                    break
            if not current_tool:
                logger.error(
                    f"[CLIENT-MCP-EXEC-ERROR] MCP tool not found: message_id={message_id}, "
                    f"server={server_name}, tool={tool_name}, available_tools={[t.name for t in tools]}, "
                    f"client_id={self.client_id}"
                )
                return {
                    "id": message_id,
                    "type": "mcp_tool_result",
                    "success": False,
                    "data": {
                        "server_name": server_name,
                        "tool_name": tool_name,
                        "result": None,
                        "error": "Execute MCP tool失败: tool不存在",
                    },
                }

            result = await current_tool.ainvoke(input=arguments)

            elapsed = time.time() - start_time
            logger.info(
                f"[CLIENT-MCP-EXEC-SUCCESS] MCP tool completed: message_id={message_id}, "
                f"server={server_name}, tool={tool_name}, elapsed={elapsed:.2f}s, client_id={self.client_id}"
            )

            # Log to terminal.log
            self._log_operation(
                session_id=session_id,
                operation_type="MCP_TOOL",
                operation=f"{server_name}:{tool_name}",
                arguments=arguments,
                result=result,
                success=True,
                elapsed=elapsed,
            )

            return {
                "id": message_id,
                "type": "mcp_tool_result",
                "success": True,
                "data": {
                    "server_name": server_name,
                    "tool_name": tool_name,
                    "result": result,
                },
            }

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                f"[CLIENT-MCP-EXEC-ERROR] MCP tool execution failed: message_id={message_id}, "
                f"server={server_name}, tool={tool_name}, error={e}, elapsed={elapsed:.2f}s, "
                f"client_id={self.client_id}",
                exc_info=True,
            )
            return {
                "id": message_id,
                "type": "mcp_tool_result",
                "success": False,
                "data": {
                    "server_name": server_name,
                    "tool_name": tool_name,
                    "result": None,
                    "error": f"Execute MCP tool失败: {str(e)}",
                },
            }

    async def _execute_doc_read(
        self,
        message_id: str,
        file_path: str,
        session_id: str,
        encoding: Optional[str] = None,
    ) -> dict:
        """
        Execute document read

        Args:
            message_id: 消息ID
            file_path: 文件路径
            session_id: 聊天Session ID
            encoding: 文件编码

        Returns:
            dict: 响应消息
        """
        start_time = time.time()
        try:
            logger.info(
                f"[CLIENT-DOC-READ-EXEC-START] Executing doc read: message_id={message_id}, "
                f"file_path={file_path}, session_id={session_id}, encoding={encoding}, client_id={self.client_id}"
            )

            # Call document.read_document
            result = document.read_document(file_path=file_path, encoding=encoding)

            elapsed = time.time() - start_time
            logger.info(
                f"[CLIENT-DOC-READ-EXEC-SUCCESS] Doc read completed: message_id={message_id}, "
                f"success={result.get('success')}, elapsed={elapsed:.2f}s, client_id={self.client_id}"
            )

            # Log to terminal.log
            self._log_operation(
                session_id=session_id,
                operation_type="DOC_READ",
                operation=file_path,
                arguments={"encoding": encoding},
                result={"size": result.get("size"), "encoding": result.get("encoding")},
                success=result.get("success", False),
                elapsed=elapsed,
                error=result.get("error"),
            )

            return {
                "id": message_id,
                "type": "doc_read_result",
                "success": result.get("success", False),
                "data": {
                    "content": result.get("content"),
                    "encoding": result.get("encoding"),
                    "size": result.get("size"),
                    "error": result.get("error"),
                },
            }

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                f"[CLIENT-DOC-READ-EXEC-ERROR] Doc read execution failed: message_id={message_id}, "
                f"error={e}, elapsed={elapsed:.2f}s, client_id={self.client_id}",
                exc_info=True,
            )

            # Log error to terminal.log
            self._log_operation(
                session_id=session_id,
                operation_type="DOC_READ",
                operation=file_path,
                arguments={"encoding": encoding},
                result=None,
                success=False,
                elapsed=elapsed,
                error=str(e),
            )

            return {
                "id": message_id,
                "type": "doc_read_result",
                "success": False,
                "data": {
                    "content": None,
                    "encoding": None,
                    "size": None,
                    "error": f"Execute document read失败: {str(e)}",
                },
            }

    async def _execute_doc_write(
        self,
        message_id: str,
        file_path: str,
        session_id: str,
        content: str,
        encoding: str = "utf-8",
        create_dirs: bool = True,
    ) -> dict:
        """
        Execute document write

        Args:
            message_id: 消息ID
            file_path: 文件路径
            session_id: 聊天Session ID
            content: 文件内容
            encoding: 文件编码
            create_dirs: 是否创建父目录

        Returns:
            dict: 响应消息
        """
        start_time = time.time()
        try:
            logger.info(
                f"[CLIENT-DOC-WRITE-EXEC-START] Executing doc write: message_id={message_id}, "
                f"file_path={file_path}, content_len={len(content)}, session_id={session_id}, encoding={encoding}, "
                f"create_dirs={create_dirs}, client_id={self.client_id}"
            )

            # Call document.write_document
            result = document.write_document(
                file_path=file_path,
                content=content,
                encoding=encoding,
                create_dirs=create_dirs,
            )

            elapsed = time.time() - start_time
            logger.info(
                f"[CLIENT-DOC-WRITE-EXEC-SUCCESS] Doc write completed: message_id={message_id}, "
                f"success={result.get('success')}, elapsed={elapsed:.2f}s, client_id={self.client_id}"
            )

            # Log to terminal.log
            self._log_operation(
                session_id=session_id,
                operation_type="DOC_WRITE",
                operation=file_path,
                arguments={
                    "content_length": len(content),
                    "encoding": encoding,
                    "create_dirs": create_dirs,
                },
                result={"size": result.get("size"), "path": result.get("path")},
                success=result.get("success", False),
                elapsed=elapsed,
                error=result.get("error"),
            )

            return {
                "id": message_id,
                "type": "doc_write_result",
                "success": result.get("success", False),
                "data": {
                    "path": result.get("path"),
                    "size": result.get("size"),
                    "error": result.get("error"),
                },
            }

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                f"[CLIENT-DOC-WRITE-EXEC-ERROR] Doc write execution failed: message_id={message_id}, "
                f"error={e}, elapsed={elapsed:.2f}s, client_id={self.client_id}",
                exc_info=True,
            )

            # Log error to terminal.log
            self._log_operation(
                session_id=session_id,
                operation_type="DOC_WRITE",
                operation=file_path,
                arguments={
                    "content_length": len(content),
                    "encoding": encoding,
                    "create_dirs": create_dirs,
                },
                result=None,
                success=False,
                elapsed=elapsed,
                error=str(e),
            )

            return {
                "id": message_id,
                "type": "doc_write_result",
                "success": False,
                "data": {
                    "path": None,
                    "size": None,
                    "error": f"Execute document write失败: {str(e)}",
                },
            }

    async def _execute_doc_edit(
        self,
        message_id: str,
        file_path: str,
        session_id: str,
        operation: str,
        new_content: str,
        old_content: Optional[str] = None,
        encoding: Optional[str] = None,
    ) -> dict:
        """
        Execute document edit

        Args:
            message_id: 消息ID
            file_path: 文件路径
            session_id: 聊天Session ID
            operation: Operation type（replace, append, prepend）
            new_content: 新内容
            old_content: 旧内容（Only needed for replace operation）
            encoding: 文件编码

        Returns:
            dict: 响应消息
        """
        start_time = time.time()
        try:
            logger.info(
                f"[CLIENT-DOC-EDIT-EXEC-START] Executing doc edit: message_id={message_id}, "
                f"file_path={file_path}, operation={operation}, session_id={session_id}, encoding={encoding}, client_id={self.client_id}"
            )

            # Call document.edit_document
            result = document.edit_document(
                file_path=file_path,
                operation=operation,
                new_content=new_content,
                old_content=old_content,
                encoding=encoding,
            )

            elapsed = time.time() - start_time
            logger.info(
                f"[CLIENT-DOC-EDIT-EXEC-SUCCESS] Doc edit completed: message_id={message_id}, "
                f"success={result.get('success')}, operation={operation}, elapsed={elapsed:.2f}s, "
                f"client_id={self.client_id}"
            )

            # Log to terminal.log
            self._log_operation(
                session_id=session_id,
                operation_type="DOC_EDIT",
                operation=f"{operation}:{file_path}",
                arguments={
                    "new_content_length": len(new_content),
                    "old_content_length": len(old_content) if old_content else 0,
                    "encoding": encoding,
                },
                result={"size": result.get("size"), "path": result.get("path")},
                success=result.get("success", False),
                elapsed=elapsed,
                error=result.get("error"),
            )

            return {
                "id": message_id,
                "type": "doc_edit_result",
                "success": result.get("success", False),
                "data": {
                    "operation": result.get("operation"),
                    "size": result.get("size"),
                    "path": result.get("path"),
                    "error": result.get("error"),
                },
            }

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                f"[CLIENT-DOC-EDIT-EXEC-ERROR] Doc edit execution failed: message_id={message_id}, "
                f"error={e}, elapsed={elapsed:.2f}s, client_id={self.client_id}",
                exc_info=True,
            )

            # Log error to terminal.log
            self._log_operation(
                session_id=session_id,
                operation_type="DOC_EDIT",
                operation=f"{operation}:{file_path}",
                arguments={
                    "new_content_length": len(new_content),
                    "old_content_length": len(old_content) if old_content else 0,
                    "encoding": encoding,
                },
                result=None,
                success=False,
                elapsed=elapsed,
                error=str(e),
            )

            return {
                "id": message_id,
                "type": "doc_edit_result",
                "success": False,
                "data": {
                    "operation": operation,
                    "size": None,
                    "path": None,
                    "error": f"Execute document edit失败: {str(e)}",
                },
            }

    async def _listen(self):
        """监听Server message"""
        try:
            logger.info(f"[CLIENT-LISTEN-START] Started listening for messages: client_id={self.client_id}")

            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        # Parse message
                        data = json.loads(msg.data)
                        logger.debug(f"[CLIENT-WS-RECV] Received raw message: data={data}, client_id={self.client_id}")

                        # Put command processing in background task to avoid blocking message receive loop
                        # This ensures other messages (like ping/pong) can still be received and processed during long tasks
                        asyncio.create_task(self._handle_and_respond(data))

                    except json.JSONDecodeError as e:
                        logger.error(
                            f"[CLIENT-MSG-PARSE-ERROR] Failed to parse message: error={e}, "
                            f"raw_data={msg.data}, client_id={self.client_id}"
                        )
                    except Exception as e:
                        logger.error(
                            f"[CLIENT-MSG-HANDLE-ERROR] Error handling message: error={e}, client_id={self.client_id}",
                            exc_info=True,
                        )

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(
                        f"[CLIENT-WS-ERROR] WebSocket error: exception={self.ws.exception()}, "
                        f"client_id={self.client_id}"
                    )
                    break

                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.info(f"[CLIENT-WS-CLOSED] WebSocket connection closed: client_id={self.client_id}")
                    break

        except Exception as e:
            logger.error(
                f"[CLIENT-LISTEN-ERROR] Error in message listener: error={e}, client_id={self.client_id}",
                exc_info=True,
            )

    async def _handle_and_respond(self, data: dict):
        """
        Handle command and send response (run as background task)

        Put command handling and response sending in separate task to avoid blocking _listen() loop。
        这样可以确保在长任务执行期间：
        1. Message receive loop continues running, can receive server PING/PONG messages
        2. Heartbeat task can send normally
        3. WebSocket Connection stays active

        Args:
            data: Received message data
        """
        try:
            # Handle command
            response = await self._handle_command(data)

            # Send response（if any）
            if response is not None:
                logger.info(
                    f"[CLIENT-RESPONSE-SEND] Sending response: message_id={response.get('id')}, "
                    f"type={response.get('type')}, success={response.get('success')}, "
                    f"client_id={self.client_id}"
                )
                await self.ws.send_json(response)
                logger.info(
                    f"[CLIENT-RESPONSE-SENT] Response sent successfully: message_id={response.get('id')}, "
                    f"client_id={self.client_id}"
                )
            else:
                logger.debug(
                    f"[CLIENT-NO-RESPONSE] No response needed for message: "
                    f"message_id={data.get('id')}, type={data.get('type')}, client_id={self.client_id}"
                )
        except Exception as e:
            logger.error(
                f"[CLIENT-HANDLE-RESPOND-ERROR] Error in handle_and_respond: error={e}, "
                f"message_id={data.get('id')}, client_id={self.client_id}",
                exc_info=True,
            )

    async def connect(self):
        """Establish WebSocket connection"""
        ws_url = self._get_ws_url()
        logger.info(
            f"[CLIENT-CONNECT-START] Attempting to connect to server: url={ws_url}, "
            f"client_id={self.client_id}, workspace_id={self.workspace_id}"
        )

        try:
            # Don't set global timeout when creating ClientSession
            # This ensures long-running commands won't be interrupted by timeout
            self.session = aiohttp.ClientSession()
            logger.debug(f"[CLIENT-SESSION-CREATED] aiohttp session created: client_id={self.client_id}")

            # Establish WebSocket connection，配置适合长时间任务的Arguments
            self.ws = await self.session.ws_connect(
                ws_url,
                heartbeat=self.heartbeat_interval,  # Enable WebSocket protocol-level heartbeat（PING/PONG）
                timeout=900.0,  # 15minute timeout，Support long-running commands
                autoclose=False,  # Don't auto-close connection
                autoping=True,  # Auto-respond to server PING
            )
            logger.info(
                f"[CLIENT-CONNECT-SUCCESS] WebSocket connection established: client_id={self.client_id}, "
                f"ws_closed={self.ws.closed}, heartbeat={self.heartbeat_interval}s"
            )

            # Start heartbeat task
            self.heartbeat_task = asyncio.create_task(self._send_heartbeat())
            logger.info(
                f"[CLIENT-HEARTBEAT-TASK] Heartbeat task started: interval={self.heartbeat_interval}s, "
                f"client_id={self.client_id}"
            )

            return True

        except Exception as e:
            logger.error(
                f"[CLIENT-CONNECT-ERROR] Failed to connect: error={e}, client_id={self.client_id}",
                exc_info=True,
            )
            if self.session:
                await self.session.close()
            return False

    async def disconnect(self):
        """Disconnect WebSocket connection"""
        logger.info(f"[CLIENT-DISCONNECT-START] Starting disconnect process: client_id={self.client_id}")

        # Stop heartbeat task
        if self.heartbeat_task and not self.heartbeat_task.done():
            logger.debug(f"[CLIENT-DISCONNECT-HEARTBEAT] Cancelling heartbeat task: client_id={self.client_id}")
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass
            logger.info(f"[CLIENT-DISCONNECT-HEARTBEAT] Heartbeat task stopped: client_id={self.client_id}")

        if self.ws and not self.ws.closed:
            logger.debug(f"[CLIENT-DISCONNECT-WS] Closing WebSocket connection: client_id={self.client_id}")
            await self.ws.close()
            logger.info(f"[CLIENT-DISCONNECT-WS] WebSocket closed: client_id={self.client_id}")

        if self.session:
            logger.debug(f"[CLIENT-DISCONNECT-SESSION] Closing aiohttp session: client_id={self.client_id}")
            await self.session.close()
            logger.info(f"[CLIENT-DISCONNECT-SESSION] Session closed: client_id={self.client_id}")

        logger.info(f"[CLIENT-DISCONNECT-COMPLETE] Disconnect completed: client_id={self.client_id}")

    async def run(self):
        """Run client (with automatic reconnection)"""
        self.running = True
        logger.info(
            f"[CLIENT-RUN-START] Starting client: client_id={self.client_id}, "
            f"server_url={self.server_url}, workspace_id={self.workspace_id}"
        )

        # Connect to MCP services
        try:
            logger.info(f"[CLIENT-MCP-CONNECT] Connecting to MCP services: client_id={self.client_id}")
            mcp_count = await self.mcp_manager.connect_all()
            if mcp_count > 0:
                logger.info(
                    f"[CLIENT-MCP-CONNECTED] Successfully connected to MCP services: count={mcp_count}, "
                    f"client_id={self.client_id}"
                )
            else:
                logger.warning(f"[CLIENT-MCP-NONE] No MCP services configured or connected: client_id={self.client_id}")
        except Exception as e:
            logger.error(
                f"[CLIENT-MCP-ERROR] Error connecting to MCP services: error={e}, client_id={self.client_id}",
                exc_info=True,
            )

        reconnect_count = 0
        while self.running:
            # Attempting to connect
            logger.info(
                f"[CLIENT-RECONNECT] Attempting to connect: attempt={reconnect_count + 1}, client_id={self.client_id}"
            )

            if await self.connect():
                reconnect_count = 0  # Reset reconnection count
                try:
                    # Listen for messages
                    await self._listen()
                except Exception as e:
                    logger.error(
                        f"[CLIENT-RUN-ERROR] Error during client run: error={e}, client_id={self.client_id}",
                        exc_info=True,
                    )
                finally:
                    # Disconnect
                    await self.disconnect()
            else:
                reconnect_count += 1
                logger.warning(
                    f"[CLIENT-CONNECT-FAILED] Failed to establish connection: attempts={reconnect_count}, "
                    f"client_id={self.client_id}"
                )

            # If still running, wait then reconnect
            if self.running:
                logger.info(
                    f"[CLIENT-RECONNECT-WAIT] Waiting for reconnection: delay={self.reconnect_interval}s, "
                    f"client_id={self.client_id}"
                )
                await asyncio.sleep(self.reconnect_interval)

    async def stop(self):
        """Stop client"""
        logger.info(f"[CLIENT-STOP-START] Stopping client: client_id={self.client_id}")

        self.running = False
        await self.disconnect()

        # Disconnect from MCP services
        try:
            logger.info(f"[CLIENT-MCP-DISCONNECT] Disconnecting from MCP services: client_id={self.client_id}")
            await self.mcp_manager.disconnect_all()
            logger.info(f"[CLIENT-MCP-DISCONNECTED] MCP services disconnected: client_id={self.client_id}")
        except Exception as e:
            logger.error(
                f"[CLIENT-MCP-DISCONNECT-ERROR] Error disconnecting from MCP services: error={e}, "
                f"client_id={self.client_id}",
                exc_info=True,
            )

        logger.info(f"[CLIENT-STOP-COMPLETE] Client stopped: client_id={self.client_id}")
