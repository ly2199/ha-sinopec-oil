/**
 * Sinopec Oil Card — 中石化油价 · 加油记账一体化卡片
 *
 * 安装：将本文件复制到 /config/www/sinopec-oil-card.js，然后在
 * 仪表盘 → 右上角编辑 → 管理资源 → 添加
 *   URL: /local/sinopec-oil-card.js   版本: 1.0.1
 * 使用：仪表盘添加卡片 → 手动 →
 *   type: custom:sinopec-oil-card
 * 可选: title: 我的油卡   vehicle: 某辆车（默认记住上次选择）
 *
 * 卡片自动发现本集成实体（基于 sinopec_role 属性），
 * 无需填写任何实体 ID。
 *
 * 页签：⛽ 加油 · 📋 历史 · 📈 油价 · 🚗 统计
 * 规则：油耗计算要求时间-里程对应（相邻区间里程 0 < Δ ≤ 900 km），
 * 冲突记录会被拒绝入库（必须修正才能算）。
 */
(() => {
  const FUEL_OPTIONS = ['自动', '92', '95', '98', '89', '0#', '-10', '-20', '-35', 'LNG'];
  const TABS = [
    { id: 'refuel', label: '⛽ 加油' },
    { id: 'history', label: '📋 历史' },
    { id: 'price', label: '📈 油价' },
    { id: 'stats', label: '🚗 统计' },
  ];

  const esc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  const fmt = (v, d = 2) => (v == null || v === '' || isNaN(v)) ? '—' : Number(v).toFixed(d);

  class SinopecOilCard extends HTMLElement {
    static getStubConfig() { return { type: 'custom:sinopec-oil-card' }; }
    getCardSize() { return 5; }
    getConfigElement() { return null; }
    getConfig() { return this._config; }

    setConfig(config) {
      if (!config) throw new Error('配置无效');
      this._config = { title: '⛽ 中石化加油记账', ...config };
      this._tab = 'refuel';
      this._form = { date: null, odometer: '', volume: '', total_cost: '', fuel: '自动', note: '' };
      this._result = null;      // 提交响应
      this._error = null;       // 错误信息
      this._busy = false;
      this._editIdx = null;     // 正在编辑的记录序号
      this._editForm = {};
      this._showImport = false;
      this._importText = '';
      this._importResult = null;
    }

    set hass(hass) {
      this._hass = hass;
      this._discover();
      this._rememberVehicle();
      this._render();
    }

    /* ---------- 实体自动发现 ---------- */
    _discover() {
      const states = Object.values(this._hass.states || {});
      const byRole = (role) => states.filter((s) => s.attributes && s.attributes.sinopec_role === role);
      this._recordsEnts = byRole('sinopec_records');
      this._qualityEnts = byRole('sinopec_quality');
      this._priceEnts = byRole('sinopec_price');
      this._historyEnt = byRole('sinopec_price_history')[0] || null;
      this._periodEndEnt = byRole('sinopec_period_end')[0] || null;
      this._vehicles = this._recordsEnts
        .map((s) => s.attributes.vehicle)
        .filter(Boolean);
      if (!this._vehicle && this._vehicles.length) {
        this._vehicle = this._vehicles[0];
      }
    }

    _rememberVehicle() {
      if (this._config.vehicle && this._config.vehicle !== this._vehicle) {
        if (this._vehicles.includes(this._config.vehicle)) {
          this._vehicle = this._config.vehicle;
        }
      }
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

    _currentOdometer() {
      const recs = this._records();
      for (let i = recs.length - 1; i >= 0; i--) {
        if (recs[i].odometer != null) return recs[i].odometer;
      }
      return '';
    }

    /* ---------- 服务调用 ---------- */
    async _call(service, payload, useResponse) {
      this._busy = true; this._error = null; this._render();
      try {
        const opts = useResponse ? { return_response: true } : undefined;
        const resp = await this._hass.callService('sinopec_oil', service, payload, opts);
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
      if (!f.date) {
        const now = new Date();
        const pad = (n) => String(n).padStart(2, '0');
        f.date = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
      }
      payload.date = f.date + (f.date.length === 16 ? ':00' : '');
      if (f.odometer !== '' && f.odometer != null) payload.odometer = Number(f.odometer);
      if (f.volume !== '') payload.volume = Number(f.volume);
      if (f.total_cost !== '') payload.total_cost = Number(f.total_cost);
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
      if (!confirm(`确定删除第 ${index + 1} 条记录？`)) return;
      try {
        await this._call('delete_refuel_record', { vehicle: this._vehicle, index }, false);
        this._result = { deleted: index };
      } catch (e) { /* 已记录 _error */ }
    }

    async _saveEdit() {
      const f = this._editForm;
      const payload = { vehicle: this._vehicle, index: this._editIdx };
      if (f.date) payload.date = f.date;
      if (f.odometer !== '') payload.odometer = Number(f.odometer);
      if (f.volume !== '') payload.volume = Number(f.volume);
      if (f.total_cost !== '') payload.total_cost = Number(f.total_cost);
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
        const parts = line.split(/[,;\t，]+/).map((p) => p.trim()).filter((p) => p !== '');
        if (parts.length < 2) { out.push({ raw: line, error: '至少需要 日期,里程' }); continue; }
        const [date, odo, vol, cost, fuel, ...noteParts] = parts;
        const rec = { date: date.length === 10 ? date + 'T12:00:00' : date };
        const o = parseFloat(odo);
        if (isNaN(o)) { out.push({ raw: line, error: '里程不是数字' }); continue; }
        rec.odometer = o;
        if (vol && !isNaN(parseFloat(vol))) rec.volume = parseFloat(vol);
        if (cost && !isNaN(parseFloat(cost))) rec.total_cost = parseFloat(cost);
        if (fuel) rec.fuel_type = fuel;
        if (noteParts.length) rec.note = noteParts.join(' ');
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
      const style = `
        <style>
          :host { display: block; }
          ha-card { overflow: hidden; }
          .card { padding: 12px 16px 16px; }
          .header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
          .title { font-size: 1.1em; font-weight: 600; color: var(--primary-text-color); }
          .tabs { display: flex; gap: 4px; margin: 8px 0 12px; flex-wrap: wrap; }
          .tab { padding: 4px 12px; border-radius: 16px; cursor: pointer; font-size: 0.9em;
                 color: var(--secondary-text-color); background: var(--secondary-background-color, #eee); }
          .tab.active { color: var(--text-primary-color, #fff); background: var(--primary-color); font-weight: 600; }
          .row { display: flex; gap: 8px; margin: 8px 0; flex-wrap: wrap; align-items: center; }
          .field { display: flex; flex-direction: column; flex: 1 1 120px; min-width: 110px; }
          .field label { font-size: 0.78em; color: var(--secondary-text-color); margin-bottom: 2px; }
          .field input, .field select, textarea {
            width: 100%; box-sizing: border-box; padding: 6px 8px; border: 1px solid var(--divider-color, #ccc);
            border-radius: var(--ha-card-border-radius, 8px); background: var(--card-background-color, #fff);
            color: var(--primary-text-color); font-size: 0.95em; }
          textarea { min-height: 90px; font-family: monospace; }
          .btn { padding: 8px 18px; border: none; border-radius: 18px; cursor: pointer; font-size: 0.95em;
                 background: var(--primary-color); color: var(--text-primary-color, #fff); font-weight: 600; }
          .btn:disabled { opacity: .5; cursor: default; }
          .btn.secondary { background: var(--secondary-background-color, #eee); color: var(--primary-text-color); }
          .btn.danger { background: var(--error-color, #db4437); color: #fff; }
          .msg { margin: 10px 0; padding: 10px 12px; border-radius: 8px; font-size: 0.9em; }
          .msg.ok { background: rgba(76,175,80,.12); color: var(--success-color, #2e7d32); }
          .msg.err { background: rgba(219,68,55,.10); color: var(--error-color, #db4437); }
          .msg.warn { background: rgba(255,152,0,.12); color: var(--warning-color, #ef6c00); }
          .msg b { display: block; margin-bottom: 4px; }
          table { width: 100%; border-collapse: collapse; font-size: 0.85em; }
          th { text-align: left; color: var(--secondary-text-color); font-weight: 500;
               border-bottom: 1px solid var(--divider-color, #ccc); padding: 4px 6px; }
          td { padding: 5px 6px; border-bottom: 1px solid var(--divider-color, #eee); color: var(--primary-text-color); }
          tr:last-child td { border-bottom: none; }
          .muted { color: var(--secondary-text-color); }
          .pill { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 0.78em;
                  background: var(--secondary-background-color, #eee); color: var(--secondary-text-color); }
          .pill.good { background: rgba(76,175,80,.15); color: var(--success-color, #2e7d32); }
          .pill.bad { background: rgba(219,68,55,.12); color: var(--error-color, #db4437); }
          .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; margin: 10px 0; }
          .stat { padding: 10px; border-radius: 10px; background: var(--secondary-background-color, #f2f2f2); }
          .stat .v { font-size: 1.25em; font-weight: 600; color: var(--primary-text-color); }
          .stat .k { font-size: 0.75em; color: var(--secondary-text-color); margin-top: 2px; }
          .bar-wrap { display: flex; align-items: center; gap: 8px; margin: 3px 0; font-size: 0.8em; }
          .bar-label { width: 86px; color: var(--secondary-text-color); text-align: right; flex: none; }
          .bar-track { flex: 1; background: var(--secondary-background-color, #eee); border-radius: 4px; height: 14px; overflow: hidden; }
          .bar-fill { height: 100%; background: var(--primary-color); border-radius: 4px; }
          .bar-val { width: 56px; flex: none; color: var(--primary-text-color); }
          .hint { font-size: 0.78em; color: var(--secondary-text-color); margin: 6px 0; }
          .actions { display: flex; gap: 6px; }
          .actions .btn { padding: 3px 10px; font-size: 0.8em; }
          .editbox { background: var(--secondary-background-color, #f5f5f5); border-radius: 10px; padding: 10px; margin: 6px 0; }
          .empty { text-align: center; color: var(--secondary-text-color); padding: 18px 0; }
          .flexright { display: flex; justify-content: flex-end; margin-top: 8px; gap: 8px; }
        </style>`;

      const root = this.shadowRoot || this.attachShadow({ mode: 'open' });
      root.innerHTML = style + `
        <ha-card>
          <div class="card">
            ${this._htmlHeader()}
            ${this._error ? `<div class="msg err"><b>⛔ 出错了</b>${esc(this._error)}</div>` : ''}
            ${this._htmlTab()}
          </div>
        </ha-card>`;
      this._bind(root);
    }

    _htmlHeader() {
      const tabs = TABS.map((t) =>
        `<div class="tab ${this._tab === t.id ? 'active' : ''}" data-tab="${t.id}">${t.label}</div>`).join('');
      return `
        <div class="header">
          <div class="title">${esc(this._config.title || '加油记账')}</div>
          ${this._vehicles.length > 1 ? this._htmlVehicleSelect() : ''}
        </div>
        <div class="tabs">${tabs}</div>`;
    }

    _htmlVehicleSelect() {
      const opts = this._vehicles.map((v) =>
        `<option value="${esc(v)}" ${v === this._vehicle ? 'selected' : ''}>${esc(v)}</option>`).join('');
      return `<select data-vehicle style="padding:4px 8px;border-radius:8px;border:1px solid var(--divider-color,#ccc);
        background:var(--card-background-color,#fff);color:var(--primary-text-color)">${opts}</select>`;
    }

    _htmlTab() {
      if (this._tab === 'refuel') return this._htmlRefuel();
      if (this._tab === 'history') return this._htmlHistory();
      if (this._tab === 'price') return this._htmlPrice();
      return this._htmlStats();
    }

    /* ⛽ 加油页签 */
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
        resultHtml = `<div class="msg ok"><b>✅ 已记录加油</b>
          加油量：${fmt(r.volume)} L ｜ 费用：${fmt(r.total_cost)} 元<br>
          单价：${fmt(r.price)} 元/L${r.price_approximate ? '（约）' : ''}${r.price_source ? ` ｜ ${esc(r.price_source)}` : ''}${r.distance_since_last != null ? `<br>区间里程：${fmt(r.distance_since_last, 1)} km` : ''}${r.consumption_last != null ? ` ｜ 本次油耗：${fmt(r.consumption_last)} L/100km` : ''}</div>`;
      }
      return `
        <div class="row">
          <div class="field"><label>加油时间（改历史日期=按当时油价）</label>
            <input type="datetime-local" data-f="date" value="${esc(f.date || this._nowLocal())}"></div>
          <div class="field"><label>里程表读数 km（需大于上次 ${cur === '' ? '—' : cur}）</label>
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
          <button class="btn" data-action="submit" ${this._busy ? 'disabled' : ''}>${this._busy ? '提交中…' : '提交加油记录'}</button>
        </div>
        ${resultHtml}
        <div class="hint">只填量 → 按当日/历史油价算费用；只填费用 → 反算加油量；里程与时间需与上次记录递增对应（区间 ≤ 900 km）。</div>`;
    }

    _nowLocal() {
      const now = new Date();
      const pad = (n) => String(n).padStart(2, '0');
      return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
    }

    /* 📋 历史页签 */
    _htmlHistory() {
      const recs = this._records();
      const q = this._qualityEntity();
      const problems = (q && q.attributes.problems) || [];
      let html = '';
      if (problems.length) {
        html += `<div class="msg warn"><b>⚠️ 数据需修正（${problems.length} 项）——修正前油耗不可用</b>
          ${problems.map((p) => `• ${esc(p)}`).join('<br>')}</div>`;
      }
      if (!recs.length) {
        html += `<div class="empty">暂无记录。可在「⛽ 加油」页签录入，或用下方批量导入。</div>`;
      } else {
        const rows = recs.map((rec) => {
          if (this._editIdx === rec.index) return this._htmlEditRow(rec);
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
            <td><div class="actions">
              <button class="btn secondary" data-edit="${rec.index}">改</button>
              <button class="btn danger" data-del="${rec.index}">删</button>
            </div></td>
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
          <button class="btn secondary" data-action="toggle-import">${this._showImport ? '收起导入' : '📥 批量导入历史记录'}</button>
        </div>`;
      if (this._showImport) {
        const ir = this._importResult;
        html += `
          <div class="editbox">
            <div class="hint">每行一条：<b>日期, 里程, 加油量, 费用, [油品], [备注]</b>（逗号/分号/Tab 分隔；日期如 2026-08-01 或 2026-08-01 14:30；量与费用可只填一项）</div>
            <textarea data-f="import" placeholder="2026-08-01, 11800, 41.2, 338.5, 92, 中石化&#10;2026-08-20, 12350, 40.8, 335.0, 92, 优惠0.3">${esc(this._importText)}</textarea>
            <div class="flexright"><button class="btn" data-action="do-import" ${this._busy ? 'disabled' : ''}>导入</button></div>
            ${ir ? (ir.imported ? `<div class="msg ok"><b>✅ 导入 ${ir.imported} 条</b>${ir.rejected && ir.rejected.length ? `另有 ${ir.rejected.length} 条被拒绝：<br>${ir.rejected.map((x) => `• ${esc(x)}`).join('<br>')}` : ''}</div>` : (ir.rejected && ir.rejected.length ? `<div class="msg err"><b>⛔ 全部被拒绝</b>${ir.rejected.map((x) => `• ${esc(x)}`).join('<br>')}</div>` : '')) : ''}
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

    /* 📈 油价页签 */
    _htmlPrice() {
      let html = '';
      const prices = this._priceEnts || [];
      const hist = (this._historyEnt && this._historyEnt.attributes.price_history) || [];
      const period = this._historyEnt && this._historyEnt.attributes.current_period;
      const daysLeft = this._periodEndEnt && this._periodEndEnt.attributes.days_left;

      if (prices.length) {
        html += `<div class="grid">` + prices.map((p) => {
          const label = p.attributes.label || p.entity_id;
          const chg = p.attributes.price_change;
          const arrow = chg == null ? '' : (chg > 0 ? ' <span style="color:var(--error-color,#d32f2f)">▲</span>' : chg < 0 ? ' <span style="color:var(--success-color,#2e7d32)">▼</span>' : '');
          return `<div class="stat"><div class="v">${fmt(p.state)}${arrow}</div><div class="k">${esc(label)} 元/L${chg != null && chg !== 0 ? `（${chg > 0 ? '+' : ''}${fmt(chg)}）` : ''}</div></div>`;
        }).join('') + `</div>`;
      }
      if (period) {
        html += `<div class="hint">当前调价周期：${esc(period)}${daysLeft != null ? `，剩余 ${daysLeft} 天` : ''}（到期参考下一轮调价）</div>`;
      }

      if (hist.length) {
        const keys = ['92', '95', '0'];
        const head = `<tr><th>调价周期</th>${keys.map((k) => `<th>${k}</th>`).join('')}<th>涨跌(92)</th></tr>`;
        const rows = hist.slice(0, 12).map((h, i) => {
          const prev = hist[i + 1];
          const p92 = h['prices'] ? h['prices']['92'] : h['92'];
          const prev92 = prev ? (prev['prices'] ? prev['prices']['92'] : prev['92']) : null;
          const delta = (p92 != null && prev92 != null) ? p92 - prev92 : null;
          return `<tr>
            <td class="muted">${esc(h.start || h.from || '')} ~ ${esc(h.end || h.to || '')}</td>
            ${keys.map((k) => `<td>${fmt(h['prices'] ? h['prices'][k] : h[k])}</td>`).join('')}
            <td>${delta == null ? '—' : `<span style="color:${delta > 0 ? 'var(--error-color,#d32f2f)' : delta < 0 ? 'var(--success-color,#2e7d32)' : 'inherit'}">${delta > 0 ? '+' : ''}${fmt(delta)}</span>`}</td>
          </tr>`;
        }).join('');
        html += `<div style="overflow-x:auto"><table>${head}${rows}</table></div>`;

        // 92 号走势（近 12 期，水平条形）
        const series = hist.slice(0, 12).map((h) => ({
          end: (h.end || h.to || '').slice(5),
          v: h['prices'] ? h['prices']['92'] : h['92'],
        })).reverse().filter((x) => x.v != null);
        if (series.length > 1) {
          const vals = series.map((x) => x.v);
          const min = Math.min(...vals), max = Math.max(...vals);
          const span = (max - min) || 1;
          html += `<div style="margin-top:10px"><div class="hint">92 号汽油价格走势（近 ${series.length} 期）：</div>` +
            series.map((x) => {
              const w = 12 + Math.round(((x.v - min) / span) * 88);
              return `<div class="bar-wrap"><div class="bar-label">${esc(x.end)}</div>
                <div class="bar-track"><div class="bar-fill" style="width:${w}%"></div></div>
                <div class="bar-val">${fmt(x.v)}</div></div>`;
            }).join('') + `</div>`;
        }
      } else {
        html += `<div class="empty">油价数据尚未加载完成（稍等片刻或检查集成状态）。</div>`;
      }
      return html;
    }

    /* 🚗 统计页签 */
    _htmlStats() {
      if (!this._vehicles.length) {
        return `<div class="empty">还没有车辆。</div>`;
      }
      const recs = this._records();
      const q = this._qualityEntity();
      const problems = (q && q.attributes.problems) || [];
      let totalVolume = 0, totalCost = 0, count = recs.length;
      for (const r of recs) {
        totalVolume += Number(r.volume) || 0;
        totalCost += Number(r.total_cost) || 0;
      }
      const odoRecs = recs.filter((r) => r.odometer != null);
      const lastOdo = odoRecs.length ? odoRecs[odoRecs.length - 1].odometer : null;
      // 区间油耗合计（去除首箱）
      let segVol = 0, segDist = 0;
      for (const r of recs) {
        if (r.segment_consumption != null) {
          segVol += Number(r.volume) || 0;
          segDist += Number(r.segment_distance) || 0;
        }
      }
      const avgCons = (segDist > 0 && segVol > 0) ? (segVol * 100 / segDist) : null;
      const perKm = (totalCost > 0 && segDist > 0) ? (totalCost / segDist) : null;

      return `
        ${problems.length ? `<div class="msg warn"><b>⚠️ 数据需修正（${problems.length} 项）——以下油耗相关指标不可用</b>${problems.map((p) => `• ${esc(p)}`).join('<br>')}</div>` : ''}
        <div class="grid">
          <div class="stat"><div class="v">${fmt(lastOdo, 1)}</div><div class="k">当前里程 km</div></div>
          <div class="stat"><div class="v">${count}</div><div class="k">加油次数</div></div>
          <div class="stat"><div class="v">${fmt(totalVolume, 1)}</div><div class="k">累计加油 L</div></div>
          <div class="stat"><div class="v">${fmt(totalCost, 0)}</div><div class="k">累计费用 元</div></div>
          <div class="stat"><div class="v">${problems.length ? '—' : fmt(segDist, 0)}</div><div class="k">记录期里程 km</div></div>
          <div class="stat"><div class="v">${avgCons != null ? fmt(avgCons) : '—'}</div><div class="k">平均油耗 L/100km</div></div>
          <div class="stat"><div class="v">${perKm != null ? fmt(perKm, 2) : '—'}</div><div class="k">每公里油费 元</div></div>
          <div class="stat"><div class="v">${totalVolume > 0 ? fmt(totalCost / totalVolume) : '—'}</div><div class="k">平均油价 元/L</div></div>
        </div>
        <div class="hint">平均油耗 = 除去首箱的区间加油量合计 ÷ 区间里程合计（加满假设）。数据质量：${q ? `<span class="pill ${problems.length ? 'bad' : 'good'}">${esc(q.state)}</span>` : '—'}</div>`;
    }

    /* ---------- 事件绑定 ---------- */
    _bind(root) {
      const on = (sel, ev, fn) => {
        root.querySelectorAll(sel).forEach((el) => el.addEventListener(ev, fn));
      };
      on('[data-tab]', 'click', (e) => {
        this._tab = e.target.dataset.tab; this._error = null; this._render();
      });
      on('[data-vehicle]', 'change', (e) => {
        this._vehicle = e.target.value;
        this._form.odometer = '';
        this._result = null; this._editIdx = null; this._render();
      });
      on('[data-f]', 'input', (e) => {
        const key = e.target.dataset.f;
        if (key === 'import') { this._importText = e.target.value; return; }
        this._form[key] = e.target.value;
      });
      on('[data-f="fuel"]', 'change', (e) => { this._form.fuel = e.target.value; });
      on('[data-ef]', 'input', (e) => {
        this._editForm[e.target.dataset.ef] = e.target.value;
      });
      on('[data-ef="fuel"]', 'change', (e) => { this._editForm.fuel = e.target.value; });
      on('[data-action="submit"]', 'click', () => this._submit());
      on('[data-action="toggle-import"]', 'click', () => {
        this._showImport = !this._showImport; this._importResult = null; this._render();
      });
      on('[data-action="do-import"]', 'click', () => this._doImport());
      on('[data-del]', 'click', (e) => this._delete(Number(e.target.dataset.del)));
      on('[data-edit]', 'click', (e) => {
        const idx = Number(e.target.dataset.edit);
        const rec = this._records().find((r) => r.index === idx);
        this._editIdx = idx;
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
  });
})();
