"""WXPUSH —— 企业微信应用推送后台。

一个进程 + 一个数据目录：SQLite 存配置与消息历史，静态前端由同一个
FastAPI 进程吐出去。外部应用只需要把变量 POST 到 webhook key，服务端按
模板拼装消息并调用企业微信「应用消息」接口。

模块划分：

    config.py     环境变量 -> Settings（不可变）
    db.py         SQLite schema + 连接
    crypto.py     企业微信 secret / webhook key 的落库加密
    auth.py       管理员登录（HMAC 签名 cookie）
    templating.py {{ var }} 模板渲染 + 结构校验
    wecom.py      企业微信 access_token 缓存与消息发送
    service.py    唯一的业务写入口
    api.py        /api/* JSON 接口 + 公开 webhook
    web.py        Vue 构建产物与页面路由
"""

__version__ = "0.1.0"
