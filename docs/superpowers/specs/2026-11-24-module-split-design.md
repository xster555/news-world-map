# 新闻世界地图 · 模块拆分设计

日期：2026-11-24
状态：已批准，待实施

## 目标

把「新闻获取」与「地图展示」划成两个相对独立的模块：两侧各自能读懂、各自能演进，
**只通过一份显式契约**通信。任何一侧改动，另一侧要么无感，要么被明确拦下。

## 非目标（本轮明确不做）

- 不拆 `web/app.js`（前端单文件保持原样，只加契约校验接入）
- 不改 UI、不改交互、不改采集逻辑本身、不改任何既有行为
- 不引入第三方依赖、不引入 GitHub Actions / Pages
- 不改 README 承诺的使用方式：入口仍是 `http://127.0.0.1:8000/`，
  `web/index.html` 双击仍能用 `file://` 打开

## 1. 目标结构

```
news-world-map/
├── collector/              ← 模块 A：新闻获取（Python，零第三方依赖）
│   ├── collect.py          抓取→定位→去重合并→只写 data/news.json
│   ├── feeds.py  normalize.py  geocode.py  gazetteer.py
│   ├── config.py           只描述自己的路径与数据源（删掉 WEB_*）
│   ├── contract.py         加载契约规格 + Python 侧校验器
│   └── build_gazetteer.py  ← 从仓库根归位（需修路径，见 §6）
├── contract/               ← 契约层：不属于任何一方，两侧共享
│   └── news-v1.json        机器可读字段规格（唯一真相）
├── data/                   ← 模块 A 的私有数据
│   ├── news.json           采集器读写的唯一真相
│   └── gazetteer.json
├── web/                    ← 模块 B：地图（静态站点）
│   ├── index.html  app.js  style.css
│   ├── contract.js         JS 侧校验器（读同一份规格）
│   ├── data/               ← 发布产物（由 publish 生成，采集器不再写）
│   │   ├── news.json
│   │   ├── news-data.js
│   │   └── contract.js     随快照一同发布的契约
│   └── vendor/
├── scripts/
│   └── publish.py          两个模块之间的桥（不属于任一方）
└── docs/DATA_CONTRACT.md   人读版契约
```

`web/data/` 保留，但从「偷偷的第二份真相」变成**有来源、有校验的发布产物**——
README 原本就是这么描述它的，实施后实现终于对上承诺。

## 2. 契约层

`contract/news-v1.json` 是唯一真相，纯 JSON、零依赖可读。

### 规格支持的规则子集

| 键 | 含义 |
|---|---|
| `type` | `string` / `number` / `integer` / `boolean` / `array` / `object` / `any` |
| `required` | 是否必须存在，默认 `false` |
| `nullable` | 是否允许为 `null`，默认 `false` |
| `enum` | 取值白名单 |
| `minLength` | 字符串最小长度 |
| `items` | 当 `type=array` 时，逐元素套用的字段规格 |
| `fields` | 当 `type=object` 时，子字段规格（仅一层） |

未知字段**默认放行**（向前兼容）。校验器返回错误列表，每条包含字段路径
（如 `items[37].title`）与期望/实际。

### 已核实的事实，直接写进规格

- `lat` / `lon` / `location` **允许为 null**——当前 360 条里有 10 条未定位
- `confidence_label` 实际取值只有 `high` / `medium` / `low`；
  `custom` 是前端本地添加的用户点，**不属于采集契约**
- `location` 子字段 9 个，前端只读 4 个（`name` / `zh` / `country_zh` / `cc`）
- 采集器产出 19 个 item 字段，前端只读 13 个；
  `tkey` / `ukey` / `fallback` / `section` / `source_id` 前端一个都不碰，
  属采集器内部实现，规格里标注但**前端不得依赖**

## 3. 发布器（两个模块之间的桥）

`scripts/publish.py` 不属于任何一方——它同时知道 `data/` 和 `web/data/`，
但采集核心不知道。

```
python3 -m collector.collect    # 模块 A：只写 data/news.json
python3 scripts/publish.py      # 桥：校验 → 发布到 web/data/
```

行为：

1. 读 `data/news.json`
2. 用 `collector/contract.py` 按 `contract/news-v1.json` 校验
3. **不通过 → 打印错误列表（精确到字段路径），退出码非 0，一个字节都不写**——
   旧的发布产物原样保留，网页继续显示上一次的好数据
4. 通过 → 原子写 3 个文件（先写 `.tmp` 再 `os.replace`）：
   `web/data/news.json`、`web/data/news-data.js`、`web/data/contract.js`
5. 打印摘要：条数 / 来源数 / 生成时间

契约随快照一起发布：快照自带契约，天然自描述——不会出现「规格是新的、数据是旧的」。

## 4. 前端接入

- `web/index.html`：加 `<script src="data/contract.js"></script>` 与
  `<script src="contract.js"></script>`
- `web/contract.js`：JS 侧校验器，读 `window.__NWM_CONTRACT__`
- `web/app.js`：`loadData()` 拿到数据后校验一次；
  **不通过时在状态条提示，但不阻断渲染**（前端是消费者，只报告，不越权拒绝）

若 `window.__NWM_CONTRACT__` 不存在（只拷了数据没拷契约），校验器静默跳过，不误报。

## 5. 日常流程

| 脚本 | 改动 |
|---|---|
| `daily.bat` / `daily.sh` | 采集后加一行发布，两步串起来 |
| `run.bat` / `run.sh` | 同上 |
| `serve.bat` / `serve.sh` | 不变（只服务） |
| README 中英文 | 更新目录结构图、数据流图、新增发布命令说明 |

失败模式被消灭：**采集完不发布，网页看不到新数据**——脚本里两步是连着的。

## 6. 边界清理

`build_gazetteer.py` 归位到 `collector/build_gazetteer.py`，同时修路径：

- `ROOT` 从 `dirname(__file__)` 改成 `dirname(dirname(__file__))`
- 下载缓存目录从仓库根 `vendor/` 改到 `data/_vendor/`
  （与 `_geocode_cache.json`、`_discovered_places.json` 一样用下划线前缀表示私有）

它与 `collector/geocode.py` 有重复的 Open-Meteo 地理编码逻辑——
**本轮不合并**（属于顺手重构，不在本次范围），但在此记录一笔。

## 7. 验证矩阵

| # | 验证项 | 期望 |
|---|---|---|
| 1 | `collector.collect` 后 `git status` | 只 `data/news.json` 变，`web/data/` 不变 |
| 2 | `scripts/publish.py` 后 `git status` | `web/data/` 三个文件变 |
| 3 | 故意删掉某条的 `title` 再发布 | 拒绝发布，报错指出 `items[37].title`，退出码非 0，`web/data/` 保持不变 |
| 4 | 发布后开页面 | 统计条数字与改动前一致 |
| 5 | `file://` 双击 `web/index.html` | 正常显示地图与数据 |
| 6 | 依赖审计 | `pip list` 无新增；`web/` 无新 vendor 文件 |

## 8. 关键取舍

选择「保留 `web/data/` 但给它一个正当身份」，而不是消除它。
代价是多一次发布动作、多一个发布器文件；
换来的是入口地址不变、`file://` 照常能用、README 已有措辞直接变成事实——
把「副本」变成「产物」比「消灭副本」更小的一步。

## 9. 后续决定：新闻数据不入库（2026-11-24）

模块拆分落地后又定了一条：**新闻数据是运行时产物，不作为仓库内容提交**。

- `data/news.json`、`web/data/news.json`、`web/data/news-data.js` 三个文件写进
  `.gitignore`，并从 Git 跟踪中移除
- `web/data/contract.js` 仍然入库——它是契约的发布产物，稳定且体积小，
  保证克隆下来就带着「这份数据该长什么样」
- 代价：全新克隆没有数据，页面第一次打开是空的。页面状态条会提示
  「采集 + 发布」两步，`serve.*` 也会先提示还没发布过快照
- 换来：仓库只装代码、契约与地点库，不会被每小时变化的新闻淹没；
  每个克隆自己建一份档案，历史与快照都留在本机

§7 验证矩阵里「`git status` 只 `data/news.json` 变」那几条预期，
在这条决定之后变成了「这三个文件根本不进 Git 索引」。

## 10. 后续决定：发布时裁字段 + 限窗口（2026-11-24）

评估「换成 SQLite 存储」时实测发现：

- 浏览器端在 `file://` 下 `fetch` 与 `XHR` **都失败**，SQLite 只能内嵌成 base64 的 JS
  （实测 677 KB，比现在的 JSON 521 KB 还大 30%，还要多背一个 ~1.2 MB 的 WASM 运行时）
- 采集端 SQLite 要替代的「载入档案 + 建去重集合」只花 **3.1 ms**，不在瓶颈上

结论是 SQLite 不划算——它拿一个已经解决的问题换一堆新问题。改用两条更小的杠杆：

1. **裁掉内部字段**——发布时按契约 `internal_fields` 去掉
   `tkey / ukey / fallback / section / source_id`。发布产物因此与契约**逐字一致**：
   「前端不得依赖」从一句约定变成数据层面的硬边界。
   实测每条 19 字段 → 14 字段，产物 521 KB → 439 KB。
2. **限制发布窗口**——本机档案保留完整 90 天，发布产物只含最近 30 天
   （`--window-days` 可调，`--window-days 0` 为不限）；产物超过 3 MB 时自动收紧窗口。
   档案涨到 4000 条上限时，发布产物不会跟着线性膨胀。

窗口天数写进产物的 `window_days` 字段，页面在统计条里如实写明「已发布最近 30 天」，
避免用户点「全部」时误以为那就是完整历史。
