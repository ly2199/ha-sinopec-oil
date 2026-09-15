# Sinopec Oil Price 中石化油价

![HA 版本](https://img.shields.io/badge/Home%20Assistant-2024.6%2B-blue)
![HACS](https://img.shields.io/badge/HACS-Custom-green)

一个 [Home Assistant](https://www.home-assistant.io/) 的 [HACS](https://hacs.xyz/) 自定义集成：

- ⛽ **查询实时油价**：数据来自中国石化"今日油价"公开页面 [cx.sinopecsales.com](https://cx.sinopecsales.com/yjkqiantai/core/initCpb)，支持全国 31 个省/直辖市/自治区；
- 📝 **记录加油数据**：通过 `记录加油` 服务记录加油量、里程表读数、加油时间、油品类型与备注；
- 💰 **自动计算统计**：加油费用、累计加油量、累计行驶里程、最近/平均油耗（L/100km）、平均油价、每公里油费、加油次数。

> ⚠️ 免责声明：本集成仅供个人学习与参考，油价数据以中国石化官方渠道及油站实际价格为准。

---

## 功能与实体

### 油价实体（每个已启用的油品一个传感器）

| 实体 | 说明 |
| --- | --- |
| `sensor.*_92号汽油` | 当日价格（元/L），属性中包含涨跌 `price_change`、更新时间等 |
| `sensor.*_95号汽油` / `98号汽油` / `0号柴油` 等 | 按所选省份实际启用的油品自动生成（92/95/98/爱跑系列/乙醇汽油/柴油系列/天然气） |
| `sensor.*_油价更新时间` | 油价数据更新时间 |

### 加油统计实体（每辆车一组，首次记录加油后自动生成）

| 实体 | 单位 | 说明 |
| --- | --- | --- |
| 当前里程表 | km | 最近一次加油的里程表读数 |
| 累计加油量 | L | 所有记录加油量之和 |
| 累计加油费用 | 元 | 所有记录费用之和 |
| 累计行驶里程 | km | 相邻两次加油里程差之和 |
| 最近油耗 | L/100km | 最近一次区间的油耗 |
| 平均油耗 | L/100km | （除首箱外）总加油量 ÷ 总里程 × 100 |
| 平均油价 | 元/L | 累计费用 ÷ 累计加油量 |
| 每公里油费 | 元/km | 累计费用 ÷ 累计行驶里程 |
| 加油次数 | 次 | 记录条数 |

> 油耗计算假设"每次加满"。首次加油仅作为基准，不参与平均油耗计算。

---

## 安装

### 方式一：通过 HACS（推荐）

1. HACS → 右上角菜单 → **自定义存储库**；
2. 仓库地址填 `https://github.com/ly2199/ha-sinopec-oil`，类别选 **集成（Integration）**；
3. 在 HACS 中搜索 **Sinopec Oil Price 中石化油价** 并下载；
4. 重启 Home Assistant。

### 方式二：手动安装

将 `custom_components/sinopec_oil` 整个目录复制到 HA 配置目录的 `custom_components/` 下，重启 HA：

```text
config/
└── custom_components/
    └── sinopec_oil/
        ├── __init__.py
        ├── api.py
        ├── ...
```

---

## 配置

1. HA → **设置** → **设备与服务** → **添加集成** → 搜索 **Sinopec Oil Price 中石化油价**；
2. 在初始配置中选择**默认油价查询位置**（省份），例如"北京"；
3. 添加完成后，油价传感器即自动创建（仅创建该省份实际启用的油品）。

### 修改油价位置（填写时配置）

- **设置** → **设备与服务** → 找到"中石化油价" → 点击 **配置（选项）**；
- 可随时修改油价查询位置与刷新间隔（默认 60 分钟）；
- 保存后集成自动重载并重建传感器。

如需同时关注多个省份，可再次"添加集成"选择另一省份（每个省份一个实例）。

---

## 使用：记录加油

在开发者工具或自动化中调用服务 `sinopec_oil.record_refuel`：

```yaml
service: sinopec_oil.record_refuel
data:
  vehicle: 我的 car          # 车辆名称（必填，用于区分多车）
  odometer: 12345            # 里程表读数 km（必填）
  volume: 40.5               # 加油量 L（必填）
  total_cost: 350            # 总费用 元（与单价至少填一项）
  # price: 8.29              # 单价 元/L（不填总费用时用；都不填则自动引用实时油价）
  fuel_type: "92"            # 油品类型（可选）
  # date: "2026-09-15 10:00:00"  # 加油时间（可选，默认当前）
  note: 中石化XX加油站         # 备注（可选）
```

服务支持返回结果（开发者工具中勾选"响应"），返回本次区间的行驶里程、最近油耗及最新统计。

其他服务：

```yaml
# 清除某辆车的全部记录
service: sinopec_oil.clear_vehicle_data
data:
  vehicle: 我的 car

# 立即刷新油价
service: sinopec_oil.refresh_oil_price
```

### 自动化示例：洗车建议（大雨后）

```yaml
automation:
  - alias: 加油提醒
    trigger:
      - platform: numeric_state
        entity_id: sensor.my_car_jiayoucishu
        below: 1
    action:
      - service: persistent_notification.create
        data:
          message: "记录第一次加油后即可开始统计油耗。"
```

---

## 仓库与发布

- GitHub：<https://github.com/ly2199/ha-sinopec-oil>
- 版本发布：通过 Release 打标签（HACS 用户据此看到版本选择），如 `gh release create v1.0.0 --title "v1.0.0" --notes "首个版本"`

---

## 数据来源与接口

数据抓取自中国石化公开的"今日油价"页面，接口流程：

1. `GET https://cx.sinopecsales.com/yjkqiantai/core/initCpb`（建立会话）
2. `POST https://cx.sinopecsales.com/yjkqiantai/data/switchProvince`（`{"provinceId": "11"}`，按省份切换）
3. `GET https://cx.sinopecsales.com/yjkqiantai/data/initMainData`（返回油价 JSON）

接口为非官方公开接口，若中石化调整网站导致失效，欢迎提 Issue。

## License

[MIT](LICENSE)
