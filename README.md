# 博物馆展柜照度预算 API (Museum Showcase Light Budget API)

基于 **Python + FastAPI + SQLite** 的展柜照明曝光预算服务。

客户端提交展品的光敏感度等级、年度 **lux·hour（勒克斯·小时）** 曝光上限以及
带起止时间的照明区间；服务会：

1. **按时间线合并同一展柜内相互重叠的灯光区间** —— 重叠时段照度取最大值
   （展柜里的灯是“取最亮”，不是照度相加）；
2. **累计每件展品的实际曝光量**（lux × 小时）；
3. 返回**首次超出年度预算的时间点**、**超出量（lux·hour）**和**每日剩余额度**；
4. 支持**按展柜 + 日期**查询合并后的照明时间线，以及按展品 + 日期查询曝光报告；
5. 拒绝**负照度**、**反向时间区间**和**未知展品**；
6. 启动时**自动初始化数据库**，并提供 `/health` 健康检查。

---

## 一条命令启动

需要已安装 Docker（含 Compose v2）：

```bash
docker compose up --build
```

启动后：

- API 服务：<http://localhost:8000>
- 交互式文档（Swagger UI）：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/health>
- SQLite 数据文件保存在 Docker 命名卷 `museum-data`（容器内 `/data/museum.db`），
  容器重建后数据不丢失。

`LUX_SEED_SAMPLE=true` 时会预置一个示例展柜 `case-a`（书画厅 A 号展柜）和
展品 `ex-1`（清代绢本设色扇面，高敏感度，年限额 15 000 lux·hour），
方便立刻体验。不想预置数据时把 compose 文件里的该变量改为 `"false"`。

停止并删除容器（保留数据卷）：

```bash
docker compose down
```

连数据一起清空：

```bash
docker compose down -v
```

---

## 本地直接运行（不用 Docker）

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

数据库默认使用 `/data/museum.db`；本地运行时建议覆盖路径：

```bash
export LUX_DB_PATH=./museum.db
export LUX_SEED_SAMPLE=true
uvicorn app.main:app --reload
```

运行测试：

```bash
pip install pytest httpx
python3 -m pytest -q
```

---

## 数据模型

| 表 | 关键字段 |
| --- | --- |
| `showcases` 展柜 | `id`、`name` |
| `exhibits` 展品 | `id`、`showcase_id`、`name`、`sensitivity`、`annual_limit_lux_hour` |
| `lighting_intervals` 照明区间 | `showcase_id`、`exhibit_id`、`start_at`、`end_at`、`lux` |

**敏感度等级与默认年度曝光上限**（可在建展品时用 `annual_limit_lux_hour` 覆盖）：

| sensitivity | 典型材质 | 默认年度 lux·hour |
| --- | --- | --- |
| `high_sensitivity` | 纺织品、水彩、照片、染色纸张 | 15 000 |
| `medium_sensitivity` | 油画/蛋彩画、木材、骨角 | 150 000 |
| `stable` | 金属、石材、陶瓷、玻璃 | 不限（`null`） |

时间一律使用 ISO 8601（建议带 `Z` 时区），服务内部统一按 **UTC** 处理。

---

## API 速览

所有接口前缀 `/api`；时间均为 ISO 8601 UTC。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/showcases` | 创建展柜 |
| `GET`  | `/api/showcases/{id}` | 查询展柜 |
| `POST` | `/api/exhibits` | 创建展品（可带初始照明区间） |
| `GET`  | `/api/exhibits/{id}` | 查询展品 |
| `POST` | `/api/lighting` | 提交照明区间，返回合并时间线与预算报告 |
| `GET`  | `/api/showcases/{id}/timeline?day=YYYY-MM-DD` | 按展柜（+日期）查照明时间线 |
| `GET`  | `/api/exhibits/{id}/report?day=YYYY-MM-DD` | 按展品 + 日期查年度/每日曝光报告 |
| `GET`  | `/health` | 健康检查（会探测数据库连通性） |

错误约定：参数校验失败 → `422`；未知展柜/展品 → `404`；ID 冲突 → `409`。

---

## 使用示例（curl）

### 1. 建展柜与展品

```bash
curl -X POST http://localhost:8000/api/showcases \
  -H 'Content-Type: application/json' \
  -d '{"id":"case-a","name":"书画厅 A 号展柜"}'

curl -X POST http://localhost:8000/api/exhibits \
  -H 'Content-Type: application/json' \
  -d '{
    "id": "ex-1",
    "showcase_id": "case-a",
    "name": "清代绢本设色扇面",
    "sensitivity": "high_sensitivity",
    "annual_limit_lux_hour": 15000
  }'
```

`annual_limit_lux_hour` 可省略（取敏感度默认值），也可显式传 `null` 表示不限。

### 2. 提交照明区间（核心接口）

同一展柜两盏灯在 10:00–12:00 重叠：

```bash
curl -X POST http://localhost:8000/api/lighting \
  -H 'Content-Type: application/json' \
  -d '{
    "exhibit_id": "ex-1",
    "intervals": [
      {"start_at": "2026-03-02T09:00:00Z", "end_at": "2026-03-02T12:00:00Z", "lux": 50},
      {"start_at": "2026-03-02T10:00:00Z", "end_at": "2026-03-02T13:00:00Z", "lux": 200}
    ]
  }'
```

合并后的时间线为 **50 lux（09:00–10:00）→ 200 lux（10:00–13:00）**，
曝光量 = 50×1 + 200×3 = **650 lux·hour**（而不是把照度相加算出的 750）。

响应节选：

```json
{
  "stored": 2,
  "report": {
    "total_lux_hour": 650.0,
    "annual_year": 2026,
    "annual_lux_hour": 650.0,
    "annual_limit_lux_hour": 15000.0,
    "annual_remaining_lux_hour": 14350.0,
    "first_overrun_at": null,
    "over_lux_hour": 0.0,
    "daily": {
      "date": "2026-03-02",
      "budget_lux_hour": 41.09589,
      "used_lux_hour": 650.0,
      "remaining_lux_hour": 0.0,
      "remaining_hours_at_max_lux": 0.0,
      "max_lux_today": 200.0
    }
  },
  "showcase_timeline": [
    {"start_at": "2026-03-02T09:00:00Z", "end_at": "2026-03-02T10:00:00Z", "lux": 50.0,  "lux_hour": 50.0},
    {"start_at": "2026-03-02T10:00:00Z", "end_at": "2026-03-02T13:00:00Z", "lux": 200.0, "lux_hour": 600.0}
  ]
}
```

### 3. 首次超预算时间与超出量

若年限额为 100 lux·hour，200 lux 的灯开 1 小时（共 200 lux·hour），
累计曝光在 **09:30** 越过预算：

```json
{
  "annual_lux_hour": 200.0,
  "first_overrun_at": "2026-05-01T09:30:00Z",
  "over_lux_hour": 100.0,
  "annual_remaining_lux_hour": 0.0
}
```

越过点按段内线性插值计算：到达限额还需 `(限额 − 已累计) / 当前段照度` 小时。

### 4. 按展柜 + 日期查询

```bash
curl "http://localhost:8000/api/showcases/case-a/timeline?day=2026-03-02"
```

跨午夜的区间会按 UTC 日界切分；省略 `day` 返回全部时间线。

### 5. 按展品 + 日期查询报告

```bash
curl "http://localhost:8000/api/exhibits/ex-1/report?day=2026-03-02"
```

返回展品信息、该日合并后的 `segments` 以及完整年度/每日报告。

### 6. 校验拒绝示例

```bash
# 负照度 → 422
curl -i -X POST http://localhost:8000/api/lighting \
  -H 'Content-Type: application/json' \
  -d '{"exhibit_id":"ex-1","intervals":[
       {"start_at":"2026-03-02T10:00:00Z","end_at":"2026-03-02T09:00:00Z","lux":-5}]}'

# 反向区间（end < start）→ 422
curl -i -X POST http://localhost:8000/api/lighting \
  -H 'Content-Type: application/json' \
  -d '{"exhibit_id":"ex-1","intervals":[
       {"start_at":"2026-03-02T12:00:00Z","end_at":"2026-03-02T09:00:00Z","lux":50}]}'

# 未知展品 → 404
curl -i -X POST http://localhost:8000/api/lighting \
  -H 'Content-Type: application/json' \
  -d '{"exhibit_id":"ghost","intervals":[
       {"start_at":"2026-03-02T09:00:00Z","end_at":"2026-03-02T10:00:00Z","lux":50}]}'
```

零长度区间（start == end）不产生曝光，会被静默忽略。

---

## 计算口径说明

- **合并规则**：对同一展柜所有照明区间做扫描线（sweep-line）合并；每个时间点的
  照度 = 当时所有开启灯具照度的**最大值**；相邻且照度相同的段自动拼接。
  不同展柜互不影响。
- **曝光量**：`Σ 段照度 × 段时长（小时）`。
- **年度窗口**：查询日期所在公历年的 UTC `[1月1日, 次年1月1日)`。
- **首次超预算**：按合并段顺序累计，首次累计值严格超过年度限额的时刻；
  `over_lux_hour` 为年度总曝光超出限额的量；未超限分别为 `null` / `0`。
- **每日额度 `daily`**：
  - `budget_lux_hour`：年度限额按当年天数（365/366）均摊到该日的份额；
  - `used_lux_hour`：该日截至当前时刻已经发生的曝光（未来的计划开灯不计入已用）；
  - `remaining_lux_hour`：当日剩余可耗额度，并受年度剩余额度钳制；
  - `remaining_hours_at_max_lux`：按当日计划最大照度折算，“最亮的灯还能开多久”；
  - `stable`（不限额）展品这些字段为 `null`。

---

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LUX_DB_PATH` | `/data/museum.db` | SQLite 数据库文件路径，父目录自动创建 |
| `LUX_SEED_SAMPLE` | `false` | `true` 时在空库中预置示例展柜/展品 |

---

## 项目结构

```
.
├── app/
│   ├── main.py        # FastAPI 应用、启动初始化、健康检查、异常处理
│   ├── routers.py     # HTTP 路由
│   ├── schemas.py     # Pydantic 请求/响应模型与入参校验
│   ├── repository.py  # 数据访问与报告组装
│   ├── budget.py      # 年度累计、超预算判定、每日额度
│   ├── timeline.py    # 区间合并（扫描线，重叠取最大照度）
│   ├── database.py    # SQLite 连接、建表、初始数据
│   └── config.py      # 环境变量配置
├── tests/             # pytest 端到端测试（25 个用例）
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```
