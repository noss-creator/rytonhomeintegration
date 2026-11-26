// The client's view of Ryton Home Automations, and the administrator's link
// to the setup form. Plain JavaScript, with no build step and nothing fetched
// from the internet.
//
// The view reads the upcoming schedule from the integration and makes
// short-term changes through the integration's own actions. It never changes
// the schedule itself.

const DOMAIN = 'ryton_home_automations'

const esc = (value) =>
  String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])

const addDays = (iso, n) => {
  const d = new Date(`${iso}T12:00:00`)
  d.setDate(d.getDate() + n)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const weekdayOf = (iso) => new Date(`${iso}T12:00:00`).getDay() // 0 is Sunday

const STYLE = `
  :host { display: block; height: 100%; background: var(--primary-background-color, #f3f4f6); color: var(--primary-text-color, #1b2130); font-family: var(--paper-font-body1_-_font-family, system-ui, sans-serif); }
  * { box-sizing: border-box; }
  .bar { display: flex; align-items: center; gap: 8px; height: 56px; padding: 0 12px; background: var(--app-header-background-color, var(--primary-color, #2d5be3)); color: var(--app-header-text-color, #fff); font-size: 1.25rem; font-weight: 500; }
  .tabs { display: flex; gap: 4px; padding: 8px 12px 0; overflow-x: auto; border-bottom: 1px solid var(--divider-color, #d3d8df); background: var(--card-background-color, #fff); }
  .tab { border: 0; background: none; color: var(--secondary-text-color, #4a5563); font: inherit; font-weight: 600; padding: 10px 14px; border-bottom: 3px solid transparent; cursor: pointer; white-space: nowrap; }
  .tab[aria-selected="true"] { color: var(--primary-color, #2d5be3); border-bottom-color: var(--primary-color, #2d5be3); }
  main { max-width: 860px; margin: 0 auto; padding: 16px 12px 48px; display: grid; gap: 16px; }
  .scroll { height: calc(100% - 56px); overflow-y: auto; }
  .card { background: var(--card-background-color, #fff); border: 1px solid var(--divider-color, #d3d8df); border-radius: 12px; padding: 16px; display: grid; gap: 12px; }
  h2 { margin: 0; font-size: 1.1rem; }
  h3 { margin: 0; font-size: 1rem; }
  p { margin: 0; }
  .muted { color: var(--secondary-text-color, #4a5563); font-size: 0.92rem; }
  .day-title { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; }
  .tag { font-size: 0.8rem; font-weight: 600; padding: 2px 8px; border-radius: 999px; background: var(--secondary-background-color, #e7eaee); color: var(--secondary-text-color, #4a5563); }
  .auto { display: grid; grid-template-columns: 64px 1fr; gap: 4px 12px; padding: 10px 0; border-top: 1px solid var(--divider-color, #d3d8df); }
  .auto.past { opacity: 0.5; }
  .time { font-weight: 700; font-variant-numeric: tabular-nums; }
  .auto-name { font-weight: 600; }
  .lines { grid-column: 2; display: grid; gap: 2px; font-size: 0.92rem; }
  .room-link { border: 0; background: none; padding: 0; font: inherit; font-weight: 600; color: var(--primary-color, #2d5be3); cursor: pointer; }
  .row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
  .between { justify-content: space-between; }
  label.field { display: grid; gap: 4px; font-size: 0.9rem; font-weight: 600; }
  input, select { font: inherit; padding: 8px 10px; border: 1px solid var(--divider-color, #c4cad3); border-radius: 8px; background: var(--card-background-color, #fff); color: inherit; min-height: 40px; }
  input[type="number"] { width: 96px; }
  input[type="checkbox"] { min-height: 0; width: 18px; height: 18px; }
  .btn { font: inherit; font-weight: 600; padding: 9px 16px; border-radius: 8px; border: 1px solid var(--primary-color, #2d5be3); background: var(--primary-color, #2d5be3); color: var(--text-primary-color, #fff); cursor: pointer; min-height: 40px; }
  .btn.ghost { background: transparent; color: var(--primary-color, #2d5be3); }
  .btn.danger { background: transparent; border-color: var(--error-color, #b3261e); color: var(--error-color, #b3261e); }
  .btn:disabled { opacity: 0.5; cursor: default; }
  .item { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px; padding: 10px 0; border-top: 1px solid var(--divider-color, #d3d8df); }
  .item:first-of-type { border-top: 0; }
  .error { color: var(--error-color, #b3261e); font-weight: 600; }
  .notice { color: var(--success-color, #0f7a48); font-weight: 600; }
  .checks { display: flex; flex-wrap: wrap; gap: 6px 16px; }
  .checks label { display: flex; align-items: center; gap: 6px; font-weight: 400; font-size: 0.95rem; }
  .entity { display: grid; grid-template-columns: 1fr auto; gap: 6px 12px; align-items: center; padding: 6px 0; border-top: 1px solid var(--divider-color, #d3d8df); }
  .state { font-weight: 700; }
  .state.off { color: var(--error-color, #b3261e); }
  .state.on { color: var(--success-color, #0f7a48); }
  a.btn { text-decoration: none; display: inline-flex; align-items: center; }
`

class RytonClientView extends HTMLElement {
  constructor() {
    super()
    this.attachShadow({ mode: 'open' })
    this._data = null
    this._tab = 'upcoming'
    this._room = ''
    this._message = null
    this._busy = false
    this._form = this._emptyForm()
    this._quick = { early: '', simchaFrom: '', simchaUntil: '' }
    this._until = {}
    this._timer = null
    this.shadowRoot.addEventListener('click', (event) => this._click(event))
    this.shadowRoot.addEventListener('change', (event) => this._change(event))
  }

  _emptyForm() {
    return {
      what: 'time',
      from: '',
      until: '',
      days: null, // the days found in the dates, each with whether it is ticked
      automation: '',
      mode: 'clock',
      clock: '',
      minutes: 30,
      direction: 'later',
      room: '',
      entities: {},
    }
  }

  set hass(hass) {
    const first = !this._hass
    this._hass = hass
    if (first) this._load()
    const button = this.shadowRoot.querySelector('ha-menu-button')
    if (button) button.hass = hass
  }

  set narrow(narrow) {
    this._narrow = narrow
    const button = this.shadowRoot.querySelector('ha-menu-button')
    if (button) button.narrow = narrow
  }

  set panel(panel) {
    this._panel = panel
  }

  connectedCallback() {
    this._render()
    this._timer = setInterval(() => {
      if (!this._editing()) this._load()
    }, 60000)
  }

  disconnectedCallback() {
    clearInterval(this._timer)
  }

  /** Whether the client is in the middle of filling something in. */
  _editing() {
    const active = this.shadowRoot.activeElement
    return Boolean(active && ['INPUT', 'SELECT'].includes(active.tagName))
  }

  async _load() {
    if (!this._hass) return
    try {
      this._data = await this._hass.callWS({ type: `${DOMAIN}/view`, days: 7 })
    } catch (error) {
      this._message = { error: `The schedule could not be read: ${error.message || error}` }
    }
    this._render()
  }

  async _service(service, data, wantAnswer = false) {
    const answer = await this._hass.callWS({
      type: 'call_service',
      domain: DOMAIN,
      service,
      service_data: data,
      return_response: wantAnswer,
    })
    return answer && answer.response
  }

  async _do(work, done) {
    this._busy = true
    this._message = null
    this._render()
    try {
      await work()
      this._message = done ? { notice: done } : null
    } catch (error) {
      this._message = { error: error.message || String(error) }
    }
    this._busy = false
    await this._load()
  }

  // --- words ---------------------------------------------------------------

  _date(iso, long = false) {
    const language = (this._hass && this._hass.locale && this._hass.locale.language) || 'en'
    return new Date(`${iso}T12:00:00`).toLocaleDateString(
      language,
      long ? { weekday: 'long', day: 'numeric', month: 'long' } : { day: 'numeric', month: 'short' },
    )
  }

  _roomName(id) {
    const room = (this._data.rooms || []).find((r) => r.id === id)
    return room ? room.name : id
  }

  _entityName(id) {
    for (const room of this._data.rooms || []) {
      const found = room.entities.find((e) => e.entity_id === id)
      if (found) return found.name
    }
    return id
  }

  _automationName(id) {
    for (const list of [...Object.values(this._data.automations_by_day || {}), this._data.alongside || []]) {
      const found = list.find((a) => a.id === id)
      if (found) return found.name
    }
    return id
  }

  _dayName(id) {
    const found = (this._form.days || []).find((d) => d.day === id)
    if (found) return found.name
    const shown = (this._data.days || []).find((d) => d.day === id)
    return shown ? shown.day_name : id.replace(/__/g, ' on ').replace(/_/g, ' ')
  }

  _action(action) {
    if (action === null) return 'left as is'
    if (action.option !== undefined) return String(action.option)
    if (action.position !== undefined) return `${action.position}% open`
    if (action.state === 'on') return action.brightness_pct !== undefined ? `on, ${action.brightness_pct}%` : 'on'
    return String(action.state)
  }

  _describe(change) {
    let what = change.kind
    if (change.kind === 'time') {
      const name = this._automationName(change.automation)
      if (change.time) {
        what = `${name} at ${change.time.at}`
      } else {
        const m = Math.abs(change.shift_minutes)
        what = `${name} ${m} minutes ${change.shift_minutes > 0 ? 'later' : 'earlier'} than usual`
      }
    } else if (change.kind === 'room') {
      const set = Object.entries(change.entities || {})
        .map(([id, action]) => `${this._entityName(id)} ${this._action(action)}`)
        .join(', ')
      what = `${this._automationName(change.automation)}, ${this._roomName(change.room)}: ${set}`
    } else if (change.kind === 'room_switch') {
      what = `${this._roomName(change.room)}: scheduling ${change.scheduling}`
    } else if (change.kind === 'shabbos') {
      what = change.week === 'late' ? 'Late Shabbos (at candle lighting)' : `Early Shabbos, starting at ${(change.start || {}).at || '?'}`
    } else if (change.kind === 'simcha') {
      what = 'Simcha: a later Night'
    }
    const dates =
      change.from === change.until ? this._date(change.from) : `${this._date(change.from)} to ${this._date(change.until)}`
    const days = change.days === 'all' ? '' : `, only on ${change.days.map((d) => this._dayName(d)).join(', ')}`
    return { what, when: `${dates}${days}` }
  }

  // --- drawing -------------------------------------------------------------

  _render() {
    const tabs = [
      ['upcoming', 'Upcoming'],
      ['changes', 'Temporary changes'],
      ['quick', 'Quick switches'],
      ['rooms', 'Rooms'],
    ]
    let body = '<div class="card"><p class="muted">Loading…</p></div>'
    if (this._data && !this._data.ready) {
      body = '<div class="card"><p>This house has no schedule yet.</p></div>'
    } else if (this._data) {
      body = { upcoming: () => this._upcoming(), changes: () => this._changes(), quick: () => this._quickTab(), rooms: () => this._rooms() }[this._tab]()
    }
    const message = this._message
      ? `<p class="${this._message.error ? 'error' : 'notice'}" role="status">${esc(this._message.error || this._message.notice)}</p>`
      : ''
    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <div class="bar"><ha-menu-button></ha-menu-button><span>Ryton Home Automations</span></div>
      <div class="scroll">
        <div class="tabs" role="tablist">
          ${tabs.map(([id, name]) => `<button class="tab" role="tab" aria-selected="${this._tab === id}" data-do="tab" data-id="${id}">${name}</button>`).join('')}
        </div>
        <main>${message}${body}</main>
      </div>`
    const button = this.shadowRoot.querySelector('ha-menu-button')
    if (button) {
      button.hass = this._hass
      button.narrow = this._narrow
    }
  }

  _upcoming() {
    const rooms = this._data.rooms || []
    const filter = `
      <div class="card">
        <label class="field">Show
          <select data-set="room">
            <option value="">Every room</option>
            ${rooms.map((r) => `<option value="${esc(r.id)}" ${this._room === r.id ? 'selected' : ''}>Only ${esc(r.name)}</option>`).join('')}
          </select>
        </label>
        <p class="muted">Tap a room's name below to see only that room. Temporary changes are already included.</p>
      </div>`
    const days = (this._data.days || [])
      .map((day) => {
        const automations = day.automations
          .map((a) => {
            const lines = a.rooms.filter((r) => !this._room || r.room === this._room)
            if (this._room && lines.length === 0) return ''
            return `
              <div class="auto${a.past ? ' past' : ''}">
                <span class="time">${esc(a.time.slice(11, 16))}</span>
                <span class="auto-name">${esc(a.name)}</span>
                <div class="lines">
                  ${lines.length === 0 ? '<span class="muted">Changes nothing</span>' : ''}
                  ${lines.map((r) => `<span><button class="room-link" data-do="room" data-id="${esc(r.room)}">${esc(r.name)}</button>: ${esc(r.text)}</span>`).join('')}
                </div>
              </div>`
          })
          .join('')
        if (!automations.trim()) return ''
        const off = day.rooms_off.length
          ? `<p class="muted">Scheduling is off for: ${esc(day.rooms_off.map((r) => this._roomName(r)).join(', '))}</p>`
          : ''
        return `
          <section class="card">
            <div class="day-title">
              <h2>${esc(this._date(day.date, true))}</h2>
              <span class="tag">${esc(day.day_name)}</span>
              ${day.shabbos_start ? `<span class="tag">Shabbos starts ${esc(day.shabbos_start.slice(11, 16))}</span>` : ''}
            </div>
            ${off}
            <div>${automations}</div>
          </section>`
      })
      .join('')
    return filter + (days.trim() ? days : '<div class="card"><p>Nothing is coming up in the next week.</p></div>')
  }

  _changeList(kinds) {
    const found = (this._data.changes || []).filter((c) => kinds.includes(c.kind))
    if (found.length === 0) return '<p class="muted">None at the moment.</p>'
    return found
      .map((change) => {
        const words = this._describe(change)
        return `
          <div class="item">
            <div><div><strong>${esc(words.what)}</strong></div><div class="muted">${esc(words.when)}</div></div>
            <button class="btn danger" data-do="remove" data-id="${esc(change.id)}" ${this._busy ? 'disabled' : ''}>Remove</button>
          </div>`
      })
      .join('')
  }

  _changes() {
    const f = this._form
    const today = this._data.today
    const dayChecks = f.days
      ? `<div class="field"><span class="muted">On which days? Untick the ones this should not touch.</span>
           <div class="checks">${f.days.map((d, i) => `<label><input type="checkbox" data-day="${i}" ${d.on ? 'checked' : ''}> ${esc(d.name)} (${d.dates.length})</label>`).join('')}</div></div>`
      : ''
    const chosenDays = (f.days || []).filter((d) => d.on).map((d) => d.day)
    const automations = []
    for (const day of chosenDays) {
      for (const a of (this._data.automations_by_day || {})[day] || []) {
        if (!automations.some((b) => b.id === a.id)) automations.push(a)
      }
    }
    for (const a of this._data.alongside || []) if (!automations.some((b) => b.id === a.id)) automations.push(a)
    const automationSelect = `
      <label class="field">Which automation
        <select data-form="automation">
          <option value="">Choose…</option>
          ${automations.map((a) => `<option value="${esc(a.id)}" ${f.automation === a.id ? 'selected' : ''}>${esc(a.name)}</option>`).join('')}
        </select>
      </label>`

    let detail = ''
    if (f.days && f.what === 'time') {
      detail = `
        ${automationSelect}
        <label class="field">Its time
          <select data-form="mode">
            <option value="clock" ${f.mode === 'clock' ? 'selected' : ''}>At a clock time</option>
            <option value="shift" ${f.mode === 'shift' ? 'selected' : ''}>Earlier or later than usual</option>
          </select>
        </label>
        ${
          f.mode === 'clock'
            ? `<label class="field">Time<input type="time" data-form="clock" value="${esc(f.clock)}"></label>
               <p class="muted">A time after midnight and before ${esc(this._data.rollover)} counts as the end of that night.</p>`
            : `<div class="row">
                 <input type="number" min="1" max="600" data-form="minutes" value="${esc(f.minutes)}" aria-label="Minutes">
                 <span>minutes</span>
                 <select data-form="direction" aria-label="Earlier or later">
                   <option value="later" ${f.direction === 'later' ? 'selected' : ''}>later</option>
                   <option value="earlier" ${f.direction === 'earlier' ? 'selected' : ''}>earlier</option>
                 </select>
                 <span>than usual</span>
               </div>`
        }`
    } else if (f.days && f.what === 'room') {
      const room = (this._data.rooms || []).find((r) => r.id === f.room)
      const entities = room ? room.entities.filter((e) => !e.entity_id.startsWith('scene.')) : []
      detail = `
        ${automationSelect}
        <label class="field">Which room
          <select data-form="room">
            <option value="">Choose…</option>
            ${(this._data.rooms || []).map((r) => `<option value="${esc(r.id)}" ${f.room === r.id ? 'selected' : ''}>${esc(r.name)}</option>`).join('')}
          </select>
        </label>
        ${room && entities.length === 0 ? '<p class="muted">This room has nothing to set.</p>' : ''}
        <div>${entities.map((e) => this._entityRow(e)).join('')}</div>`
    }

    return `
      <section class="card">
        <h2>Changes in place now</h2>
        ${this._changeList(['time', 'room'])}
      </section>
      <section class="card">
        <h2>Make a temporary change</h2>
        <p class="muted">It lasts for the dates you choose, then the house goes back to its schedule by itself.</p>
        <label class="field">What to change
          <select data-form="what">
            <option value="time" ${f.what === 'time' ? 'selected' : ''}>The time of an automation</option>
            <option value="room" ${f.what === 'room' ? 'selected' : ''}>What an automation does in a room</option>
          </select>
        </label>
        <div class="row">
          <label class="field">From<input type="date" data-form="from" min="${esc(today)}" value="${esc(f.from)}"></label>
          <label class="field">Until<input type="date" data-form="until" min="${esc(f.from || today)}" value="${esc(f.until)}"></label>
        </div>
        ${dayChecks}
        ${detail}
        <div class="row">
          <button class="btn" data-do="save" ${this._canSave() && !this._busy ? '' : 'disabled'}>Save the change</button>
          <button class="btn ghost" data-do="clear">Clear</button>
        </div>
      </section>`
  }

  _entityRow(entity) {
    const id = entity.entity_id
    const domain = id.split('.')[0]
    const chosen = this._form.entities[id]
    const value = chosen === undefined ? '' : chosen === null ? 'leave' : chosen.option !== undefined ? `option:${chosen.option}` : chosen.position !== undefined ? 'position' : chosen.state
    let options = [['', 'No change'], ['leave', 'Leave as is']]
    if (domain === 'select' || domain === 'input_select') {
      options = options.concat((entity.options || []).map((o) => [`option:${o}`, o]))
    } else if (domain === 'cover') {
      options = options.concat([['open', 'Open'], ['closed', 'Closed']])
      if (entity.position) options.push(['position', 'Partly open'])
    } else {
      options = options.concat([['on', 'On'], ['off', 'Off']])
    }
    let extra = ''
    if (chosen && chosen.state === 'on' && entity.dimmable) {
      extra = `<span class="row"><input type="number" min="1" max="100" data-entity-brightness="${esc(id)}" value="${esc(chosen.brightness_pct ?? 100)}" aria-label="Brightness"> %</span>`
    } else if (chosen && chosen.position !== undefined) {
      extra = `<span class="row"><input type="number" min="0" max="100" data-entity-position="${esc(id)}" value="${esc(chosen.position)}" aria-label="How far open"> % open</span>`
    }
    return `
      <div class="entity">
        <span>${esc(entity.name)}</span>
        <span class="row">
          <select data-entity="${esc(id)}" aria-label="${esc(entity.name)}">
            ${options.map(([v, label]) => `<option value="${esc(v)}" ${v === value ? 'selected' : ''}>${esc(label)}</option>`).join('')}
          </select>
          ${extra}
        </span>
      </div>`
  }

  _canSave() {
    const f = this._form
    if (!f.days || !f.from || !f.until || !f.days.some((d) => d.on) || !f.automation) return false
    if (f.what === 'time') return f.mode === 'clock' ? Boolean(f.clock) : Number(f.minutes) > 0
    return Boolean(f.room) && Object.keys(f.entities).length > 0
  }

  _quickTab() {
    const q = this._quick
    const friday = this._friday()
    return `
      <section class="card">
        <h2>In place now</h2>
        ${this._changeList(['shabbos', 'simcha'])}
      </section>
      <section class="card">
        <h2>This Shabbos, ${esc(this._date(friday))}</h2>
        <p class="muted">Each of these is for this week only.</p>
        <div class="row between">
          <span><strong>Late Shabbos</strong><br><span class="muted">Shabbos starts at candle lighting, even where it is usually early.</span></span>
          <button class="btn" data-do="late" ${this._busy ? 'disabled' : ''}>Late this week</button>
        </div>
        <div class="row between">
          <span><strong>Early Shabbos</strong><br><span class="muted">Shabbos starts at the time you enter. It is never later than candle lighting.</span></span>
          <span class="row">
            <input type="time" data-quick="early" value="${esc(q.early)}" aria-label="Early Shabbos start time">
            <button class="btn" data-do="early" ${q.early && !this._busy ? '' : 'disabled'}>Early this week</button>
          </span>
        </div>
      </section>
      <section class="card">
        <h2>Simcha</h2>
        <p class="muted">Night runs later on the dates you choose.${this._data.has_simcha_time ? '' : ' This house has no simcha time set, so it cannot be used yet.'}</p>
        <div class="row">
          <label class="field">From<input type="date" data-quick="simchaFrom" min="${esc(this._data.today)}" value="${esc(q.simchaFrom)}"></label>
          <label class="field">Until<input type="date" data-quick="simchaUntil" min="${esc(q.simchaFrom || this._data.today)}" value="${esc(q.simchaUntil)}"></label>
          <button class="btn" data-do="simcha" ${q.simchaFrom && this._data.has_simcha_time && !this._busy ? '' : 'disabled'}>Turn on</button>
        </div>
      </section>`
  }

  /** The Friday of this week: today if it is Friday, otherwise the next one. */
  _friday() {
    const today = this._data.today
    return addDays(today, (5 - weekdayOf(today) + 7) % 7)
  }

  _rooms() {
    const timed = (this._data.changes || []).filter((c) => c.kind === 'room_switch')
    const rows = (this._data.rooms || [])
      .map((room) => {
        const off = (this._data.rooms_off || []).includes(room.id)
        const until = this._until[room.id] || ''
        const mine = timed.filter((c) => c.room === room.id)
        return `
          <div class="item">
            <div>
              <strong>${esc(room.name)}</strong>
              <span class="state ${off ? 'off' : 'on'}">${off ? 'Off' : 'On'}</span>
              ${mine.map((c) => `<div class="muted">${esc(c.scheduling === 'off' ? 'Off' : 'On')} ${esc(this._describe(c).when)} <button class="room-link" data-do="remove" data-id="${esc(c.id)}">Remove</button></div>`).join('')}
            </div>
            <div class="row">
              <button class="btn ghost" data-do="switch" data-id="${esc(room.id)}" data-to="${off ? 'on' : 'off'}" ${this._busy ? 'disabled' : ''}>Turn ${off ? 'on' : 'off'}</button>
              <input type="date" data-until="${esc(room.id)}" min="${esc(this._data.today)}" value="${esc(until)}" aria-label="Until which date">
              <button class="btn ghost" data-do="until" data-id="${esc(room.id)}" data-to="${off ? 'on' : 'off'}" ${until && !this._busy ? '' : 'disabled'}>${off ? 'On' : 'Off'} until then</button>
            </div>
          </div>`
      })
      .join('')
    return `
      <section class="card">
        <h2>Room scheduling</h2>
        <p class="muted">While a room's scheduling is off, automations skip that room. Turn it off or on with no end, or pick a date and it goes back by itself the day after.</p>
        ${rows || '<p class="muted">This house has no rooms.</p>'}
      </section>`
  }

  // --- what the client does ------------------------------------------------

  _click(event) {
    const target = event.target.closest('[data-do]')
    if (!target || target.disabled) return
    const id = target.dataset.id
    const today = this._data && this._data.today
    switch (target.dataset.do) {
      case 'tab':
        this._tab = id
        this._message = null
        return this._render()
      case 'room':
        this._room = this._room === id ? '' : id
        return this._render()
      case 'remove':
        return this._do(() => this._service('remove_change', { id }), 'Removed.')
      case 'clear':
        this._form = this._emptyForm()
        return this._render()
      case 'save':
        return this._save()
      case 'late':
        return this._do(() => this._add({ kind: 'shabbos', week: 'late' }, this._friday(), this._friday()), 'Late Shabbos is set for this week.')
      case 'early':
        return this._do(
          () => this._add({ kind: 'shabbos', week: 'early', start: { kind: 'clock', at: this._quick.early } }, this._friday(), this._friday()),
          'Early Shabbos is set for this week.',
        )
      case 'simcha': {
        const from = this._quick.simchaFrom
        const until = this._quick.simchaUntil && this._quick.simchaUntil >= from ? this._quick.simchaUntil : from
        return this._do(() => this._add({ kind: 'simcha' }, from, until), 'Simcha is on for those dates.')
      }
      case 'switch':
        return this._do(() => this._service('set_room_scheduling', { room: id, scheduling: target.dataset.to }))
      case 'until':
        return this._do(
          () => this._add({ kind: 'room_switch', room: id, scheduling: target.dataset.to }, today, this._until[id]),
          'Saved. It goes back by itself afterwards.',
        )
      default:
    }
  }

  _add(change, from, until, days = 'all') {
    return this._service('add_change', { change: { from, until, days, ...change } })
  }

  async _change(event) {
    const el = event.target
    const f = this._form
    if (el.dataset.set === 'room') {
      this._room = el.value
      return this._render()
    }
    if (el.dataset.quick) {
      this._quick[el.dataset.quick] = el.value
      return this._render()
    }
    if (el.dataset.until) {
      this._until[el.dataset.until] = el.value
      return this._render()
    }
    if (el.dataset.day !== undefined) {
      f.days[Number(el.dataset.day)].on = el.checked
      return this._render()
    }
    if (el.dataset.entity) {
      const id = el.dataset.entity
      const v = el.value
      if (v === '') delete f.entities[id]
      else if (v === 'leave') f.entities[id] = null
      else if (v === 'position') f.entities[id] = { position: 50 }
      else if (v.startsWith('option:')) f.entities[id] = { option: v.slice(7) }
      else f.entities[id] = { state: v }
      return this._render()
    }
    if (el.dataset.entityBrightness) {
      const pct = Math.min(100, Math.max(1, Number(el.value) || 100))
      f.entities[el.dataset.entityBrightness] = { state: 'on', brightness_pct: pct }
      return
    }
    if (el.dataset.entityPosition) {
      f.entities[el.dataset.entityPosition] = { position: Math.min(100, Math.max(0, Number(el.value) || 0)) }
      return
    }
    const key = el.dataset.form
    if (!key) return
    f[key] = el.value
    if (key === 'room') f.entities = {}
    if (key === 'from' && (!f.until || f.until < f.from)) f.until = f.from
    if ((key === 'from' || key === 'until') && f.from && f.until && f.until >= f.from) {
      await this._findDays()
    }
    this._render()
  }

  /** Asks the house which of its days occur in the dates chosen. */
  async _findDays() {
    const f = this._form
    try {
      const answer = await this._service('days_in_dates', { from: f.from, until: f.until }, true)
      f.days = (answer.days || []).map((d) => ({
        day: d.day,
        dates: d.dates,
        on: true,
        name: d.day.replace(/__/g, ' on ').replace(/_(\d)$/, ', day $1').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()),
      }))
      this._message = null
    } catch (error) {
      f.days = null
      this._message = { error: error.message || String(error) }
    }
  }

  _save() {
    const f = this._form
    const all = f.days.every((d) => d.on)
    const days = all ? 'all' : f.days.filter((d) => d.on).map((d) => d.day)
    let change
    if (f.what === 'time') {
      if (f.mode === 'clock') {
        // A time before the rollover belongs to the end of that night.
        const late = f.clock < this._data.rollover
        change = { kind: 'time', automation: f.automation, time: { kind: 'clock', at: f.clock, ...(late ? { day_offset: 1 } : {}) } }
      } else {
        const minutes = Math.round(Number(f.minutes)) * (f.direction === 'earlier' ? -1 : 1)
        change = { kind: 'time', automation: f.automation, shift_minutes: minutes }
      }
    } else {
      change = { kind: 'room', automation: f.automation, room: f.room, entities: f.entities }
    }
    return this._do(async () => {
      await this._add(change, f.from, f.until, days)
      this._form = this._emptyForm()
    }, 'Saved. The house goes back to its schedule afterwards.')
  }
}

class RytonSetupForm extends HTMLElement {
  set panel(panel) {
    this._panel = panel
    this._render()
  }

  set hass(hass) {
    this._hass = hass
    const button = this.shadowRoot && this.shadowRoot.querySelector('ha-menu-button')
    if (button) button.hass = hass
  }

  set narrow(narrow) {
    this._narrow = narrow
  }

  connectedCallback() {
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' })
    this._render()
  }

  _render() {
    if (!this.shadowRoot) return
    const url = (this._panel && this._panel.config && this._panel.config.url) || ''
    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <div class="bar"><ha-menu-button></ha-menu-button><span>Ryton setup form</span></div>
      <main>
        <section class="card">
          <h2>The setup form</h2>
          <p>This house's schedule is set up on the Ryton Home Automations website. It opens in a new tab and needs the installer's login.</p>
          <div><a class="btn" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Open the setup form</a></div>
        </section>
      </main>`
    const button = this.shadowRoot.querySelector('ha-menu-button')
    if (button) {
      button.hass = this._hass
      button.narrow = this._narrow
    }
  }
}

if (!customElements.get('ryton-client-view')) customElements.define('ryton-client-view', RytonClientView)
if (!customElements.get('ryton-setup-form')) customElements.define('ryton-setup-form', RytonSetupForm)
