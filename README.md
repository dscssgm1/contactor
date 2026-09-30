# Contacter UDP Relay

服务端和客户端已经拆分为两个独立模块：

```text
A 游戏客户端 ⇄ server.py（公网服务器） ⇄ client.py（B 内网客户端） ⇄ B 本地 UDP 服务
```

## 公网服务端

公网服务器只部署服务端模块：

```bash
python -m contacter.server --config relay.json
```

或使用统一入口：

```bash
python -m contacter server --config relay.json
```

服务端配置示例：

```json
{
  "listen_host": "0.0.0.0",
  "listen_port": 40000,
  "targets": {
    "game-1": {
      "b_secret": "00112233445566778899aabbccddeeff",
      "a_secret": "ffeeddccbbaa99887766554433221100",
      "public_port": 40001,
      "multiple_a_policy": "exclusive",
      "max_sessions": 1
    }
  }
}
```

## B 内网客户端

B 内网机器只部署客户端模块：

```bash
python -m contacter.client --config b-client.json
```

客户端配置示例：

```json
{
  "relay_host": "your.public.host",
  "relay_port": 40000,
  "target_id": "game-1",
  "b_secret": "00112233445566778899aabbccddeeff",
  "local_game_host": "127.0.0.1",
  "local_game_port": 8080,
  "keepalive_seconds": 15
}
```

B 客户端会主动连接公网服务器并维持 UDP 心跳，所以 B 不需要公网 IP 或路由器端口映射。它负责将公网 Relay 的数据转给本地 UDP 游戏服务，并把游戏服务响应发回 Relay。

## A 端参考客户端

A 端测试客户端单独提供：

```bash
python -m contacter.a_client_app --config a-client.json
```

也可以使用统一入口：

```bash
python -m contacter a-client --config a-client.json
```

原来的命令仍保留兼容：

```bash
python -m contacter relay --config relay.json
python -m contacter b-client --config b-client.json
```

## 模块边界

- `contacter/server.py`：服务端启动入口，只负责加载服务端配置并启动 Relay。
- `contacter/client.py`：B 端客户端启动入口，只负责加载客户端配置并启动 BClient。
- `contacter/a_client_app.py`：A 端参考客户端启动入口。
- `contacter/relay.py`：服务端核心转发逻辑。
- `contacter/b_client.py`：B 端 NAT 隧道和本地 UDP 服务桥接逻辑。
- `contacter/a_client.py`：A 端参考协议客户端。
- `contacter/protocol.py`：服务端和客户端共享的协议定义。

服务端与客户端共享的只有 `protocol.py`、`auth.py`、`config.py` 和 `models.py` 等协议/数据模型代码；运行入口和网络角色已经分离。

## 安全提示

- UDP Relay 只负责 UDP，不进行 TCP/UDP 协议转换。
- HMAC 提供认证和完整性，不提供加密。
- 公网部署时必须在云防火墙和系统防火墙中限制端口，并配置限速。
- 生产密钥不要提交到 Git，也不要写入日志。
- 公开服务端口不应单独作为授权依据，A 端应先完成控制会话授权。
