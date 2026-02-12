"""
WebSocket 客户端模块

负责与服务端建立 WebSocket 连接，接收命令并返回执行结果
"""

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Optional

import aiohttp

from bridge import document_operations
from bridge.executor import get_executor
from bridge.interactive_executor import get_interactive_executor
from bridge.mcp_manager import get_mcp_manager

# 配置日志
logger = logging.getLogger(__name__)


class WebSocketClient:
    """WebSocket 客户端"""

    def __init__(
        self,
        server_url: str,
        client_id: str,
        verification_code: str,
        workspace_id: str,
        reconnect_interval: float = 5.0,
    ):
        """
        初始化 WebSocket 客户端

        Args:
            server_url: 服务端 URL
            client_id: 客户端唯一标识
            verification_code: 验证码
            workspace_id: 工作区ID
            reconnect_interval: 重连间隔时间（秒）
        """
        self.server_url = server_url
        self.client_id = client_id
        self.verification_code = verification_code
        self.workspace_id = workspace_id
        self.reconnect_interval = reconnect_interval
        self.executor = get_executor()
        self.interactive_executor = get_interactive_executor()
        self.mcp_manager = get_mcp_manager()
        self.running = False
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.heartbeat_task: Optional[asyncio.Task] = None
        self.heartbeat_interval = 60.0  # 1分钟

    def _get_ws_url(self) -> str:
        """获取 WebSocket URL"""
        # 将 http/https 转换为 ws/wss
        ws_url = self.server_url.replace("https://", "wss://").replace("http://", "ws://")
        ws_url = ws_url.rstrip("/")

        # 添加客户端认证参数
        return f"{ws_url}/api/v1/bridge/ws?client_id={self.client_id}&workspace_id={self.workspace_id}&verification_code={self.verification_code}"

    async def _handle_command(self, message: dict) -> Optional[dict]:
        """
        处理服务端命令

        Args:
            message: 服务端消息

        Returns:
            Optional[dict]: 响应消息，如果不需要响应则返回 None
        """
        message_id = message.get("id")
        message_type = message.get("type")
        timestamp = message.get("timestamp")

        logger.info(
            f"[CLIENT-MSG-RECV] Received message: message_id={message_id}, "
            f"message_type={message_type}, timestamp={timestamp}, client_id={self.client_id}"
        )

        if message_type == "connected":
            # 连接成功消息
            session_id = message.get("session_id", "")
            msg = message.get("message", "")
            logger.info(
                f"[CLIENT-CONNECTED] Connection established: session_id={session_id}, "
                f"message={msg}, client_id={self.client_id}"
            )
            # 不需要响应
            return None

        elif message_type == "local_tool_call":
            # 处理本地命令调用
            data = message.get("data", {})
            command = data.get("command", "")
            args = data.get("args", [])
            cwd = data.get("cwd")
            timeout = data.get("timeout", 300)

            logger.info(
                f"[CLIENT-LOCAL-CALL] Local tool call received: message_id={message_id}, "
                f"command={command}, args={args}, cwd={cwd}, timeout={timeout}s, client_id={self.client_id}"
            )

            return await self._execute_local_command(
                message_id=message_id,
                command=command,
                args=args,
                cwd=cwd,
                timeout=timeout,
            )

        elif message_type == "mcp_tool_call":
            # 处理 MCP 工具调用
            data = message.get("data", {})
            server_name = data.get("server_name", "")
            tool_name = data.get("tool_name", "")
            arguments = data.get("arguments", {})

            logger.info(
                f"[CLIENT-MCP-CALL] MCP tool call received: message_id={message_id}, "
                f"server={server_name}, tool={tool_name}, arguments={arguments}, client_id={self.client_id}"
            )

            return await self._execute_mcp_tool(
                message_id=message_id,
                server_name=server_name,
                tool_name=tool_name,
                arguments=arguments,
            )

        elif message_type == "local_interactive_call":
            data = message.get("data", {})
            action = data.get("action", "")
            interactive_session_id = data.get("interactive_session_id")
            command = data.get("command")
            args = data.get("args")
            cwd = data.get("cwd")
            input_text = data.get("input_text")
            last_stdout_seq = data.get("last_stdout_seq", 0)
            last_stderr_seq = data.get("last_stderr_seq", 0)
            wait_ms = data.get("wait_ms", 0)
            max_output_bytes = data.get("max_output_bytes", 65536)

            logger.info(
                f"[CLIENT-INTERACTIVE-CALL] Interactive call received: message_id={message_id}, "
                f"action={action}, interactive_session_id={interactive_session_id}, command={command}, "
                f"client_id={self.client_id}"
            )
            return await self._execute_local_interactive(
                message_id=message_id,
                action=action,
                interactive_session_id=interactive_session_id,
                command=command,
                args=args,
                cwd=cwd,
                input_text=input_text,
                last_stdout_seq=last_stdout_seq,
                last_stderr_seq=last_stderr_seq,
                wait_ms=wait_ms,
                max_output_bytes=max_output_bytes,
            )

        elif message_type == "doc_read_call":
            # 处理文档读取调用
            data = message.get("data", {})
            file_path = data.get("file_path", "")
            encoding = data.get("encoding")

            logger.info(
                f"[CLIENT-DOC-READ-CALL] Doc read call received: message_id={message_id}, "
                f"file_path={file_path}, encoding={encoding}, client_id={self.client_id}"
            )

            return await self._execute_doc_read(
                message_id=message_id,
                file_path=file_path,
                encoding=encoding,
            )

        elif message_type == "doc_write_call":
            # 处理文档写入调用
            data = message.get("data", {})
            file_path = data.get("file_path", "")
            content = data.get("content", "")
            encoding = data.get("encoding", "utf-8")
            create_dirs = data.get("create_dirs", True)

            logger.info(
                f"[CLIENT-DOC-WRITE-CALL] Doc write call received: message_id={message_id}, "
                f"file_path={file_path}, content_len={len(content)}, encoding={encoding}, "
                f"create_dirs={create_dirs}, client_id={self.client_id}"
            )

            return await self._execute_doc_write(
                message_id=message_id,
                file_path=file_path,
                content=content,
                encoding=encoding,
                create_dirs=create_dirs,
            )

        elif message_type == "doc_edit_call":
            # 处理文档编辑调用
            data = message.get("data", {})
            file_path = data.get("file_path", "")
            operation = data.get("operation", "")
            new_content = data.get("new_content", "")
            old_content = data.get("old_content")
            encoding = data.get("encoding")

            logger.info(
                f"[CLIENT-DOC-EDIT-CALL] Doc edit call received: message_id={message_id}, "
                f"file_path={file_path}, operation={operation}, encoding={encoding}, client_id={self.client_id}"
            )

            return await self._execute_doc_edit(
                message_id=message_id,
                file_path=file_path,
                operation=operation,
                new_content=new_content,
                old_content=old_content,
                encoding=encoding,
            )

        elif message_type == "ping":
            # 服务端发来的心跳，需要响应
            logger.debug(f"[CLIENT-PING-RECV] Received ping: message_id={message_id}, client_id={self.client_id}")
            return {"id": message_id, "type": "pong"}

        elif message_type == "pong":
            # 服务端对客户端心跳的响应
            logger.debug(f"[CLIENT-PONG-RECV] Received pong: message_id={message_id}, client_id={self.client_id}")
            # 不需要响应
            return None

        else:
            # 未知命令类型
            logger.warning(
                f"[CLIENT-MSG-UNKNOWN] Unknown message type: message_id={message_id}, "
                f"message_type={message_type}, client_id={self.client_id}"
            )
            return {
                "id": message_id,
                "type": "error",
                "error": f"未知消息类型: {message_type}",
            }

    async def _send_heartbeat(self):
        """定时发送心跳"""
        logger.info(
            f"[CLIENT-HEARTBEAT-START] Heartbeat task started: interval={self.heartbeat_interval}s, "
            f"client_id={self.client_id}"
        )

        while self.running and self.ws and not self.ws.closed:
            try:
                # 发送心跳消息
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

                # 等待下次心跳
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
        args: list = None,
        cwd: Optional[str] = None,
        timeout: int = 300,
    ) -> dict:
        """
        执行本地命令

        Args:
            message_id: 消息ID
            command: 命令名称
            args: 命令参数列表
            cwd: 工作目录
            timeout: 超时时间（秒）

        Returns:
            dict: 响应消息
        """
        start_time = time.time()
        try:
            if args is None:
                args = []

            # 展开参数中的 ~ 路径和环境变量
            expanded_args = []
            for arg in args:
                # 只对看起来像路径的参数进行展开（包含 ~ 或 $）
                if "~" in arg or "$" in arg:
                    expanded_args.append(os.path.expanduser(os.path.expandvars(arg)))
                else:
                    expanded_args.append(arg)

            # 构建完整命令
            if expanded_args:
                full_command = f"{command} {' '.join(expanded_args)}"
            else:
                full_command = command

            logger.info(
                f"[CLIENT-LOCAL-EXEC-START] Executing local command: message_id={message_id}, "
                f"command={full_command}, cwd={cwd}, timeout={timeout}s, client_id={self.client_id}"
            )

            # 如果指定了工作目录，更新执行器
            if cwd:
                original_dir = self.executor.working_dir
                self.executor.working_dir = cwd

            # 更新超时时间
            original_timeout = self.executor.timeout
            self.executor.timeout = timeout

            # 执行命令
            result = await self.executor.execute(full_command)

            # 恢复原始配置
            if cwd:
                self.executor.working_dir = original_dir
            self.executor.timeout = original_timeout

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
                    "stderr": f"执行本地命令失败: {str(e)}",
                    "execution_time": 0.0,
                },
            }

    async def _execute_mcp_tool(self, message_id: str, server_name: str, tool_name: str, arguments: dict) -> dict:
        """
        执行 MCP 工具

        Args:
            message_id: 消息ID
            server_name: MCP 服务器名称
            tool_name: 工具名称
            arguments: 工具参数

        Returns:
            dict: 响应消息
        """
        start_time = time.time()
        try:
            logger.info(
                f"[CLIENT-MCP-EXEC-START] Executing MCP tool: message_id={message_id}, "
                f"server={server_name}, tool={tool_name}, arguments={arguments}, client_id={self.client_id}"
            )

            # 调用 MCP 工具
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
            # 遍历tool_name，获取对应的tool
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
                        "error": "执行 MCP 工具失败: tool不存在",
                    },
                }

            result = await current_tool.ainvoke(input=arguments)

            elapsed = time.time() - start_time
            logger.info(
                f"[CLIENT-MCP-EXEC-SUCCESS] MCP tool completed: message_id={message_id}, "
                f"server={server_name}, tool={tool_name}, elapsed={elapsed:.2f}s, client_id={self.client_id}"
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
                    "error": f"执行 MCP 工具失败: {str(e)}",
                },
            }

    async def _execute_local_interactive(
        self,
        message_id: str,
        action: str,
        interactive_session_id: Optional[str] = None,
        command: Optional[str] = None,
        args: Optional[list] = None,
        cwd: Optional[str] = None,
        input_text: Optional[str] = None,
        last_stdout_seq: int = 0,
        last_stderr_seq: int = 0,
        wait_ms: int = 0,
        max_output_bytes: int = 65536,
    ) -> dict:
        start_time = time.time()
        try:
            if action == "start":
                if not command:
                    raise ValueError("command is required for start action")
                full_command = command
                if args:
                    full_command = f"{command} {' '.join(args)}"
                payload = await self.interactive_executor.start_session(command=full_command, cwd=cwd)
            elif action == "input":
                if not interactive_session_id:
                    raise ValueError("interactive_session_id is required for input action")
                payload = await self.interactive_executor.send_input(
                    session_id=interactive_session_id,
                    input_text=input_text or "",
                )
            elif action == "poll":
                if not interactive_session_id:
                    raise ValueError("interactive_session_id is required for poll action")
                payload = await self.interactive_executor.poll(
                    session_id=interactive_session_id,
                    last_stdout_seq=last_stdout_seq,
                    last_stderr_seq=last_stderr_seq,
                    wait_ms=wait_ms,
                    max_output_bytes=max_output_bytes,
                )
            elif action == "stop":
                if not interactive_session_id:
                    raise ValueError("interactive_session_id is required for stop action")
                payload = await self.interactive_executor.stop_session(
                    session_id=interactive_session_id,
                    force=False,
                )
            else:
                raise ValueError(f"unknown interactive action: {action}")

            elapsed = time.time() - start_time
            logger.info(
                f"[CLIENT-INTERACTIVE-SUCCESS] Interactive action completed: message_id={message_id}, "
                f"action={action}, elapsed={elapsed:.2f}s, state={payload.get('state')}, client_id={self.client_id}"
            )
            return {
                "id": message_id,
                "type": "local_interactive_result",
                "success": True,
                "data": payload,
            }
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                f"[CLIENT-INTERACTIVE-ERROR] Interactive action failed: message_id={message_id}, "
                f"action={action}, error={e}, elapsed={elapsed:.2f}s, client_id={self.client_id}",
                exc_info=True,
            )
            return {
                "id": message_id,
                "type": "local_interactive_result",
                "success": False,
                "data": {
                    "session_id": interactive_session_id,
                    "state": "error",
                    "exit_code": None,
                    "error": f"interactive action failed: {str(e)}",
                },
            }

    async def _execute_doc_read(
        self,
        message_id: str,
        file_path: str,
        encoding: Optional[str] = None,
    ) -> dict:
        """
        执行文档读取

        Args:
            message_id: 消息ID
            file_path: 文件路径
            encoding: 文件编码

        Returns:
            dict: 响应消息
        """
        start_time = time.time()
        try:
            logger.info(
                f"[CLIENT-DOC-READ-EXEC-START] Executing doc read: message_id={message_id}, "
                f"file_path={file_path}, encoding={encoding}, client_id={self.client_id}"
            )

            # 调用 document_operations.read_document
            result = document_operations.read_document(file_path=file_path, encoding=encoding)

            elapsed = time.time() - start_time
            logger.info(
                f"[CLIENT-DOC-READ-EXEC-SUCCESS] Doc read completed: message_id={message_id}, "
                f"success={result.get('success')}, elapsed={elapsed:.2f}s, client_id={self.client_id}"
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
            return {
                "id": message_id,
                "type": "doc_read_result",
                "success": False,
                "data": {
                    "content": None,
                    "encoding": None,
                    "size": None,
                    "error": f"执行文档读取失败: {str(e)}",
                },
            }

    async def _execute_doc_write(
        self,
        message_id: str,
        file_path: str,
        content: str,
        encoding: str = "utf-8",
        create_dirs: bool = True,
    ) -> dict:
        """
        执行文档写入

        Args:
            message_id: 消息ID
            file_path: 文件路径
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
                f"file_path={file_path}, content_len={len(content)}, encoding={encoding}, "
                f"create_dirs={create_dirs}, client_id={self.client_id}"
            )

            # 调用 document_operations.write_document
            result = document_operations.write_document(
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
            return {
                "id": message_id,
                "type": "doc_write_result",
                "success": False,
                "data": {
                    "path": None,
                    "size": None,
                    "error": f"执行文档写入失败: {str(e)}",
                },
            }

    async def _execute_doc_edit(
        self,
        message_id: str,
        file_path: str,
        operation: str,
        new_content: str,
        old_content: Optional[str] = None,
        encoding: Optional[str] = None,
    ) -> dict:
        """
        执行文档编辑

        Args:
            message_id: 消息ID
            file_path: 文件路径
            operation: 操作类型（replace, append, prepend）
            new_content: 新内容
            old_content: 旧内容（仅 replace 操作需要）
            encoding: 文件编码

        Returns:
            dict: 响应消息
        """
        start_time = time.time()
        try:
            logger.info(
                f"[CLIENT-DOC-EDIT-EXEC-START] Executing doc edit: message_id={message_id}, "
                f"file_path={file_path}, operation={operation}, encoding={encoding}, client_id={self.client_id}"
            )

            # 调用 document_operations.edit_document
            result = document_operations.edit_document(
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
            return {
                "id": message_id,
                "type": "doc_edit_result",
                "success": False,
                "data": {
                    "operation": operation,
                    "size": None,
                    "path": None,
                    "error": f"执行文档编辑失败: {str(e)}",
                },
            }

    async def _listen(self):
        """监听服务端消息"""
        try:
            logger.info(f"[CLIENT-LISTEN-START] Started listening for messages: client_id={self.client_id}")

            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        # 解析消息
                        data = json.loads(msg.data)
                        logger.debug(f"[CLIENT-WS-RECV] Received raw message: data={data}, client_id={self.client_id}")

                        # 处理命令
                        response = await self._handle_command(data)

                        # 发送响应（如果有的话）
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
                f"[CLIENT-LISTEN-ERROR] Error in message listener: error={e}, client_id={self.client_id}", exc_info=True
            )

    async def connect(self):
        """建立 WebSocket 连接"""
        ws_url = self._get_ws_url()
        logger.info(
            f"[CLIENT-CONNECT-START] Attempting to connect to server: url={ws_url}, "
            f"client_id={self.client_id}, workspace_id={self.workspace_id}"
        )

        try:
            self.session = aiohttp.ClientSession()
            logger.debug(f"[CLIENT-SESSION-CREATED] aiohttp session created: client_id={self.client_id}")

            self.ws = await self.session.ws_connect(ws_url)
            logger.info(
                f"[CLIENT-CONNECT-SUCCESS] WebSocket connection established: client_id={self.client_id}, "
                f"ws_closed={self.ws.closed}"
            )

            # 启动心跳任务
            self.heartbeat_task = asyncio.create_task(self._send_heartbeat())
            logger.info(
                f"[CLIENT-HEARTBEAT-TASK] Heartbeat task started: interval={self.heartbeat_interval}s, "
                f"client_id={self.client_id}"
            )

            return True

        except Exception as e:
            logger.error(
                f"[CLIENT-CONNECT-ERROR] Failed to connect: error={e}, client_id={self.client_id}", exc_info=True
            )
            if self.session:
                await self.session.close()
            return False

    async def disconnect(self):
        """断开 WebSocket 连接"""
        logger.info(f"[CLIENT-DISCONNECT-START] Starting disconnect process: client_id={self.client_id}")

        # 停止心跳任务
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
        """运行客户端（带自动重连）"""
        self.running = True
        logger.info(
            f"[CLIENT-RUN-START] Starting client: client_id={self.client_id}, "
            f"server_url={self.server_url}, workspace_id={self.workspace_id}"
        )

        # 连接 MCP 服务
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
            # 尝试连接
            logger.info(
                f"[CLIENT-RECONNECT] Attempting to connect: attempt={reconnect_count + 1}, client_id={self.client_id}"
            )

            if await self.connect():
                reconnect_count = 0  # 重置重连计数
                try:
                    # 监听消息
                    await self._listen()
                except Exception as e:
                    logger.error(
                        f"[CLIENT-RUN-ERROR] Error during client run: error={e}, client_id={self.client_id}",
                        exc_info=True,
                    )
                finally:
                    # 断开连接
                    await self.disconnect()
            else:
                reconnect_count += 1
                logger.warning(
                    f"[CLIENT-CONNECT-FAILED] Failed to establish connection: attempts={reconnect_count}, "
                    f"client_id={self.client_id}"
                )

            # 如果还在运行，等待后重连
            if self.running:
                logger.info(
                    f"[CLIENT-RECONNECT-WAIT] Waiting for reconnection: delay={self.reconnect_interval}s, "
                    f"client_id={self.client_id}"
                )
                await asyncio.sleep(self.reconnect_interval)

    async def stop(self):
        """停止客户端"""
        logger.info(f"[CLIENT-STOP-START] Stopping client: client_id={self.client_id}")

        self.running = False
        await self.disconnect()

        # 断开 MCP 服务
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
