# 析数 · 数据分析 Agent（v0.10.2）

上传 Excel / CSV，用一句中文问题完成**趋势、异常、对比**分析，并支持连续追问、字段备注、收藏和报告导出。所有数字由本地 DuckDB 查询与 pandas 计算得出，大模型只负责理解问题、选择字段和撰写结论，不直接生成数字。

前端是 FastAPI 托管的原生 HTML / CSS / JavaScript + 本地 ECharts，无需 Node 构建；历史记录保存在 SQLite，原始文件保存在本机 `data/uploads`。

> 当前版本 `0.10.2`。版本变化见 [CHANGELOG.md](CHANGELOG.md)。
>
> 在线仓库（公开，MIT）：<https://github.com/Visionarying/xishu-data-analysis-agent>

## 功能一览

- **文件接入**：支持 `.xlsx` / `.xls` / `.csv`，优先识别多个工作表；自动检测表头行、字段类型、日期范围、缺失值、重复行和强制类型转换。
- **自然语言分析**：趋势（默认近 12 个月）、异常月份（稳健 Z 分数）、分组对比排名、常规汇总查询。
- **固定结果结构**：一句话结论、关键指标卡、交互图表、数据事实、推测与建议、数据明细、分析口径与 SQL。
- **可交互与可带走**：ECharts 缩放/悬浮提示、图表下载 PNG、结论复制、明细导出 CSV。
- **字段备注（轻量语义层）**：点击字段 chip 可为任意列补充业务含义/别名；备注会参与规则匹配，也会出现在 LLM 规划提示中，问“毛利”也能命中备注了“毛利口径”的“利润”字段。
- **多轮追问**：在同一文件、同一工作表内继续提问（如“那销售额呢？”“只看华东”），自动继承上一轮的分析类型、指标、分组、时间粒度与筛选，不需要重复完整问题。
- **收藏与收藏面板**：分析结果右上角星标即可收藏；左侧“我的收藏”可快速打开、重跑最新数据、重命名或删除；“面板”按钮提供卡片式管理。
- **一键导出报告**：每条结果都可下载 Markdown 报告，或打开打印版 HTML 后用浏览器“另存为 PDF”；报告包含结论、指标、图表数据、事实、建议、口径和明细。
- **历史与恢复**：SQLite 保存会话、文件元信息、分析记录；刷新页面后仍能查看最近文件与历史结果。
- **双模式**：配置 OpenAI 兼容模型后启用 AI 规划与结论；未配置时自动使用本地规则引擎，功能不降级。
- **安全默认值**：API Key 仅服务端环境变量；前端只拿到“是否已配置 / 模型名 / 端点主机”；不接受用户直接执行 SQL。

## 快速开始（本地）

要求 Python 3.11+，推荐 3.12。

```powershell
cd data-analysis-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
Copy-Item .env.example .env

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 <http://127.0.0.1:8000>，可直接下载页面上的示例 Excel，或使用 `samples/示例销售数据.xlsx`。

Windows 下也可以直接双击项目根目录的 `启动数据分析Agent.bat`（会启动服务并自动打开浏览器；桌面如有“析数 数据分析Agent(启动)”快捷方式，同样是它）。

macOS / Linux：

```bash
cd data-analysis-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

首次启动会自动创建 `data/`、`data/uploads/` 和 SQLite 表结构。

### 不配置模型也能用

`.env` 中 `OPENAI_API_KEY` 留空时，页面右上角显示“规则模式 · 未配置模型”。趋势方向、异常检测、指标、图表和规则结论全部在本地完成。

### 接入 OpenAI 兼容模型

编辑 `.env`：

```dotenv
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
```

常见兼容端点示例：

```dotenv
# 阿里云百炼 / DashScope
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL=qwen-plus

# DeepSeek
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-chat
```

修改后重启服务。模型调用失败、超时或返回的数字无法通过校验时，会自动回退到规则结论，并在结果中给出提示。

## 使用流程

1. 拖拽或选择文件，等待解析完成。
2. 在顶部切换工作表，查看字段类型、时间范围、缺失值与预览。
3. 点击推荐问题，或输入自己的问题，例如“近12个月销售额趋势如何？”。
4. 查看结论、指标卡、图表和明细；展开“分析口径与方法”可核对 SQL。
5. 继续用短句追问，例如“那销售额呢？”“只看华东”“再按月看看”，系统会沿用上一轮口径。
6. 点击字段 chip 补充业务备注；用结果右上角星标收藏，在左侧“我的收藏”中管理。
7. 使用图标复制结论、下载图表 PNG、导出明细 CSV、下载 Markdown 报告或打开打印版 HTML。
8. 刷新页面后，左侧会恢复文件、收藏和最近的分析记录。

示例问题与预期结果见 [samples/示例问题.md](samples/示例问题.md)。

## 字段备注、追问、收藏与报告

### 字段备注（轻量语义层）

- 点击数据概览里的字段 chip（带紫色圆点表示已有备注），填写业务含义、口径或常用别名，最多 200 字；留空保存即删除。
- 备注存入 SQLite 的 `column_notes` 表，随文件/工作表隔离，不会改原始文件。
- 规则规划会把备注拆成别名参与字段匹配，例如给“利润”备注“毛利口径，不含运费”后，问“找出毛利的异常波动月份”会选中“利润”字段。
- 配置模型时，备注会随字段清单进入规划提示，帮助模型理解业务叫法。
- 结果卡“分析口径与方法”中会列出本次用到的字段备注，便于复核。

### 多轮追问

- 前端会在同一文件、同一工作表内，把上一条结果的 `meta.plan` 作为 `context` 随问题发送。
- 仅当本轮像追问（短句，或含“那 / 再 / 换成 / 只看 / 呢 / 同样”等承接词）时继承上一轮未明确改变的口径：分析类型、指标、分组、时间粒度、统计周期和筛选。
- 追问里明确写出的字段会覆盖继承值，例如上一轮是“各区域利润”，追问“那销售额呢？”会保留“区域”分组、把指标换成“销售额”。
- “只看华东 / 仅看线上渠道”这类句子会从当前分组字段的取值中提取等值筛选。
- 结果卡会显示“追问”标记；换文件或换工作表后自动清空上一轮上下文，避免串口径。

### 收藏

- 结果右上角星标按钮可收藏/取消收藏；收藏保存的是分析快照引用（问题、标题、一句话结论、文件与工作表）。
- 左侧“我的收藏”显示最近 8 条，可直接打开；悬停右侧按钮可重跑最新数据。点“面板”打开卡片式管理，支持查看、重跑、重命名和删除。
- 重跑会优先读取原分析的规划口径，因此像“那销售额呢？”这类追问收藏也能复现原来的指标与分组。

### 报告导出

- 结果工具条的文档图标：下载 UTF-8 Markdown 报告（`.md`）。
- 打印机图标：在新窗口打开打印版 HTML；按 `Ctrl + P`（macOS `⌘ + P`）可另存为 PDF。
- 报告包含：问题与生成时间、一句话结论、关键指标、图表数据表、数据事实、推测与建议、分析口径/筛选条件/SQL，以及最多 200 行数据明细。
- 报告不依赖新增字体或 PDF 库，离线可用。

## 分析口径

- **时间窗口**：从问题中识别“近 N 个月 / 季度 / 年”等表达；趋势未指定时默认近 12 个月，异常检测默认使用全部时间范围。
- **趋势方向**：比较首尾窗口的中位数，避免单点尖峰把整体方向带偏；区间变化率同样使用窗口中位数计算。
- **异常检测**：双重口径——原始序列与线性去趋势残差分别计算稳健 Z 分数（中位数 + MAD），任一 |Z| ≥ 3.5 判定为异常；月度序列累计 ≥ 36 个月时再叠加月度季节修正；MAD 为 0 时回退 IQR（|Z| ≥ 2）。这样能避免“长趋势抬高整体离散度、把季节性极值洗白”的漏检。
- **分组对比**：按分组字段聚合指标，降序排名，计算占比、首尾差、前三名占比和第一名领先幅度。
- **百分比字段**：字段名包含“率 / 占比 / 同比 / 环比”等提示且被要求求和时，自动改用平均值，避免百分比相加失真。
- **数字来源**：聚合、排名、异常分数、指标卡都来自本地查询；模型结论会经过数字白名单校验，出现输入中不存在的数字即回退。
- **只读查询**：服务端仅执行自己拼装的单条 `SELECT` 聚合语句，字段名与字面量经过引用/转义，不接受用户 SQL。

## 数据与隐私

- 原始文件、Parquet 解析结果、SQLite 历史仅保存在本机 `data/` 目录。
- API Key 不会进入前端、日志或分析结果；`/api/settings` 只返回是否配置、模型名和端点主机。
- 启用模型时，会向模型发送：字段结构、少量示例值/统计范围、用户问题、本地聚合结果和结论草稿，**不会上传原始文件**。
- 当前版本没有登录和权限系统，会话通过浏览器 `localStorage` 中的 `X-Session-Id` 区分。请勿直接暴露到公网；如需多人使用，应在前面加反向代理与认证。

## Docker 部署

```powershell
Copy-Item .env.example .env
docker compose up -d --build
docker compose logs -f
```

访问 <http://127.0.0.1:8000>。健康检查地址：`/api/health`。

数据保存在命名卷 `data-analysis-agent-data` 的 `/app/data`，删除容器不会丢数据。彻底清空：

```bash
docker compose down -v
```

如果希望直接查看宿主机上的文件，可把 `docker-compose.yml` 的卷改为：

```yaml
volumes:
  - ./data:/app/data
```

容器以 UID `10001` 运行；Linux 下需确保宿主机目录可写：

```bash
mkdir -p data
sudo chown -R 10001:10001 data
```

## 目录结构

```text
data-analysis-agent/
├─ app/
│  ├─ main.py          # FastAPI 路由、静态托管、CSV 导出
│  ├─ config.py        # 环境变量与公开设置
│  ├─ db.py            # SQLite schema 与读写
│  ├─ ingest.py        # Excel/CSV 解析、表头与类型推断、Parquet
│  ├─ planner.py       # 意图识别、字段映射、备注别名、追问继承、LLM 规划与校验
│  ├─ analyzer.py      # DuckDB 聚合、趋势/异常/对比、图表与指标
│  ├─ narrative.py     # 规则结论、LLM 结论数字校验
│  ├─ notes.py         # 字段备注（轻量语义层）存取
│  ├─ report.py        # Markdown 与可打印 HTML 报告
│  ├─ llm.py           # OpenAI 兼容客户端
│  └─ utils.py         # 格式化、转义、JSON 安全转换
├─ web/
│  ├─ index.html
│  └─ assets/          # app.css / app.js / 本地 ECharts / favicon
├─ samples/
│  ├─ 示例销售数据.xlsx
│  └─ 示例问题.md
├─ scripts/
│  └─ make_sample_data.py
├─ data/               # 运行时生成，已被 git 忽略
├─ requirements.txt
├─ Dockerfile
├─ docker-compose.yml
├─ .env.example
├─ LICENSE
└─ README.md
```

## 许可证

本项目采用 [MIT License](LICENSE)。可自由使用、修改和分发，保留版权与许可声明即可。

## API 摘要

所有 `/api/*` 请求都可携带 `X-Session-Id`；缺失或格式不合法时服务端会生成新会话，并通过响应头返回。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET | `/api/settings` | 公开设置（不含 Key） |
| GET | `/api/bootstrap` | 当前会话的文件、历史与设置 |
| POST | `/api/files` | 上传文件（multipart `file`） |
| GET | `/api/files/{id}` | 文件详情与推荐问题 |
| GET | `/api/files/{id}/sheets/{sheet_id}/preview` | 工作表预览 |
| DELETE | `/api/files/{id}` | 删除文件及其解析数据 |
| POST | `/api/analyze` | `{file_id, sheet_id, question, context?}` 执行分析；`context` 为上一轮 `meta.plan` |
| PUT | `/api/files/{id}/sheets/{sheet_id}/columns/{name}` | 保存/删除字段备注 `{note}` |
| GET | `/api/analyses` | 分析历史 |
| GET | `/api/analyses/{id}` | 单条分析结果 |
| POST | `/api/analyses/{id}/regenerate` | 用同一问题重新生成 |
| DELETE | `/api/analyses/{id}` | 删除分析记录 |
| GET | `/api/analyses/{id}/export.csv` | 导出明细 CSV（UTF-8 BOM） |
| GET | `/api/analyses/{id}/export.md` | 下载 Markdown 报告 |
| GET | `/api/analyses/{id}/export.html` | 打开打印版 HTML 报告 |
| GET | `/api/favorites` | 收藏列表 |
| POST | `/api/favorites` | 收藏分析 `{analysis_id, title?}` |
| PATCH | `/api/favorites/{id}` | 重命名收藏 `{title}` |
| DELETE | `/api/favorites/{id}` | 删除收藏 |
| POST | `/api/favorites/{id}/rerun` | 按原口径重跑收藏 |
| DELETE | `/api/data` | 清空当前会话的文件、分析、备注与收藏 |

交互式 API 文档：<http://127.0.0.1:8000/api/docs>。

## 已知限制

- 单机 SQLite 与本地文件存储，适合个人/小团队演示，不适合高并发或多租户生产环境。
- 没有登录、角色和共享权限；会话 ID 不是安全边界。
- 不做预测、因果推断、PPT/图片/视频解析，也不做复杂多 Agent 协作。
- 表头与类型识别是启发式规则；极端合并单元格、多级表头、公式结果缺失可能需要先整理数据。
- 默认上限：单文件 50 MB、20 万行、20 个工作表；可通过环境变量调整，但大文件会受内存限制。
- `.xls` 依赖 `xlrd`，仅支持旧版二进制格式；新版 `.xlsx` 由 `openpyxl` 读取。
- 启用模型时，结论质量依赖模型能力；数字校验只能保证“不出现输入外数字”，不能保证业务解读一定正确。
- 趋势/异常对日期字段要求较高；日期列若被识别为文本，需要先在源文件中规范格式。

## 故障排查

| 现象 | 处理 |
| --- | --- |
| 页面打不开 / 端口占用 | 换端口：`--port 8001`；或结束占用 8000 的进程 |
| 上传提示格式不支持 | 仅支持 `.xlsx` / `.xls` / `.csv`，检查扩展名 |
| 上传后提示解析失败 | 检查是否为空文件、是否超过大小限制、表头是否过于复杂 |
| 一直显示规则模式 | `.env` 是否在项目根目录、Key/模型名是否填写、修改后是否重启 |
| 模型调用失败 | 检查 `OPENAI_BASE_URL` 是否包含 `/v1`、网络是否可达、Key 是否有额度；失败会自动回退规则结论 |
| 图表空白 | 确认 `web/assets/echarts.min.js` 存在；查看浏览器控制台与 `/api/health` |
| 刷新后历史不见 | 浏览器是否禁用了 `localStorage`，或更换了浏览器/无痕窗口 |
| Docker 数据无法写入 | 使用默认命名卷，或按上文修正 bind mount 目录权限 |

## 开发与验证

```bash
# 重新生成示例数据
python scripts/make_sample_data.py

# 启动
python -m uvicorn app.main:app --reload --port 8000
```

已用示例文件验证：多工作表解析、表头跳过、四类分析、异常分数、CSV 导出、会话隔离、清空数据和刷新恢复。v0.10.2 另已验证：字段备注保存/别名命中、追问继承、收藏增删改查与重跑、Markdown/打印版报告导出。未配置模型时默认走规则模式。
