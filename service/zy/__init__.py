"""
browser-assistant: 通用浏览器 AI 助手服务

架构：
  server.py             — 入口：WebSocket(18767) + HTTP(18768)
  agent.py              — 会话管理 + DeepSeek function calling 对话循环
  deepseek_client.py    — DeepSeek OpenAI 兼容客户端
  tools.py              — 工具定义（浏览器操作）与执行分发
  config.py             — 配置加载（config.json / 环境变量 / 运行时覆盖）
  actions/              — 通用页面操作（点击文本、输入、关闭标签页、滑块、延时等）
"""
