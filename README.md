# OpenClaw Python Channel Server

该仓库提供 Python 虚拟消息平台服务端与命令行模拟客户端，用于对接 OpenClaw `python-platform` 插件。

## 仓库职责

1. 提供 WebSocket 消息中转与会话存储
2. 提供本地模拟用户输入能力（CLI）
3. 向 OpenClaw 插件广播 `inbound_message` / `bot_message_stream` 等事件

## 目录说明

1. `server.py`: Python 虚拟平台服务端（默认监听 `0.0.0.0:8765`）
2. `simulate.py`: 交互式命令行客户端
3. `requirements.txt`: Python 依赖

## 快速启动

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python server.py
```

另开终端启动模拟器：

```bash
source .venv/bin/activate
python simulate.py
```

## 关联仓库

1. OpenClaw Fork: https://github.com/XuSenfeng/openclaw
2. Android Client: https://github.com/XuSenfeng/openclaw-channel-android-client
3. Integration Docs: https://github.com/XuSenfeng/openclaw-android-demo

## AI 生成声明

本项目文档与部分代码在开发过程中使用了 AI 辅助生成与修改。
所有 AI 产出内容均经过人工审查、调试与验证后再提交。
