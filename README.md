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
3. 若该省按价区发布油价（如云南），会自动出现**价区选择**步骤（显示各区当前参考价）；全省统一价的省份自动跳过；
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
| `sensor.*_油价更新时间` | 油价数据更新时间 |

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

## 仓库与发布

- GitHub：<https://github.com/ly2199/ha-sinopec-oil>
- 版本发布：通过 Release 打标签（HACS 用户据此看到版本选择），如 `gh release create v1.0.0 --title "v1.0.0" --notes "首个版本"`

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
