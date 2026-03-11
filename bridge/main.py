import asyncio
import base64
import json
import logging
from typing import Any, Dict

import typer

from bridge.api import APIError, NetworkError, PairingError, get_api_client
from bridge.client_id import get_client_id
from bridge.config import ConfigError, get_config
from bridge.mcp_manager import get_mcp_manager
from bridge.skill_cli import skill_app
from bridge.skill_manager import get_skill_manager
from bridge.websocket_client import WebSocketClient

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

app = typer.Typer(add_completion=False, pretty_exceptions_show_locals=False)
app.add_typer(skill_app, name="skill")


def decode_verification_code(verification_code: str) -> Dict[str, Any]:
    """
    解码验证码，提取时间戳、workspace_id、随机码

    Args:
        verification_code: 编码的验证码

    Returns:
        Dict[str, Any]: 包含 ts (timestamp), wid (workspace_id), rand (random_code) 的字典

    Raises:
        ValueError: 验证码格式无效
    """
    try:
        # 添加可能缺失的填充字符
        padding = 4 - (len(verification_code) % 4)
        if padding != 4:
            verification_code += "=" * padding

        # Base64 解码
        decoded_bytes = base64.urlsafe_b64decode(verification_code)
        json_str = decoded_bytes.decode("utf-8")

        # 解析 JSON
        code_data = json.loads(json_str)

        # 验证必需字段
        if not all(key in code_data for key in ["ts", "wid", "rand"]):
            raise ValueError("Missing required fields in verification code")

        return code_data

    except Exception as e:
        raise ValueError(f"Invalid verification code format: {str(e)}")


@app.command()
def pair(
    code: str = typer.Argument(..., help="服务端提供的验证码"),
    server_url: str = typer.Argument(..., help="服务端URL地址"),
):
    """
    配对到服务端

    使用验证码将本地 bridge 与服务端配对。验证码包含工作区ID等信息，无需手动输入。

    使用方法：
      castrel-bridge-cli pair <验证码> <服务端URL>

    例如：
      castrel-bridge-cli pair eyJ0cyI6MTczNTA4ODQwMCwid2lkIjoiZGVmYXVsdCIsInJhbmQiOiIxMjM0NTYifQ https://server.example.com
    """
    config = get_config()
    api_client = get_api_client()

    try:
        # 解码验证码以获取 workspace_id
        typer.echo("正在解析验证码...")
        try:
            code_info = decode_verification_code(code)
            workspace_id = code_info["wid"]

            typer.secho("✓ 验证码解析成功", fg=typer.colors.GREEN)
            typer.echo(f"  工作区ID: {workspace_id}")
        except ValueError as e:
            typer.secho(f"✗ 验证码格式无效: {e}", fg=typer.colors.RED, err=True)
            typer.echo("提示: 请确保使用从服务端获取的完整验证码", err=True)
            raise typer.Exit(1)

        # 生成客户端ID
        typer.echo("\n正在生成客户端标识...")
        client_id = get_client_id()
        typer.echo(f"客户端ID: {client_id}")

        # 连接服务端并验证
        typer.echo(f"\n正在连接到服务端: {server_url}")
        typer.echo(f"使用验证码: {code}")
        typer.echo(f"工作区ID: {workspace_id}")

        # 调用服务端验证接口
        api_client.verify_pairing(server_url, code, client_id, workspace_id)

        # 验证成功，保存配置
        config.save(server_url, code, client_id, workspace_id)

        typer.secho("✓ 配对成功！", fg=typer.colors.GREEN)
        typer.echo(f"配置已保存到: {config.config_file}")

        # 提交客户端信息到服务端（创建/更新会话），即使未配置 MCP 也必须执行，否则 WebSocket 会因找不到 session 而握手失败
        typer.echo("\n正在向服务端注册客户端信息...")
        try:
            mcp_manager = get_mcp_manager()
            skill_manager = get_skill_manager()

            async def register_client_info():
                tools_payload: Dict[str, Any] = {}
                try:
                    # 尝试连接 MCP 服务并获取 tools（可选）
                    count = await mcp_manager.connect_all()
                    if count == 0:
                        typer.echo("未配置 MCP 服务，将以空 tools 注册")
                    else:
                        typer.echo(f"已连接 {count} 个 MCP 服务")
                        tools_payload = await mcp_manager.get_all_tools()
                        total_tools = sum(len(v) for v in tools_payload.values())
                        typer.echo(f"获取到 {total_tools} 个 tools")
                except Exception as e:
                    # MCP tools 获取失败不应阻塞会话创建；可后续使用 mcp-sync 再同步
                    typer.secho(f"⚠ MCP tools 获取失败: {e}", fg=typer.colors.YELLOW)
                    typer.echo("提示: 将以空 tools 继续注册，可稍后执行 'castrel-bridge-cli mcp-sync'")
                    tools_payload = {}
                finally:
                    try:
                        await mcp_manager.disconnect_all()
                    except Exception:
                        pass

                # 加载本地 Skills
                skills_payload = skill_manager.get_skills_for_registration()
                skill_count = len(skills_payload)
                if skill_count > 0:
                    typer.echo(f"发现 {skill_count} 个本地 Skills")
                else:
                    typer.echo("未发现本地 Skills")

                typer.echo("正在提交客户端信息到服务端...")
                await api_client._send_client_info(
                    server_url, client_id, code, workspace_id, tools_payload,
                    skills=skills_payload,
                )

            asyncio.run(register_client_info())
            typer.secho("✓ 客户端信息已注册（会话已创建）", fg=typer.colors.GREEN)

        except Exception as e:
            typer.secho(f"✗ 客户端信息注册失败: {e}", fg=typer.colors.RED, err=True)
            raise typer.Exit(1)

        typer.echo("\n提示: 使用 'castrel-bridge-cli start' 启动 bridge 服务")

    except PairingError as e:
        typer.secho(f"✗ 配对失败: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    except NetworkError as e:
        typer.secho(f"✗ 网络错误: {e}", fg=typer.colors.RED, err=True)
        typer.echo("请检查服务端地址是否正确以及网络连接是否正常", err=True)
        raise typer.Exit(1)
    except ConfigError as e:
        typer.secho(f"✗ 配置错误: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    except APIError as e:
        typer.secho(f"✗ API 错误: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"✗ 未知错误: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


@app.command()
def start(
    daemon: bool = typer.Option(False, "--daemon", "-d", help="在后台运行"),
):
    """
    启动 bridge 服务

    启动 bridge 并连接到已配对的服务端。

    前台运行（默认）：
      castrel-bridge-cli start

    后台运行：
      castrel-bridge-cli start --daemon
      castrel-bridge-cli start -d
    """
    config = get_config()

    try:
        # 加载配置
        config_data = config.load()
        server_url = config_data["server_url"]
        client_id = config_data["client_id"]
        verification_code = config_data["verification_code"]
        workspace_id = config_data["workspace_id"]

        typer.secho("=== 启动 Bridge 服务 ===", bold=True)
        typer.echo(f"服务端: {server_url}")
        typer.echo(f"客户端ID: {client_id}")
        typer.echo(f"工作区ID: {workspace_id}")

        if daemon:
            typer.echo("正在后台启动 bridge...")
            # TODO: 实现守护进程逻辑
            typer.secho("✗ 后台运行模式暂未实现", fg=typer.colors.YELLOW)
            typer.echo("提示: 请使用前台模式运行")
            raise typer.Exit(1)
        else:
            typer.echo("\n正在连接到服务端...")
            typer.echo("提示: 按 Ctrl+C 停止服务\n")

            # 创建 WebSocket 客户端
            ws_client = WebSocketClient(
                server_url=server_url,
                client_id=client_id,
                verification_code=verification_code,
                workspace_id=workspace_id,
            )

            # 运行客户端
            try:
                asyncio.run(ws_client.run())
            except KeyboardInterrupt:
                typer.echo("\n正在停止 bridge...")
                typer.secho("✓ Bridge 已停止", fg=typer.colors.GREEN)
            except Exception as e:
                typer.secho(f"\n✗ 运行错误: {e}", fg=typer.colors.RED, err=True)
                raise typer.Exit(1)

    except ConfigError as e:
        typer.secho(f"✗ {e}", fg=typer.colors.RED, err=True)
        typer.echo("提示: 请先使用 'castrel-bridge-cli pair' 命令进行配对", err=True)
        raise typer.Exit(1)


@app.command()
def config():
    """
    查看配置信息
    """
    config_obj = get_config()

    try:
        # 加载配置
        config_data = config_obj.load()

        typer.secho("=== 配置信息 ===", bold=True)
        typer.echo(f"配置文件: {config_obj.config_file}")
        typer.echo(f"服务端URL: {config_data['server_url']}")
        typer.echo(f"验证码: {config_data['verification_code']}")
        typer.echo(f"客户端ID: {config_data['client_id']}")
        typer.echo(f"工作区ID: {config_data['workspace_id']}")

        if "paired_at" in config_data:
            typer.echo(f"配对时间: {config_data['paired_at']}")

    except ConfigError as e:
        typer.secho(f"✗ {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


@app.command()
def status():
    """
    查看 bridge 运行状态
    """
    config = get_config()

    try:
        # 加载配置
        config_data = config.load()

        typer.secho("=== Bridge 状态 ===", bold=True)
        typer.echo("配对状态: ", nl=False)
        typer.secho("已配对", fg=typer.colors.GREEN)
        typer.echo(f"服务端: {config_data['server_url']}")
        typer.echo(f"客户端ID: {config_data['client_id']}")
        typer.echo(f"工作区ID: {config_data['workspace_id']}")

        if "paired_at" in config_data:
            typer.echo(f"配对时间: {config_data['paired_at']}")

        # TODO: 添加运行状态检查（是否在运行、连接状态等）
        typer.echo("运行状态: ", nl=False)
        typer.secho("未运行", fg=typer.colors.YELLOW)
        typer.echo("提示: 使用 'castrel-bridge-cli start' 启动服务")

    except ConfigError:
        typer.secho("=== Bridge 状态 ===", bold=True)
        typer.echo("配对状态: ", nl=False)
        typer.secho("未配对", fg=typer.colors.YELLOW)
        typer.echo("提示: 使用 'castrel-bridge-cli pair' 命令进行配对")


@app.command()
def stop():
    """
    停止 bridge 服务
    """
    typer.echo("正在停止 bridge...")
    typer.secho("✓ Bridge 已停止", fg=typer.colors.GREEN)


@app.command()
def unpair():
    """
    取消配对
    """
    config = get_config()

    try:
        # 检查配置是否存在
        if not config.exists():
            typer.secho("✗ 未找到配对配置", fg=typer.colors.YELLOW)
            raise typer.Exit(0)

        # 显示当前配置信息
        config_data = config.load()
        typer.echo(f"当前配对服务端: {config_data['server_url']}")
        typer.echo(f"客户端ID: {config_data['client_id']}")
        typer.echo(f"工作区ID: {config_data['workspace_id']}")

        # 确认删除
        confirm = typer.confirm("确定要取消配对吗？")
        if confirm:
            typer.echo("正在取消配对...")
            config.delete()
            typer.secho("✓ 已取消配对", fg=typer.colors.GREEN)
        else:
            typer.echo("已取消")

    except ConfigError as e:
        typer.secho(f"✗ {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


@app.command()
def logs(
    lines: int = typer.Option(50, "--lines", "-n", help="显示最后N行日志"),
    follow: bool = typer.Option(False, "--follow", "-f", help="实时跟踪日志"),
):
    """
    查看 bridge 日志
    """
    if follow:
        typer.echo("正在跟踪日志... (Ctrl+C 退出)")
    else:
        typer.echo(f"最近 {lines} 行日志:")


@app.command()
def mcp_list():
    """
    列出配置的 MCP 服务
    """
    mcp_manager = get_mcp_manager()
    servers = mcp_manager.get_server_list()

    if not servers:
        typer.echo("未配置 MCP 服务")
        typer.echo(f"配置文件: {mcp_manager.config_file}")
        typer.echo("提示: 参考 mcp.json.example 创建配置文件")
        return

    typer.secho("=== MCP 服务列表 ===", bold=True)
    typer.echo(f"配置文件: {mcp_manager.config_file}")
    typer.echo(f"共 {len(servers)} 个服务:\n")

    for server in servers:
        name = server["name"]
        transport = server["transport"]

        typer.echo(f"📦 {name}")
        typer.echo(f"   传输方式: {transport}")

        if transport == "stdio":
            command = server["command"]
            args = server["args"]
            typer.echo(f"   命令: {command} {' '.join(args)}")
            if server["env"]:
                typer.echo(f"   环境变量: {len(server['env'])} 个")
        elif transport == "http":
            typer.echo(f"   URL: {server['url']}")

        typer.echo()


@app.command()
def mcp_sync():
    """
    同步 MCP tools 信息到服务端
    """
    config = get_config()

    try:
        # 加载配置
        config_data = config.load()
        server_url = config_data["server_url"]
        client_id = config_data["client_id"]
        verification_code = config_data["verification_code"]
        workspace_id = config_data["workspace_id"]

        typer.secho("=== 同步 MCP Tools ===", bold=True)
        typer.echo(f"服务端: {server_url}")
        typer.echo(f"客户端ID: {client_id}")
        typer.echo(f"工作区ID: {workspace_id}\n")

        mcp_manager = get_mcp_manager()
        skill_manager = get_skill_manager()
        api_client = get_api_client()

        # 异步同步 MCP tools
        async def sync_mcp_tools():
            tools_by_server: Dict[str, Any] = {}
            try:
                # 连接所有 MCP 服务
                typer.echo("正在连接 MCP 服务...")
                count = await mcp_manager.connect_all()

                if count == 0:
                    typer.secho("✗ 没有可用的 MCP 服务", fg=typer.colors.YELLOW)
                    typer.echo(f"配置文件: {mcp_manager.config_file}")
                    typer.echo("提示: 使用 'castrel-bridge-cli mcp-list' 查看配置")
                    return

                typer.secho(f"✓ 已连接 {count} 个 MCP 服务", fg=typer.colors.GREEN)

                # 获取所有 tools
                typer.echo("\n正在获取 tools 信息...")
                tools_by_server = await mcp_manager.get_all_tools()
                total_tools = sum(len(v) for v in tools_by_server.values())
                typer.secho(f"✓ 获取到 {total_tools} 个 tools", fg=typer.colors.GREEN)

                # 显示 tools 概览
                if tools_by_server:
                    typer.echo("\nTools 概览:")
                    for server, server_tools in tools_by_server.items():
                        typer.echo(f"  {server}: {len(server_tools)} 个 tools")
                        for tool in server_tools[:3]:  # 只显示前3个
                            name = tool.get("name") if isinstance(tool, dict) else str(tool)
                            typer.echo(f"    - {name}")
                        if len(server_tools) > 3:
                            typer.echo(f"    ... 还有 {len(server_tools) - 3} 个")

                # 同步 tools + skills（保持会话能力完整）
                skills_payload = skill_manager.get_skills_for_registration()
                typer.echo("\n正在发送到服务端...")
                await api_client._send_client_info(
                    server_url,
                    client_id,
                    verification_code,
                    workspace_id,
                    tools_by_server,
                    skills=skills_payload,
                )
                typer.secho(
                    f"✓ MCP tools 与 Skills 已同步 (tools: {total_tools}, skills: {len(skills_payload)})",
                    fg=typer.colors.GREEN,
                )
            finally:
                await mcp_manager.disconnect_all()

        asyncio.run(sync_mcp_tools())

    except ConfigError as e:
        typer.secho(f"✗ {e}", fg=typer.colors.RED, err=True)
        typer.echo("提示: 请先使用 'castrel-bridge-cli pair' 命令进行配对", err=True)
        raise typer.Exit(1)
    except (NetworkError, APIError) as e:
        typer.secho(f"✗ 同步失败: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.secho(f"✗ 未知错误: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


def run():
    app()


if __name__ == "__main__":
    run()
