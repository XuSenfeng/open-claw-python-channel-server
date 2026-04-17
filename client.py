"""
Python Virtual Platform Client - 本地测试客户端
连接到虚拟平台，模拟用户交互
"""

import asyncio
import json
import logging
from typing import Any, Dict, Optional

import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("PythonClient")


class VirtualPlatformClient:
    """虚拟平台客户端"""

    def __init__(self, uri: str = "ws://127.0.0.1:8765"):
        self.uri = uri
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.user_id: Optional[str] = None
        self.running = False

    async def connect(self):
        """连接到服务器"""
        try:
            logger.info(f"Connecting to {self.uri}...")
            self.websocket = await websockets.connect(self.uri)
            logger.info("✅ Connected to Virtual Platform Server")
            self.running = True

            # 接收欢迎消息
            welcome = await self.websocket.recv()
            welcome_data = json.loads(welcome)
            logger.info(f"Received welcome: {welcome_data}")

            return True
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            return False

    async def send_message(self, user_id: str, chat_id: str, content: str):
        """发送消息"""
        if not self.websocket:
            logger.error("Not connected")
            return

        message = {
            "type": "simulate_user_message",
            "user_id": user_id,
            "chat_id": chat_id,
            "content": content,
        }

        try:
            await self.websocket.send(json.dumps(message))
            logger.info(f"Sent: {content}")
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

    async def get_messages(self, user_id: str, chat_id: str):
        """获取消息历史"""
        if not self.websocket:
            logger.error("Not connected")
            return

        message = {"type": "get_messages", "user_id": user_id, "chat_id": chat_id}

        try:
            await self.websocket.send(json.dumps(message))

            # 等待响应
            response_raw = await asyncio.wait_for(self.websocket.recv(), timeout=5)
            response = json.loads(response_raw)

            logger.info(f"Message history:")
            if "messages" in response:
                for msg in response["messages"]:
                    from_user = msg.get("from_name", msg.get("from", "Unknown"))
                    logger.info(f"  [{msg.get('timestamp')}] {from_user}: {msg.get('content')}")
            else:
                logger.info(f"Response: {response}")
        except asyncio.TimeoutError:
            logger.error("Timeout waiting for response")
        except Exception as e:
            logger.error(f"Failed to get messages: {e}")

    async def ping(self):
        """测试连接"""
        if not self.websocket:
            logger.error("Not connected")
            return

        message = {"type": "ping"}
        try:
            await self.websocket.send(json.dumps(message))
            response_raw = await asyncio.wait_for(self.websocket.recv(), timeout=5)
            response = json.loads(response_raw)
            logger.info(f"Ping response: {response}")
        except Exception as e:
            logger.error(f"Ping failed: {e}")

    async def listen_for_responses(self):
        """监听来自服务器的响应"""
        if not self.websocket:
            logger.error("Not connected")
            return

        try:
            while self.running:
                try:
                    message_raw = await asyncio.wait_for(
                        self.websocket.recv(), timeout=1
                    )
                    message = json.loads(message_raw)

                    msg_type = message.get("type")
                    if msg_type == "send_message_response":
                        logger.info(
                            f"💬 Message sent: {message.get('message_id')} - {message.get('status')}"
                        )
                    else:
                        logger.info(f"📨 Received: {message}")

                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Error listening: {e}")
                    break
        finally:
            self.running = False

    async def disconnect(self):
        """断开连接"""
        if self.websocket:
            await self.websocket.close()
            logger.info("Disconnected")


async def interactive_cli(client: VirtualPlatformClient):
    """交互式CLI"""
    print("\n🎯 Virtual Platform Interactive Client")
    print("Commands:")
    print("  send <user_id> <chat_id> <message> - Send a message")
    print("  history <user_id> <chat_id>         - Get message history")
    print("  ping                                  - Ping server")
    print("  quit                                  - Exit")
    print()

    while client.running:
        try:
            command = input(">>> ").strip()

            if not command:
                continue

            parts = command.split(maxsplit=3)
            cmd = parts[0].lower()

            if cmd == "send" and len(parts) >= 4:
                user_id, chat_id, message = parts[1], parts[2], parts[3]
                await client.send_message(user_id, chat_id, message)

            elif cmd == "history" and len(parts) >= 3:
                user_id, chat_id = parts[1], parts[2]
                await client.get_messages(user_id, chat_id)

            elif cmd == "ping":
                await client.ping()

            elif cmd == "quit":
                client.running = False
                break

            else:
                print("❌ Invalid command")

        except KeyboardInterrupt:
            client.running = False
            break
        except Exception as e:
            logger.error(f"Error: {e}")


async def demo_scenario(client: VirtualPlatformClient):
    """演示场景"""
    logger.info("\n=== Demo Scenario: 模拟用户交互 ===\n")

    # 场景1: Alice发送消息
    logger.info("📍 [场景1] Alice发送消息到虚拟平台")
    await client.send_message("user001", "chat_001", "你好，我想查询今天的天气")
    await asyncio.sleep(1)

    # 获取消息历史
    logger.info("\n📍 [场景2] 查看Alice的消息历史")
    await client.get_messages("user001", "chat_001")
    await asyncio.sleep(1)

    # 场景3: Bob发送消息
    logger.info("\n📍 [场景3] Bob发送消息")
    await client.send_message("user002", "chat_002", "帮我翻译一下这句英文")
    await asyncio.sleep(1)

    logger.info("\n📍 [场景4] 查看Bob的消息历史")
    await client.get_messages("user002", "chat_002")

    logger.info("\n✅ Demo scenario completed!\n")


async def main():
    client = VirtualPlatformClient("ws://127.0.0.1:8765")

    # 连接到服务器
    if not await client.connect():
        return

    # 创建后台监听任务
    listen_task = asyncio.create_task(client.listen_for_responses())

    try:
        # 运行演示场景
        await demo_scenario(client)

        # 进入交互模式
        await interactive_cli(client)

    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
    finally:
        client.running = False
        await client.disconnect()
        await listen_task


if __name__ == "__main__":
    asyncio.run(main())
