/**
 * Sinopec Oil Card — 中石化油价 · 加油记账一体化卡片
 *
 * 安装：将本文件复制到 /config/www/sinopec-oil-card.js，然后在
 * 仪表盘 → 右上角 ⋮ → 管理资源 → 添加
 *   URL: /local/sinopec-oil-card.js   版本: 1.0.3
 * 使用：仪表盘添加卡片 → 手动 →
 *   type: custom:sinopec-oil-card
 * 可选: title: 我的油卡   vehicle: 某辆车（不填则记住上次选择）
 *
 * 卡片自动发现本集成实体（基于 sinopec_role 属性），
 * 无需填写任何实体 ID。
 *
 * 页签：加油 · 历史 · 油价 · 统计
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
    ha-card { overflow: hidden; }
    .card { padding: 12px 16px 16px; }
    .header { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 4px; }
    .title { display: flex; align-items: center; gap: 6px; font-size: 1.1em; font-weight: 600;
             color: var(--primary-text-color); }
    .title ha-icon { color: var(--primary-color); --mdc-icon-size: 22px; }
    .tabs { display: flex; gap: 4px; margin: 10px 0 12px; flex-wrap: wrap; }
    .tab { display: flex; align-items: center; gap: 4px; padding: 5px 12px; border-radius: 16px;
           cursor: pointer; font-size: 0.9em; color: var(--secondary-text-color);
           background: var(--secondary-background-color); }
    .tab ha-icon { --mdc-icon-size: 16px; }
    .tab.active { color: var(--text-primary-color); background: var(--primary-color); font-weight: 600; }
    .row { display: flex; gap: 8px; margin: 8px 0; flex-wrap: wrap; align-items: center; }
    .field { display: flex; flex-direction: column; flex: 1 1 120px; min-width: 110px; }
    .field label { font-size: 0.78em; color: var(--secondary-text-color); margin-bottom: 2px; }
    .field input, .field select, textarea, select.vehicle {
      width: 100%; box-sizing: border-box; padding: 6px 8px;
      border: 1px solid var(--divider-color); border-radius: 6px;
      background: var(--card-background-color); color: var(--primary-text-color); font-size: 0.95em; }
    select.vehicle { width: auto; padding: 4px 8px; border-radius: 6px; }
    textarea { min-height: 90px; font-family: monospace; }
    .btn { display: inline-flex; align-items: center; gap: 4px; padding: 8px 18px; border: none;
           border-radius: 18px; cursor: pointer; font-size: 0.95em; background: var(--primary-color);
           color: var(--text-primary-color); font-weight: 600; }
    .btn ha-icon { --mdc-icon-size: 18px; }
    .btn:disabled { opacity: .5; cursor: default; }
    .btn.secondary { background: var(--secondary-background-color); color: var(--primary-text-color); }
    .btn.danger { background: var(--error-color, #db4437); color: #fff; }
    .msg { display: flex; gap: 8px; margin: 10px 0; padding: 10px 12px; border-radius: 8px; font-size: 0.9em; }
    .msg ha-icon { flex: none; --mdc-icon-size: 20px; margin-top: 1px; }
    .msg.ok { background: rgba(76,175,80,.12); color: var(--success-color, #2e7d32); }
    .msg.err { background: rgba(219,68,55,.10); color: var(--error-color, #db4437); }
    .msg.warn { background: rgba(255,152,0,.12); color: var(--warning-color, #ef6c00); }
    .msg.info { background: var(--secondary-background-color); color: var(--primary-text-color); }
    .msg b { display: block; margin-bottom: 4px; }
    table { width: 100%; border-collapse: collapse; font-size: 0.85em; }
    th { text-align: left; color: var(--secondary-text-color); font-weight: 500; white-space: nowrap;
         border-bottom: 1px solid var(--divider-color); padding: 4px 6px; }
    td { padding: 5px 6px; border-bottom: 1px solid var(--divider-color); color: var(--primary-text-color); }
    tr:last-child td { border-bottom: none; }
    .muted { color: var(--secondary-text-color); }
    .up { color: var(--error-color, #d32f2f); }
    .down { color: var(--success-color, #2e7d32); }
    .pill { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 0.78em;
            background: var(--secondary-background-color); color: var(--secondary-text-color); }
    .pill.good { background: rgba(76,175,80,.15); color: var(--success-color, #2e7d32); }
    .pill.bad { background: rgba(219,68,55,.12); color: var(--error-color, #db4437); }
    .pill.up { background: rgba(219,68,55,.12); }
    .pill.down { background: rgba(76,175,80,.15); }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; margin: 10px 0; }
    .stat { padding: 10px; border-radius: 10px; background: var(--secondary-background-color); }
    .stat .v { font-size: 1.25em; font-weight: 600; color: var(--primary-text-color); }
    .stat .k { font-size: 0.75em; color: var(--secondary-text-color); margin-top: 2px; }
    .stat .d { font-size: 0.78em; margin-top: 2px; color: var(--secondary-text-color); }
    .bar-wrap { display: flex; align-items: center; gap: 8px; margin: 3px 0; font-size: 0.8em; }
    .bar-label { width: 62px; color: var(--secondary-text-color); text-align: right; flex: none; }
    .bar-track { flex: 1; background: var(--secondary-background-color); border-radius: 4px; height: 14px; overflow: hidden; }
    .bar-fill { height: 100%; background: var(--primary-color); border-radius: 4px; }
    .bar-val { width: 56px; flex: none; color: var(--primary-text-color); }
    .hint { font-size: 0.78em; color: var(--secondary-text-color); margin: 6px 0; line-height: 1.5; }
    .actions { display: flex; gap: 6px; }
    .actions .btn { padding: 3px 10px; font-size: 0.8em; }
    .editbox { background: var(--secondary-background-color); border-radius: 10px; padding: 10px; margin: 6px 0; }
    .empty { text-align: center; color: var(--secondary-text-color); padding: 18px 0; }
    .flexright { display: flex; justify-content: flex-end; margin-top: 8px; gap: 8px; }
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
      this._form = { date: null, odometer: '', volume: '', total_cost: '', fuel: '自动', note: '' };
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

      // 实体增删（新车辆、新油品）时才重新发现，避免每次推送全表扫描
      if (!this._entityIds || count !== this._stateCount) {
        this._stateCount = count;
        const before = this._vehicle;
        this._discover(states);
        this._rememberVehicle();
        vehicleChanged = before !== this._vehicle;
      }

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
      const byRole = (role) => Object.values(states)
        .filter((s) => s.attributes && s.attributes.sinopec_role === role);
      this._recordsEnts = byRole('sinopec_records');
      this._qualityEnts = byRole('sinopec_quality');
      this._odometerEnts = byRole('sinopec_odometer');
      this._priceEnts = byRole('sinopec_price');
      this._historyEnt = byRole('sinopec_price_history')[0] || null;
      this._periodEndEnt = byRole('sinopec_period_end')[0] || null;
      this._trendEnt = byRole('sinopec_trend')[0] || null;
      this._vehicles = this._recordsEnts.map((s) => s.attributes.vehicle).filter(Boolean);
      this._entityIds = [...new Set([
        ...this._recordsEnts, ...this._qualityEnts, ...this._odometerEnts,
        ...this._priceEnts, this._historyEnt, this._periodEndEnt, this._trendEnt,
      ].filter(Boolean).map((s) => s.entity_id))];
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
      if (f.fuel && f.fuel !== '自动') payload.fuel_type = f.fuel;
      if (f.note) payload.note = f.note;
      if (payload.volume == null && payload.total_cost == null) {
        this._error = '请至少填写加油量或费用之一（都填则自动算单价）。';
        this._render(); return;
      }
      try {
        const resp = await this._call('record_refuel', payload, true);
        this._result = resp || { ok: true };
        // 清空量/费/备注，里程停留在提交值供下次微调
        this._form.volume = '';
        this._form.total_cost = '';
        this._form.note = '';
      } catch (e) { /* 已记录 _error */ }
    }

    async _delete(index) {
      this._pendingDelete = null;
      try {
        await this._call('delete_refuel_record', { vehicle: this._vehicle, index }, false);
        this._result = { deleted: index };
      } catch (e) { /* 已记录 _error */ }
    }

    async _saveEdit() {
      const f = this._editForm;
      const payload = { vehicle: this._vehicle, index: this._editIdx };
      if (f.date) payload.date = f.date;
      if (f.odometer !== '' && f.odometer != null) payload.odometer = Number(f.odometer);
      if (f.volume !== '' && f.volume != null) payload.volume = Number(f.volume);
      if (f.total_cost !== '' && f.total_cost != null) payload.total_cost = Number(f.total_cost);
      if (f.fuel && f.fuel !== '自动') payload.fuel_type = f.fuel;
      if (f.note !== undefined) payload.note = f.note;
      try {
        await this._call('edit_refuel_record', payload, false);
        this._editIdx = null;
        this._result = { edited: true };
      } catch (e) { /* 已记录 _error */ }
    }

    _parseImport() {
      const lines = this._importText.split('\n').map((l) => l.trim()).filter(Boolean);
      const out = [];
      for (const line of lines) {
        if (/^(日期|date)/i.test(line)) continue; // 表头
        // 保留空单元格以维持列位置（否则 "日期,,41.2,338" 会被错位解析），
        // 只去掉行尾的空列
        const parts = line.split(/[,;\t，]/).map((p) => p.trim());
        while (parts.length && parts[parts.length - 1] === '') parts.pop();
        if (!parts.length || !parts[0]) {
          out.push({ raw: line, error: '缺少日期' });
          continue;
        }
        const [date, odo, vol, cost, fuel, ...noteParts] = parts;
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
          if (isNaN(c)) { out.push({ raw: line, error: `费用不是数字：${cost}` }); continue; }
          rec.total_cost = c;
        }
        if (rec.volume == null && rec.total_cost == null) {
          out.push({ raw: line, error: '加油量与费用至少填一项' });
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
        `<div class="tab ${this._tab === t.id ? 'active' : ''}" data-tab="${t.id}">
          <ha-icon icon="${t.icon}"></ha-icon>${t.label}</div>`).join('');
      return `
        <div class="header">
          <div class="title"><ha-icon icon="mdi:gas-station"></ha-icon>${esc(this._config.title)}</div>
          ${this._vehicles.length > 1 ? this._htmlVehicleSelect() : ''}
        </div>
        <div class="tabs">${tabs}</div>`;
    }

    _htmlVehicleSelect() {
      const opts = this._vehicles.map((v) =>
        `<option value="${esc(v)}" ${v === this._vehicle ? 'selected' : ''}>${esc(v)}</option>`).join('');
      return `<select class="vehicle" data-vehicle aria-label="选择车辆">${opts}</select>`;
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
        return `<div class="empty">还没有车辆。请先在集成「配置」中添加车辆。</div>`;
      }
      const f = this._form;
      const cur = this._currentOdometer();
      if (f.odometer === '' && cur !== '') f.odometer = cur;
      const r = this._result;
      let resultHtml = '';
      if (r && (r.volume != null || r.total_cost != null)) {
        resultHtml = `<div class="msg ok"><ha-icon icon="mdi:check-circle-outline"></ha-icon><div>
          <b>已记录加油</b>
          加油量：${fmt(r.volume)} L ｜ 费用：${fmt(r.total_cost)} 元<br>
          单价：${fmt(r.price)} 元/L${r.price_approximate ? '（约）' : ''}${r.price_source ? ` ｜ ${esc(r.price_source)}` : ''}${r.distance_since_last != null ? `<br>区间里程：${fmt(r.distance_since_last, 1)} km` : ''}${r.consumption_last != null ? ` ｜ 本次油耗：${fmt(r.consumption_last)} L/100km` : ''}
          </div></div>`;
      } else if (r && r.deleted != null) {
        resultHtml = `<div class="msg ok"><ha-icon icon="mdi:check-circle-outline"></ha-icon>
          <div>已删除第 ${r.deleted + 1} 条记录，统计已重算。</div></div>`;
      }
      return `
        <div class="row">
          <div class="field"><label>加油时间（改历史日期=按当时油价）</label>
            <input type="datetime-local" data-f="date" value="${esc(f.date || this._nowLocal())}"></div>
          <div class="field"><label>里程表读数 km（可留空；上次 ${esc(cur)}）</label>
            <input type="number" step="0.1" min="0" data-f="odometer" value="${esc(f.odometer)}"></div>
        </div>
        <div class="row">
          <div class="field"><label>加油量 L（与费用填其一或都填）</label>
            <input type="number" step="0.01" min="0" data-f="volume" value="${esc(f.volume)}"></div>
          <div class="field"><label>费用 元</label>
            <input type="number" step="0.01" min="0" data-f="total_cost" value="${esc(f.total_cost)}"></div>
          <div class="field"><label>油品</label>
            <select data-f="fuel">${FUEL_OPTIONS.map((x) =>
              `<option ${x === f.fuel ? 'selected' : ''}>${x}</option>`).join('')}</select></div>
          <div class="field"><label>备注</label>
            <input type="text" data-f="note" value="${esc(f.note)}" placeholder="加油站/优惠等"></div>
        </div>
        <div class="flexright">
          <button class="btn" data-action="submit" ${this._busy ? 'disabled' : ''}>
            <ha-icon icon="mdi:send"></ha-icon>${this._busy ? '提交中…' : '提交加油记录'}</button>
        </div>
        ${resultHtml}
        <div class="hint">只填量 → 按当日/历史油价算费用；只填费用 → 反算加油量。
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
        html += `<div class="empty">暂无记录。可在「加油」页签录入，或用下方批量导入。</div>`;
      } else {
        const rows = recs.map((rec) => {
          if (this._editIdx === rec.index) return this._htmlEditRow(rec);
          const actions = this._pendingDelete === rec.index
            ? `<button class="btn danger" data-del-confirm="${rec.index}">确认删除</button>
               <button class="btn secondary" data-del-cancel>取消</button>`
            : `<button class="btn secondary" data-edit="${rec.index}">改</button>
               <button class="btn danger" data-del="${rec.index}">删</button>`;
          return `
          <tr>
            <td class="muted">${rec.index + 1}</td>
            <td>${esc(String(rec.date || '').slice(0, 10))}</td>
            <td>${fmt(rec.odometer, 1)}</td>
            <td>${fmt(rec.volume)}</td>
            <td>${fmt(rec.total_cost)}</td>
            <td>${fmt(rec.price)}</td>
            <td>${rec.segment_distance != null ? fmt(rec.segment_distance, 0) + ' km' : '—'}</td>
            <td>${rec.segment_consumption != null ? fmt(rec.segment_consumption) : '—'}</td>
            <td class="muted">${esc(rec.note || '')}</td>
            <td><div class="actions">${actions}</div></td>
          </tr>`;
        }).join('');
        html += `
          <div style="overflow-x:auto">
          <table>
            <tr><th>#</th><th>日期</th><th>里程</th><th>加油量</th><th>费用</th><th>单价</th><th>区间里程</th><th>区间油耗</th><th>备注</th><th></th></tr>
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
            <div class="hint">每行一条：<b>日期, 里程, 加油量, 费用, [油品], [备注]</b>（逗号/分号/Tab 分隔；日期如 2026-08-01 或 2026-08-01 14:30；量与费用可只填一项）<br>
              <b>里程可以留空</b>，那一列写空即可（如 <code>2026-08-01, , 41.2, 338.5</code>）——该行照常入库，只是这个区间不参与油耗统计。</div>
            <textarea data-f="import" placeholder="2026-07-05, 11800, 41.2, 338.5, 92, 中石化&#10;2026-07-20, , 40.8, 335.0, 92, 里程缺失也可导入&#10;2026-08-20, 12350, , 335.0, 92, 只填费用">${esc(this._importText)}</textarea>
            <div class="flexright"><button class="btn" data-action="do-import" ${this._busy ? 'disabled' : ''}>导入</button></div>
            ${ir ? (ir.imported ? `<div class="msg ok"><ha-icon icon="mdi:check-circle-outline"></ha-icon><div><b>导入 ${ir.imported} 条</b>${ir.rejected && ir.rejected.length ? `另有 ${ir.rejected.length} 条被拒绝：<br>${ir.rejected.map((x) => `• ${esc(x)}`).join('<br>')}` : ''}</div></div>` : (ir.rejected && ir.rejected.length ? `<div class="msg err"><ha-icon icon="mdi:alert-circle-outline"></ha-icon><div><b>全部被拒绝</b>${ir.rejected.map((x) => `• ${esc(x)}`).join('<br>')}</div></div>` : '')) : ''}
          </div>`;
      }
      return html;
    }

    _htmlEditRow(rec) {
      const f = this._editForm;
      return `
        <tr><td colspan="10">
          <div class="editbox">
            <div class="row">
              <div class="field"><label>日期时间</label>
                <input type="datetime-local" data-ef="date" value="${esc((f.date || rec.date || '').slice(0, 16))}"></div>
              <div class="field"><label>里程 km</label>
                <input type="number" step="0.1" data-ef="odometer" value="${esc(f.odometer != null ? f.odometer : rec.odometer)}"></div>
              <div class="field"><label>加油量 L</label>
                <input type="number" step="0.01" data-ef="volume" value="${esc(f.volume != null ? f.volume : rec.volume)}"></div>
              <div class="field"><label>费用 元</label>
                <input type="number" step="0.01" data-ef="total_cost" value="${esc(f.total_cost != null ? f.total_cost : rec.total_cost)}"></div>
            </div>
            <div class="row">
              <div class="field"><label>油品</label>
                <select data-ef="fuel">${FUEL_OPTIONS.map((x) =>
                  `<option ${x === (f.fuel || rec.fuel_type || '自动') ? 'selected' : ''}>${x}</option>`).join('')}</select></div>
              <div class="field"><label>备注</label>
                <input type="text" data-ef="note" value="${esc(f.note != null ? f.note : rec.note)}"></div>
            </div>
            <div class="flexright">
              <button class="btn" data-action="save-edit" ${this._busy ? 'disabled' : ''}>保存修改</button>
              <button class="btn secondary" data-action="cancel-edit">取消</button>
            </div>
            <div class="hint">修改量或费用其一，另一项将按该记录日期的油价智能重算；时间-里程仍需保持递增对应。</div>
          </div>
        </td></tr>`;
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

      if (fuels.length) {
        html += `<div class="grid">` + fuels.map((f) => {
          const dir = f.chg == null || f.chg === 0 ? '' : (f.chg > 0 ? 'up' : 'down');
          const arrow = f.chg == null || f.chg === 0 ? '' : (f.chg > 0 ? '▲' : '▼');
          return `<div class="stat">
            <div class="v">${fmt(f.price)}${arrow ? ` <span class="${dir}" style="font-size:.7em">${arrow}</span>` : ''}</div>
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
      if (bits.length) html += `<div class="hint">${bits.join(' ｜ ')}</div>`;

      if (!hist.length || !fuels.length) {
        return html + `<div class="empty">油价历史数据尚未加载完成（稍等片刻或检查集成状态）。</div>`;
      }

      // prices/changes 的 key 是接口数据字段名（GAS_92 等），与实体的 fuel_key 对应
      const head = `<tr><th>调价周期</th>${fuels.map((f) => `<th>${esc(f.label)}</th>`).join('')}<th>涨跌</th></tr>`;
      const baseKey = fuels[0].key;
      const rows = hist.slice(0, HISTORY_ROWS).map((h) => {
        const p = h.prices || {};
        const c = (h.changes || {})[baseKey];
        const dir = c == null || c === 0 ? '' : (c > 0 ? 'up' : 'down');
        return `<tr>
          <td class="muted">${esc(h.start || '')} ~ ${esc(h.end || '')}</td>
          ${fuels.map((f) => `<td>${fmt(p[f.key])}</td>`).join('')}
          <td class="${dir}">${c == null ? '—' : signed(c)}</td>
        </tr>`;
      }).join('');
      html += `<div style="overflow-x:auto"><table>${head}${rows}</table></div>`;

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
        html += `<div style="margin-top:10px"><div class="hint">${esc(chart.label)} 价格走势（近 ${series.length} 期）：</div>` +
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
        return `<div class="empty">还没有车辆。</div>`;
      }
      const s = this._stats();
      const q = this._qualityEntity();
      const problems = (q && q.attributes.problems) || [];
      const gaps = Number((q && q.attributes.odometer_gaps) || 0);
      const tile = (v, k, d = 2) =>
        `<div class="stat"><div class="v">${v == null ? '—' : fmt(v, d)}</div><div class="k">${k}</div></div>`;

      return `
        ${problems.length ? `<div class="msg warn"><ha-icon icon="mdi:alert-outline"></ha-icon><div><b>数据需修正（${problems.length} 项）——这些区间已排除在统计外</b>${problems.map((p) => `• ${esc(p)}`).join('<br>')}</div></div>` : ''}
        ${gaps ? `<div class="msg info"><ha-icon icon="mdi:information-outline"></ha-icon><div><b>${gaps} 处区间缺少里程读数</b>未计入里程与油耗统计。</div></div>` : ''}
        <div class="grid">
          ${tile(s.odometer, '当前里程 km', 1)}
          <div class="stat"><div class="v">${esc(s.refuel_count == null ? '—' : s.refuel_count)}</div><div class="k">加油次数</div></div>
          ${tile(s.total_volume, '累计加油 L', 1)}
          ${tile(s.total_cost, '累计费用 元', 0)}
          ${tile(s.total_distance, '累计行驶 km', 1)}
          ${tile(s.last_consumption, '最近油耗 L/100km')}
          ${tile(s.avg_consumption, '平均油耗 L/100km')}
          ${tile(s.avg_price, '平均油价 元/L')}
          ${tile(s.per_km_cost, '每公里油费 元', 3)}
        </div>
        <div class="hint">数值直接取自集成后端统计（与「加油记录」设备下的传感器一致）。
          平均油耗 = 除去首箱的区间加油量合计 ÷ 区间里程合计（加满假设）。
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
