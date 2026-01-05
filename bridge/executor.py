"""
命令执行器模块

负责执行 shell 命令并返回结果
"""

import asyncio
import os
from typing import Dict, Optional


class ExecutionResult:
    """命令执行结果"""

    def __init__(self, exit_code: int, stdout: str, stderr: str, execution_time: float):
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.execution_time = execution_time

    def to_dict(self) -> Dict:
        """转换为字典格式"""
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "execution_time": self.execution_time,
        }


class CommandExecutor:
    """命令执行器"""

    def __init__(self, working_dir: Optional[str] = None, timeout: float = 300.0):
        """
        初始化命令执行器

        Args:
            working_dir: 工作目录，默认为当前目录
            timeout: 命令执行超时时间（秒）
        """
        self.working_dir = working_dir or os.getcwd()
        self.timeout = timeout

    async def execute(self, command: str) -> ExecutionResult:
        """
        异步执行 shell 命令

        Args:
            command: 要执行的命令

        Returns:
            ExecutionResult: 命令执行结果
        """
        import time

        start_time = time.time()

        try:
            # 展开路径中的 ~ 和环境变量
            working_dir = os.path.expanduser(os.path.expandvars(self.working_dir))

            # 创建子进程执行命令
            # stdin 设置为 DEVNULL，防止命令等待输入而挂起
            process = await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                env=os.environ.copy(),
            )

            # 等待命令执行完成（带超时）
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=self.timeout)
            except asyncio.TimeoutError:
                # 超时，终止进程
                process.kill()
                await process.wait()
                execution_time = time.time() - start_time
                return ExecutionResult(
                    exit_code=-1,
                    stdout="",
                    stderr=f"命令执行超时（超过 {self.timeout} 秒）",
                    execution_time=execution_time,
                )

            # 解码输出
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            exit_code = process.returncode

            execution_time = time.time() - start_time

            return ExecutionResult(exit_code=exit_code, stdout=stdout, stderr=stderr, execution_time=execution_time)

        except Exception as e:
            execution_time = time.time() - start_time
            return ExecutionResult(
                exit_code=-2, stdout="", stderr=f"命令执行异常: {str(e)}", execution_time=execution_time
            )


# 全局命令执行器实例
_executor = CommandExecutor()


def get_executor() -> CommandExecutor:
    """获取全局命令执行器实例"""
    return _executor
