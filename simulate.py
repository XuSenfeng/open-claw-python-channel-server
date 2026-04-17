import asyncio
import json
import os
import sys

import websockets

# Helper to read input without blocking the event loop
async def ainput(prompt: str) -> str:
    print(prompt, end='', flush=True)
    return await asyncio.to_thread(sys.stdin.readline)


async def receiver_loop(ws, state: dict):
    """后台接收服务器消息，实时显示 AI 回复"""
    while True:
        raw = await ws.recv()
        data = json.loads(raw)
        msg_type = data.get("type")

        if msg_type in ["start_new_conversation", "start_new_conversation_response"]:
            chat_id = data.get("chat_id")
            if chat_id:
                state["active_chat_id"] = chat_id
                state["last_processed_msg_id"] = None
                event = state.get("new_conversation_event")
                if event is not None and not event.is_set():
                    event.set()
                print(f"\nSystem: Conversation switched -> {chat_id}")
            continue

        if msg_type == "bot_message":
            if data.get("user_id") != state["user_id"]:
                continue

            msg_id = data.get("message_id")
            if msg_id and msg_id == state["last_processed_msg_id"]:
                continue

            content = data.get("content", "")
            chat_id = data.get("chat_id", "")
            state["last_processed_msg_id"] = msg_id

            if chat_id and chat_id != state["active_chat_id"]:
                print(f"\nAI[{chat_id}]: {content}")
            else:
                print(f"\nAI: {content}")
            continue

        if msg_type == "error":
            print(f"\nSystem Error: {data.get('error', 'unknown error')}")


async def simulate():
    uri = os.getenv("PYTHON_PLATFORM_WS_URL", "ws://192.168.0.8:8765")
    user_id = "user001"
    state = {
        "user_id": user_id,
        "active_chat_id": "default_chat",
        "last_processed_msg_id": None,
        "new_conversation_event": None,
    }
    
    while True:
        try:
            async with websockets.connect(uri) as ws:
                print("\n✅ Connected to Virtual Platform. Type 'exit' to quit.")
                print("💡 Type '/new' to start a new conversation.")

                receiver_task = asyncio.create_task(receiver_loop(ws, state))
                
                while True:
                    user_input_raw = await ainput(f"You[{state['active_chat_id']}]: ")
                    user_input = user_input_raw.strip()
                    
                    if user_input.lower() in ["exit", "quit"]:
                        receiver_task.cancel()
                        try:
                            await receiver_task
                        except asyncio.CancelledError:
                            pass
                        return

                    if user_input.lower() == "/new":
                        event = asyncio.Event()
                        state["new_conversation_event"] = event
                        req = {"type": "start_new_conversation", "user_id": user_id}
                        await ws.send(json.dumps(req))

                        try:
                            await asyncio.wait_for(event.wait(), timeout=3.0)
                        except asyncio.TimeoutError:
                            print("System: Start new conversation request sent, no ack yet.")
                        finally:
                            state["new_conversation_event"] = None
                        continue
                        
                    if not user_input:
                        continue

                    msg = {
                        "type": "simulate_user_message",
                        "user_id": user_id,
                        "chat_id": state["active_chat_id"],
                        "content": user_input
                    }
                    await ws.send(json.dumps(msg))
                    print(f"System: Message sent in {state['active_chat_id']}, waiting for realtime AI push...")

        except websockets.ConnectionClosed:
            print("❌ Connection lost. Retrying in 3 seconds...")
            await asyncio.sleep(3)

        except ConnectionRefusedError:
            print("❌ Connection lost. Retrying in 3 seconds...")
            await asyncio.sleep(3)
        except Exception as e:
            print(f"⚠️ Error: {e}")
            await asyncio.sleep(3)

if __name__ == "__main__":
    try:
        asyncio.run(simulate())
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
