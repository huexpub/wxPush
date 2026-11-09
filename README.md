# WXPUSH · 企业微信应用推送后台

把「企业微信应用的三要素 + 消息模板 + 一把 webhook key」放在一台 VPS 上，
任何项目——gitea action、GitHub action、脚本、别的服务——只要往那个 key
POST 一段 JSON，服务端就会套模板、推到企业微信，并把每次调用记进历史。

```
你的项目 ──POST /api/hook/wxp_xxx──► WXPUSH ──► 企业微信「应用消息」
                                      │
                                      └─► SQLite（消息历史，可在后台查）
```

## 为什么这么做

- **不用每个项目都配一遍 secret**：secret 只存在 VPS 上，加密落库。
- **不用群里加机器人**：走自建应用，能发给指定人 / 部门 / 标签。
- **消息格式统一**：模板在后台维护，改文案不用改流水线。
- **可追溯**：成功、失败、企业微信的原始返回、渲染后的正文都在历史里。

## 快速开始（本地）

```bat
run.bat
```

手动：

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

cd web
npm install
npm run build          # 产物直接写进 wxpush/static
cd ..

$env:WXPUSH_ADMIN_PASSWORD = "换成你自己的"
.\.venv\Scripts\python.exe -m wxpush serve      # → http://127.0.0.1:8000
```

开发前端时另开一个终端跑 `cd web && npm run dev`，Vite 会把 `/api` 代理到
`127.0.0.1:8100`（见 `web/vite.config.js`）。

## Docker

镜像由 GitHub Actions 构建（前端在镜像里用 node 阶段编译，仓库不提交 dist）：

```bash
docker run -d --name wxpush -p 8000:8000 \
  -e WXPUSH_ADMIN_PASSWORD=换成你自己的 \
  -v wxpush-data:/app/data \
  ghcr.io/huexpub/wxpush:latest
```

或直接用仓库里的 compose（`cp .env.example .env` 后填），然后
`docker compose up -d`。

## 用起来

### 1. 建应用

企业微信管理后台 → 应用管理 → 自建应用 → 创建应用，然后拿到三样东西：

| 字段 | 从哪来 |
| --- | --- |
| 企业 ID（corpid） | 我的企业 → 企业信息 |
| AgentId | 应用详情页 |
| Secret | 应用详情页（只显示一次，丢了要重置） |

填进「应用」页，点「测试」能往自己企业微信发一条纯文本就说明三要素对了。

> 应用详情里要配置「可见范围」，否则推送会返回 `81013`。
> 接收人用 UserID（通讯录里那个账号），多个用 `|` 分隔，留空即 `@all`。

### 2. 建模板

模板就是一段带 `{{ 变量 }}` 的正文：

| 类型 | 正文形态 |
| --- | --- |
| `text` | 纯文本，支持换行 |
| `markdown` | 支持 `**加粗**`、`[链接](url)`、`> 引用`、列表 |
| `textcard` | JSON：`{"title","description","url","btntxt"}` |
| `news` | JSON：`{"articles":[{"title","description","url","picurl"}]}`，最多 8 条 |

例如「构建完成」：

```text
{{ project }} 构建 {{ status }}
分支：{{ branch }}
提交：{{ commit }}
耗时：{{ duration }}
{{ url }}
```

变量语法：

```
{{ name }}                  缺失时渲染成空串
{{ name | default "无" }}   缺失时用默认值
{{ repo.name }}             点号取嵌套字段
```

保存模板时服务端会用示例值渲染一遍；`textcard` / `news` 还会校验结构，
拼错的 JSON 在保存时就报错，不会等到线上推送失败。

### 3. 建 webhook

选一个应用 + 一个模板，生成一把 `wxp_` 开头的 key。三处都能带它：

```bash
# 1. 路径（推荐）
POST https://push.example.com/api/hook/wxp_xxxxxxxx

# 2. Header —— 方便某些不方便改 URL 的平台
POST https://push.example.com/api/hook
X-Wxpush-Key: wxp_xxxxxxxx

# 3. Query
POST https://push.example.com/api/hook?key=wxp_xxxxxxxx
```

请求体就是模板变量：

```bash
curl -X POST https://push.example.com/api/hook/wxp_xxxxxxxx \
  -H "Content-Type: application/json" \
  -d '{"project":"bfs","status":"成功","branch":"main","commit":"a1b2c3d","url":"https://example.com"}'
```

也接受：

- `text/plain` 正文 → 整段当作 `content`（模板里写 `{{ content }}`）；
- `application/x-www-form-urlencoded` → 每个字段是一个变量；
- JSON 里的 `touser` 字段可以临时覆盖接收人（不会进模板）；
- 服务端自动补 `time` 变量（`YYYY-MM-DD HH:MM:SS`）。

响应：

```json
{
  "ok": true,
  "id": "msg_1a2b3c4d",
  "status": "success",
  "msg_type": "text",
  "touser": "@all",
  "rendered": "bfs 构建 成功\n分支：main...",
  "duration_ms": 218
}
```

失败返回 502 + `{"error":"send_failed","message":"企业微信错误 81013：..."}`，
但**历史里依然有一条记录**，点开能看到原始返回。

### 4. gitea / GitHub action

```yaml
- name: 推送企业微信
  if: always()
  run: |
    curl -sS -X POST "${{ secrets.WXPUSH_HOOK }}" \
      -H 'Content-Type: application/json' \
      -d "{\"project\":\"${{ github.repository }}\",\"status\":\"${{ job.status }}\",\"url\":\"${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}\"}"
```

把 key 放进仓库 secret 即可；换 key 只需改一处。

## 配置

| 变量 | 说明 |
| --- | --- |
| `WXPUSH_DATA_DIR` | 数据目录，默认 `./data`（SQLite + secret.key） |
| `WXPUSH_ADMIN_PASSWORD` | 管理员密码。**公网部署必须设**，否则谁都能改配置 |
| `WXPUSH_ADMIN_USER` | 可选用户名，设了就要求两项 |
| `WXPUSH_BASE_URL` | 对外地址，用于生成示例 |
| `WXPUSH_PATH_PREFIX` | 挂在子路径下，如 `wxpush` → `/wxpush/...` |
| `WXPUSH_ENCRYPTION_KEY` | base64 的 32 字节；留空则用 `data/secret.key` |
| `WXPUSH_MESSAGE_RETENTION_DAYS` | 历史保留天数，默认 180；0 = 永久 |
| `WXPUSH_RATE_LIMIT_PER_MINUTE` | 每个 key 每分钟调用上限，默认 120 |
| `WXPUSH_MAX_PAYLOAD_KB` | 单次请求体上限，默认 64 KB |
| `WXPUSH_FOOTER_HTML` | 页脚（支持 HTML，可放备案号） |

### 反代到子路径

```yaml
environment:
  WXPUSH_PATH_PREFIX: wxpush
  WXPUSH_BASE_URL: https://example.com/wxpush
```

```nginx
location /wxpush/ {
    proxy_pass http://127.0.0.1:8000/;
}
```

## 安全设计

- **Secret 与 key 加密落库**：AES-256-GCM（`cryptography`），密钥来自
  `WXPUSH_ENCRYPTION_KEY` 或首次启动生成的 `data/secret.key`（0600）。
  换了密钥就解不开已有 secret —— 备份数据目录时把 `secret.key` 一起带上。
- **webhook key 只存哈希用于查找**，另有加密副本供后台「复制」按钮读取。
  轮换后旧 key 立即失效。
- **管理面**用 HMAC 签名 cookie（无会话表），登录尝试每 IP 每分钟 10 次。
- **webhook 面**每个 key 每分钟限速，请求体有上限，且只影响自己那一条流水线。
- **历史**里保存的是渲染后的正文和调用方传的变量，不含任何密钥。

## 数据

```
data/
  wxpush.sqlite3    应用 / 模板 / webhook / 消息历史
  secret.key        加密密钥（备份时务必带上）
```

## 常用命令

```bash
python -m wxpush serve          # 启动
python -m wxpush purge          # 清理超过保留期的历史
python -m wxpush info           # 数据目录与统计
python -m pytest -q             # 测试
cd web && npm run build         # 构建前端
```

## 技术栈

Python 3.10+ / FastAPI / SQLite（WAL）/ `cryptography`（AES-GCM），
前端 Vue 3 + Vite（构建产物由同一个 Python 进程托管，部署时不需要 nginx）。

后端只用标准库 `urllib` 调企业微信接口 —— 没有 `requests`、没有 OAuth 库，
一个进程、一个数据目录就是全部运行时。
