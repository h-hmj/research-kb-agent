# 前端：科研知识库与实验助理 Agent

React + Vite + TypeScript 的本地演示界面。没有登录、云端存储或大型 UI 框架。

## 开发

要求 Node.js 20.19+（本项目已用 Node 24 验证）。

```powershell
cd web
npm install
npm run dev
```

打开 `http://127.0.0.1:5173`。

开发服务器把 `/api` 代理到 `http://127.0.0.1:8000`，因此不需要在前端处理 CORS。
先启动后端：

```powershell
cd ..
uvicorn src.research_agent.main:app --reload --port 8000
```

## API 地址

默认 `VITE_API_BASE_URL` 为空，表示使用 Vite proxy 或同源 nginx：

```powershell
$env:VITE_API_BASE_URL = ""
npm run dev
```

如果要明确指向其他本地后端，可设置为：

```powershell
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000"
npm run dev
```

不要把 API Key、模型路径或后端绝对路径写进前端环境变量。

## 测试与构建

```powershell
npm run test
npm run build
```

`npm run build` 会先执行 TypeScript 严格检查，再生成 `dist/`。不要把 `dist/` 或
`node_modules/` 提交到 Git。

## 页面

- **总览**：能力卡片、流程图、健康状态和快捷入口。
- **文档库**：PDF 上传、列表、索引、删除、详情、逐页统计和 PDF 预览。
- **Agent 问答**：基础 QA 与 LangGraph Agent；SSE 流式 token、workflow 步骤、
  拒答、request_id 和页码引用。
- **科研工具**：实验 checklist 与组会总结，引用来自后端。
- **评测**：运行 JSONL 评测、查看 QA/Agent 对比指标和历史报告。
- **系统状态**：健康检查、进程内 metrics、能力与限制。

点击引用中的“文档名 · 第 N 页”会打开 PDF 抽屉，并显示“引用页码：第 N 页”。
浏览器若不支持 `#page=N` 自动跳页，界面仍会明确标注页码。

## Docker

`web/Dockerfile` 使用 Node 构建，再由 nginx 提供静态文件。nginx 将 `/api/`
反向代理到 compose 内的 `research-agent:8000`，关闭代理缓冲以支持 SSE。
前端容器在宿主机暴露 `5173`：

```powershell
docker compose up -d --build research-agent-web
```

本轮已实际构建前端镜像并启动容器，验证了：

- 宿主机 `5173` 页面返回 200
- nginx 同源 `/api/v1/health`
- PDF 上传、索引和 `application/pdf` 预览
- 检索和 retrieval 评测
- nginx SSE 收到 workflow 事件和 heartbeat

## 已知限制

- 不做移动端专门适配，只保证窄屏基本可用。
- 不使用 React Router；单页通过本地状态切换视图。
- 不持久化聊天记录、评测运行状态或筛选条件。
- PDF 预览依赖浏览器内置 PDF 查看器；不解析或重新渲染 PDF。
- Ollama 未启动，真实 token/final 流式回答和真实科研语料评测仍需验证。
- 其他页面的表单提交尚未逐项做真实浏览器验收。
