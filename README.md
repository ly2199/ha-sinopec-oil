# Sinopec Oil Price 中石化油价

![HA 版本](https://img.shields.io/badge/Home%20Assistant-2024.6%2B-blue)
![HACS](https://img.shields.io/badge/HACS-Custom-green)
![版本](https://img.shields.io/badge/版本-1.0.0-orange)

一个 [Home Assistant](https://www.home-assistant.io/) 的 [HACS](https://hacs.xyz/) 自定义集成：

- ⛽ **查询实时油价**：数据来自中国石化"今日油价"公开页面 [cx.sinopecsales.com](https://cx.sinopecsales.com/yjkqiantai/core/initCpb)；
- 🗺️ **省份 + 价区两级配置**：支持云南、四川等按"一价区/二价区…"发布价格的省份，也支持北京、广东等全省统一价的省份；
- 🚗 **多车辆管理**：每辆车独立维护名称、初始里程表读数、常用油品，可在集成选项界面添加/编辑/删除，也可通过服务调用管理；
- 📝 **记录加油**：记录加油量、里程表读数、加油时间、油品与备注，支持**批量导入历史加油数据**；
- 🧮 **智能计算，少填少输**：
  - 只填**加油金额** → 自动按当日油价算出加油量；
  - 只填**加油量** → 自动算出费用；
  - 录入**历史日期**的加油记录 → 自动查询中石化历史调价周期（约 11 个月），按**当天的真实油价**计算；
  - 里程不填自动沿用上次读数；
- 📊 **自动统计**：累计加油量/费用/次数、累计行驶里程、最近与平均油耗（L/100km）、平均油价、每公里油费、最近加油日期。

> ⚠️ 免责声明：本集成仅供个人学习与参考，油价数据以中国石化官方渠道及油站实际价格为准。

---

## 安装

### 方式一：HACS（推荐）

1. 确保已安装 [HACS](https://hacs.xyz/)；
2. HACS → 右上角 ⋮ → **自定义存储库** → 仓库地址 `https://github.com/ly2199/ha-sinopec-oil`，类别选 **集成**；
3. 在 HACS 中搜索「Sinopec Oil Price 中石化油价」并下载；
4. 重启 Home Assistant。

### 方式二：手动

将 `custom_components/sinopec_oil/` 整个目录复制到 HA 配置目录的 `custom_components/` 下，重启 HA。

---

## 配置

### 初始配置（添加集成）

1. 设置 → 设备与服务 → **添加集成** → 搜索「中石化油价」；
2. **选择省份**；
3. 若该省按价区发布油价（如云南），会自动出现**价区选择**步骤：每个选项直接列出**官方公布的适用州市**（如"一价区 · 适用于：昆明"）与参考油价（如"92号 8.44 元/L"），按你所在州市对照选择即可；全省统一价的省份自动跳过；
4. （可选）**添加第一辆车**：名称、当前里程表读数、常用油品。全部留空可跳过。

### 集成选项（修改位置 / 管理车辆）

点击集成条目 → **配置**，菜单式管理：

| 菜单 | 功能 |
| --- | --- |
| ⚙️ 油价设置 | 修改省份/价区、油价刷新间隔（分钟） |
| ➕ 添加车辆 | 名称、初始里程表读数、常用油品 |
| ✏️ 编辑车辆 | 修改初始里程、常用油品 |
| 🗑️ 删除车辆 | 删除车辆及全部记录 |
| 🧹 清空记录 | 保留车辆，清空加油记录 |
| 🧾 加油记录管理 | 查看/删除单条加油记录（修改用 edit 服务） |
| ✅ 完成 | 保存并应用 |

---

## 服务调用

### 记录加油 `sinopec_oil.record_refuel`

volume（加油量）与 total_cost（总费用）**至少填一项**，其余自动推算：

```yaml
# 例 1：今天加油花了 400 元，自动按当前油价算出加油量
service: sinopec_oil.record_refuel
data:
  vehicle: 家里的 white SUV
  odometer: 12345        # 不填则沿用上次读数
  total_cost: 400

# 例 2：录入上个月的历史加油（自动匹配当天油价算费用）
service: sinopec_oil.record_refuel
data:
  vehicle: 家里的 white SUV
  date: "2026-08-20 18:30:00"
  volume: 42.5           # 自动按 8/15~8/28 调价周期的油价算费用
  odometer: 11800
```

服务响应（`response_variable`）包含：加油量、费用、单价、**油价来源**（当前价/历史调价周期）、本次区间里程与油耗。

### 批量导入历史加油 `sinopec_oil.import_refuel_records`

```yaml
service: sinopec_oil.import_refuel_records
data:
  vehicle: 家里的 white SUV
  records:
    - {date: "2026-07-05 09:00:00", odometer: 8500,  total_cost: 300}
    - {date: "2026-07-20 19:00:00", odometer: 9080,  total_cost: 320}
    - {date: "2026-08-03 08:30:00", odometer: 9650,  volume: 40.2, total_cost: 330}
```

每条记录同样走智能计算（自动查当日油价），按日期排序后写入，导入完成即生成全部统计。

**有加油量和费用时，当时油价自动得出**：两字段同时填写时单价=费用÷加油量，
响应中 `price_source` 显示为"费用/加油量"，无需手动算。

### 记录维护（查看 / 删除 / 修改）

```yaml
# 1) 查看全部记录（含 index 序号，按日期升序）
service: sinopec_oil.list_refuel_records
data: {vehicle: 家里的 white SUV}
# 响应：{count, records: [{index, date, odometer, volume, total_cost, price, price_source...}], stats}

# 2) 删除一条记录（统计自动重算）
service: sinopec_oil.delete_refuel_record
data: {vehicle: 家里的 white SUV, index: 2}

# 3) 修改一条记录（只填要改的字段，其余智能重算）
#    只改加油量 → 按记录日期油价重算费用；只改费用 → 重算加油量；
#    量费同给 → 单价=费用/加油量；改时间 → 按新日期重新匹配历史油价
service: sinopec_oil.edit_refuel_record
data:
  vehicle: 家里的 white SUV
  index: 2
  volume: 41.5      # 只改这一项，费用按该记录日期的油价自动重算
```

也可以在 **集成选项 → 🧾 加油记录管理** 中按车浏览并删除单条记录。

### 查询历史油价 `sinopec_oil.get_price_history`

返回当前省份/价区的历史调价周期（约 24 期 ≈ 11 个月），每期含起止日期与各油品价格：

```yaml
service: sinopec_oil.get_price_history
# 响应：{location: "云南·一价区", period_count: 24,
#        periods: [{start: "2026-09-12", end: "2026-09-24",
#                   prices: {"92号汽油": 8.44, "95号汽油": 9.06, ...}}, ...]}
```

同样数据也挂在 **"油价更新时间"传感器的 `price_history` 属性**中，仪表盘可直接引用。

### 可视化填表录入（不想写 YAML？）

**方式一：开发者工具直接填表**。开发者工具 → 动作 → 选择
`sinopec_oil.record_refuel`，界面会渲染出车辆、里程、加油量、费用、
油品、时间、备注的完整表单，填完点"运行动作"即录入（勾选"响应"可看计算结果）。

**方式二：仪表盘填表（蓝图）**。本集成自带自动化蓝图 `中石化油价 · 加油记录填表`：

1. 先创建 7 个助手（设置 → 设备与服务 → 助手）：文本×3（车辆名/油品/备注）、
   数字×3（里程/加油量/费用）、按钮×1（提交）；
2. 创建自动化 → 蓝图 → 选择"中石化油价 · 加油记录填表"，把 7 个助手对应绑定；
3. 把下面的卡片加到仪表盘，日常加油在手机上点填即可，提交后表单自动清零：

```yaml
type: vertical-stack
cards:
  - type: entities
    title: ⛽ 加油记录
    entities:
      - entity: input_text.sinopec_vehicle
        name: 车辆
      - entity: input_number.sinopec_odometer
        name: 里程表读数 (km)
      - entity: input_number.sinopec_volume
        name: 加油量 (L，可不填)
      - entity: input_number.sinopec_cost
        name: 费用 (元，可不填)
      - entity: input_text.sinopec_fuel
        name: 油品 (92/95/0#)
      - entity: input_text.sinopec_note
        name: 备注
  - type: button
    name: 提交加油记录
    icon: mdi:fuel
    tap_action:
      action: perform-action
      perform_action: input_button.press
      target:
        entity_id: input_button.sinopec_submit
```

加油量与费用都填 → 单价=费用÷加油量；只填一个 → 另一个按当时油价自动算出。

### 车辆管理服务

```yaml
sinopec_oil.add_vehicle:    # {vehicle, initial_odometer, fuel_type}
sinopec_oil.remove_vehicle: # {vehicle}
sinopec_oil.clear_vehicle_data: # {vehicle} 清空记录保留车辆
sinopec_oil.refresh_oil_price:  # 立即刷新油价
```

---

## 实体

### 油价实体（按省份/价区自动生成）

| 实体 | 说明 |
| --- | --- |
| `sensor.*_92号汽油` 等 | 当日价格（元/L），属性含涨跌、更新时间、数据来源；有价区的省份设备名为「中石化油价 云南·二价区」 |
| `sensor.*_油价更新时间` | 油价数据更新时间；属性 `price_history` 为完整历史调价周期（约 24 期） |

### 车辆实体（每辆车一组）

| 实体 | 单位 | 说明 |
| --- | --- | --- |
| 当前里程表 | km | 最近一次加油的里程表读数 |
| 累计行驶里程 | km | 最新里程 − 初始里程（未设初始里程时为加油区间里程和） |
| 累计加油量 | L | 所有记录加油量之和 |
| 累计加油费用 | 元 | 所有记录费用之和 |
| 最近油耗 | L/100km | 最近一次加油区间的油耗 |
| 平均油耗 | L/100km | 记录期总加油量（首箱不计）/ 记录期总里程 × 100 |
| 平均油价 | 元/L | 累计费用 ÷ 累计加油量 |
| 每公里油费 | 元/km | 累计费用 ÷ 累计行驶里程 |
| 加油次数 | 次 | 记录条数 |
| 最近加油日期 | - | 最后一次加油时间 |

---

## 数据来源与接口

数据抓取自中国石化公开的"今日油价"页面：

| 接口 | 用途 |
| --- | --- |
| `GET /yjkqiantai/core/initCpb` | 建立会话 |
| `POST /yjkqiantai/data/switchProvince` | 切换省份（会话级） |
| `GET /yjkqiantai/data/initMainData` | 当日油价（省级 + 价区 area 列表） |
| `GET /yjkqiantai/data/initOilPrice` | 历史调价周期（约 24 期 ≈ 11 个月） |

接口为非官方公开接口，若中石化调整网站导致失效，欢迎提 Issue。

## License

[MIT](LICENSE)
