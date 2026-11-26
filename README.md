# 山地缆车站洗窗回水晨间备水

长坡缆车站洗窗值班组用单池日台账预测未来七天的早班补水量。值班分析员录入实测日期和用量，worker 对照加性 Holt–Winters 与季节朴素法，复核负责人签核后，早班可下载备水交班单。输入口径、公式与验收样例见 [业务说明](BUSINESS.md)。

| 模块 | 能力 |
|---|---|
| 晨间补水台账 | 导入 UTF-8 CSV，校验日期连续性与实测、留出、待预测区段，保存输入快照 |
| 季节平滑配置 | 设置水平、趋势、季节系数与早班备水上限，异步执行预测和滚动回测 |
| 七日备水交班单 | 查看点预测、整升需求、备水差额、误差与起点明细，复核通过后导出 CSV |
| 早班交班复核 | 记录签核决定和意见，保留运行审计 |

## 启动

```sh
cp .env.example .env
docker compose build backend
docker compose up -d --no-build --wait
docker compose exec -T backend python -m scripts.seed_demo
```

本地 API 地址为 `http://127.0.0.1:19435/api`，可访问 `/api/health`、`/api/spec` 和 `/api/openapi.json`。MySQL 宿主端口为 `17935`。项目使用 Python 3.11、FastAPI、SQLAlchemy、MySQL 8.0 与 Redis，Compose 服务为 `backend`、`worker`、`db`、`redis`。`BACKEND_PORT` 与 `DB_PORT` 可通过 `.env` 改写，`SEED_DEMO` 控制自动生成演示数据，`COMPOSE_PROJECT_NAME` 用于区分容器名称，`JWT_SECRET` 用于签发本地登录令牌。`docker compose down` 保留具名卷。

| 演示账号 | 口令 | 操作 |
|---|---|---|
| `analyst@demo.local` | `Demo-2611!` | 导入、运行、查看计算结果、下载已批准报告 |
| `admin@demo.local` | `Demo-2611!` | 导入、运行、签核、查看审计、下载已批准报告 |
| `viewer@demo.local` | `Demo-2611!` | 查阅台账及已批准结果、下载已批准报告 |

## API 工作流

| 请求 | 说明 |
|---|---|
| `POST /api/auth/login` | 提交 `email` 和 `password`，从 `access_token` 取得 Bearer 令牌 |
| `GET /api/spec` | 查看列名、参数范围和模块说明 |
| `POST /api/datasets` | 提交 `name` 和完整的 `csv` 文本，得到 `id` 和快照摘要 |
| `GET /api/datasets/{id}` | 检查日期、区段和实测补水量，可用 `offset` 与 `limit` 分页 |
| `POST /api/runs` | 提交 `dataset_id`、`label` 和 `settings`，空参数对象采用默认配置 |
| `GET /api/runs/{id}` | 等待 `completed`，查看 `result` 的交班单、回测及拟合截点 |
| `POST /api/runs/{id}/review` | 复核负责人提交 `decision` 和 `note`，批准值为 `approved` |
| `GET /api/runs/{id}/export/staging_handover` | 下载批准后的七日备水交班单，其他表使用相应结果键 |

从项目根目录生成可直接导入的完整演示 CSV。它与固定 seed 使用同一套数据。

```sh
PYTHONPATH=backend python3 -B -c 'from src.domain.fixtures import demo_csv; print(demo_csv(), end="")' > gondola-demo.csv
```

业务模块位于 `backend/src/domain/`，通用 HTTP、存储及队列逻辑位于 `backend/src/{routes,services,models}/`，启动及 seed 位于 `backend/{migrations,scripts}/`。角色、运行状态及复核决定定义在 `backend/src/constants/workflow.py`，用于路由鉴权、运行队列和报告复核。第三方依赖适用各自的许可证。
