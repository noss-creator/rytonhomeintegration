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
  .tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
  .tile { display: grid; gap: 4px; text-align: left; font: inherit; color: inherit; padding: 12px; min-height: 76px; border: 1px solid var(--divider-color, #d3d8df); border-radius: 12px; background: var(--secondary-background-color, #f3f4f6); cursor: pointer; }
  .tile:hover, .line:hover { border-color: var(--primary-color, #2d5be3); }
  .tile strong { font-size: 1rem; }
  .line { display: flex; justify-content: space-between; align-items: center; gap: 12px; width: 100%; text-align: left; font: inherit; color: inherit; padding: 12px; border: 1px solid var(--divider-color, #d3d8df); border-radius: 10px; background: var(--card-background-color, #fff); cursor: pointer; }
  .list { display: grid; gap: 8px; }
  .back { border: 0; background: none; padding: 4px 0; font: inherit; font-weight: 600; color: var(--primary-color, #2d5be3); cursor: pointer; justify-self: start; }
  .suspended { text-decoration: line-through; opacity: 0.7; }
  fieldset { border: 0; margin: 0; padding: 0; display: grid; gap: 10px; }
  fieldset:disabled { opacity: 0.45; }
  .check { display: flex; align-items: center; gap: 8px; font-weight: 600; }
  .indent { margin-left: 26px; display: grid; gap: 6px; justify-items: start; }
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
    this._quick = { early: '', simchaFrom: '', simchaUntil: '', simchaAt: '' }
    this._until = {}
    this._away = { run: 'off', rooms: null, end: 'motzei', date: '' }
    this._at = { room: '', entity: '' } // where the Rooms tab is: the house, a room, or an entity
    this._child = {} // what is being filled in for a room's own Night (child or adult), by room
    this._timer = null
    this.shadowRoot.addEventListener('click', (event) => this._click(event))
    this.shadowRoot.addEventListener('change', (event) => this._change(event))
  }

  _emptyForm() {
    return {
      from: '',
      until: '',
      days: null, // the days found in the dates, each with whether it is ticked
      automation: '',
      mode: 'clock',
      clock: '',
      minutes: 30,
      direction: 'later',
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
      what = `${this._automationName(change.automation)}: ${set}`
    } else if (change.kind === 'room_switch') {
      what = `${this._roomName(change.room)}: scheduling ${change.scheduling}`
    } else if (change.kind === 'shabbos') {
      what = change.week === 'late' ? 'Late Shabbos (at candle lighting)' : `Early Shabbos, starting at ${(change.start || {}).at || '?'}`
    } else if (change.kind === 'simcha') {
      what = change.at ? `Simcha: Night at ${change.at.slice(0, 5)} in the simcha rooms` : 'Simcha: a later Night'
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
      ['changes', 'Time changes'],
      ['quick', 'Quick switches'],
      ['away', 'Away'],
      ['rooms', 'Rooms'],
    ]
    let body = '<div class="card"><p class="muted">Loading…</p></div>'
    if (this._data && !this._data.ready) {
      body = '<div class="card"><p>This house has no schedule yet.</p></div>'
    } else if (this._data) {
      body = { upcoming: () => this._upcoming(), changes: () => this._changes(), quick: () => this._quickTab(), away: () => this._awayTab(), rooms: () => this._rooms() }[this._tab]()
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
    const days = this._dayCards(this._room)
    const away = this._data.away
      ? `<div class="card"><p><strong>Away mode is on: ${esc(this._data.away.name)}.</strong> What is listed below is what runs while it is on.</p></div>`
      : ''
    return away + filter + (days.trim() ? days : '<div class="card"><p>Nothing is coming up in the next week.</p></div>')
  }

  /** The coming days, each with its automations: all of them, or only what one room does. */
  _dayCards(only, links = true) {
    return (this._data.days || [])
      .map((day) => {
        const automations = day.automations
          .map((a) => {
            const lines = a.rooms.filter((r) => !only || r.room === only)
            if (only && lines.length === 0) return ''
            return `
              <div class="auto${a.past ? ' past' : ''}">
                <span class="time">${esc(a.time.slice(11, 16))}</span>
                <span class="auto-name">${esc(a.name)}</span>
                <div class="lines">
                  ${lines.length === 0 ? '<span class="muted">Changes nothing</span>' : ''}
                  ${lines.map((r) => (links ? `<span><button class="room-link" data-do="room" data-id="${esc(r.room)}">${esc(r.name)}</button>: ${esc(r.text)}</span>` : `<span>${esc(r.text)}</span>`)).join('')}
                </div>
              </div>`
          })
          .join('')
        if (!automations.trim()) return ''
        const off = day.rooms_off.length && !only
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
    if (f.days) {
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
    }

    return `
      <section class="card">
        <h2>Changes in place now</h2>
        ${this._changeList(['time', 'room'])}
      </section>
      <section class="card">
        <h2>Change a time</h2>
        <p class="muted">Change the time of an automation for the dates you choose. Then the house goes back to its schedule by itself.</p>
        <p class="muted">To stop one light or switch from being changed, open it under Rooms.</p>
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

  _canSave() {
    const f = this._form
    if (!f.days || !f.from || !f.until || !f.days.some((d) => d.on) || !f.automation) return false
    return f.mode === 'clock' ? Boolean(f.clock) : Number(f.minutes) > 0
  }

  _quickTab() {
    const q = this._quick
    const friday = this._friday()
    const sh = this._data.shabbos && this._data.shabbos.date === friday ? this._data.shabbos : null
    const clock = (iso) => (iso ? iso.slice(11, 16) : '?')
    const mine = (this._data.changes || []).some((c) => c.kind === 'shabbos' && c.from <= friday && friday <= c.until)
    const early = Boolean(sh && sh.early)
    const facts = sh
      ? `<p>Shkia this Friday is at <strong>${esc(clock(sh.shkia))}</strong>. Candle lighting is at ${esc(clock(sh.candle_lighting))}.</p>
         <p>${early ? `By this house's settings, Shabbos is <strong>early</strong> this week, starting at ${esc(clock(sh.start))}.` : `By this house's settings, Shabbos starts at <strong>candle lighting</strong> this week.`}</p>`
      : ''
    let choice
    if (mine) {
      choice = '<p class="muted">You have changed this week. Remove the change above to go back to the settings of the house.</p>'
    } else if (early) {
      choice = `
        <div class="row between">
          <span><strong>Late Shabbos</strong><br><span class="muted">Shabbos starts at candle lighting this week.</span></span>
          <button class="btn" data-do="late" ${this._busy ? 'disabled' : ''}>Late this week</button>
        </div>`
    } else {
      choice = `
        <div class="row between">
          <span><strong>Early Shabbos</strong><br><span class="muted">Shabbos starts at the time you enter. It is never later than candle lighting.</span></span>
          <span class="row">
            <input type="time" data-quick="early" value="${esc(q.early)}" aria-label="Early Shabbos start time">
            <button class="btn" data-do="early" ${q.early && !this._busy ? '' : 'disabled'}>Early this week</button>
          </span>
        </div>`
    }
    return `
      <section class="card">
        <h2>In place now</h2>
        ${this._changeList(['shabbos', 'simcha'])}
      </section>
      <section class="card">
        <h2>This Shabbos, ${esc(this._date(friday))}</h2>
        ${facts}
        ${choice}
        <p class="muted">The change is for this week only.</p>
      </section>
      <section class="card">
        <h2>Simcha</h2>
        ${this._simchaWords()}
        <div class="row">
          <label class="field">From<input type="date" data-quick="simchaFrom" min="${esc(this._data.today)}" value="${esc(q.simchaFrom)}"></label>
          <label class="field">Until<input type="date" data-quick="simchaUntil" min="${esc(q.simchaFrom || this._data.today)}" value="${esc(q.simchaUntil)}"></label>
          <label class="field">Night at<input type="time" data-quick="simchaAt" value="${esc(this._simchaAt())}"></label>
          <button class="btn" data-do="simcha" ${q.simchaFrom && this._simchaAt() && this._simchaCan() && !this._busy ? '' : 'disabled'}>Turn on</button>
        </div>
        <p class="muted">The time has to be later than the house's Night and before the house's day starts over at ${esc(String(this._data.rollover || '04:00').slice(0, 5))}. On a night when it is not, Night runs as usual.</p>
      </section>`
  }

  _moment(iso) {
    return `${this._date(iso.slice(0, 10), true)} at ${iso.slice(11, 16)}`
  }

  _awayTab() {
    const data = this._data
    const a = this._away
    const rooms = data.rooms || []
    const presets = data.presets || []
    const now = data.away
    if (a.run !== 'off' && a.run !== 'rooms' && !presets.some((p) => p.id === a.run)) a.run = 'off'
    if (a.end === 'motzei' && !data.motzei) a.end = 'date'
    const ticked = a.rooms || rooms.map((r) => r.id)

    let state = '<p class="muted">Away mode is off. The house runs its regular schedule.</p>'
    if (now) {
      const which =
        now.run === 'rooms'
          ? `Only these rooms run: ${now.rooms.map((r) => this._roomName(r)).join(', ') || 'none'}. Everything else is off.`
          : now.run === 'off'
            ? 'Everything is off and nothing runs.'
            : `The house runs its "${now.name}" schedule.`
      state =
        now.by === 'client'
          ? `<p><strong>Away mode is on.</strong> ${esc(which)}</p>
             <p class="muted">Until ${esc(this._moment(now.ends_at))}. Then each room goes to where the regular schedule has it.</p>
             <div><button class="btn danger" data-do="end-away" ${this._busy ? 'disabled' : ''}>End away mode now</button></div>`
          : `<p><strong>Away mode is on.</strong> ${esc(which)}</p>
             <p class="muted">These dates are set up for this house every year. Choosing below takes over from them.</p>`
    }

    const roomChecks =
      a.run === 'rooms'
        ? `<div class="field"><span class="muted">Tick the rooms that keep running their regular schedule. The others are switched off.</span>
             <div class="checks">${rooms.map((r) => `<label><input type="checkbox" data-away-room="${esc(r.id)}" ${ticked.includes(r.id) ? 'checked' : ''}> ${esc(r.name)}</label>`).join('')}</div></div>`
        : ''
    const canStart = !this._busy && (a.end === 'motzei' ? Boolean(data.motzei) : Boolean(a.date))

    const meals = data.meals || []
    const mealRows = meals
      .map((m) => {
        // A night meal belongs to the date it starts on: Friday night is listed under Friday.
        const label = `${m.name}, ${this._date(m.date, true)}${m.meal === 'night' ? ' night' : ''}`
        return `
          <div class="item">
            <div><strong>${esc(label)}</strong>${m.out ? '<div class="state off">Away for this meal</div>' : ''}</div>
            ${
              m.out
                ? `<button class="btn ghost" data-do="remove" data-id="${esc(m.out)}" ${this._busy ? 'disabled' : ''}>Home after all</button>`
                : `<button class="btn" data-do="meal-out" data-id="${esc(m.date)}" data-to="${esc(m.meal)}" ${this._busy ? 'disabled' : ''}>Away for this meal</button>`
            }
          </div>`
      })
      .join('')

    return `
      <section class="card">
        <h2>Away mode</h2>
        ${state}
      </section>
      <section class="card">
        <h2>${now ? 'Change away mode' : 'Turn away mode on'}</h2>
        <label class="field">While away
          <select data-away="run">
            <option value="off" ${a.run === 'off' ? 'selected' : ''}>Everything off</option>
            ${presets.map((p) => `<option value="${esc(p.id)}" ${a.run === p.id ? 'selected' : ''}>Run the "${esc(p.name)}" schedule</option>`).join('')}
            <option value="rooms" ${a.run === 'rooms' ? 'selected' : ''}>Only some rooms run</option>
          </select>
        </label>
        ${roomChecks}
        <label class="field">Until
          <select data-away="end">
            ${data.motzei ? `<option value="motzei" ${a.end === 'motzei' ? 'selected' : ''}>Motzei Shabbos or Yom Tov (${esc(this._moment(data.motzei.ends_at))})</option>` : ''}
            <option value="date" ${a.end === 'date' ? 'selected' : ''}>The end of a date</option>
          </select>
        </label>
        ${a.end === 'date' ? `<label class="field">Last date away<input type="date" data-away="date" min="${esc(data.today)}" value="${esc(a.date)}"></label>` : ''}
        <p class="muted">Away mode starts as soon as you turn it on.${a.end === 'motzei' ? ' It ends an hour after havdalah.' : ''}</p>
        <div><button class="btn" data-do="start-away" ${canStart ? '' : 'disabled'}>Turn away mode on</button></div>
      </section>
      <section class="card">
        <h2>Away for a meal</h2>
        <p class="muted">The rooms set up for it run differently for that meal. These are the meals of the coming week.</p>
        ${mealRows || '<p class="muted">No Shabbos or Yom Tov meals in the coming week.</p>'}
      </section>`
  }

  /** The Friday of this week: today if it is Friday, otherwise the next one. */
  _friday() {
    const today = this._data.today
    return addDays(today, (5 - weekdayOf(today) + 7) % 7)
  }

  /** How an entity is now, in a word or two. */
  _stateNow(id) {
    const state = this._hass && this._hass.states && this._hass.states[id]
    if (!state) return ''
    if (state.state === 'on' && state.attributes && state.attributes.brightness) {
      return `On, ${Math.round((state.attributes.brightness / 255) * 100)}%`
    }
    return String(state.state).replace(/^./, (c) => c.toUpperCase())
  }

  /**
   * Every time in the coming week that an automation sets this entity, with
   * the ones the client has suspended.
   */
  _entityTimes(id) {
    const found = []
    for (const day of this._data.days || []) {
      for (const a of day.automations) {
        const base = { date: day.date, automation: a.id, name: a.name, time: a.time, past: a.past }
        for (const set of a.sets || []) {
          if (set.entity === id) found.push({ ...base, room: set.room, text: set.text, fixed: set.fixed })
        }
        // A suspended entity is no longer in what the automation sets.
        for (const c of this._data.changes || []) {
          const mine =
            c.kind === 'room' &&
            c.automation === a.id &&
            c.from <= day.date &&
            day.date <= c.until &&
            (c.days === 'all' || c.days.includes(day.day)) &&
            c.entities &&
            c.entities[id] === null
          if (mine && !found.some((row) => row.date === day.date && row.automation === a.id && !row.suspended)) {
            // Only a change made here, for this one entity and date, is undone here.
            const own = Object.keys(c.entities).length === 1 && c.from === c.until
            found.push({ ...base, room: c.room, suspended: true, change: own ? c.id : null })
          }
        }
      }
    }
    return found
  }

  _rooms() {
    const rooms = this._data.rooms || []
    const room = rooms.find((r) => r.id === this._at.room)
    if (!room) return this._house(rooms)
    const entity = room.entities.find((e) => e.entity_id === this._at.entity)
    return entity ? this._entityPage(room, entity) : this._roomPage(room)
  }

  /** The house: its floors, and the rooms on each. */
  _house(rooms) {
    if (rooms.length === 0) return '<section class="card"><p class="muted">This house has no rooms.</p></section>'
    const floors = []
    for (const room of rooms) {
      const name = room.floor || 'Other rooms'
      let floor = floors.find((f) => f.name === name)
      if (!floor) floors.push((floor = { name, rooms: [] }))
      floor.rooms.push(room)
    }
    const off = this._data.rooms_off || []
    return floors
      .map(
        (floor) => `
        <section class="card">
          <h2>${esc(floor.name)}</h2>
          <div class="tiles">
            ${floor.rooms
              .map((room) => {
                const count = room.entities.filter((e) => !e.entity_id.startsWith('scene.')).length
                return `
                  <button class="tile" data-do="open-room" data-id="${esc(room.id)}">
                    <strong>${esc(room.name)}</strong>
                    <span class="muted">${count} ${count === 1 ? 'device' : 'devices'}</span>
                    ${off.includes(room.id) ? '<span class="state off">Scheduling off</span>' : ''}
                  </button>`
              })
              .join('')}
          </div>
        </section>`,
      )
      .join('')
  }

  /** The simcha time being entered: what the client typed, or the time the schedule suggests. */
  _simchaAt() {
    return this._quick.simchaAt || this._data.simcha_time || ''
  }

  /** Whether simcha mode would do anything: the house has simcha rooms. */
  _simchaCan() {
    return (this._data.simcha_rooms || []).length > 0
  }

  _simchaWords() {
    const rooms = this._data.simcha_rooms || []
    if (rooms.length === 0) {
      return '<p class="muted">This house has no simcha rooms set, so it cannot be used yet.</p>'
    }
    const names = rooms.map((id) => esc(this._roomName(id))).join(', ')
    return `<p class="muted">On the dates you choose, Night runs at the time you enter in the simcha rooms: <strong>${names}</strong>. The rest of the house has its Night as usual.</p>`
  }

  /** A room's own Night as it is being filled in, starting from what the house has. */
  _childDraft(roomId) {
    if (!this._child[roomId]) {
      const saved = (this._data.room_night || {})[roomId]
      const minutes = saved && saved.minutes ? saved.minutes : 60
      this._child[roomId] = {
        kind: saved ? saved.mode || 'child' : '', // '', 'child' (earlier) or 'adult' (later)
        mode: saved && saved.at ? 'clock' : 'from',
        hours: Math.floor(minutes / 60),
        minutes: minutes % 60,
        at: saved && saved.at ? saved.at.slice(0, 5) : '',
      }
    }
    return this._child[roomId]
  }

  /**
   * Tonight's usual Night of the house, as HH:MM, where the house has one,
   * and the time the schedule gives the room tonight, where it gives one.
   */
  _nightTonight(roomId) {
    const days = this._data.days || []
    const day = days.find((d) => d.date === this._data.today && d.night_usual) || days.find((d) => d.night_usual)
    const own = day && day.night_rooms ? day.night_rooms[roomId] : ''
    return { night: day ? day.night_usual.slice(11, 16) : '', own: own ? own.slice(11, 16) : '' }
  }

  _childCard(room) {
    const d = this._childDraft(room.id)
    const saved = (this._data.room_night || {})[room.id]
    const adult = d.kind === 'adult'
    const word = adult ? 'later' : 'earlier'
    // Hours and minutes are counted from the room's own time, where the schedule gives it one.
    const { night, own } = this._nightTonight(room.id)
    const from = own || night
    const tonight = own
      ? `Tonight this room's Night is set for ${own} (the house's is at ${night})`
      : `Tonight the house's Night is at ${night}`
    const whose = own ? "this room's usual Night" : "the house's Night"
    const rollover = String(this._data.rollover || '04:00').slice(0, 5)
    const apart = Number(d.hours) * 60 + Number(d.minutes)
    const mins = (clock) => {
      const [h, m] = clock.split(':').map(Number)
      return h * 60 + m
    }
    let computed = ''
    if (night && apart > 0) {
      const at = (((mins(from) + (adult ? apart : -apart)) % 1440) + 1440) % 1440
      const clock = `${String(Math.floor(at / 60)).padStart(2, '0')}:${String(at % 60).padStart(2, '0')}`
      // How long after Night the house's day starts over; an adult's Night has to be before that.
      const room_left = (((mins(rollover) - mins(from)) % 1440) + 1440) % 1440
      computed =
        adult && apart >= room_left
          ? `${tonight}, and this would be at ${clock}, which is not before the house's day starts over at ${rollover}. On such a night the room keeps its usual time.`
          : `${tonight}, so with this it is at <strong>${clock}</strong>.`
    } else if (night) {
      computed = `${tonight}.`
    }
    const valid = d.mode === 'from' ? apart >= 1 && apart <= 720 : Boolean(d.at)
    const same =
      saved &&
      (saved.mode || 'child') === d.kind &&
      (d.mode === 'from' ? saved.minutes === apart : saved.at && saved.at.slice(0, 5) === d.at)
    const off = this._busy ? 'disabled' : ''
    return `
      <section class="card">
        <h2>This room's own Night</h2>
        <label class="check"><input type="checkbox" data-child="kind" data-id="${esc(room.id)}" value="child" ${d.kind === 'child' ? 'checked' : ''} ${off}> Child night mode: this room has its Night earlier than the house</label>
        <label class="check"><input type="checkbox" data-child="kind" data-id="${esc(room.id)}" value="adult" ${adult ? 'checked' : ''} ${off}> Adult night mode: this room has its Night later than the house</label>
        <fieldset ${d.kind ? '' : 'disabled'}>
          <label class="check"><input type="radio" name="child-mode" data-child="mode" data-id="${esc(room.id)}" value="from" ${d.mode === 'from' ? 'checked' : ''}> ${adult ? 'Later' : 'Earlier'} than ${whose}</label>
          <div class="indent">
            <div class="row">
              <input type="number" min="0" max="12" data-child="hours" data-id="${esc(room.id)}" value="${esc(d.hours)}" aria-label="Hours ${word}" ${d.mode === 'from' ? '' : 'disabled'}> hours
              <input type="number" min="0" max="59" data-child="minutes" data-id="${esc(room.id)}" value="${esc(d.minutes)}" aria-label="Minutes ${word}" ${d.mode === 'from' ? '' : 'disabled'}> minutes ${word}
            </div>
            <p class="muted">${computed} It moves with ${whose}, so it can differ on Shabbos and Yom Tov.</p>
          </div>
          <label class="check"><input type="radio" name="child-mode" data-child="mode" data-id="${esc(room.id)}" value="clock" ${d.mode === 'clock' ? 'checked' : ''}> At a clock time</label>
          <div class="indent">
            <input type="time" data-child="at" data-id="${esc(room.id)}" value="${esc(d.at)}" aria-label="Clock time of this room's Night" ${d.mode === 'clock' ? '' : 'disabled'}>
            <p class="muted">A clock time does not change from night to night. It is the same on Shabbos and Yom Tov, whatever time the house's Night is then. ${
              adult
                ? `It must be later than the house's Night and before the house's day starts over at ${rollover}; on a night when it is not, the room runs with the house.`
                : "It must be earlier than the house's Night; on a night when it is not, the room runs with the house."
            }</p>
          </div>
          <div class="row">
            <button class="btn" data-do="child-save" data-id="${esc(room.id)}" ${d.kind && valid && !same && !this._busy ? '' : 'disabled'}>${saved ? 'Save the change' : 'Turn on'}</button>
            ${saved && same ? '<span class="state on">On</span>' : ''}
          </div>
        </fieldset>
        <p class="muted">${
          adult
            ? "The house's Night leaves this room as it is, and the room's Night runs at its own, later time."
            : "From this room's own Night until the house's Night, automations skip this room, so it stays as its Night left it."
        }</p>
      </section>`
  }

  /** One room: its scheduling switch, and everything in it. */
  _roomPage(room) {
    const off = (this._data.rooms_off || []).includes(room.id)
    const until = this._until[room.id] || ''
    const timed = (this._data.changes || []).filter((c) => c.kind === 'room_switch' && c.room === room.id)
    const entities = room.entities.filter((e) => !e.entity_id.startsWith('scene.'))
    const lines = entities
      .map((e) => {
        const times = this._entityTimes(e.entity_id).filter((t) => !t.past)
        const next = times.find((t) => !t.suspended)
        const suspended = times.filter((t) => t.suspended).length
        const now = this._stateNow(e.entity_id)
        return `
          <button class="line" data-do="open-entity" data-id="${esc(e.entity_id)}">
            <span>
              <strong>${esc(e.name)}</strong>
              <span class="muted"><br>${next ? `Next: ${esc(this._date(next.date))} ${esc(next.time.slice(11, 16))}, ${esc(next.text)}` : 'Nothing set in the coming week'}${suspended ? ` · ${suspended} suspended` : ''}</span>
            </span>
            <span class="tag">${esc(now)}</span>
          </button>`
      })
      .join('')
    return `
      <button class="back" data-do="open-room" data-id="">‹ All rooms</button>
      <section class="card">
        <div class="row between">
          <h2>${esc(room.name)}</h2>
          <span class="state ${off ? 'off' : 'on'}">Scheduling ${off ? 'off' : 'on'}</span>
        </div>
        <p class="muted">While a room's scheduling is off, automations skip this room. Turn it off or on with no end, or pick a date and it goes back by itself the day after.</p>
        ${timed.map((c) => `<div class="muted">${esc(c.scheduling === 'off' ? 'Off' : 'On')} ${esc(this._describe(c).when)} <button class="room-link" data-do="remove" data-id="${esc(c.id)}">Remove</button></div>`).join('')}
        <div class="row">
          <button class="btn" data-do="switch" data-id="${esc(room.id)}" data-to="${off ? 'on' : 'off'}" ${this._busy ? 'disabled' : ''}>Turn scheduling ${off ? 'on' : 'off'}</button>
          <input type="date" data-until="${esc(room.id)}" min="${esc(this._data.today)}" value="${esc(until)}" aria-label="Until which date">
          <button class="btn ghost" data-do="until" data-id="${esc(room.id)}" data-to="${off ? 'on' : 'off'}" ${until && !this._busy ? '' : 'disabled'}>${off ? 'On' : 'Off'} until then</button>
        </div>
      </section>
      ${this._childCard(room)}
      <section class="card">
        <h2>In this room</h2>
        <p class="muted">Tap one to see when it is changed in the coming week.</p>
        <div class="list">${lines || '<p class="muted">This room has nothing that is scheduled.</p>'}</div>
      </section>
      <section class="card">
        <h2>This room's schedule</h2>
        <p class="muted">What the automations do in this room in the coming week. Temporary changes are already included.</p>
      </section>
      ${this._dayCards(room.id, false).trim() || '<div class="card"><p class="muted">Nothing is set in this room in the coming week.</p></div>'}`
  }

  /** One entity: each time it is changed in the coming week, to suspend or bring back. */
  _entityPage(room, entity) {
    const id = entity.entity_id
    const times = this._entityTimes(id)
    const off = (this._data.rooms_off || []).includes(room.id)
    let rows = ''
    let day = ''
    for (const t of times) {
      if (t.date !== day) {
        day = t.date
        rows += `<h3>${esc(this._date(t.date, true))}</h3>`
      }
      let action = ''
      if (t.past) action = '<span class="muted">Done</span>'
      else if (t.suspended) {
        action = t.change
          ? `<button class="btn ghost" data-do="remove" data-id="${esc(t.change)}" ${this._busy ? 'disabled' : ''}>Bring back</button>`
          : '<span class="muted">Suspended</span>'
      } else if (t.fixed) action = '<span class="muted">Part of a scene</span>'
      else {
        action = `<button class="btn" data-do="suspend" data-id="${esc(id)}" data-date="${esc(t.date)}" data-automation="${esc(t.automation)}" data-room="${esc(t.room)}" ${this._busy ? 'disabled' : ''}>Suspend</button>`
      }
      rows += `
        <div class="item${t.past ? ' auto past' : ''}" style="display:flex">
          <div>
            <div><span class="time">${esc(t.time.slice(11, 16))}</span> <strong>${esc(t.name)}</strong></div>
            <div class="${t.suspended ? 'state off' : 'muted'}">${t.suspended ? 'Suspended: left as it is' : `Set to ${esc(t.text)}`}</div>
          </div>
          ${action}
        </div>`
    }
    return `
      <button class="back" data-do="open-entity" data-id="">‹ ${esc(room.name)}</button>
      <section class="card">
        <div class="row between">
          <h2>${esc(entity.name)}</h2>
          <span class="tag">${esc(this._stateNow(id))}</span>
        </div>
        <p class="muted">These are the times the schedule changes it in the coming week. Suspend one and it is left as it is at that time, that once.</p>
        ${off ? `<p class="state off">Scheduling is off for ${esc(room.name)}, so nothing here runs.</p>` : ''}
      </section>
      <section class="card">
        <h2>Coming week</h2>
        ${rows || '<p class="muted">Nothing changes it in the coming week.</p>'}
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
        // Tapping Rooms again goes back to the whole house.
        if (id === 'rooms') this._at = { room: '', entity: '' }
        this._tab = id
        this._message = null
        return this._render()
      case 'child-save': {
        const d = this._childDraft(id)
        const how = d.mode === 'from' ? { minutes: Number(d.hours) * 60 + Number(d.minutes) } : { at: d.at }
        const name = d.kind === 'adult' ? 'Adult' : 'Child'
        return this._do(async () => {
          await this._service('set_room_night', { room: id, mode: d.kind, ...how })
          delete this._child[id]
        }, `${name} night mode is on for this room.`)
      }
      case 'open-room':
        this._at = { room: id, entity: '' }
        this._message = null
        return this._render()
      case 'open-entity':
        this._at = { ...this._at, entity: id }
        this._message = null
        return this._render()
      case 'suspend':
        return this._do(
          () =>
            this._add(
              { kind: 'room', automation: target.dataset.automation, room: target.dataset.room, entities: { [id]: null } },
              target.dataset.date,
              target.dataset.date,
            ),
          'Suspended for that time.',
        )
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
        return this._do(() => this._add({ kind: 'simcha', at: this._simchaAt() }, from, until), 'Simcha is on for those dates.')
      }
      case 'start-away': {
        const a = this._away
        const data = { run: a.run, until: a.end === 'motzei' ? 'motzei' : a.date }
        if (a.run === 'rooms') data.rooms = a.rooms || (this._data.rooms || []).map((r) => r.id)
        return this._do(() => this._service('start_away', data), 'Away mode is on.')
      }
      case 'end-away':
        return this._do(() => this._service('end_away', {}), 'Away mode has ended. The house is back on its schedule.')
      case 'meal-out':
        return this._do(() => this._add({ kind: 'meal_out', meal: target.dataset.to }, id, id), 'Saved for that meal.')
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
    if (el.dataset.child) {
      const room = el.dataset.id
      const d = this._childDraft(room)
      const key = el.dataset.child
      if (key === 'kind') {
        // One at a time: ticking one unticks the other.
        d.kind = el.checked ? el.value : ''
        // Unticking takes it away at once, where the house has it.
        if (!el.checked && (this._data.room_night || {})[room]) {
          return this._do(async () => {
            await this._service('set_room_night', { room })
            delete this._child[room]
          }, "This room has the house's Night again.")
        }
      } else if (key === 'hours') d.hours = Math.min(12, Math.max(0, Math.round(Number(el.value) || 0)))
      else if (key === 'minutes') d.minutes = Math.min(59, Math.max(0, Math.round(Number(el.value) || 0)))
      else d[key] = el.value
      return this._render()
    }
    if (el.dataset.away) {
      this._away[el.dataset.away] = el.value
      return this._render()
    }
    if (el.dataset.awayRoom) {
      const all = (this._data.rooms || []).map((r) => r.id)
      const ticked = new Set(this._away.rooms || all)
      if (el.checked) ticked.add(el.dataset.awayRoom)
      else ticked.delete(el.dataset.awayRoom)
      this._away.rooms = all.filter((r) => ticked.has(r))
      return this._render()
    }
    if (el.dataset.day !== undefined) {
      f.days[Number(el.dataset.day)].on = el.checked
      return this._render()
    }
    const key = el.dataset.form
    if (!key) return
    f[key] = el.value
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
    if (f.mode === 'clock') {
      // A time before the rollover belongs to the end of that night.
      const late = f.clock < this._data.rollover
      change = { kind: 'time', automation: f.automation, time: { kind: 'clock', at: f.clock, ...(late ? { day_offset: 1 } : {}) } }
    } else {
      const minutes = Math.round(Number(f.minutes)) * (f.direction === 'earlier' ? -1 : 1)
      change = { kind: 'time', automation: f.automation, shift_minutes: minutes }
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
