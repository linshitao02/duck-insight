# AI 数据中台：实时链路与智能问数设计

> 日期：2026-11-27  
> 适用范围：Duck Insight（本仓库）  
> 对标材料：仓库内 `Taier/`、`SQLBot/`  
> 与 `系统设计文档.md` 的关系：那份文档定义分析工作台和 DAG。本文只定义中台增量：一条 MySQL → Kafka → Doris 短链路、指标口径，以及受控的自然语言问数。分析、训练、现有 BI 继续保留。

## 1. 要做成什么

业务库的变更要能流进分析库，分析库里的每个核心数字都有写死的口径，业务人员用中文提问后拿到图表、口径说明，以及可展开的 SQL。模型不能直接连业务库，也不能自己决定表和权限。

第一条闭环用现有电商订单场景，不先做通用 CDC 平台：

```text
MySQL 订单库
  → Flink CDC（一条作业）
  → Kafka（一个主题）
  → Doris Routine Load
  → 明细表 + 5 到 10 个指标视图
  → Data Agent（语义约束、受控 SQL、权限过滤）
  → 图表 + 口径说明 + 可展开 SQL
```

现有能力继续承担文件分析：数据集、清洗、训练、DAG、BI、知识库问答。问数是一条新入口，不替换智能问答。

## 2. 和 Taier、SQLBot 怎么对标

### 2.1 结论

| 产品 | 能对上的部分 | 不整包搬的原因 |
|------|----------------|----------------|
| Taier | 实时采集的四步模型：来源、目标、通道、提交运行；Flink 作业的 Checkpoint 续跑；Doris SQL 只作为查询引擎 | Taier 是 Java DAG 调度平台，依赖 Hadoop/YARN/集群控制台。本项目只要一条短链路，调度面用现有 Flask 管一个 Flink 作业即可 |
| SQLBot | 问数主路径：术语、SQL 示例、表筛选、生成 SQL、解析校验、行权限改写、执行、图表、分析、推荐追问 | SQLBot 是独立 FastAPI 产品，许可证要求衍生作品遵守 GPL，并限制修改其标识。本仓库不复制其源码，只按同一控制顺序在 Flask 里重写 |

Taier 使用 Apache-2.0，作业模板和任务状态机可以参考后改写。SQLBot 使用 FIT2CLOUD Open Source License（以 GPLv3 为基础并附加限制），只参考其文档中的流程和安全顺序，不把 `SQLBot/backend` 或 `SQLBot/frontend` 拷进运行代码。

### 2.2 从 Taier 改写进来的模块

Taier 的实时采集文档把任务分成来源、目标、通道控制、预览提交，并支持 Checkpoint 续跑。MySQL Binlog 到 Kafka 是它已经覆盖的源端模式。Doris SQL 在 Taier 里只是一种任务类型，不是数仓本身。

在本项目中收成一个「实时链路」对象，而不是接入 Taier 调度器：

| Taier 概念 | 落到 Duck Insight |
|------------|-------------------|
| 数据来源 MySQL Binlog | `pipeline.source`：主机、库、表、起始位点 |
| 数据目标 Kafka | `pipeline.sink`：主题 `cdc.ecommerce.order` |
| 通道控制 | 并行度、checkpoint 间隔、脏数据策略，写成作业参数 |
| 提交 / 停止 / 续跑 | Flask 调 Flink REST：`POST /jars/:id/run`、`/jobs/:id/stop`、从 savepoint 恢复 |
| Doris SQL 任务 | 不走调度器。指标视图由中台在 Doris 上执行一次 DDL |

作业定义保存为 JSON。运行状态只保留 `draft / running / failed / stopped` 和最近一次 Flink Job ID、Checkpoint 路径。第一条链路不需要 Taier 的多租户、Kerberos、YARN 队列和任务插件市场。

### 2.3 从 SQLBot 改写进来的模块

SQLBot 的问数顺序是可以照做的，安全文档里的执行顺序也直接采用：

1. 只把允许的表和字段交给模型。
2. 解析模型返回的 JSON，取出 SQL。
3. 用语法树提取真实表名，CTE 别名不算表。提不出表名就拒绝。
4. 表名必须落在本次允许集合内。
5. 按当前用户改写行权限。
6. 校验并保存最终 SQL。
7. 用只读账号执行，限制行数。

对应到本项目的新模块：

| SQLBot 概念 | Duck Insight 模块 | 做法 |
|-------------|-------------------|------|
| 数据源表结构、表关系 | 语义目录 `semantic_table` / `semantic_column` / `semantic_join` | 只登记 Doris 中允许问的表，不扫描业务 MySQL |
| 术语 | `semantic_term` | 「GMV」「成交额」「退款」等同义词和口径编号 |
| SQL 示例 | `semantic_sql_example` | 问题加已审核 SQL，注入提示词 |
| 自定义提示词 | 沿用 `llm_prompt`，增加 `task=ask_sql` | 不新做一套提示词产品 |
| 表筛选 | `ask_service.select_tables` | 先按指标和术语命中，再让模型在候选表里选 |
| 行权限、列权限 | `ask_policy` | 第一期做行权限；列权限用「不把该列放进提示词」实现 |
| 图表 | 现有 BI 的图表规格 | 返回 `line/bar/pie/kpi`，前端用现有组件画，不引入 SQLBot 的 G2 服务 |
| 分析与追问 | 问数记录上的第二段模型调用 | 只根据查询结果写解读，不能再生成新 SQL |
| 工作空间 | 现有项目 `data_project` | 电商项目和门店项目各看各的语义目录 |

现有 `chat_service.py` 是知识库问答，系统提示词仍偏解释和记忆。问数不塞进这条链路，单独做 `ask_service`，页面上是「智能问数」。知识库问答保留。

## 3. 总体结构

```text
浏览器
  智能问数 / 指标目录 / 实时链路
        │
        ▼
Flask
  auth
  pipeline_service     只管理一条 Flink 作业
  metric_service       口径定义与发布
  ask_service          问数编排
  sql_guard            解析、白名单、行权限、LIMIT
        │
        ├── 元数据：现有 SQLite 或 MySQL
        ├── 模型：现有 DeepSeek 配置
        └── 查询：Doris 只读账号
                ▲
                │
MySQL 业务库 ── Flink CDC ── Kafka ── Doris Routine Load
```

组件部署分开：

- 控制面和问数跟现有 `duck-insight` 容器走，继续用当前虚拟机。
- Kafka、Flink、Doris 用独立 compose profile `realtime`。这台约 8GB 的虚拟机已经跑着 Duck Insight 和 duck-harness，三个新组件同时常驻会顶满内存。实时组件放到另一台机器，或只在演示时启动。问数代码先按「Doris 不可用就明确失败」处理，不静默改去查业务库。

## 4. 实时短链路

### 4.1 范围

只同步电商订单这一张事实表，维表用全量快照，不进 CDC。

| 对象 | 来源 | 进 Doris 的表 | 方式 |
|------|------|----------------|------|
| 订单明细 | MySQL `oms_order_item` | `dwd_order_item_rt` | Flink CDC → Kafka → Routine Load |
| 门店、品类、渠道 | MySQL 维表 | `dim_store` 等 | 每日一次 `INSERT OVERWRITE` 或 JDBC 全量，第一期可手工导入 |

Kafka 只建一个主题 `cdc.ecommerce.order`。消息体保留 Flink CDC 的 `op`（`c/u/d/r`）和 `after`。不做多主题、不做变更宽表拼接。

### 4.2 Flink 作业

用 Flink CDC SQL 连接器，不自己写 Binlog 解析。作业模板放在 `realtime/flink/order_cdc.sql`，由中台用参数替换库表和 Kafka 地址后提交。

作业只做三件事：读 MySQL、转 JSON、写入 Kafka。过滤、去重和指标计算都放在 Doris。

```sql
CREATE TABLE src_order (
  order_item_id BIGINT,
  order_id      BIGINT,
  order_time    TIMESTAMP(3),
  pay_time      TIMESTAMP(3),
  store_id      BIGINT,
  category_id   BIGINT,
  channel       STRING,
  pay_amount    DECIMAL(18,2),
  refund_amount DECIMAL(18,2),
  status        STRING,
  PRIMARY KEY (order_item_id) NOT ENFORCED
) WITH (
  'connector' = 'mysql-cdc',
  'hostname' = '${mysql_host}',
  'port' = '${mysql_port}',
  'username' = '${mysql_user}',
  'password' = '${mysql_password}',
  'database-name' = '${mysql_db}',
  'table-name' = 'oms_order_item',
  'server-time-zone' = 'Asia/Shanghai'
);

CREATE TABLE kafka_order (
  order_item_id BIGINT,
  order_time    TIMESTAMP(3),
  pay_amount    DECIMAL(18,2),
  refund_amount DECIMAL(18,2),
  status        STRING,
  op_ts         TIMESTAMP_LTZ(3) METADATA FROM 'op_ts'
) WITH (
  'connector' = 'kafka',
  'topic' = 'cdc.ecommerce.order',
  'properties.bootstrap.servers' = '${kafka_bootstrap}',
  'format' = 'json'
);

INSERT INTO kafka_order
SELECT order_item_id, order_time, pay_amount, refund_amount, status, op_ts
FROM src_order;
```

上面是模板示意，提交前补齐主键和其余字段。Checkpoint 间隔 10 秒，状态后端用文件系统，续跑时把 savepoint 路径交给 Flink REST。中台页面只提供启动、停止、查看延迟和最近错误，不提供通用 Flink SQL IDE。

### 4.3 Doris 装载

`dwd_order_item_rt` 使用 Unique Key，按 `order_item_id` 覆盖，保证更新和删除幂等。Routine Load 消费同一个主题，`strict_mode` 打开，最大错误行数设上限，超过后作业暂停并在中台告警。

```sql
CREATE TABLE dwd_order_item_rt (
  order_item_id BIGINT,
  order_id      BIGINT,
  order_time    DATETIME,
  pay_time      DATETIME,
  store_id      BIGINT,
  category_id   BIGINT,
  channel       VARCHAR(32),
  pay_amount    DECIMAL(18,2),
  refund_amount DECIMAL(18,2),
  status        VARCHAR(32)
)
UNIQUE KEY(order_item_id)
DISTRIBUTED BY HASH(order_item_id) BUCKETS 8
PROPERTIES ("replication_num" = "1");
```

延迟目标：演示环境端到端 10 秒内。页面展示 Kafka 积压和 Doris Routine Load 的 `loadedRows`，不接 Prometheus。

### 4.4 和现有数据源的边界

`source_service` 今天只连接 MySQL，用于浏览库表和导入数据集。这条能力保留给离线分析。CDC 使用单独的只读复制账号，Doris 查询使用另一个只有 `SELECT` 的账号。两个密码放在服务端配置，不回显到前端，也不写进 Git。

## 5. 指标口径

口径是数据，不是提示词里的一段话。每个指标有编号、名称、粒度、是否含退款、SQL 模板和负责人。问数只能引用已发布指标，不能临时发明公式。

### 5.1 目录字段

`metric_definition`：

| 字段 | 含义 |
|------|------|
| code | 稳定编号，如 `gmv_pay` |
| name | 中文名 |
| grain | `day`、`store`、`category`、`channel` |
| includes_refund | `exclude` / `include` / `net` |
| formula_note | 给人读的口径，问数回答必须引用原文 |
| sql_template | 带 `${start_date}`、`${end_date}` 的 Doris SQL，只允许查询已登记视图 |
| status | `draft` / `published` |
| version | 发布后递增，历史问数记录绑定版本 |

发布时把 `sql_template` 作成 Doris 视图 `ads_metric_<code>`。问数优先查视图，不把模板再交给模型改写。模型只被允许选择指标、维度、时间范围和已登记过滤条件。

### 5.2 首批 8 个指标

金额单位元。时间用支付时间 `pay_time`。未支付订单不进入 GMV。`status='cancelled'` 且未支付的订单排除。

| 编号 | 名称 | 含退款 | 口径 |
|------|------|--------|------|
| `gmv_pay` | 支付 GMV | 含已退款的原支付额 | `status in ('paid','refunded')` 的 `pay_amount` 之和。退款不从本指标扣减 |
| `refund_amount` | 退款金额 | 仅退款 | `refund_amount` 之和，`refund_amount > 0` |
| `gmv_net` | 净 GMV | 扣除退款 | `gmv_pay - refund_amount`。对外说「成交额」且未说明含退款时，默认用本指标 |
| `order_cnt` | 支付订单数 | 不含未支付 | 支付订单 `order_id` 去重。一单多行只计一次 |
| `aov` | 客单价 | 同净 GMV | `gmv_net / order_cnt`，分母为 0 时返回空 |
| `refund_rate` | 退款率 | — | `refund_amount / gmv_pay` |
| `paid_qty` | 支付件数 | 不含未支付 | 明细行 `qty` 之和。现有演示 CSV 没有数量时，本指标标记为不可用 |
| `discount_rate` | 平均折扣率 | — | 支付订单 `discount_rate` 的金额加权平均 |

视图示例：

```sql
CREATE VIEW ads_metric_gmv_pay AS
SELECT DATE(pay_time) AS dt, store_id, category_id, channel,
       SUM(pay_amount) AS metric_value
FROM dwd_order_item_rt
WHERE status IN ('paid', 'refunded')
GROUP BY DATE(pay_time), store_id, category_id, channel;

CREATE VIEW ads_metric_gmv_net AS
SELECT DATE(pay_time) AS dt, store_id, category_id, channel,
       SUM(pay_amount) - SUM(refund_amount) AS metric_value
FROM dwd_order_item_rt
WHERE status IN ('paid', 'refunded')
GROUP BY DATE(pay_time), store_id, category_id, channel;
```

「GMV 含不含退款」在回答里写成固定句子：支付 GMV 含已退款订单的原支付额；净 GMV 已扣除退款。用户只说 GMV 时，系统选用 `gmv_net`，并在口径说明里写明这个默认。

现有 3.2 万条演示订单没有支付状态和退款额。接入真实 MySQL 前，用 `sales_amount` 映射 `pay_amount`，`refund_amount` 置 0，`status` 置 `paid`，并在口径上标记「演示数据无退款，净 GMV 等于支付 GMV」。不要把这批 CSV 的结果说成含退款口径。

## 6. Data Agent

### 6.1 一次提问的路径

```text
用户问题
  → 补全本轮省略的时间、指标、维度（只用于检索，不改写展示给用户的原话）
  → 用术语和 SQL 示例召回
  → 在当前用户可见的指标和表里筛选候选
  → 模型输出 JSON：指标、维度、时间、过滤、图表类型
  → 服务端用指标视图拼 SQL，不执行模型原文
  → sql_guard 解析、白名单、行权限、LIMIT
  → Doris 只读执行
  → 返回图表、口径原文、最终 SQL、三行以内的数据解读
```

模型可以提议 SQL，服务端不执行这段原文。可执行 SQL 只能由指标视图、已登记维度和权限条件拼出来。这样「受控 SQL」是结构约束，不是提示词里写一句「不要查别的表」。

模型输出：

```json
{
  "metric_code": "gmv_net",
  "dims": ["dt", "channel"],
  "time": {"start": "2025-01-01", "end": "2025-01-31"},
  "filters": [{"field": "channel", "op": "=", "value": "直播"}],
  "chart": "line"
}
```

服务端生成：

```sql
SELECT dt, channel, SUM(metric_value) AS metric_value
FROM ads_metric_gmv_net
WHERE dt >= '2025-01-01' AND dt < '2025-02-01'
  AND channel = '直播'
  AND store_id IN (/* 当前用户的门店范围，由策略注入 */)
GROUP BY dt, channel
ORDER BY dt
LIMIT 1000
```

无法映射到已发布指标时，拒绝执行并回答「当前只能查询已发布指标」，同时给出可问的指标名单。不为了答上来而退回自由 Text-to-SQL。

### 6.2 SQL 守卫

独立模块 `backend/services/sql_guard.py`，用 `sqlglot` 解析 Doris 方言：

- 只允许一条 `SELECT`。拒绝多语句、`INSERT`、`UPDATE`、`DELETE`、`CREATE`、`SET`。
- 提取物理表名。解析失败直接拒绝。
- 表必须属于本次候选视图。
- 过滤值只来自白名单字段，字符串使用参数绑定或转义函数，条件之间只用 `AND`。
- 强制 `LIMIT`，默认 1000，上限 5000。
- 超时 15 秒，只读账号。
- 保存的是改写后的最终 SQL。前端展开的也是这一份，不展示模型草稿。

这和 SQLBot 安全说明的 1 到 7 步一致，差别是第 2 步之后不采用模型 SQL 作为执行文本。

### 6.3 权限

第一期两种角色：

| 角色 | 行范围 | 可见指标 |
|------|--------|----------|
| admin | 全部门店 | 已发布指标 |
| analyst | `ask_policy` 中绑定的 `store_id` 列表 | 已发布指标，去掉标记为敏感的列 |

策略在服务端按登录用户读取。请求体里的用户 ID、项目 ID 只作校验，不能扩大范围。没有策略的普通用户不能问数。

列权限第一期不做表达式。敏感列不进入 `semantic_column`，模型看不到，SQL 也拼不出来。

### 6.4 返回给页面的结构

```json
{
  "question": "今年 1 月各渠道净 GMV",
  "metric": {
    "code": "gmv_net",
    "name": "净 GMV",
    "note": "支付 GMV 减去退款金额。用户只说 GMV 时默认使用本指标。"
  },
  "chart": {"type": "line", "x": "dt", "series": "channel", "y": "metric_value"},
  "columns": ["dt", "channel", "metric_value"],
  "rows": [],
  "sql": "SELECT ...",
  "summary": "1 月净 GMV 最高的渠道是直播。"
}
```

图表类型只允许 `kpi`、`line`、`bar`、`pie`。解读使用同一次查询的行，禁止模型补数字。SQL 默认折叠，点击展开。

页面放在现有布局的「智能问数」菜单。会话列表可复用 `ChatWorkspace` 的交互，但接口走 `/api/ask`，不走 `/api/chat`。

### 6.5 接口

| 方法 | 路径 | 作用 |
|------|------|------|
| POST | `/api/pipeline/order-cdc/start` | 提交 Flink 作业 |
| POST | `/api/pipeline/order-cdc/stop` | 停止并记录 savepoint |
| GET | `/api/pipeline/order-cdc` | 状态、延迟、最近错误 |
| GET | `/api/metric` | 已发布口径 |
| POST | `/api/metric` | 管理员保存草稿 |
| POST | `/api/metric/{code}/publish` | 生成或替换 Doris 视图 |
| POST | `/api/ask` | 提问，返回图表、口径、SQL |
| GET | `/api/ask/history` | 当前用户的问数记录 |

## 7. 元数据表

加在现有库中，不新建业务库。

```text
cdc_pipeline        一条链路的来源、主题、Flink Job ID、savepoint
metric_definition   口径与 SQL 模板、版本、发布状态
semantic_term       术语、同义词、指向的 metric code
semantic_sql_example 已审核的问题与 SQL
ask_policy          user_id、store_ids、允许的 metric code
ask_record          question、metric_version、final_sql、row_count、chart、summary
```

`ask_record.final_sql` 是审计依据。删除会话不删除审计记录，管理员可按时间查询。

## 8. 分步实现

### 第 1 步：口径和问数，先不启 CDC

用现有电商数据集在 Doris 中建一张静态明细，或在 Doris 未就绪时用同一套语义目录指向一张已导入的 Doris 表。发布 8 个指标视图。做 `sql_guard` 和 `/api/ask`。页面能问「各渠道净 GMV」，展开 SQL，看到口径说明。

验收：未发布指标不能执行；普通用户 SQL 中带有门店过滤；回答中的数字都能在返回行里找到。

### 第 2 步：一条实时链路

在 `realtime` profile 启动 Kafka、Flink、Doris。MySQL 插入、更新、删除一条订单后，10 秒内 `dwd_order_item_rt` 变化，净 GMV 视图跟着变化。中台能停止作业并用 savepoint 拉起。

验收：重复投递同一 `order_item_id` 不产生两行；Doris 账号不能写入。

### 第 3 步：和现有产品接上

问数图表可「保存到 BI」。保存时写入现有看板的数据源类型 `doris_metric`，不再把结果导出成 CSV。训练和 DAG 仍读数据集或逻辑数据集，不读 Agent 的临时结果。

## 9. 明确不做

- 不部署 Taier，不把 Chunjun 整套同步任务搬进来。
- 不嵌入 SQLBot 服务，不复制其源码。
- 第一期不做多条 CDC、不做整库同步、不做 Flink SQL 在线编辑。
- 不做自由 Text-to-SQL 兜底。
- 不把问数 SQL 发到业务 MySQL。
- 不在问数里触发训练、下单或改数。

## 10. 风险

| 风险 | 处理 |
|------|------|
| 8GB 虚拟机同时跑 Flink、Kafka、Doris | 实时组件与现有站点分开部署；问数依赖 Doris 地址配置 |
| 演示订单没有退款和支付状态 | 口径标记为演示映射，净 GMV 与支付 GMV 相同，页面上写出来 |
| 模型编造口径 | 口径句子只从 `formula_note` 原文返回 |
| GPL 代码混入本仓库 | 评审时禁止提交 `SQLBot/` 下的实现文件；该目录只作对照阅读 |
| 随机问法超出 8 个指标 | 拒绝并列出可问指标，不扩大 SQL 权限 |
