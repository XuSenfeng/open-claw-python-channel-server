"""
Python Virtual Platform Server - 虚拟消息平台
模拟第三方消息平台（类似Feishu/WeChat）
通过WebSocket与OpenClaw插件通信
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set

import websockets
from websockets.server import WebSocketServerProtocol

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("PythonPlatform")


class VirtualPlatformUser:
    """虚拟平台用户"""

    def __init__(self, user_id: str, name: str):
        self.user_id = user_id
        self.name = name
        self.chat_sessions: Dict[str, List[Dict[str, Any]]] = {}
        self.active_chat_id = "default_chat"

    def get_or_create_chat(self, chat_id: str) -> List[Dict[str, Any]]:
        """获取或创建聊天会话"""
        if chat_id not in self.chat_sessions:
            self.chat_sessions[chat_id] = []
        return self.chat_sessions[chat_id]

    def start_new_conversation(self, chat_id: Optional[str] = None) -> str:
        """显式开启新会话，并切换为当前会话"""
        next_chat_id = chat_id or f"chat_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self.active_chat_id = next_chat_id
        self.get_or_create_chat(next_chat_id)
        return next_chat_id


class VirtualPlatformServer:
    """虚拟平台服务器"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = port
        self.users: Dict[str, VirtualPlatformUser] = {}
        self.connected_plugins: Set[WebSocketServerProtocol] = set()
        self.message_handlers: List[Callable] = []
        self._init_demo_users()

    def _init_demo_users(self):
        """初始化演示用户"""
        self.users["user001"] = VirtualPlatformUser("user001", "Alice")
        self.users["user002"] = VirtualPlatformUser("user002", "Bob")
        logger.info("Demo users initialized: Alice, Bob")

    def register_message_handler(self, handler: Callable):
        """注册消息处理器"""
        self.message_handlers.append(handler)

    async def broadcast_to_plugins(self, message: Dict[str, Any]):
        """广播消息到所有已连接的插件"""
        if not self.connected_plugins:
            logger.warning("No plugins connected to broadcast message")
            return

        logger.info(f"Broadcasting to {len(self.connected_plugins)} plugins: {message}")
        disconnected = set()

        for plugin_ws in self.connected_plugins:
            try:
                await plugin_ws.send(json.dumps(message))
            except Exception as e:
                logger.error(f"Failed to send to plugin: {e}")
                disconnected.add(plugin_ws)

        self.connected_plugins -= disconnected

    async def handle_plugin_connection(self, websocket: WebSocketServerProtocol):
        """处理插件连接"""
        plugin_id = str(uuid.uuid4())[:8]
        self.connected_plugins.add(websocket)
        logger.info(f"Plugin connected: {plugin_id}")

        try:
            # 发送欢迎消息
            welcome = {
                "type": "connect",
                "platform_id": "python-virtual-platform",
                "plugin_id": plugin_id,
                "timestamp": datetime.now().isoformat(),
                "features": ["messages", "reactions", "typing"],
            }
            await websocket.send(json.dumps(welcome))

            async for message_raw in websocket:
                try:
                    message = json.loads(message_raw)
                    # 只有 simulate_user_message 是来自模拟器，其他可能来自插件自身
                    if message.get("type") == "simulate_user_message":
                        logger.info(f"Received simulate_user_message from {message.get('user_id')}")
                    await self.handle_plugin_message(message, plugin_id, websocket)
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON from plugin: {message_raw}")
                except Exception as e:
                    logger.error(f"Error processing plugin message: {e}")

        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Plugin disconnected: {plugin_id}")
        finally:
            self.connected_plugins.discard(websocket)

    async def handle_plugin_message(
        self, message: Dict[str, Any], plugin_id: str, websocket: WebSocketServerProtocol
    ):
        """处理来自插件的消息"""
        msg_type = message.get("type")
        logger.info(f"Plugin {plugin_id} sent: {msg_type}")

        if msg_type == "send_message":
            # 插件发送消息给用户
            await self._handle_send_message(message, websocket)

        elif msg_type == "get_messages":
            # 插件查询消息历史
            await self._handle_get_messages(message, websocket)

        elif msg_type == "ping":
            # 测试连接
            response = {"type": "pong", "timestamp": datetime.now().isoformat()}
            await websocket.send(json.dumps(response))

        elif msg_type == "simulate_user_message":
            # 模拟用户发送消息
            logger.info(f"Handling simulate_user_message for user: {message.get('user_id')}")
            await self._handle_simulate_message(message)

        elif msg_type == "start_new_conversation":
            # 显式开启新会话
            await self._handle_start_new_conversation(message, websocket)

        else:
            logger.warning(f"Unknown message type: {msg_type}")
            response = {"type": "error", "error": f"Unknown message type: {msg_type}"}
            await websocket.send(json.dumps(response))

    async def _handle_send_message(self, message: Dict[str, Any], websocket: WebSocketServerProtocol):
        """处理插件发送消息（阿助理回复）"""
        chat_id = message.get("chat_id")
        user_id = message.get("to_user_id")
        content = message.get("content")

        if not all([chat_id, user_id, content]):
            response = {
                "type": "error",
                "error": "Missing required fields: chat_id, to_user_id, content",
            }
            await websocket.send(json.dumps(response))
            return

        # 保存消息
        if user_id in self.users:
            chat = self.users[user_id].get_or_create_chat(chat_id)
            msg_record = {
                "id": str(uuid.uuid4()),
                "from": "bot",
                "content": content,
                "timestamp": datetime.now().isoformat(),
            }
            chat.append(msg_record)

            logger.info(f"Bot replied to {user_id} in chat {chat_id}: {content}")

            # 主动推送机器人回复，客户端可实时显示，无需轮询 get_messages
            await self.broadcast_to_plugins(
                {
                    "type": "bot_message",
                    "user_id": user_id,
                    "user_name": self.users[user_id].name,
                    "chat_id": chat_id,
                    "message_id": msg_record["id"],
                    "content": content,
                    "from": "bot",
                    "timestamp": msg_record["timestamp"],
                }
            )

            # 返回成功响应
            response = {
                "type": "send_message_response",
                "message_id": msg_record["id"],
                "status": "success",
                "timestamp": datetime.now().isoformat(),
            }
            await websocket.send(json.dumps(response))
        else:
            response = {"type": "error", "error": f"User {user_id} not found"}
            await websocket.send(json.dumps(response))

    async def _handle_get_messages(self, message: Dict[str, Any], websocket: WebSocketServerProtocol):
        """处理插件查询消息"""
        user_id = message.get("user_id")
        chat_id = message.get("chat_id")

        if not user_id or not chat_id:
            response = {"type": "error", "error": "Missing required fields: user_id, chat_id"}
            await websocket.send(json.dumps(response))
            return

        if user_id in self.users:
            chat = self.users[user_id].get_or_create_chat(chat_id)
            response = {
                "type": "get_messages_response",
                "messages": chat,
                "user_name": self.users[user_id].name,
            }
            await websocket.send(json.dumps(response))
        else:
            response = {"type": "error", "error": f"User {user_id} not found"}
            await websocket.send(json.dumps(response))

    async def _handle_simulate_message(self, message: Dict[str, Any]):
        """模拟用户发送消息"""
        user_id = message.get("user_id")
        content = message.get("content")
        requested_chat_id = message.get("chat_id")
        start_new_conversation = bool(message.get("start_new_conversation"))

        if not all([user_id, content]):
            logger.error("Missing user_id or content in simulate_user_message")
            return

        if user_id not in self.users:
            logger.error(f"User {user_id} not found")
            return

        user = self.users[user_id]

        if start_new_conversation:
            chat_id = user.start_new_conversation(
                requested_chat_id
                if isinstance(requested_chat_id, str) and requested_chat_id.strip()
                else None
            )
            await self.broadcast_to_plugins(
                {
                    "type": "start_new_conversation",
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            logger.info(f"Started new conversation for {user_id}: {chat_id}")
        elif isinstance(requested_chat_id, str) and requested_chat_id.strip():
            chat_id = requested_chat_id
            user.active_chat_id = chat_id
        else:
            chat_id = user.active_chat_id

        # 添加用户消息到历史
        chat = user.get_or_create_chat(chat_id)
        msg_record = {
            "id": str(uuid.uuid4()),
            "from": user_id,
            "from_name": user.name,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        }
        chat.append(msg_record)

        logger.info(f"User {user_id} ({user.name}) sent in {chat_id}: {content}")

        # 广播给插件处理
        event = {
            "type": "inbound_message",
            "user_id": user_id,
            "user_name": user.name,
            "chat_id": chat_id,
            "message_id": msg_record["id"],
            "content": content,
            "timestamp": msg_record["timestamp"],
        }

        await self.broadcast_to_plugins(event)

    async def _handle_start_new_conversation(
        self, message: Dict[str, Any], websocket: WebSocketServerProtocol
    ):
        """处理显式新会话请求"""
        user_id = message.get("user_id")
        requested_chat_id = message.get("chat_id")

        if not user_id:
            response = {"type": "error", "error": "Missing required field: user_id"}
            await websocket.send(json.dumps(response))
            return

        if user_id not in self.users:
            response = {"type": "error", "error": f"User {user_id} not found"}
            await websocket.send(json.dumps(response))
            return

        user = self.users[user_id]
        chat_id = user.start_new_conversation(
            requested_chat_id
            if isinstance(requested_chat_id, str) and requested_chat_id.strip()
            else None
        )

        await self.broadcast_to_plugins(
            {
                "type": "start_new_conversation",
                "user_id": user_id,
                "chat_id": chat_id,
                "timestamp": datetime.now().isoformat(),
            }
        )

        response = {
            "type": "start_new_conversation_response",
            "user_id": user_id,
            "chat_id": chat_id,
            "status": "success",
            "timestamp": datetime.now().isoformat(),
        }
        await websocket.send(json.dumps(response))

    async def start(self):
        """启动服务器"""
        logger.info(f"Starting Virtual Platform Server on ws://{self.host}:{self.port}")

        async with websockets.serve(self.handle_plugin_connection, self.host, self.port):
            logger.info(f"✅ Virtual Platform Server listening on ws://{self.host}:{self.port}")
            await asyncio.Future()


async def main():
    server = VirtualPlatformServer(host="0.0.0.0", port=8765)
    await server.start()


if __name__ == "__main__":
    asyncio.run(main())
