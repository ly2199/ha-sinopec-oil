/**
 * Sinopec Oil Card — 中石化油价 · 加油记账一体化卡片
 *
 * 安装：将本文件复制到 /config/www/sinopec-oil-card.js，然后在
 * 仪表盘 → 右上角 ⋮ → 管理资源 → 添加
 *   URL: /local/sinopec-oil-card.js   版本: 1.0.5
 * 使用：仪表盘添加卡片 → 手动 →
 *   type: custom:sinopec-oil-card
 * 可选: title: 我的油卡   vehicle: 某辆车（不填则记住上次选择）
 *
 * 卡片自动发现本集成实体（基于 sinopec_role 属性），
 * 无需填写任何实体 ID。
 *
 * 页签：加油 · 历史 · 油价 · 统计
 * 1.0.5 记账口径：区分「加油费用」（挂牌价合计）与「实际支付」（真实付款），
 *       优惠金额 = 加油费用 - 实际支付，由后端自动计算；
 *       留空实际支付即视为无优惠；历史记录与统计磁贴同步展示优惠。
 * 1.0.4 界面重构：容器查询自适应布局（按卡片实际宽度而非屏幕）、
 *       分段式页签、分区表单、统计/油价磁贴、表格圆角化 + 行悬浮 +
 *       数字右对齐、提交按钮回车快捷键；功能与数据口径完全不变。
 * 规则：区间油耗由相邻里程差算出（0 < Δ ≤ 900 km）。
 * 里程可留空 → 该区间记为「缺口」不参与油耗统计，不影响其他区间；
 * 时间与里程矛盾（Δ ≤ 0 或与紧邻记录 Δ > 900 km）的记录会被拒绝入库。
 */
(() => {
  const FUEL_OPTIONS = ['自动', '92', '95', '98', '89', '0#', '-10', '-20', '-35', 'LNG'];
  const TABS = [
    { id: 'refuel', label: '加油', icon: 'mdi:gas-station' },
    { id: 'history', label: '历史', icon: 'mdi:table' },
    { id: 'price', label: '油价', icon: 'mdi:chart-line' },
    { id: 'stats', label: '统计', icon: 'mdi:car' },
  ];
  const LS_VEHICLE_KEY = 'sinopec-oil-card.vehicle';
  // 历史调价周期表最多展示的行数
  const HISTORY_ROWS = 12;

  const CARD_CSS = `
    :host { display: block; }

    /* ---------- 卡片骨架：顶部渐变点缀 + 容器查询（按卡片实际宽度自适应） ---------- */
    ha-card { position: relative; overflow: hidden; container-type: inline-size; }
    ha-card::before {
      content: '';
      position: absolute; top: 0; left: 0; right: 0; height: 3px;
      background: linear-gradient(90deg,
        var(--primary-color) 0%,
        color-mix(in srgb, var(--primary-color) 35%, transparent) 55%,
        transparent 100%);
    }
    .card { padding: 18px 22px 22px; }

    /* ---------- 头部 ---------- */
    .header {
      display: flex; align-items: center; justify-content: space-between;
      gap: 10px 14px; flex-wrap: wrap; margin-bottom: 14px;
    }
    .title {
      display: flex; align-items: center; gap: 10px;
      font-size: 1.18em; font-weight: 700; letter-spacing: .3px;
      color: var(--primary-text-color);
    }
    .title-icon {
      display: inline-flex; align-items: center; justify-content: center;
      width: 36px; height: 36px; flex: none; border-radius: 11px;
      color: var(--primary-color);
      background: rgba(128,128,128,.12);
      background: color-mix(in srgb, var(--primary-color) 15%, transparent);
    }
    .title-icon ha-icon { --mdc-icon-size: 22px; }

    .vehicle-wrap {
      display: inline-flex; align-items: center; gap: 7px; height: 38px;
      padding: 0 7px 0 13px; border: 1px solid var(--divider-color);
      border-radius: 999px; background: var(--secondary-background-color);
      cursor: pointer; transition: border-color .2s, box-shadow .2s;
    }
    .vehicle-wrap:hover, .vehicle-wrap:focus-within {
      border-color: var(--primary-color);
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary-color) 15%, transparent);
    }
    .vehicle-wrap ha-icon { --mdc-icon-size: 18px; color: var(--primary-color); }
    .vehicle-wrap .chev { color: var(--secondary-text-color); }
    select.vehicle {
      appearance: none; -webkit-appearance: none;
      border: none; background: transparent; color: var(--primary-text-color);
      font: inherit; font-size: .88em; font-weight: 600;
      height: 100%; padding: 0; max-width: 180px;
      cursor: pointer; outline: none;
    }

    /* ---------- 页签：分段式控制器 ---------- */
    .tabs {
      display: grid; grid-template-columns: repeat(4, 1fr); gap: 4px;
      margin: 2px 0 18px; padding: 4px;
      background: var(--secondary-background-color); border-radius: 13px;
    }
    .tab {
      display: flex; align-items: center; justify-content: center; gap: 6px;
      padding: 9px 6px; border-radius: 9px; cursor: pointer;
      font-size: .88em; font-weight: 500; color: var(--secondary-text-color);
      transition: color .2s, background-color .2s, box-shadow .2s;
      user-select: none; white-space: nowrap;
    }
    .tab ha-icon { --mdc-icon-size: 17px; }
    .tab:hover { color: var(--primary-text-color); }
    .tab.active {
      color: var(--text-primary-color); background: var(--primary-color);
      font-weight: 600; box-shadow: 0 2px 8px rgba(0,0,0,.16);
    }

    /* ---------- 表单：自适应网格（窄卡片自动降列数） ---------- */
    .form-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(190px, 100%), 1fr));
      gap: 12px 14px;
    }
    .field { display: flex; flex-direction: column; min-width: 0; }
    .field label {
      font-size: .78em; font-weight: 600; letter-spacing: .2px;
      color: var(--secondary-text-color);
      margin-bottom: 6px; line-height: 1.4;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    }
    .field .sub {
      font-size: .72em; color: var(--secondary-text-color);
      margin-top: 4px; line-height: 1.45;
    }
    .field input, .field select, textarea {
      width: 100%; box-sizing: border-box; min-height: 42px;
      padding: 9px 12px;
      border: 1px solid var(--divider-color); border-radius: 10px;
      background: var(--card-background-color); color: var(--primary-text-color);
      font: inherit; font-size: .95em;
      transition: border-color .2s, box-shadow .2s;
    }
    .field input:hover, .field select:hover, textarea:hover {
      border-color: color-mix(in srgb, var(--primary-color) 45%, var(--divider-color));
    }
    .field input:focus, .field select:focus, textarea:focus {
      outline: none; border-color: var(--primary-color);
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--primary-color) 16%, transparent);
    }
    .field input::placeholder, textarea::placeholder {
      color: color-mix(in srgb, var(--secondary-text-color) 75%, transparent);
    }
    textarea {
      min-height: 120px; resize: vertical; border-radius: 12px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: .88em; line-height: 1.6;
    }

    /* ---------- 按钮 ---------- */
    .btn {
      display: inline-flex; align-items: center; justify-content: center; gap: 7px;
      padding: 10px 22px; border: none; border-radius: 12px; cursor: pointer;
      font: inherit; font-size: .92em; font-weight: 600; letter-spacing: .3px;
      background: var(--primary-color); color: var(--text-primary-color);
      box-shadow: 0 2px 8px color-mix(in srgb, var(--primary-color) 32%, transparent);
      transition: box-shadow .2s, transform .15s, background-color .2s,
                  border-color .2s, color .2s, opacity .2s;
    }
    .btn ha-icon { --mdc-icon-size: 18px; }
    .btn:hover:not(:disabled) {
      box-shadow: 0 4px 16px color-mix(in srgb, var(--primary-color) 45%, transparent);
    }
    .btn:active:not(:disabled) { transform: translateY(1px); }
    .btn:disabled { opacity: .55; cursor: default; }
    .btn.secondary {
      background: transparent; color: var(--primary-text-color);
      border: 1px solid var(--divider-color); box-shadow: none;
    }
    .btn.secondary:hover:not(:disabled) {
      border-color: var(--primary-color); color: var(--primary-color);
      background: color-mix(in srgb, var(--primary-color) 7%, transparent); box-shadow: none;
    }
    .btn.danger {
      background: var(--error-color, #db4437); color: #fff;
      box-shadow: 0 2px 8px color-mix(in srgb, var(--error-color, #db4437) 30%, transparent);
    }
    .btn.danger:hover:not(:disabled) {
      box-shadow: 0 4px 16px color-mix(in srgb, var(--error-color, #db4437) 45%, transparent);
    }
    .btn.mini { padding: 6px 14px; font-size: .78em; border-radius: 9px; box-shadow: none; }
    .btn-lg { padding: 12px 28px; font-size: .98em; border-radius: 13px; }

    /* ---------- 表格内的小图标按钮 ---------- */
    .actions { display: inline-flex; gap: 6px; }
    .icon-btn {
      display: inline-flex; align-items: center; justify-content: center;
      width: 30px; height: 30px; flex: none;
      border: 1px solid var(--divider-color); border-radius: 9px;
      background: var(--card-background-color); color: var(--secondary-text-color);
      cursor: pointer;
      transition: color .2s, border-color .2s, background-color .2s;
    }
    .icon-btn ha-icon { --mdc-icon-size: 16px; }
    .icon-btn:hover { color: var(--primary-color); border-color: var(--primary-color); }
    .icon-btn.danger:hover {
      color: var(--error-color, #db4437); border-color: var(--error-color, #db4437);
      background: color-mix(in srgb, var(--error-color, #db4437) 8%, transparent);
    }

    /* ---------- 提示条 ---------- */
    .msg {
      display: flex; gap: 10px; margin: 12px 0; padding: 12px 14px;
      border-radius: 12px; border: 1px solid transparent; border-left-width: 3px;
      font-size: .86em; line-height: 1.65;
    }
    .msg ha-icon { flex: none; --mdc-icon-size: 19px; margin-top: 2px; }
    .msg b { display: block; margin-bottom: 4px; font-weight: 700; }
    .msg.ok { background: rgba(76,175,80,.10); color: var(--success-color, #2e7d32); border-left-color: var(--success-color, #2e7d32); }
    .msg.err { background: rgba(219,68,55,.08); color: var(--error-color, #db4437); border-left-color: var(--error-color, #db4437); }
    .msg.warn { background: rgba(255,152,0,.10); color: var(--warning-color, #ef6c00); border-left-color: var(--warning-color, #ef6c00); }
    .msg.info { background: var(--secondary-background-color); color: var(--primary-text-color); border-left-color: var(--divider-color); }

    /* ---------- 表格：圆角容器 + 行悬浮 + 数字右对齐 ---------- */
    .table-wrap {
      overflow-x: auto; margin: 12px 0 4px;
      border: 1px solid var(--divider-color); border-radius: 12px;
      background: var(--card-background-color);
    }
    table { width: 100%; border-collapse: collapse; font-size: .84em; }
    th {
      text-align: left; white-space: nowrap;
      padding: 10px 12px;
      color: var(--secondary-text-color); font-weight: 600; font-size: .95em;
      background: var(--secondary-background-color);
      border-bottom: 1px solid var(--divider-color);
    }
    td {
      padding: 9px 12px; vertical-align: middle;
      border-bottom: 1px solid var(--divider-color);
      border-bottom-color: color-mix(in srgb, var(--divider-color) 50%, transparent);
      color: var(--primary-text-color);
    }
    tr:last-child td { border-bottom: none; }
    tbody tr { transition: background-color .15s; }
    tbody tr:hover td { background: color-mix(in srgb, var(--primary-color) 4%, transparent); }
    .num, th.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .period { white-space: nowrap; }
    .note-cell { max-width: 170px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .muted { color: var(--secondary-text-color); }
    .up { color: var(--error-color, #d32f2f); }
    .down { color: var(--success-color, #2e7d32); }

    /* ---------- 统计 / 油价磁贴 ---------- */
    .grid {
      display: grid; gap: 10px; margin: 12px 0;
      grid-template-columns: repeat(auto-fill, minmax(min(148px, 100%), 1fr));
    }
    .stat {
      padding: 14px; border-radius: 14px;
      background: var(--secondary-background-color);
      border: 1px solid var(--divider-color);
      border-color: color-mix(in srgb, var(--divider-color) 60%, transparent);
      transition: transform .2s, box-shadow .2s, border-color .2s;
    }
    .stat:hover {
      transform: translateY(-2px);
      border-color: color-mix(in srgb, var(--primary-color) 35%, transparent);
      box-shadow: 0 8px 20px rgba(0,0,0,.08);
    }
    .stat-icon { display: inline-flex; margin-bottom: 8px; color: var(--primary-color); opacity: .85; }
    .stat-icon ha-icon { --mdc-icon-size: 20px; }
    .stat .v {
      font-size: 1.3em; font-weight: 700; letter-spacing: .2px;
      color: var(--primary-text-color); font-variant-numeric: tabular-nums;
    }
    .stat .k { font-size: .74em; font-weight: 500; color: var(--secondary-text-color); margin-top: 3px; }
    .stat .d { font-size: .78em; font-weight: 600; margin-top: 4px; color: var(--secondary-text-color); }
    .stat .d.up { color: var(--error-color, #d32f2f); }
    .stat .d.down { color: var(--success-color, #2e7d32); }
    .stat.wide {
      grid-column: 1 / -1;
      display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
      background: var(--primary-color);
      background: linear-gradient(120deg,
        var(--primary-color),
        color-mix(in srgb, var(--primary-color) 78%, #000));
      border-color: transparent;
    }
    .stat.wide:hover {
      transform: none; border-color: transparent;
      box-shadow: 0 8px 20px color-mix(in srgb, var(--primary-color) 35%, transparent);
    }
    .stat.wide .stat-icon { color: var(--text-primary-color); opacity: .95; margin-bottom: 0; }
    .stat.wide .v { color: var(--text-primary-color); font-size: 1.5em; }
    .stat.wide .v .unit { font-size: .5em; font-weight: 500; opacity: .85; margin-left: 4px; }
    .stat.wide .k { color: var(--text-primary-color); opacity: .85; margin-top: 0; font-size: .8em; }

    .pill {
      display: inline-block; padding: 2px 11px; border-radius: 999px;
      font-size: .78em; font-weight: 600;
      background: var(--secondary-background-color); color: var(--secondary-text-color);
    }
    .pill.good { background: rgba(76,175,80,.14); color: var(--success-color, #2e7d32); }
    .pill.bad { background: rgba(219,68,55,.12); color: var(--error-color, #db4437); }
    .pill.up { background: rgba(219,68,55,.12); color: var(--error-color, #db4437); }
    .pill.down { background: rgba(76,175,80,.14); color: var(--success-color, #2e7d32); }

    /* ---------- 油价页签元信息 ---------- */
    .meta {
      display: flex; flex-wrap: wrap; align-items: center;
      gap: 6px 18px; margin: 12px 0 2px;
      font-size: .8em; color: var(--secondary-text-color);
    }
    .meta b { color: var(--primary-text-color); }

    /* ---------- 走势条形图 ---------- */
    .chart { margin-top: 14px; }
    .bar-wrap { display: flex; align-items: center; gap: 10px; margin: 4px 0; font-size: .8em; }
    .bar-label { width: 58px; flex: none; text-align: right; color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
    .bar-track { flex: 1; height: 16px; border-radius: 999px; background: var(--secondary-background-color); overflow: hidden; }
    .bar-fill {
      height: 100%; border-radius: 999px;
      background: var(--primary-color);
      background: linear-gradient(90deg, color-mix(in srgb, var(--primary-color) 50%, transparent), var(--primary-color));
      transition: width .5s ease;
    }
    .bar-val { width: 58px; flex: none; font-weight: 600; font-variant-numeric: tabular-nums; color: var(--primary-text-color); }

    /* ---------- 编辑 / 导入面板 ---------- */
    .editbox {
      background: var(--secondary-background-color);
      background: color-mix(in srgb, var(--primary-color) 4%, var(--secondary-background-color));
      border: 1px solid var(--divider-color);
      border-color: color-mix(in srgb, var(--primary-color) 18%, var(--divider-color));
      border-radius: 14px; padding: 14px; margin: 10px 0;
    }
    .editbox-title {
      display: flex; align-items: center; gap: 8px;
      font-size: .86em; font-weight: 600; color: var(--primary-text-color);
      margin-bottom: 12px;
    }
    .editbox-title ha-icon { --mdc-icon-size: 17px; color: var(--primary-color); }
    tr.editing td {
      background: color-mix(in srgb, var(--primary-color) 8%, transparent);
      border-top: 1px solid color-mix(in srgb, var(--primary-color) 30%, transparent);
      border-bottom: 1px solid color-mix(in srgb, var(--primary-color) 30%, transparent);
    }

    .empty {
      text-align: center; color: var(--secondary-text-color);
      padding: 34px 16px; font-size: .9em; line-height: 1.8;
    }
    .empty ha-icon {
      --mdc-icon-size: 42px; display: block; margin: 0 auto 10px;
      opacity: .35; color: var(--primary-color);
    }
    .flexright {
      display: flex; justify-content: flex-end; align-items: center;
      gap: 10px; margin-top: 14px; flex-wrap: wrap;
    }
    .hint { font-size: .8em; color: var(--secondary-text-color); margin: 8px 0; line-height: 1.75; }
    .hint b { color: var(--primary-text-color); }
    .hint code {
      background: rgba(128,128,128,.14);
      background: color-mix(in srgb, var(--primary-color) 10%, transparent);
      padding: 1px 6px; border-radius: 5px;
      font-family: ui-monospace, Menlo, Consolas, monospace;
    }
    .tips {
      margin-top: 14px; padding: 11px 14px; border-radius: 12px;
      background: var(--secondary-background-color);
      font-size: .8em; color: var(--secondary-text-color); line-height: 1.8;
    }
    .tips b { color: var(--primary-text-color); }

    .spin { display: inline-flex; animation: soc-rot 1s linear infinite; }
    @keyframes soc-rot { to { transform: rotate(360deg); } }

    /* ---------- 自适应：按卡片实际宽度（容器查询，而非屏幕宽度） ---------- */
    @container (max-width: 620px) {
      .card { padding: 14px 14px 16px; }
      .title { font-size: 1.08em; gap: 8px; }
      .title-icon { width: 32px; height: 32px; border-radius: 9px; }
      .title-icon ha-icon { --mdc-icon-size: 20px; }
      .flexright > .btn { flex: 1 1 auto; }
      .bar-label, .bar-val { width: 50px; }
    }
    @container (max-width: 430px) {
      .form-grid { grid-template-columns: 1fr; }
      .tab { gap: 4px; font-size: .82em; }
      .stat .v { font-size: 1.18em; }
      .grid { grid-template-columns: repeat(auto-fill, minmax(min(126px, 100%), 1fr)); }
    }

    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { transition: none !important; animation: none !important; }
    }
  `;

  const esc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  const fmt = (v, d = 2) => (v == null || v === '' || isNaN(v)) ? '—' : Number(v).toFixed(d);

  const num = (v) => (v == null || v === '' || v === 'unknown' || v === 'unavailable' || isNaN(v))
    ? null : Number(v);

  const signed = (v) => `${v > 0 ? '+' : ''}${fmt(v)}`;

  const lsGet = () => { try { return localStorage.getItem(LS_VEHICLE_KEY); } catch (e) { return null; } };
  const lsSet = (v) => { try { localStorage.setItem(LS_VEHICLE_KEY, v); } catch (e) { /* 隐私模式忽略 */ } };

  class SinopecOilCard extends HTMLElement {
    static getStubConfig() { return { type: 'custom:sinopec-oil-card' }; }

    getCardSize() {
      if (this._tab === 'history') return 8;
      if (this._tab === 'price') return 9;
      if (this._tab === 'stats') return 5;
      return 4;
    }

    getConfigElement() { return null; }
    getConfig() { return this._config; }

    setConfig(config) {
      if (!config) throw new Error('配置无效');
      this._config = { title: '中石化加油记账', ...config };
      this._tab = 'refuel';
      this._form = { date: null, odometer: '', volume: '', total_cost: '', actual_payment: '', fuel: '自动', note: '' };
      this._result = null;      // 提交响应
      this._error = null;       // 错误信息
      this._busy = false;
      this._editIdx = null;     // 正在编辑的记录序号
      this._editForm = {};
      this._pendingDelete = null; // 待二次确认的删除序号
      this._showImport = false;
      this._importText = '';
      this._importResult = null;
      this._vehicle = null;
      this._entityIds = null;
      this._stateCount = null;
      this._lastSig = null;
      this._styled = false;
    }

    set hass(hass) {
      this._hass = hass;
      const states = hass.states || {};
      const count = Object.keys(states).length;
      let vehicleChanged = false;

      // 实体增删（新车辆、新油品）时才重新扫描角色，避免每次推送全表过滤
      if (!this._entityIds || count !== this._stateCount) {
        this._stateCount = count;
        const before = this._vehicle;
        this._discover(states);
        this._rememberVehicle();
        vehicleChanged = before !== this._vehicle;
      }
      // 每次推送都必须用当前 states 重新绑定实体对象：
      // _discover 只在实体增删时运行，若此处不重绑，读到的 attributes
      // 会停留在上次扫描的快照（表现为改完记录/刷新油价后界面不变）。
      this._bindStates(states);

      // 仅在本卡片关心的实体发生变化时重绘：
      // HA 每秒都会推送 hass，无节流会导致输入框反复失焦。
      const sig = this._entityIds.map((id) => {
        const s = states[id];
        return s ? `${s.state}|${s.last_updated}` : '-';
      }).join(';');
      if (sig === this._lastSig && !vehicleChanged) return;
      this._lastSig = sig;
      this._render();
    }

    /* ---------- 实体自动发现 ---------- */
    _discover(states) {
      // 只记录「角色 → 实体 ID」，状态对象由 _bindStates 每次推送时重取
      const idsByRole = (role) => Object.values(states)
        .filter((s) => s.attributes && s.attributes.sinopec_role === role)
        .map((s) => s.entity_id);
      this._ids = {
        records: idsByRole('sinopec_records'),
        quality: idsByRole('sinopec_quality'),
        odometer: idsByRole('sinopec_odometer'),
        price: idsByRole('sinopec_price'),
        history: idsByRole('sinopec_price_history')[0] || null,
        periodEnd: idsByRole('sinopec_period_end')[0] || null,
        trend: idsByRole('sinopec_trend')[0] || null,
      };
      this._vehicles = this._ids.records
        .map((id) => states[id] && states[id].attributes.vehicle)
        .filter(Boolean);
      this._entityIds = [...new Set([
        ...this._ids.records, ...this._ids.quality, ...this._ids.odometer,
        ...this._ids.price, this._ids.history, this._ids.periodEnd,
        this._ids.trend,
      ].filter(Boolean))];
    }

    /** 用当前 states 重新绑定实体对象，保证读到的 attributes 是最新的。 */
    _bindStates(states) {
      const ids = this._ids;
      if (!ids) return;
      const pickAll = (list) => list.map((id) => states[id]).filter(Boolean);
      this._recordsEnts = pickAll(ids.records);
      this._qualityEnts = pickAll(ids.quality);
      this._odometerEnts = pickAll(ids.odometer);
      this._priceEnts = pickAll(ids.price);
      this._historyEnt = (ids.history && states[ids.history]) || null;
      this._periodEndEnt = (ids.periodEnd && states[ids.periodEnd]) || null;
      this._trendEnt = (ids.trend && states[ids.trend]) || null;
    }

    _rememberVehicle() {
      if (!this._vehicles.length) { this._vehicle = null; return; }
      if (this._vehicle && this._vehicles.includes(this._vehicle)) return;
      const wanted = this._config.vehicle || lsGet();
      this._vehicle = this._vehicles.includes(wanted) ? wanted : this._vehicles[0];
    }

    _recEntity() {
      return this._recordsEnts.find((s) => s.attributes.vehicle === this._vehicle) || null;
    }

    _qualityEntity() {
      return this._qualityEnts.find((s) => s.attributes.vehicle === this._vehicle) || null;
    }

    _records() {
      const ent = this._recEntity();
      return (ent && ent.attributes.records) || [];
    }

    /** 后端算好的权威统计（store.compute_stats），前端不再重复实现口径。 */
    _stats() {
      const ent = this._recEntity();
      return (ent && ent.attributes.stats) || {};
    }

    _currentOdometer() {
      const recs = this._records();
      for (let i = recs.length - 1; i >= 0; i--) {
        if (recs[i].odometer != null) return recs[i].odometer;
      }
      // 无记录时回退到「当前里程表」实体（其值含配置的初始里程）
      const ent = this._odometerEnts.find((s) => s.attributes.vehicle === this._vehicle);
      const v = ent ? num(ent.state) : null;
      return v == null ? '' : v;
    }

    /* ---------- 服务调用 ---------- */
    async _call(service, payload, useResponse) {
      this._busy = true; this._error = null; this._render();
      try {
        // 前端签名：callService(domain, service, serviceData, target, returnResponse)。
        // return_response 必须作为第 5 个参数传入；放进 target 会被 websocket
        // 校验拒绝（not a valid option at 'target.return_response'）。
        const resp = await this._hass.callService(
          'sinopec_oil', service, payload, undefined, useResponse === true
        );
        return resp || null;
      } catch (err) {
        this._error = (err && err.message) || String(err);
        throw err;
      } finally {
        this._busy = false;
        this._render();
      }
    }

    async _submit() {
      this._result = null;
      const f = this._form;
      const payload = { vehicle: this._vehicle };
      if (!f.date) f.date = this._nowLocal();
      payload.date = f.date + (f.date.length === 16 ? ':00' : '');
      if (f.odometer !== '' && f.odometer != null) payload.odometer = Number(f.odometer);
      if (f.volume !== '' && f.volume != null) payload.volume = Number(f.volume);
      if (f.total_cost !== '' && f.total_cost != null) payload.total_cost = Number(f.total_cost);
      if (f.actual_payment !== '' && f.actual_payment != null) payload.actual_payment = Number(f.actual_payment);
      if (f.fuel && f.fuel !== '自动') payload.fuel_type = f.fuel;
      if (f.note) payload.note = f.note;
      if (payload.volume == null && payload.total_cost == null && payload.actual_payment == null) {
        this._error = '请至少填写加油量、加油费用或实际支付之一（费用与实付都填则自动算优惠）。';
        this._render(); return;
      }
      // 本地先校验一次，避免"实付 > 加油费用"的服务端拒绝白跑一趟
      if (payload.total_cost != null && payload.actual_payment != null
          && payload.actual_payment > payload.total_cost) {
        this._error = `实际支付（${payload.actual_payment} 元）不能高于加油费用（${payload.total_cost} 元）。`;
        this._render(); return;
      }
      try {
        const resp = await this._call('record_refuel', payload, true);
        this._result = resp || { ok: true };
        // 清空量/费/实付/备注，里程停留在提交值供下次微调
        this._form.volume = '';
        this._form.total_cost = '';
        this._form.actual_payment = '';
        this._form.note = '';
        this._render();
      } catch (e) { /* 已记录 _error */ }
    }

    async _delete(index) {
      this._pendingDelete = null;
      try {
        await this._call('delete_refuel_record', { vehicle: this._vehicle, index }, false);
        this._result = { deleted: index };
        this._render();
      } catch (e) { /* 已记录 _error */ }
    }

    async _saveEdit() {
      const f = this._editForm;
      const pay = (v) => (v === '' || v == null || v === '—') ? null : Number(v);
      const payload = { vehicle: this._vehicle, index: this._editIdx };
      if (f.date) payload.date = f.date;
      const odo = pay(f.odometer);
      if (odo != null) payload.odometer = odo;
      // 编辑面板里显示的是当前值，因此"看到的即提交的"：
      // 三个金额项都按输入框内容提交，未改动即等于原值，不会误清优惠。
      const vol = pay(f.volume);
      if (vol != null) payload.volume = vol;
      const cost = pay(f.total_cost);
      if (cost != null) payload.total_cost = cost;
      const paid = pay(f.actual_payment);
      if (paid != null) payload.actual_payment = paid;
      if (f.fuel && f.fuel !== '自动') payload.fuel_type = f.fuel;
      if (f.note !== undefined) payload.note = f.note;
      if (cost != null && paid != null && paid > cost) {
        this._error = `实际支付（${paid} 元）不能高于加油费用（${cost} 元）。`;
        this._render(); return;
      }
      try {
        await this._call('edit_refuel_record', payload, false);
        this._editIdx = null;
        this._result = { edited: true };
        this._render();
      } catch (e) { /* 已记录 _error */ }
    }

    _parseImport() {
      const lines = this._importText.split('\n').map((l) => l.trim()).filter(Boolean);
      const splitLine = (line) => {
        // 保留空单元格以维持列位置（否则 "日期,,41.2,338" 会被错位解析），
        // 只去掉行尾的空列
        const parts = line.split(/[,;\t，]/).map((p) => p.trim());
        while (parts.length && parts[parts.length - 1] === '') parts.pop();
        return parts;
      };
      // 6 列时第 5 列是"实际支付"还是旧写法的"油品"列存在歧义，
      // 整批数据按一个口径统一解析：只要出现 7 列以上，或某行第 5、6 列
      // 都是非空数字（实付 + 油品号），就认定这批用的是新写法，
      // 避免同一批数据被两种口径拆散。旧写法请保持 6 列以内。
      const isNumeric = (v) => v != null && v !== '' && !isNaN(parseFloat(v));
      const newStyleByColumns = lines.some((line) => {
        const p = splitLine(line);
        return (
          p.length >= 7 ||
          (p.length === 6 && isNumeric(p[4]) && isNumeric(p[5]))
        );
      });
      const out = [];
      for (const line of lines) {
        if (/^(日期|date)/i.test(line)) continue; // 表头
        const parts = splitLine(line);
        if (!parts.length || !parts[0]) {
          out.push({ raw: line, error: '缺少日期' });
          continue;
        }
        // 列含义：日期, 里程, 加油量, 加油费用, [实际支付], [油品], [备注]
        const [date, odo, vol, cost, fifth, sixth, ...rest] = parts;
        const fifthFilled = fifth != null && fifth !== '';
        const isNew = newStyleByColumns;
        let pay = '';
        let fuel = '';
        if (isNew) {
          pay = fifthFilled ? fifth : '';
          fuel = sixth || '';
        } else {
          fuel = fifthFilled ? fifth : '';
        }
        const noteParts = isNew ? rest : [sixth, ...rest];
        const rec = { date: date.length === 10 ? date + 'T12:00:00' : date };
        // 里程可留空：该行照常入库，只是这个区间不参与油耗统计
        if (odo) {
          const o = parseFloat(odo);
          if (isNaN(o)) { out.push({ raw: line, error: `里程不是数字：${odo}` }); continue; }
          rec.odometer = o;
        }
        if (vol) {
          const v = parseFloat(vol);
          if (isNaN(v)) { out.push({ raw: line, error: `加油量不是数字：${vol}` }); continue; }
          rec.volume = v;
        }
        if (cost) {
          const c = parseFloat(cost);
          if (isNaN(c)) { out.push({ raw: line, error: `加油费用不是数字：${cost}` }); continue; }
          rec.total_cost = c;
        }
        if (pay) {
          const p = parseFloat(pay);
          if (isNaN(p)) { out.push({ raw: line, error: `实际支付不是数字：${pay}` }); continue; }
          rec.actual_payment = p;
        }
        if (rec.total_cost != null && rec.actual_payment != null
            && rec.actual_payment > rec.total_cost) {
          out.push({ raw: line, error: '实际支付不能高于加油费用' });
          continue;
        }
        if (rec.volume == null && rec.total_cost == null && rec.actual_payment == null) {
          out.push({ raw: line, error: '加油量、加油费用与实际支付至少填一项' });
          continue;
        }
        if (fuel) rec.fuel_type = fuel;
        if (noteParts.length) rec.note = noteParts.filter(Boolean).join(' ');
        out.push({ raw: line, record: rec });
      }
      return out;
    }

    async _doImport() {
      const parsed = this._parseImport();
      const valid = parsed.filter((p) => p.record).map((p) => p.record);
      const bad = parsed.filter((p) => p.error);
      if (!valid.length) {
        this._importResult = { imported: 0, rejected: bad.map((b) => `${b.raw} → ${b.error}`) };
        this._render(); return;
      }
      try {
        const resp = await this._call('import_refuel_records', {
          vehicle: this._vehicle, records: valid,
        }, true) || {};
        const rejected = (resp.rejected || []).map((r) => `${(r.date || '').slice(0, 10)} → ${r.reason}`);
        this._importResult = {
          imported: resp.imported || 0,
          rejected: [...rejected, ...bad.map((b) => `${b.raw} → ${b.error}`)],
        };
        this._importText = '';
      } catch (e) { /* 已记录 _error */ }
    }

    /* ---------- 渲染 ---------- */
    _render() {
      if (!this._hass) return;
      const root = this.shadowRoot || this.attachShadow({ mode: 'open' });
      if (!this._styled) {
        // 样式只注入一次，避免每次重绘重新解析 CSS
        root.innerHTML = `<style>${CARD_CSS}</style><div id="wrap"></div>`;
        this._styled = true;
      }
      const wrap = root.querySelector('#wrap');

      // 记住焦点与光标：状态推送触发的重绘不应打断正在进行的输入
      const active = root.activeElement;
      const ds = active && active.dataset ? active.dataset : null;
      const focusSel = ds
        ? (ds.f ? `[data-f="${ds.f}"]` : ds.ef ? `[data-ef="${ds.ef}"]` : null)
        : null;
      const caret = active && typeof active.selectionStart === 'number'
        ? active.selectionStart : null;

      wrap.innerHTML = `
        <ha-card>
          <div class="card">
            ${this._htmlHeader()}
            ${this._error ? `<div class="msg err">
              <ha-icon icon="mdi:alert-circle-outline"></ha-icon>
              <div><b>出错了</b>${esc(this._error)}</div></div>` : ''}
            ${this._htmlTab()}
          </div>
        </ha-card>`;
      this._bind(root);

      if (focusSel) {
        const el = root.querySelector(focusSel);
        if (el) {
          el.focus();
          if (caret != null && typeof el.setSelectionRange === 'function') {
            try { el.setSelectionRange(caret, caret); } catch (e) { /* number 类型不支持 */ }
          }
        }
      }
    }

    _htmlHeader() {
      const tabs = TABS.map((t) =>
        `<div class="tab ${this._tab === t.id ? 'active' : ''}" data-tab="${t.id}"
              role="tab" aria-selected="${this._tab === t.id}">
          <ha-icon icon="${t.icon}"></ha-icon><span>${t.label}</span></div>`).join('');
      return `
        <div class="header">
          <div class="title">
            <span class="title-icon"><ha-icon icon="mdi:gas-station"></ha-icon></span>
            <span>${esc(this._config.title)}</span>
          </div>
          ${this._vehicles.length > 1 ? this._htmlVehicleSelect() : ''}
        </div>
        <nav class="tabs" role="tablist">${tabs}</nav>`;
    }

    _htmlVehicleSelect() {
      const opts = this._vehicles.map((v) =>
        `<option value="${esc(v)}" ${v === this._vehicle ? 'selected' : ''}>${esc(v)}</option>`).join('');
      return `<label class="vehicle-wrap" title="切换车辆">
          <ha-icon icon="mdi:car"></ha-icon>
          <select class="vehicle" data-vehicle aria-label="选择车辆">${opts}</select>
          <ha-icon class="chev" icon="mdi:menu-down"></ha-icon>
        </label>`;
    }

    _htmlTab() {
      if (this._tab === 'refuel') return this._htmlRefuel();
      if (this._tab === 'history') return this._htmlHistory();
      if (this._tab === 'price') return this._htmlPrice();
      return this._htmlStats();
    }

    /* 加油页签 */
    _htmlRefuel() {
      if (!this._vehicles.length) {
        return `<div class="empty"><ha-icon icon="mdi:gas-station-off"></ha-icon>
          还没有车辆。<br>请先在集成「配置」中添加车辆。</div>`;
      }
      const f = this._form;
      const cur = this._currentOdometer();
      if (f.odometer === '' && cur !== '') f.odometer = cur;
      const r = this._result;
      let resultHtml = '';
      if (r && (r.volume != null || r.total_cost != null || r.actual_payment != null)) {
        const paid = r.actual_payment == null ? r.total_cost : r.actual_payment;
        const disc = r.discount != null ? r.discount
          : (r.total_cost != null && paid != null ? r.total_cost - paid : null);
        resultHtml = `<div class="msg ok"><ha-icon icon="mdi:check-circle-outline"></ha-icon><div>
          <b>已记录加油</b>
          加油量：${fmt(r.volume)} L ｜ 加油费用：${fmt(r.total_cost)} 元<br>
          实际支付：${fmt(paid)} 元${disc ? ` ｜ <b>优惠：${fmt(disc)} 元</b>` : ''}<br>
          单价：${fmt(r.price)} 元/L${r.price_approximate ? '（约）' : ''}${r.price_source ? ` ｜ ${esc(r.price_source)}` : ''}${r.distance_since_last != null ? `<br>区间里程：${fmt(r.distance_since_last, 1)} km` : ''}${r.consumption_last != null ? ` ｜ 本次油耗：${fmt(r.consumption_last)} L/100km` : ''}
          </div></div>`;
      } else if (r && r.deleted != null) {
        resultHtml = `<div class="msg ok"><ha-icon icon="mdi:check-circle-outline"></ha-icon>
          <div>已删除第 ${r.deleted + 1} 条记录，统计已重算。</div></div>`;
      }
      return `
        <div class="form-grid">
          <div class="field"><label>加油时间</label>
            <input type="datetime-local" data-f="date" value="${esc(f.date || this._nowLocal())}">
            <span class="sub">改历史日期 → 按当时油价计费</span></div>
          <div class="field"><label>里程表 km</label>
            <input type="number" step="0.1" min="0" data-f="odometer" value="${esc(f.odometer)}" placeholder="可留空">
            <span class="sub">${cur === '' ? '可留空，不参与油耗统计' : `上次 ${esc(cur)} · 可留空`}</span></div>
          <div class="field"><label>加油量 L</label>
            <input type="number" step="0.01" min="0" data-f="volume" value="${esc(f.volume)}" placeholder="0.00">
            <span class="sub">与费用二选一或都填</span></div>
          <div class="field"><label>加油费用 元</label>
            <input type="number" step="0.01" min="0" data-f="total_cost" value="${esc(f.total_cost)}" placeholder="0.00">
            <span class="sub">挂牌价合计（用于算平均油价）</span></div>
          <div class="field"><label>实际支付 元</label>
            <input type="number" step="0.01" min="0" data-f="actual_payment" value="${esc(f.actual_payment)}" placeholder="留空 = 无优惠">
            <span class="sub">留空即按费用全额，优惠自动计算</span></div>
          <div class="field"><label>油品</label>
            <select data-f="fuel">${FUEL_OPTIONS.map((x) =>
              `<option ${x === f.fuel ? 'selected' : ''}>${x}</option>`).join('')}</select></div>
          <div class="field"><label>备注</label>
            <input type="text" data-f="note" value="${esc(f.note)}" placeholder="加油站 / 优惠等"></div>
        </div>
        <div class="flexright">
          <button class="btn btn-lg" data-action="submit" ${this._busy ? 'disabled' : ''}>
            <ha-icon icon="mdi:${this._busy ? 'loading' : 'send'}" class="${this._busy ? 'spin' : ''}"></ha-icon>
            ${this._busy ? '提交中…' : '提交加油记录'}</button>
        </div>
        ${resultHtml}
        <div class="tips">只填加油量 → 按当日/历史油价自动算费用；只填费用 → 反算加油量。
          <b>加油费用与实际支付都填时自动算优惠</b>（优惠 = 加油费用 − 实际支付），
          只填一个或留空实付则视为无优惠。
          里程表读数用于计算区间油耗，<b>留空则该区间不计入统计</b>（不影响其他区间）；
          时间与里程互相矛盾（区间 ≤ 0 或 > 900 km）会被拒绝入库并说明原因。</div>`;
    }

    _nowLocal() {
      const now = new Date();
      const pad = (n) => String(n).padStart(2, '0');
      return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
    }

    /* 历史页签 */
    _htmlHistory() {
      const recs = this._records();
      const q = this._qualityEntity();
      const problems = (q && q.attributes.problems) || [];
      const gaps = Number((q && q.attributes.odometer_gaps) || 0);
      let html = '';
      if (problems.length) {
        html += `<div class="msg warn"><ha-icon icon="mdi:alert-outline"></ha-icon>
          <div><b>数据需修正（${problems.length} 项）——这些区间已排除在统计外，其余照常计算</b>
          ${problems.map((p) => `• ${esc(p)}`).join('<br>')}</div></div>`;
      }
      if (gaps) {
        html += `<div class="msg info"><ha-icon icon="mdi:information-outline"></ha-icon>
          <div><b>${gaps} 处区间缺少里程读数</b>
          这些区间不参与油耗统计，不影响其他区间；补上里程即可自动恢复。</div></div>`;
      }
      if (!recs.length) {
        html += `<div class="empty"><ha-icon icon="mdi:file-document-outline"></ha-icon>
          暂无记录。<br>可在「加油」页签录入，或用下方批量导入。</div>`;
      } else {
        const editing = this._records().find((r) => r.index === this._editIdx);
        if (editing) html += this._htmlEditPanel(editing);
        const rows = recs.map((rec) => {
          const actions = this._pendingDelete === rec.index
            ? `<button class="btn mini danger" data-del-confirm="${rec.index}">确认删除</button>
               <button class="btn mini secondary" data-del-cancel>取消</button>`
            : `<button class="icon-btn" data-edit="${rec.index}" title="修改" aria-label="修改记录"><ha-icon icon="mdi:pencil"></ha-icon></button>
               <button class="icon-btn danger" data-del="${rec.index}" title="删除" aria-label="删除记录"><ha-icon icon="mdi:delete"></ha-icon></button>`;
          return `
          <tr${this._editIdx === rec.index ? ' class="editing"' : ''}>
            <td class="muted num">${rec.index + 1}</td>
            <td>${esc(String(rec.date || '').slice(0, 10))}</td>
            <td class="num">${fmt(rec.odometer, 1)}</td>
            <td class="num">${fmt(rec.volume)}</td>
            <td class="num">${fmt(rec.total_cost)}</td>
            <td class="num">${fmt(rec.actual_payment == null ? rec.total_cost : rec.actual_payment)}</td>
            <td class="num">${rec.discount ? `<span class="pill good">${fmt(rec.discount)}</span>` : '—'}</td>
            <td class="num">${fmt(rec.price)}</td>
            <td class="num">${rec.segment_distance != null ? fmt(rec.segment_distance, 0) + ' km' : '—'}</td>
            <td class="num">${rec.segment_consumption != null ? fmt(rec.segment_consumption) : '—'}</td>
            <td class="muted note-cell" title="${esc(rec.note || '')}">${esc(rec.note || '')}</td>
            <td><div class="actions">${actions}</div></td>
          </tr>`;
        }).join('');
        html += `
          <div class="table-wrap">
          <table>
            <tr><th class="num">#</th><th>日期</th><th class="num">里程</th><th class="num">加油量</th>
              <th class="num">加油费用</th><th class="num">实际支付</th><th class="num">优惠</th>
              <th class="num">单价</th><th class="num">区间里程</th>
              <th class="num">区间油耗</th><th>备注</th><th></th></tr>
            ${rows}
          </table></div>`;
      }
      // 批量导入
      html += `
        <div class="flexright">
          <button class="btn secondary" data-action="toggle-import">
            <ha-icon icon="mdi:database-import-outline"></ha-icon>${this._showImport ? '收起导入' : '批量导入历史记录'}</button>
        </div>`;
      if (this._showImport) {
        const ir = this._importResult;
        html += `
          <div class="editbox">
            <div class="hint">每行一条：<b>日期, 里程, 加油量, 加油费用, 实际支付, [油品], [备注]</b>（逗号/分号/Tab 分隔；日期如 2026-08-01 或 2026-08-01 14:30；量与费用可只填一项）<br>
              <b>优惠自动算</b>：实际支付留空即无优惠（如 <code>2026-08-01, 12000, 41.2, 338.0</code>）；
              填了实付就算优惠（如 <code>2026-07-05, 11800, 41.2, 338.0, 300.0, 92, 中石化</code> → 优惠 38 元）。<br>
              <b>里程可以留空</b>，那一列写空即可（如 <code>2026-08-01, , 41.2, 338.5</code>）——该行照常入库，只是这个区间不参与油耗统计。<br>
              旧格式（<code>日期, 里程, 加油量, 加油费用, 油品, 备注</code>，6 列以内）仍可识别：
              整批数据里只要有一行写到 7 列（含实际支付），就统一按新格式解析，因此新旧格式请勿混用。</div>
            <textarea data-f="import" placeholder="2026-06-20, 10500, 40.5, 330.0, 300.0, 92, 中石化（优惠30）&#10;2026-07-05, 11800, 41.2, 338.0, , 92, 实际支付留空=无优惠&#10;2026-07-20, , 40.8, 335.0, 335.0, 92, 里程缺失也可导入&#10;2026-08-20, 12350, , 335.0, 310.0, 92, 只填费用与实付">${esc(this._importText)}</textarea>
            <div class="flexright"><button class="btn" data-action="do-import" ${this._busy ? 'disabled' : ''}>
              <ha-icon icon="mdi:import"></ha-icon>开始导入</button></div>
            ${ir ? (ir.imported ? `<div class="msg ok"><ha-icon icon="mdi:check-circle-outline"></ha-icon><div><b>导入 ${ir.imported} 条</b>${ir.rejected && ir.rejected.length ? `另有 ${ir.rejected.length} 条被拒绝：<br>${ir.rejected.map((x) => `• ${esc(x)}`).join('<br>')}` : ''}</div></div>` : (ir.rejected && ir.rejected.length ? `<div class="msg err"><ha-icon icon="mdi:alert-circle-outline"></ha-icon><div><b>全部被拒绝</b>${ir.rejected.map((x) => `• ${esc(x)}`).join('<br>')}</div></div>` : '')) : ''}
          </div>`;
      }
      return html;
    }

    _htmlEditPanel(rec) {
      const f = this._editForm;
      // 旧记录没有 actual_payment：按 total_cost 回退（当时即实付，优惠 0）
      const paid = rec.actual_payment == null ? rec.total_cost : rec.actual_payment;
      const cur = (k, fallback) => esc(f[k] != null ? f[k] : fallback);
      return `
        <div class="editbox">
          <div class="editbox-title"><ha-icon icon="mdi:pencil"></ha-icon>修改第 ${rec.index + 1} 条记录</div>
          <div class="form-grid">
            <div class="field"><label>日期时间</label>
              <input type="datetime-local" data-ef="date" value="${esc((f.date || rec.date || '').slice(0, 16))}"></div>
            <div class="field"><label>里程 km</label>
              <input type="number" step="0.1" data-ef="odometer" value="${cur('odometer', rec.odometer)}"></div>
            <div class="field"><label>加油量 L</label>
              <input type="number" step="0.01" data-ef="volume" value="${cur('volume', rec.volume)}"></div>
            <div class="field"><label>加油费用 元</label>
              <input type="number" step="0.01" data-ef="total_cost" value="${cur('total_cost', rec.total_cost)}"></div>
            <div class="field"><label>实际支付 元</label>
              <input type="number" step="0.01" data-ef="actual_payment" value="${cur('actual_payment', paid)}">
              <span class="sub">优惠 = 加油费用 − 实际支付</span></div>
            <div class="field"><label>油品</label>
              <select data-ef="fuel">${FUEL_OPTIONS.map((x) =>
                `<option ${x === (f.fuel || rec.fuel_type || '自动') ? 'selected' : ''}>${x}</option>`).join('')}</select></div>
            <div class="field"><label>备注</label>
              <input type="text" data-ef="note" value="${esc(f.note != null ? f.note : rec.note)}"></div>
          </div>
          <div class="flexright">
            <button class="btn mini" data-action="save-edit" ${this._busy ? 'disabled' : ''}>
              <ha-icon icon="mdi:content-save"></ha-icon>保存修改</button>
            <button class="btn mini secondary" data-action="cancel-edit">取消</button>
          </div>
          <div class="hint">修改加油量或费用其一，另一项会按该记录的单价重算，<b>原优惠金额保持不变</b>；
            两项都改则以「费用 ÷ 加油量」为准；只改实际支付则加油费用不变，优惠随之变化。
            实际支付留空 → 视为无优惠。</div>
        </div>`;
    }

    /* 油价页签 */
    _htmlPrice() {
      let html = '';
      const hist = (this._historyEnt && this._historyEnt.attributes.price_history) || [];
      const period = this._historyEnt && this._historyEnt.attributes.current_period;
      const daysLeft = this._periodEndEnt && this._periodEndEnt.attributes.days_left;
      const trendEnt = this._trendEnt;
      const trend = trendEnt && trendEnt.state !== 'unknown'
        && trendEnt.state !== 'unavailable' ? trendEnt.state : null;
      const periodId = trendEnt && trendEnt.attributes.period_id;

      // 油品列由实体动态决定（各省发布的油品不同，不能硬编码）
      const fuels = (this._priceEnts || []).map((p) => ({
        key: p.attributes.fuel_key,
        label: p.attributes.label || p.entity_id,
        price: num(p.state),
        chg: p.attributes.price_change == null ? null : Number(p.attributes.price_change),
      })).filter((f) => f.key);

      const fuelIcon = (key, label) => {
        const k = String(key || '').toUpperCase();
        const l = String(label || '');
        if (k.includes('LNG') || l.includes('LNG')) return 'mdi:gas-cylinder';
        if (k.includes('DIESEL') || l.includes('#') || /-\d+/.test(l)) return 'mdi:fuel';
        return 'mdi:gas-station';
      };

      if (fuels.length) {
        html += `<div class="grid">` + fuels.map((f) => {
          const dir = f.chg == null || f.chg === 0 ? '' : (f.chg > 0 ? 'up' : 'down');
          const arrow = f.chg == null || f.chg === 0 ? '' : (f.chg > 0 ? '▲' : '▼');
          return `<div class="stat">
            <span class="stat-icon"><ha-icon icon="${fuelIcon(f.key, f.label)}"></ha-icon></span>
            <div class="v">${fmt(f.price)}${arrow ? ` <span class="${dir}" style="font-size:.6em">${arrow}</span>` : ''}</div>
            <div class="k">${esc(f.label)} 元/L</div>
            <div class="d ${dir}">涨跌 ${f.chg == null ? '—' : signed(f.chg)}</div></div>`;
        }).join('') + `</div>`;
      }

      const bits = [];
      if (trend) {
        const cls = trend === '上调' ? 'up' : trend === '下调' ? 'down' : '';
        bits.push(`本期调价 <span class="pill ${cls}">${esc(trend)}</span>`);
      }
      if (periodId != null) bits.push(`第 ${esc(periodId)} 期`);
      if (period) bits.push(`周期 ${esc(period)}`);
      if (daysLeft != null) bits.push(`距下次调价 <b>${esc(daysLeft)}</b> 天`);
      if (bits.length) html += `<div class="meta">${bits.map((b) => `<span>${b}</span>`).join('')}</div>`;

      if (!hist.length || !fuels.length) {
        return html + `<div class="empty"><ha-icon icon="mdi:chart-line"></ha-icon>
          油价历史数据尚未加载完成。<br>稍等片刻或检查集成状态。</div>`;
      }

      // prices/changes 的 key 是接口数据字段名（GAS_92 等），与实体的 fuel_key 对应
      const head = `<tr><th>调价周期</th>${fuels.map((f) => `<th class="num">${esc(f.label)}</th>`).join('')}<th class="num">涨跌</th></tr>`;
      const baseKey = fuels[0].key;
      const rows = hist.slice(0, HISTORY_ROWS).map((h) => {
        const p = h.prices || {};
        const c = (h.changes || {})[baseKey];
        const dir = c == null || c === 0 ? '' : (c > 0 ? 'up' : 'down');
        return `<tr>
          <td class="muted period">${esc(h.start || '')} ~ ${esc(h.end || '')}</td>
          ${fuels.map((f) => `<td class="num">${fmt(p[f.key])}</td>`).join('')}
          <td class="num ${dir}">${c == null ? '—' : signed(c)}</td>
        </tr>`;
      }).join('');
      html += `<div class="table-wrap"><table>${head}${rows}</table></div>`;

      // 走势图：优先 92 号汽油，否则用第一个油品
      const chart = fuels.find((f) => f.key === 'GAS_92') || fuels[0];
      const series = hist.slice(0, HISTORY_ROWS).map((h) => ({
        end: (h.end || '').slice(5),
        v: (h.prices || {})[chart.key],
      })).reverse().filter((x) => x.v != null);
      if (series.length > 1) {
        const vals = series.map((x) => x.v);
        const min = Math.min(...vals), max = Math.max(...vals);
        const span = (max - min) || 1;
        html += `<div class="chart"><div class="hint">${esc(chart.label)} 价格走势（近 ${series.length} 期）</div>` +
          series.map((x) => {
            const w = 12 + Math.round(((x.v - min) / span) * 88);
            return `<div class="bar-wrap"><div class="bar-label">${esc(x.end)}</div>
              <div class="bar-track"><div class="bar-fill" style="width:${w}%"></div></div>
              <div class="bar-val">${fmt(x.v)}</div></div>`;
          }).join('') + `</div>`;
      }
      return html;
    }

    /* 统计页签 */
    _htmlStats() {
      if (!this._vehicles.length) {
        return `<div class="empty"><ha-icon icon="mdi:chart-box-outline"></ha-icon>还没有车辆。</div>`;
      }
      const s = this._stats();
      const q = this._qualityEntity();
      const problems = (q && q.attributes.problems) || [];
      const gaps = Number((q && q.attributes.odometer_gaps) || 0);
      const tile = (icon, v, k, d = 2) =>
        `<div class="stat"><span class="stat-icon"><ha-icon icon="${icon}"></ha-icon></span>
         <div class="v">${v == null ? '—' : fmt(v, d)}</div><div class="k">${k}</div></div>`;

      return `
        ${problems.length ? `<div class="msg warn"><ha-icon icon="mdi:alert-outline"></ha-icon><div><b>数据需修正（${problems.length} 项）——这些区间已排除在统计外</b>${problems.map((p) => `• ${esc(p)}`).join('<br>')}</div></div>` : ''}
        ${gaps ? `<div class="msg info"><ha-icon icon="mdi:information-outline"></ha-icon><div><b>${gaps} 处区间缺少里程读数</b>未计入里程与油耗统计。</div></div>` : ''}
        <div class="grid">
          ${tile('mdi:counter', s.odometer, '当前里程 km', 1)}
          <div class="stat"><span class="stat-icon"><ha-icon icon="mdi:gas-station"></ha-icon></span>
            <div class="v">${esc(s.refuel_count == null ? '—' : s.refuel_count)}</div><div class="k">加油次数</div></div>
          ${tile('mdi:fuel', s.total_volume, '累计加油 L', 1)}
          ${tile('mdi:cash-multiple', s.total_cost, '累计加油费用 元', 0)}
          ${tile('mdi:credit-card-check-outline', s.total_payment, '累计实际支付 元', 0)}
          ${tile('mdi:map-marker-distance', s.total_distance, '累计行驶 km', 1)}
          ${tile('mdi:speedometer', s.last_consumption, '最近油耗 L/100km')}
          ${tile('mdi:chart-line', s.avg_consumption, '平均油耗 L/100km')}
          ${tile('mdi:currency-cny', s.avg_price, '平均油价 元/L')}
          <div class="stat wide"><span class="stat-icon"><ha-icon icon="mdi:sale-outline"></ha-icon></span>
            <div class="v">${s.total_discount == null ? '—' : fmt(s.total_discount, 2)}<span class="unit">元</span></div>
            <div class="k">累计优惠${s.avg_discount_rate != null ? ` · 优惠率 ${fmt(s.avg_discount_rate, 1)}%` : ''}</div></div>
          <div class="stat wide"><span class="stat-icon"><ha-icon icon="mdi:calculator"></ha-icon></span>
            <div class="v">${s.per_km_cost == null ? '—' : fmt(s.per_km_cost, 3)}<span class="unit">元</span></div>
            <div class="k">每公里油费</div></div>
        </div>
        <div class="hint">数值直接取自集成后端统计（与「加油记录」设备下的传感器一致）。
          平均油耗 = 除去首箱的区间加油量合计 ÷ 区间里程合计（加满假设）。
          累计优惠 = 各次（加油费用 − 实际支付）之和；平均油价与每公里油费仍按加油费用计算。
          数据质量：${q ? `<span class="pill ${problems.length ? 'bad' : 'good'}">${esc(q.state)}</span>` : '—'}</div>`;
    }

    /* ---------- 事件绑定 ---------- */
    _bind(root) {
      const on = (sel, ev, fn) => {
        root.querySelectorAll(sel).forEach((el) => el.addEventListener(ev, fn));
      };
      on('[data-tab]', 'click', (e) => {
        const tab = e.currentTarget.dataset.tab;
        if (tab === this._tab) return;
        this._tab = tab; this._error = null; this._render();
      });
      on('[data-vehicle]', 'change', (e) => {
        this._vehicle = e.currentTarget.value;
        lsSet(this._vehicle);
        this._form.odometer = '';
        this._result = null; this._editIdx = null; this._pendingDelete = null;
        this._render();
      });
      on('[data-f]', 'input', (e) => {
        const key = e.currentTarget.dataset.f;
        if (key === 'import') { this._importText = e.currentTarget.value; return; }
        this._form[key] = e.currentTarget.value;
      });
      // 表单内回车即可提交（textarea 不会触发）
      on('input[data-f]', 'keydown', (e) => {
        if (e.key === 'Enter' && this._tab === 'refuel' && !this._busy) {
          e.preventDefault();
          this._submit();
        }
      });
      on('[data-f="fuel"]', 'change', (e) => { this._form.fuel = e.currentTarget.value; });
      on('[data-ef]', 'input', (e) => {
        this._editForm[e.currentTarget.dataset.ef] = e.currentTarget.value;
      });
      on('[data-ef="fuel"]', 'change', (e) => { this._editForm.fuel = e.currentTarget.value; });
      on('[data-action="submit"]', 'click', () => this._submit());
      on('[data-action="toggle-import"]', 'click', () => {
        this._showImport = !this._showImport; this._importResult = null; this._render();
      });
      on('[data-action="do-import"]', 'click', () => this._doImport());
      on('[data-del]', 'click', (e) => {
        this._pendingDelete = Number(e.currentTarget.dataset.del);
        this._error = null; this._render();
      });
      on('[data-del-confirm]', 'click', (e) => this._delete(Number(e.currentTarget.dataset.delConfirm)));
      on('[data-del-cancel]', 'click', () => { this._pendingDelete = null; this._render(); });
      on('[data-edit]', 'click', (e) => {
        const idx = Number(e.currentTarget.dataset.edit);
        const rec = this._records().find((r) => r.index === idx);
        if (!rec) return;
        this._editIdx = idx;
        this._pendingDelete = null;
        this._editForm = { date: String(rec.date || '').slice(0, 16) };
        this._render();
      });
      on('[data-action="save-edit"]', 'click', () => this._saveEdit());
      on('[data-action="cancel-edit"]', 'click', () => {
        this._editIdx = null; this._error = null; this._render();
      });
    }
  }

  customElements.define('sinopec-oil-card', SinopecOilCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: 'sinopec-oil-card',
    name: '中石化加油记账卡片',
    description: '油价 · 加油填表 · 历史记录 · 油耗统计一体化',
    preview: true,
  });
})();
