# 🌍 AI 旅行管家 · AI Travel Agent

> **一个 Tool-augmented LLM Agent 应用**：用户输入出发地 / 目的地 / 行程日期，Agent 自动调用外部工具获取**真实机票与酒店数据**，再结合大模型生成**结构化、可执行的旅行攻略**，并输出可一键跳转的预订链接。

本项目是一个具备**工具调用（Tool Calling）、多步编排（Orchestration）、真实数据注入与成本控制**的完整 AI Agent 工程实践，技术栈覆盖 **MCP 协议、LLM API 编排、Streamlit 前端与异步 RPC**。

---

## ✨ 核心亮点

- 🛠️ **基于 MCP（Model Context Protocol）的工具接入**：以标准协议连接 SearchAPI 工具服务器，实现大模型与外部搜索能力的松耦合集成，而非硬编码 HTTP 调用。
- 🤖 **Agent 编排管线（Orchestration）**：在一次会话内完成「去程机票 → 回程机票 → 酒店」三次工具调用，并将真实结果注入 LLM 提示词，生成带数据支撑的攻略。
- 🎯 **Prompt Engineering + 结构化输出约束**：通过角色设定 + 六维结构化模板，约束豆包输出稳定、可解析的保姆级攻略（行程表 / 住宿 / 避坑 / 美食 / B 计划 / 物资）。
- 💡 **零成本工具设计**：自研 `build_google_flights_link` 工具，纯函数式生成 Google Flights 深层链接，**不消耗任何 API 额度**，直接为用户提供可分享、可跳转的比价入口。
- 💰 **分级缓存与成本优化**：目的地为「杭州」时命中本地缓存攻略，跳过 LLM 调用；其余目的地才走大模型，兼顾体验与 token 成本。
- 🧱 **工程化与可移植**：前后端分层、相对路径解耦、环境变量集中配置、敏感信息经 `.gitignore` 隔离，可直接开源与本地部署。

---

## 🏗️ 系统架构

```
┌──────────────┐
│  用户 (Browser)│  输入：出发地 / 目的地 / 去程 / 回程日期
└──────┬───────┘
       │  Streamlit UI (app.py)
       ▼
┌──────────────────────────┐
│  Orchestrator (txc_agent) │  顶层编排：真实数据 + LLM 生成攻略
└──────┬───────────┬───────┘
       │           │
       ▼           ▼
┌──────────────┐  ┌──────────────────────────────┐
│ MCP Client   │  │  LLM (火山引擎 豆包 Responses) │
│(mcp_client)  │  │  真实数据注入 → 结构化攻略      │
│ stdio 传输   │  └──────────────────────────────┘
└──────┬───────┘
       │ 启动子进程 (stdio)
       ▼
┌──────────────────────────┐
│ MCP Server (server/)     │  FastMCP
│ - search_google_flights  │  封装 SearchAPI.io
│ - search_google_hotels   │  (google_flights / google_hotels)
│ - build_google_flights_  │
│       link (自研零成本)   │
└──────────────────────────┘
```

**数据流**：`用户输入 → UI → 编排层拉起 MCP 子进程查询真实机票/酒店 → 真实数据注入 Prompt → LLM 生成攻略 → UI 聚合渲染（机票/酒店/攻略 + 可点击链接）`。

---

## 🧩 技术架构与关键设计决策

### 1. MCP 工具调用接入（Model Context Protocol）
采用官方 `mcp` SDK 的 **stdio transport** 拉起后端工具服务器（`server/mcp_server_refactored.py`），而非在应用内直接 `requests` 调用 SearchAPI。收益：
- **标准化工具协议**：工具以 MCP Tool 形式暴露，未来可横向替换/新增数据源而不改前端。
- **进程隔离与解耦**：工具服务器独立运行，前端仅通过能力调用交互，关注点分离清晰。
- **会话复用**：一次 `ClientSession` 内串行完成去程 / 回程 / 酒店三次调用，避免重复拉起子进程的开销。

### 2. Agent 编排与数据管线
`txc_agent.build_trip()` 作为编排中枢，把「工具取数」与「LLM 生成」两段式管线串起来：先获取可信的真实价格/酒店，再交给模型生成攻略，**用真实数据约束模型幻觉**。

### 3. Prompt Engineering 与结构化输出
针对旅行场景设计六维输出约束（极简行程表 / 交通住宿最优解 / 避坑清单 / 吃喝指南 / B 计划 / 物资清单），把"机票/酒店必须与真实数据一致"作为硬约束写入提示词，提升输出可用性与一致性。

### 4. 成本控制：分级缓存策略
对高频测试用例「杭州」直接读取本地 `缓存.md`，跳过 LLM 调用；其余目的地才消耗 token。这是一种**按场景分级的成本优化**思路，体现了工程落地中对推理成本的敏感度。

### 5. 工程化与可移植
- 后端服务器独立为 `server/` 目录，路径全部改为相对路径（`REPO_ROOT / "server"`），消除 Windows 绝对路径硬编码。
- 密钥通过 `.env` + `python-dotenv` 管理，并由 `.gitignore` 隔离，杜绝密钥泄露。
- 依赖统一收敛到 `ai_travel_agent/requirements.txt`（含后端所需的 `fastmcp`）。

---

## 👨‍💻 我的工作 / 核心贡献

> 作为该 Agent 应用的主要开发者，我负责从工具层到前端呈现的关键工程落地：

1. **设计与实现零成本链接工具 `build_google_flights_link`**
   在 MCP 服务器端新增纯函数式工具，依据出发地/目的地/日期生成 Google Flights 深层链接（`#flt=` 与 `?q=` 双形态），**零 API 消耗**、无副作用，可直接分享与跳转比价。
2. **将工具能力接入用户链路**
   在 `mcp_client` 中为去程 / 回程航班分别调用该工具生成链接，并在 Streamlit 前端渲染为可点击超链接，使「真实数据 → 可操作入口」形成闭环。
3. **后端服务模块化与可移植重构**
   将 MCP 服务器（`mcp_server_refactored.py` / `config.py` / `client.py`）从仓库根抽离至独立 `server/` 目录，并把所有绝对路径改写为基于脚本位置的相对路径，使项目可跨机器、可开源分发。
4. **开源就绪的工程治理**
   补齐全量依赖（`fastmcp`）、新增 `.env.example` 模板、重构 `.gitignore`（隔离密钥、缓存与无关实现），并编写仓库级 `README`，保证他人可一键部署。

---

## 🚀 快速开始

```powershell
# 1. 进入前端目录
cd ai_travel_agent

# 2. 创建虚拟环境并安装依赖
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt

# 3. 配置环境变量
copy .env.example .env
#   编辑 .env，填入：
#   SEARCHAPI_API_KEY  (查真实机票/酒店，必填)
#   DOUBAO_API_KEY     (生成攻略，必填；目的地填「杭州」可免)

# 4. 启动 Web UI
streamlit run app.py
```

浏览器打开 **http://localhost:8501** → 填写出发地 / 目的地 / 去程 / 回程日期 → 点击「🚀 生成旅行攻略」。

---

## 📁 目录结构

```
ai_travel_agent/   (仓库根)
├── app.py                 # Streamlit 前端：输入 → 展示机票/酒店/攻略 + 可点击链接
├── mcp_client.py          # MCP 客户端：stdio 拉起 server 子进程，单会话多工具调用
├── txc_agent.py           # 编排层：真实数据 + 豆包生成攻略（含杭州本地缓存）
├── requirements.txt       # 依赖（含后端 server 所需的 fastmcp）
├── server/                # 后端 MCP 工具服务器（SearchAPI.io 封装）
│   ├── client.py          # HTTP 客户端（连接池 / 重试 / 缓存 / 熔断器）
│   ├── config.py          # Pydantic 配置
│   └── mcp_server_refactored.py # FastMCP 服务器：机票/酒店/链接工具
├── LICENSE               
├── README.md             
├── .gitignore            
├── .env.example          
└── google_open_api.yaml

```

---

## 🛠️ 技术栈

| 层 | 技术 |
|----|------|
| 前端 | Streamlit（Python Web UI） |
| Agent 编排 | Python `asyncio`、自研 Orchestrator |
| 工具协议 | Model Context Protocol（MCP, stdio transport）、FastMCP |
| 数据源 | SearchAPI.io（Google Flights / Google Hotels） |
| 大模型 | 火山引擎豆包 `doubao-seed-2-0-pro`（Ark Responses API） |
| 工程 | `python-dotenv`、Pydantic / pydantic-settings、`.gitignore` 治理 |

---

## 🔮 可扩展方向

- **真正的多轮对话 Agent**：引入 ReAct / 规划-执行循环，让 Agent 自主决定调用哪些工具、是否需要追问用户偏好。
- **地图与路线可视化**：接入地图 API，把行程在时空维度上可视化。
- **多模型路由**：按任务复杂度在 DeepSeek / GPT / 豆包之间动态路由，进一步优化成本与质量。
- **历史行程持久化**：接入数据库保存用户行程，支持复用与个性化推荐。
- **工具能力扩展**：在 MCP 服务器中补充租车、景点门票、签证等工具，形成更完整的旅行 Agent 工具箱。

---

输入框
<img width="2864" height="1536" alt="d008ca741da5284197f8a7dd9c675e18" src="https://github.com/user-attachments/assets/31862e1f-f69f-4630-bdd5-a33a08e35377" />
输出攻略
<img width="2864" height="1536" alt="183ff2f0355667ce3598de90a08b118c" src="https://github.com/user-attachments/assets/5d09f6fb-a741-4572-a6a5-2974a6db9f01" />
输出酒店跳转链接
<img width="2864" height="1536" alt="72fc129ea220c9b19815fdc1518fb824" src="https://github.com/user-attachments/assets/1f0f91e1-3745-44e0-90b4-20d00d702a0e" />



