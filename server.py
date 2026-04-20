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
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

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
        self.openclaw_connections_by_server: Dict[str, Set[WebSocketServerProtocol]] = {}
        self.client_connections_by_server_user: Dict[Tuple[str, str], Set[WebSocketServerProtocol]] = {}
        self.connection_meta: Dict[WebSocketServerProtocol, Dict[str, str]] = {}
        self.message_handlers: List[Callable] = []
        self.stream_buffers: Dict[str, Dict[str, Any]] = {}
        self._init_demo_users()

    @staticmethod
    def _stream_key(server_id: str, user_id: str, chat_id: str, stream_id: str) -> str:
        return f"{server_id}::{user_id}::{chat_id}::{stream_id}"

    def _resolve_stream_state(self, message: Dict[str, Any]) -> Optional[str]:
        state = message.get("stream_state")
        if isinstance(state, str):
            normalized = state.strip().lower()
            if normalized in {"delta", "final"}:
                return normalized

        if bool(message.get("stream")):
            if bool(message.get("stream_done")):
                return "final"
            return "delta"

        return None

    def _resolve_stream_id(self, message: Dict[str, Any]) -> Optional[str]:
        candidates = [
            message.get("stream_id"),
            message.get("response_id"),
            message.get("run_id"),
        ]
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return None

    async def _handle_streamed_send_message(
        self,
        *,
        message: Dict[str, Any],
        websocket: WebSocketServerProtocol,
        server_id: str,
        user_id: str,
        chat_id: str,
        content: str,
        stream_id: str,
        stream_state: str,
    ):
        stream_key = self._stream_key(server_id, user_id, chat_id, stream_id)
        stream_entry = self.stream_buffers.get(stream_key)
        if stream_entry is None:
            stream_entry = {
                "content": "",
                "client_message_id": message.get("client_message_id"),
            }
            self.stream_buffers[stream_key] = stream_entry

        if stream_state == "delta":
            stream_entry["content"] = f"{stream_entry['content']}{content}"

            await self._send_to_clients(
                server_id,
                user_id,
                {
                    "type": "bot_message_stream",
                    "server_id": server_id,
                    "state": "delta",
                    "user_id": user_id,
                    "user_name": self.users[user_id].name,
                    "chat_id": chat_id,
                    "stream_id": stream_id,
                    "message_id": stream_id,
                    "client_message_id": stream_entry.get("client_message_id"),
                    "delta": content,
                    "content": stream_entry["content"],
                    "timestamp": datetime.now().isoformat(),
                }
            )

            response = {
                "type": "send_message_response",
                "status": "streaming",
                "stream_id": stream_id,
                "stream_state": "delta",
                "timestamp": datetime.now().isoformat(),
            }
            await websocket.send(json.dumps(response))
            return

        final_is_full_content = bool(message.get("stream_full_content"))
        final_content = content if final_is_full_content else f"{stream_entry['content']}{content}"
        final_message_id = stream_id or str(uuid.uuid4())

        chat = self.users[user_id].get_or_create_chat(chat_id)
        msg_record = {
            "id": final_message_id,
            "from": "bot",
            "content": final_content,
            "timestamp": datetime.now().isoformat(),
        }
        client_message_id = stream_entry.get("client_message_id")
        if isinstance(client_message_id, str) and client_message_id.strip():
            msg_record["client_message_id"] = client_message_id.strip()
        chat.append(msg_record)

        await self._send_to_clients(
            server_id,
            user_id,
            {
                "type": "bot_message_stream",
                "server_id": server_id,
                "state": "final",
                "user_id": user_id,
                "user_name": self.users[user_id].name,
                "chat_id": chat_id,
                "stream_id": stream_id,
                "message_id": final_message_id,
                "client_message_id": msg_record.get("client_message_id"),
                "content": final_content,
                "timestamp": msg_record["timestamp"],
            }
        )

        self.stream_buffers.pop(stream_key, None)

        response = {
            "type": "send_message_response",
            "message_id": final_message_id,
            "status": "success",
            "stream_id": stream_id,
            "stream_state": "final",
            "timestamp": datetime.now().isoformat(),
        }
        await websocket.send(json.dumps(response))

    def _init_demo_users(self):
        """初始化演示用户"""
        self.users["user001"] = VirtualPlatformUser("user001", "Alice")
        self.users["user002"] = VirtualPlatformUser("user002", "Bob")
        logger.info("Demo users initialized: Alice, Bob")

    def register_message_handler(self, handler: Callable):
        """注册消息处理器"""
        self.message_handlers.append(handler)

    @staticmethod
    def _normalize_identity(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return value.strip()

    def _get_connection_meta(self, websocket: WebSocketServerProtocol) -> Dict[str, str]:
        return self.connection_meta.get(websocket, {})

    def _remove_connection_from_registries(self, websocket: WebSocketServerProtocol):
        meta = self.connection_meta.pop(websocket, None)
        if not meta:
            return

        role = meta.get("role")
        server_id = meta.get("server_id")
        user_id = meta.get("user_id")

        if role == "openclaw" and server_id:
            targets = self.openclaw_connections_by_server.get(server_id)
            if targets:
                targets.discard(websocket)
                if not targets:
                    self.openclaw_connections_by_server.pop(server_id, None)

        if role == "client" and server_id and user_id:
            key = (server_id, user_id)
            targets = self.client_connections_by_server_user.get(key)
            if targets:
                targets.discard(websocket)
                if not targets:
                    self.client_connections_by_server_user.pop(key, None)

    def _register_connection(self, websocket: WebSocketServerProtocol, meta: Dict[str, str]):
        self._remove_connection_from_registries(websocket)
        self.connection_meta[websocket] = meta

        role = meta.get("role", "")
        server_id = meta.get("server_id", "")
        user_id = meta.get("user_id", "")

        if role == "openclaw":
            targets = self.openclaw_connections_by_server.setdefault(server_id, set())
            targets.add(websocket)
            return

        if role == "client":
            key = (server_id, user_id)
            targets = self.client_connections_by_server_user.setdefault(key, set())
            targets.add(websocket)

    def _has_pair(self, server_id: str, user_id: str) -> bool:
        has_openclaw = bool(self.openclaw_connections_by_server.get(server_id))
        has_client = bool(self.client_connections_by_server_user.get((server_id, user_id)))
        return has_openclaw and has_client

    async def _send_to_targets(
        self, targets: Set[WebSocketServerProtocol], message: Dict[str, Any]
    ) -> int:
        if not targets:
            return 0

        disconnected = set()
        delivered = 0
        for ws in targets:
            try:
                await ws.send(json.dumps(message))
                delivered += 1
            except Exception as e:
                logger.error(f"Failed to send message: {e}")
                disconnected.add(ws)

        for ws in disconnected:
            self._remove_connection_from_registries(ws)

        return delivered

    async def _send_to_openclaw(self, server_id: str, message: Dict[str, Any]) -> int:
        targets = self.openclaw_connections_by_server.get(server_id, set()).copy()
        return await self._send_to_targets(targets, message)

    async def _send_to_clients(self, server_id: str, user_id: str, message: Dict[str, Any]) -> int:
        targets = self.client_connections_by_server_user.get((server_id, user_id), set()).copy()
        return await self._send_to_targets(targets, message)

    async def _handle_register_message(
        self, message: Dict[str, Any], websocket: WebSocketServerProtocol, connection_id: str
    ):
        role = self._normalize_identity(message.get("role")).lower()
        server_id = self._normalize_identity(message.get("server_id"))
        user_id = self._normalize_identity(message.get("user_id"))
        user_name = self._normalize_identity(message.get("user_name"))

        if role not in {"openclaw", "client"}:
            await websocket.send(
                json.dumps(
                    {
                        "type": "error",
                        "error": "Invalid role. Allowed: openclaw, client",
                    }
                )
            )
            return

        if not server_id:
            await websocket.send(
                json.dumps(
                    {
                        "type": "error",
                        "error": "Missing required field: server_id",
                    }
                )
            )
            return

        if role == "client" and not user_id:
            await websocket.send(
                json.dumps(
                    {
                        "type": "error",
                        "error": "Missing required field: user_id for client role",
                    }
                )
            )
            return

        if role == "client" and user_id not in self.users:
            display_name = user_name or user_id
            self.users[user_id] = VirtualPlatformUser(user_id, display_name)

        meta = {
            "connection_id": connection_id,
            "role": role,
            "server_id": server_id,
            "user_id": user_id if role == "client" else "",
        }
        self._register_connection(websocket, meta)

        paired = False
        if role == "openclaw":
            paired = any(
                self._has_pair(server_id, candidate_user_id)
                for _, candidate_user_id in self.client_connections_by_server_user.keys()
                if _ == server_id
            )
        else:
            paired = self._has_pair(server_id, user_id)

        response = {
            "type": "register_response",
            "status": "success",
            "role": role,
            "server_id": server_id,
            "user_id": user_id if role == "client" else None,
            "paired": paired,
            "timestamp": datetime.now().isoformat(),
        }
        await websocket.send(json.dumps(response))

    async def _require_registered(
        self,
        websocket: WebSocketServerProtocol,
        *,
        allowed_roles: Optional[Set[str]] = None,
    ) -> Optional[Dict[str, str]]:
        meta = self._get_connection_meta(websocket)
        if not meta:
            await websocket.send(
                json.dumps(
                    {
                        "type": "error",
                        "error": "Connection is not registered. Send type=register first.",
                    }
                )
            )
            return None

        if allowed_roles and meta.get("role") not in allowed_roles:
            await websocket.send(
                json.dumps(
                    {
                        "type": "error",
                        "error": f"Role {meta.get('role')} is not allowed for this operation",
                    }
                )
            )
            return None

        return meta

    async def handle_plugin_connection(self, websocket: WebSocketServerProtocol):
        """处理插件连接"""
        connection_id = str(uuid.uuid4())[:8]
        logger.info(f"Connection accepted: {connection_id}")

        try:
            # 发送欢迎消息
            welcome = {
                "type": "connect",
                "platform_id": "python-virtual-platform",
                "connection_id": connection_id,
                "register_required": True,
                "timestamp": datetime.now().isoformat(),
                "features": ["messages", "reactions", "typing"],
            }
            await websocket.send(json.dumps(welcome))

            async for message_raw in websocket:
                try:
                    message = json.loads(message_raw)
                    msg_type = message.get("type")
                    if msg_type == "register":
                        await self._handle_register_message(message, websocket, connection_id)
                        continue

                    if msg_type == "simulate_user_message":
                        logger.info(f"Received simulate_user_message from {message.get('user_id')}")

                    await self.handle_plugin_message(message, connection_id, websocket)
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON from plugin: {message_raw}")
                except Exception as e:
                    logger.error(f"Error processing plugin message: {e}")

        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Connection disconnected: {connection_id}")
        finally:
            self._remove_connection_from_registries(websocket)

    async def handle_plugin_message(
        self, message: Dict[str, Any], connection_id: str, websocket: WebSocketServerProtocol
    ):
        """处理来自插件的消息"""
        msg_type = message.get("type")
        logger.info(f"Connection {connection_id} sent: {msg_type}")

        if msg_type == "send_message":
            if not await self._require_registered(websocket, allowed_roles={"openclaw"}):
                return
            # 插件发送消息给用户
            await self._handle_send_message(message, websocket)

        elif msg_type == "get_messages":
            if not await self._require_registered(websocket):
                return
            # 插件查询消息历史
            await self._handle_get_messages(message, websocket)

        elif msg_type == "ping":
            # 测试连接
            response = {"type": "pong", "timestamp": datetime.now().isoformat()}
            await websocket.send(json.dumps(response))

        elif msg_type == "simulate_user_message":
            if not await self._require_registered(websocket, allowed_roles={"client"}):
                return
            # 模拟用户发送消息
            logger.info(f"Handling simulate_user_message for user: {message.get('user_id')}")
            await self._handle_simulate_message(message, websocket)

        elif msg_type == "start_new_conversation":
            if not await self._require_registered(websocket, allowed_roles={"client"}):
                return
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
        sender_meta = self._get_connection_meta(websocket)
        server_id = self._normalize_identity(message.get("server_id")) or sender_meta.get("server_id", "")

        if not all([chat_id, user_id, content, server_id]):
            response = {
                "type": "error",
                "error": "Missing required fields: chat_id, to_user_id, content, server_id",
            }
            await websocket.send(json.dumps(response))
            return

        if not self._has_pair(server_id, user_id):
            response = {
                "type": "error",
                "error": f"No matched client/openclaw pair for server_id={server_id}, user_id={user_id}",
            }
            await websocket.send(json.dumps(response))
            return

        # 保存消息
        if user_id in self.users:
            stream_state = self._resolve_stream_state(message)
            stream_id = self._resolve_stream_id(message)
            if stream_state is not None and stream_id is not None:
                await self._handle_streamed_send_message(
                    message=message,
                    websocket=websocket,
                    user_id=user_id,
                    chat_id=chat_id,
                    content=str(content),
                    stream_id=stream_id,
                    stream_state=stream_state,
                    server_id=server_id,
                )
                return

            chat = self.users[user_id].get_or_create_chat(chat_id)
            client_message_id = message.get("client_message_id")
            msg_record = {
                "id": str(uuid.uuid4()),
                "from": "bot",
                "content": content,
                "timestamp": datetime.now().isoformat(),
            }
            if isinstance(client_message_id, str) and client_message_id.strip():
                msg_record["client_message_id"] = client_message_id.strip()
            chat.append(msg_record)

            logger.info(f"Bot replied to {user_id} in chat {chat_id}: {content}")

            # 主动推送机器人回复，客户端可实时显示，无需轮询 get_messages
            delivered = await self._send_to_clients(
                server_id,
                user_id,
                {
                    "type": "bot_message",
                    "server_id": server_id,
                    "user_id": user_id,
                    "user_name": self.users[user_id].name,
                    "chat_id": chat_id,
                    "message_id": msg_record["id"],
                    "client_message_id": msg_record.get("client_message_id"),
                    "content": content,
                    "from": "bot",
                    "timestamp": msg_record["timestamp"],
                }
            )

            if delivered == 0:
                logger.warning(
                    f"No client online for bot_message routing: server_id={server_id}, user_id={user_id}"
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
                "chat_id": chat_id,
                "messages": chat,
                "user_name": self.users[user_id].name,
            }
            await websocket.send(json.dumps(response))
        else:
            response = {"type": "error", "error": f"User {user_id} not found"}
            await websocket.send(json.dumps(response))

    async def _handle_simulate_message(
        self, message: Dict[str, Any], websocket: WebSocketServerProtocol
    ):
        """模拟用户发送消息"""
        registered_meta = self._get_connection_meta(websocket)
        server_id = registered_meta.get("server_id", "")
        registered_user_id = registered_meta.get("user_id", "")
        user_id = message.get("user_id")
        content = message.get("content")
        requested_chat_id = message.get("chat_id")
        start_new_conversation = bool(message.get("start_new_conversation"))

        if not all([user_id, content]):
            logger.error("Missing user_id or content in simulate_user_message")
            return

        if user_id != registered_user_id:
            await websocket.send(
                json.dumps(
                    {
                        "type": "error",
                        "error": "user_id in message must match registered user_id",
                    }
                )
            )
            return

        if user_id not in self.users:
            logger.error(f"User {user_id} not found")
            return

        if not self._has_pair(server_id, user_id):
            await websocket.send(
                json.dumps(
                    {
                        "type": "error",
                        "error": f"No matched client/openclaw pair for server_id={server_id}, user_id={user_id}",
                    }
                )
            )
            return

        user = self.users[user_id]

        if start_new_conversation:
            chat_id = user.start_new_conversation(
                requested_chat_id
                if isinstance(requested_chat_id, str) and requested_chat_id.strip()
                else None
            )
            await self._send_to_openclaw(
                server_id,
                {
                    "type": "start_new_conversation",
                    "server_id": server_id,
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
        client_message_id = message.get("client_message_id")
        if isinstance(client_message_id, str) and client_message_id.strip():
            msg_record["client_message_id"] = client_message_id.strip()
        chat.append(msg_record)

        logger.info(f"User {user_id} ({user.name}) sent in {chat_id}: {content}")

        # 广播给插件处理
        event = {
            "type": "inbound_message",
            "server_id": server_id,
            "user_id": user_id,
            "user_name": user.name,
            "chat_id": chat_id,
            "message_id": msg_record["id"],
            "client_message_id": msg_record.get("client_message_id"),
            "content": content,
            "timestamp": msg_record["timestamp"],
        }

        delivered = await self._send_to_openclaw(server_id, event)
        if delivered == 0:
            await websocket.send(
                json.dumps(
                    {
                        "type": "error",
                        "error": f"No OpenClaw connection registered for server_id={server_id}",
                    }
                )
            )

    async def _handle_start_new_conversation(
        self, message: Dict[str, Any], websocket: WebSocketServerProtocol
    ):
        """处理显式新会话请求"""
        registered_meta = self._get_connection_meta(websocket)
        server_id = registered_meta.get("server_id", "")
        registered_user_id = registered_meta.get("user_id", "")
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

        if user_id != registered_user_id:
            response = {
                "type": "error",
                "error": "user_id in message must match registered user_id",
            }
            await websocket.send(json.dumps(response))
            return

        if not self._has_pair(server_id, user_id):
            response = {
                "type": "error",
                "error": f"No matched client/openclaw pair for server_id={server_id}, user_id={user_id}",
            }
            await websocket.send(json.dumps(response))
            return

        user = self.users[user_id]
        chat_id = user.start_new_conversation(
            requested_chat_id
            if isinstance(requested_chat_id, str) and requested_chat_id.strip()
            else None
        )

        await self._send_to_openclaw(
            server_id,
            {
                "type": "start_new_conversation",
                "server_id": server_id,
                "user_id": user_id,
                "chat_id": chat_id,
                "timestamp": datetime.now().isoformat(),
            }
        )

        response = {
            "type": "start_new_conversation_response",
            "server_id": server_id,
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
