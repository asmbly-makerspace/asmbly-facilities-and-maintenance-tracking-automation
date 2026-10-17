// Runs the class photo page's own <script> in node:vm against a small fake DOM, a fake
// clock and scripted server answers, one scenario per run (plan class-photo-loading,
// README Decision 12). Standard library only.
//
//   node page_script_harness.mjs <scenario> <jpeg path>   exit 0, or print why and exit 1
//   node page_script_harness.mjs --list                   the scenario names, one a line
//
// test_page_script.py runs every scenario through pytest.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash, webcrypto } from "node:crypto";
import vm from "node:vm";

const PAGE = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "page.html"), "utf8");
const SCRIPT = PAGE.match(/<script nonce="__CSP_NONCE__">([\s\S]*?)<\/script>/)[1];
const MARKUP_IDS = [...PAGE.matchAll(/\bid="([\w-]+)"/g)].map((match) => match[1]);
const PAGE_URL = "https://facilities.example/class-photo-upload";
const START_TIME = Date.UTC(2026, 9, 17, 14, 0, 0);
const HOUR_MS = 60 * 60 * 1000;
const SECOND_MS = 1000;
const REQUEST_TIMEOUT_MS = 35 * SECOND_MS;

// The page's own texts, read from its script so a scenario can't drift from it.
function pageText(name) {
  const match = SCRIPT.match(new RegExp(`const ${name} = "([^"]*)";`));
  assert.ok(match, `the page defines ${name}`);
  return match[1];
}

const CLASS_A = "Woodshop Safety";
const CLASS_B = "Intro to Laser Cutting";
const CLASS_C = "Wheel Throwing 101";
const NOTHING_CHANGED = "Couldn't open the pull request. Nothing was changed on GitHub. Try again in a minute.";

// ---- Fake DOM ----

class FakeElement {
  constructor(document, tagName, id) {
    this.ownerDocument = document;
    this.tagName = tagName.toUpperCase();
    this.id = id || "";
    this.children = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this.classes = new Set();
    this.textHistory = [];
    this.value = "";
    this.files = [];
    this._text = "";
    this._hidden = false;
    this._disabled = false;
    const classes = this.classes;
    this.classList = {
      add: (...names) => names.forEach((name) => classes.add(name)),
      remove: (...names) => names.forEach((name) => classes.delete(name)),
      contains: (name) => classes.has(name),
    };
  }

  get textContent() {
    return this._text + this.children.map((child) => child.textContent).join("");
  }

  set textContent(text) {
    this._text = String(text);
    this.children = [];
    this.textHistory.push(this._text);
  }

  // A browser moves focus to <body> when the focused control is hidden or disabled
  // (HTML's focus fixup rule); the fake does the same, so focus tests mean something.
  get hidden() {
    return this._hidden;
  }

  set hidden(value) {
    this._hidden = Boolean(value);
    if (this._hidden) this.ownerDocument.loseFocus(this);
  }

  get disabled() {
    return this._disabled;
  }

  set disabled(value) {
    this._disabled = Boolean(value);
    if (this._disabled) this.ownerDocument.loseFocus(this);
  }

  get firstElementChild() {
    return this.children[0] || null;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
    if (name === "class") String(value).split(/\s+/).filter(Boolean).forEach((item) => this.classes.add(item));
  }

  getAttribute(name) {
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }

  hasAttribute(name) {
    return this.attributes.has(name);
  }

  removeAttribute(name) {
    this.attributes.delete(name);
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  replaceChildren(...nodes) {
    this._text = "";
    this.children = nodes;
    this.busyWhenFilled = this.getAttribute("aria-busy");
  }

  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(listener);
  }

  dispatch(type, event = {}) {
    const full = { preventDefault() {}, target: this, ...event };
    for (const listener of this.listeners.get(type) || []) listener(full);
  }

  focus() {
    if (!this._disabled && !this._hidden) this.ownerDocument.activeElement = this;
  }

  // A disabled control ignores clicks, as in a browser; an aria-disabled one doesn't.
  click() {
    if (!this._disabled) this.dispatch("click");
  }
}

class FakeDocument {
  constructor(config) {
    this.body = new FakeElement(this, "body");
    this.activeElement = this.body;
    this.listeners = new Map();
    this.byId = new Map();
    for (const id of MARKUP_IDS) this.byId.set(id, new FakeElement(this, "div", id));
    this.byId.get("page-config")._text = JSON.stringify(config);
    // What the markup starts with, as far as the script relies on it.
    const select = this.byId.get("class-select");
    select.tagName = "SELECT";
    select._disabled = true;
    const placeholder = new FakeElement(this, "option");
    placeholder.value = "";
    placeholder._text = "Choose a class…";
    select.children.push(placeholder);
    this.byId.get("submit")._disabled = true;
    for (const id of ["class-retry", "class-refresh", "class-progress", "class-freshness", "submit-progress", "submit-elapsed", "app", "sign-out", "result", "sign-in-problem", "photo-note", "preview", "dry-run-banner"]) {
      this.byId.get(id)._hidden = true;
    }
    for (const id of ["class-retry", "class-refresh", "submit", "sign-out", "sign-in-again"]) this.byId.get(id).tagName = "BUTTON";
  }

  getElementById(id) {
    return this.byId.get(id) || null;
  }

  createElement(tag) {
    return new FakeElement(this, tag);
  }

  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(listener);
  }

  loseFocus(element) {
    if (this.activeElement === element) this.activeElement = this.body;
  }
}

// ---- Fake clock ----

class FakeClock {
  constructor(now) {
    this.now = now;
    this.timers = new Map();
    this.nextId = 1;
  }

  setTimeout(callback, delay) {
    const id = this.nextId++;
    this.timers.set(id, { at: this.now + Number(delay || 0), callback, every: null });
    return id;
  }

  setInterval(callback, delay) {
    const id = this.nextId++;
    this.timers.set(id, { at: this.now + Number(delay), callback, every: Number(delay) });
    return id;
  }

  clear(id) {
    this.timers.delete(id);
  }

  // Runs every timer due within ms, in time order, letting promises settle between them.
  async advance(ms) {
    const target = this.now + ms;
    await settle();
    for (;;) {
      let nextId = null;
      for (const [id, timer] of this.timers) {
        if (timer.at <= target && (nextId === null || timer.at < this.timers.get(nextId).at)) nextId = id;
      }
      if (nextId === null) break;
      const timer = this.timers.get(nextId);
      this.now = timer.at;
      if (timer.every) timer.at += timer.every;
      else this.timers.delete(nextId);
      timer.callback();
      await settle();
    }
    this.now = target;
    await settle();
  }
}

// Lets the page's pending promises (file reads, answers) run to their next wait.
async function settle() {
  for (let round = 0; round < 20; round++) await new Promise((resolve) => setImmediate(resolve));
}

// ---- Fake network: every request waits until the scenario answers it ----

class Request {
  constructor(clock, method, url, headers, body) {
    Object.assign(this, { clock, method, url, headers, body });
    this.path = url.startsWith(PAGE_URL) ? url.slice(PAGE_URL.length) : url;
    this.settled = false;
  }

  bodyLength() {
    return typeof this.body === "string" ? this.body.length : 0;
  }

  json() {
    return JSON.parse(this.body);
  }
}

class FetchRequest extends Request {
  constructor(clock, url, init) {
    super(clock, init.method || "GET", url, init.headers || {}, init.body);
    this.promise = new Promise((resolve, reject) => {
      this.resolve = resolve;
      this.reject = reject;
    });
    if (init.signal) {
      init.signal.addEventListener("abort", () => this.fail(new Error("aborted")));
    }
  }

  async respond(status, body) {
    if (this.settled) return;
    this.settled = true;
    const text = typeof body === "string" ? body : JSON.stringify(body);
    this.resolve({ status, ok: status >= 200 && status < 300, text: async () => text });
    await settle();
  }

  async fail(error = new TypeError("Failed to fetch")) {
    if (this.settled) return;
    this.settled = true;
    this.reject(error);
    await settle();
  }
}

class XhrRequest extends Request {
  constructor(xhr) {
    super(xhr.clock, xhr.method, xhr.url, xhr.headers, xhr.sent);
    this.xhr = xhr;
  }

  async uploadProgress() {
    if (this.xhr.upload.onprogress) this.xhr.upload.onprogress();
    await settle();
  }

  async finishUpload() {
    if (this.xhr.upload.onload) this.xhr.upload.onload();
    await settle();
  }

  async respond(status, body) {
    if (this.settled) return;
    this.settled = true;
    this.xhr.status = status;
    this.xhr.responseText = typeof body === "string" ? body : JSON.stringify(body);
    this.xhr.onload();
    await settle();
  }

  async fail() {
    if (this.settled) return;
    this.settled = true;
    this.xhr.onerror();
    await settle();
  }
}

function fakeXhrClass(clock, requests) {
  return class FakeXMLHttpRequest {
    constructor() {
      this.clock = clock;
      this.headers = {};
      this.upload = {};
      this.withCredentials = false;
      this.status = 0;
      this.responseText = "";
    }

    open(method, url) {
      this.method = method;
      this.url = url;
    }

    setRequestHeader(name, value) {
      this.headers[name] = value;
    }

    send(body) {
      this.sent = body;
      this.request = new XhrRequest(this);
      requests.push(this.request);
    }

    abort() {
      if (this.request.settled) return;
      this.request.settled = true;
      this.onabort();
    }
  };
}

class FakeFileReader {
  readAsDataURL(blob) {
    blob.arrayBuffer().then((buffer) => {
      this.result = "data:application/octet-stream;base64," + Buffer.from(buffer).toString("base64");
      this.onload();
    }, (error) => {
      this.error = error;
      this.onerror();
    });
  }
}

// ---- One page ----

class Page {
  constructor({ dryRun = false, reauthenticated = false } = {}) {
    this.clock = new FakeClock(START_TIME);
    this.requests = [];
    this.navigations = [];
    this.document = new FakeDocument({ authDomain: "auth.example", clientId: "client", pageUrl: PAGE_URL, dryRun });
    const storage = new Map([
      ["classPhoto.idToken", "header.payload.signature"],
      ["classPhoto.idTokenExpiry", String(START_TIME + HOUR_MS)],
    ]);
    if (reauthenticated) storage.set("classPhoto.reauthenticated", "1");
    this.storage = storage;
    const clock = this.clock;
    const requests = this.requests;
    const navigations = this.navigations;
    const context = vm.createContext({
      document: this.document,
      window: { location: { search: "", href: PAGE_URL, assign: (url) => navigations.push(url) } },
      history: { replaceState() {} },
      sessionStorage: {
        getItem: (key) => (storage.has(key) ? storage.get(key) : null),
        setItem: (key, value) => storage.set(key, String(value)),
        removeItem: (key) => storage.delete(key),
        clear: () => storage.clear(),
      },
      fetch: (url, init = {}) => {
        const request = new FetchRequest(clock, url, init);
        requests.push(request);
        return request.promise;
      },
      XMLHttpRequest: fakeXhrClass(clock, requests),
      FileReader: FakeFileReader,
      Blob,
      URL: { createObjectURL: () => "blob:fake", revokeObjectURL() {} },
      URLSearchParams,
      AbortController,
      TextDecoder,
      TextEncoder,
      atob,
      btoa,
      // SHA-256 without the thread pool, so a sign-in redirect lands within settle().
      crypto: {
        getRandomValues: (array) => webcrypto.getRandomValues(array),
        subtle: { digest: async (algorithm, data) => new Uint8Array(createHash("sha256").update(data).digest()).buffer },
      },
      setTimeout: (callback, delay) => clock.setTimeout(callback, delay),
      clearTimeout: (id) => clock.clear(id),
      setInterval: (callback, delay) => clock.setInterval(callback, delay),
      clearInterval: (id) => clock.clear(id),
      console,
    });
    vm.runInContext("Date", context).now = () => clock.now;
    vm.runInContext(SCRIPT, context, { filename: "page.html" });
  }

  el(id) {
    return this.document.getElementById(id);
  }

  status(id) {
    return this.el(id).textContent;
  }

  get focused() {
    return this.document.activeElement;
  }

  optionValues() {
    return this.el("class-select").children.map((option) => option.getAttribute("value") ?? option.value);
  }

  // The last request not yet answered.
  pending() {
    const open = this.requests.filter((request) => !request.settled);
    assert.ok(open.length, "a request is waiting for an answer");
    return open[open.length - 1];
  }

  async click(id) {
    this.el(id).click();
    await settle();
  }

  async chooseClass(name) {
    this.el("class-select").value = name;
    this.el("class-select").dispatch("change");
    await settle();
  }

  async choosePhoto(bytes) {
    const input = this.el("photo-input");
    input.files = [photoFile(bytes)];
    input.dispatch("change");
    await settle();
  }

  async dropPhoto(bytes) {
    this.el("drop-zone").dispatch("drop", { dataTransfer: { files: [photoFile(bytes)] } });
    await settle();
  }
}

function photoFile(bytes) {
  return { name: "photo.jpg", type: "image/jpeg", size: bytes.length, arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.length) };
}

function classesAnswer({ names = [CLASS_A, CLASS_B], stale = false, refresh = null, refreshedAt = "2026-10-17T13:42:00Z" } = {}) {
  return {
    dry_run: false,
    classes: names.map((name) => ({ name, file_name: name.toLowerCase().replace(/ /g, "-") + ".jpg", problem: null, warning: null })),
    refreshed_at: refreshedAt,
    stale,
    refresh,
  };
}

const OPENED_ANSWER = {
  action: "opened",
  pull_request: { number: 12, url: "https://github.com/asmbly-makerspace/website/pull/12" },
  file_path: "images/classes/woodshop-safety.jpg",
  warnings: [],
};

// A page whose class list has loaded.
async function loadedPage(options = {}, answer = classesAnswer()) {
  const page = new Page(options);
  await settle();
  await page.pending().respond(200, answer);
  return page;
}

// A page with a class and a photo chosen, ready to submit.
async function readyPage(photo, options = {}) {
  const page = await loadedPage(options);
  await page.chooseClass(CLASS_A);
  await page.choosePhoto(photo);
  assert.equal(page.el("submit").disabled, false, "Submit is enabled with a class and a photo");
  return page;
}

function submissions(page) {
  return page.requests.filter((request) => request.method === "POST");
}

function isBusy(element) {
  return element.getAttribute("aria-busy") === "true";
}

function isUnavailable(button) {
  return button.disabled || button.getAttribute("aria-disabled") === "true";
}

function assertClassListBusy(page, message) {
  const select = page.el("class-select");
  assert.equal(select.disabled, true, "the class list is disabled while it loads");
  assert.ok(isBusy(select), "the class list is marked busy");
  assert.equal(page.el("class-progress").hidden, false, "the progress bar shows");
  assert.equal(page.status("class-status"), message);
}

function assertClassListIdle(page) {
  assert.ok(!isBusy(page.el("class-select")), "aria-busy is removed");
  assert.equal(page.el("class-progress").hidden, true, "the progress bar is hidden");
}

function assertSubmitIdle(page) {
  const result = page.el("result");
  if (!result.hidden) assert.equal(result.busyWhenFilled, null, "the result is filled after aria-busy comes off");
  assert.equal(page.el("submit-progress").hidden, true);
  assert.equal(page.el("submit-elapsed").hidden, true);
  assert.ok(!isBusy(page.el("result")));
  assert.equal(page.status("submit-status"), "");
}

// ---- Scenarios ----

const SCENARIOS = {
  async classes_busy_while_loading() {
    const page = new Page();
    await settle();
    assert.equal(page.pending().path, "/classes");
    assertClassListBusy(page, pageText("LOADING_CLASSES_MESSAGE"));
    assert.equal(page.el("class-retry").hidden, true);
    assert.equal(page.el("class-refresh").hidden, true);
    assert.deepEqual(page.el("class-status").textHistory, [pageText("LOADING_CLASSES_MESSAGE")], "announced once");
  },

  async classes_still_loading_after_5s() {
    const page = new Page();
    await page.clock.advance(4900);
    assert.equal(page.status("class-status"), pageText("LOADING_CLASSES_MESSAGE"));
    await page.clock.advance(100);
    assertClassListBusy(page, pageText("STILL_LOADING_CLASSES_MESSAGE"));
    await page.clock.advance(10000);
    assert.equal(page.el("class-status").textHistory.length, 2, "each message is announced once");
  },

  async classes_failure_shows_try_again() {
    const page = new Page();
    await settle();
    await page.pending().respond(502, { error: pageText("NEON_ERROR") });
    assertClassListIdle(page);
    assert.equal(page.status("class-status"), pageText("NEON_ERROR"));
    assert.ok(page.el("class-status").classList.contains("error"));
    assert.equal(page.el("class-retry").hidden, false);
    assert.equal(isUnavailable(page.el("class-retry")), false, "Try again is enabled");
    assert.equal(page.el("class-select").disabled, true, "an empty list stays disabled");
    assert.equal(page.el("class-refresh").hidden, true);
    // A 502 without a message (API Gateway's own) is the class list's message, not the
    // submission's "may or may not have been opened".
    const gateway = new Page();
    await settle();
    await gateway.pending().respond(502, "<html>Bad gateway</html>");
    assert.equal(gateway.status("class-status"), pageText("NEON_ERROR"));
    assert.equal(gateway.el("class-retry").hidden, false);
  },

  async classes_no_answer_shows_try_again() {
    const page = new Page();
    await page.clock.advance(REQUEST_TIMEOUT_MS - 1);
    assertClassListBusy(page, pageText("STILL_LOADING_CLASSES_MESSAGE"));
    await page.clock.advance(1);
    assertClassListIdle(page);
    assert.equal(page.status("class-status"), pageText("NETWORK_MESSAGE"));
    assert.equal(page.el("class-retry").hidden, false);
  },

  async classes_try_again_reloads_in_place() {
    const page = new Page();
    await settle();
    await page.pending().fail();
    assert.equal(page.status("class-status"), pageText("NETWORK_MESSAGE"));
    const retry = page.el("class-retry");
    retry.focus();
    await page.click("class-retry");
    assert.equal(page.requests.length, 2, "a second GET /classes");
    assert.equal(page.pending().path, "/classes");
    assert.deepEqual(page.navigations, [], "no navigation");
    assertClassListBusy(page, pageText("LOADING_CLASSES_MESSAGE"));
    assert.equal(retry.hidden, false);
    assert.equal(isUnavailable(retry), true, "Try again is unavailable while it loads");
    assert.equal(page.focused, retry, "focus stays on Try again");
    await page.click("class-retry");
    assert.equal(page.requests.length, 2, "a click while loading does nothing");
    await page.pending().respond(200, classesAnswer());
    assertClassListIdle(page);
    assert.deepEqual(page.optionValues(), ["", CLASS_A, CLASS_B], "the options are listed once");
    assert.equal(retry.hidden, true);
    assert.equal(page.el("class-select").disabled, false);
    assert.equal(page.focused, page.el("class-select"), "focus moves to the class list");
  },

  async classes_loaded_shows_time() {
    const page = await loadedPage();
    assertClassListIdle(page);
    assert.equal(page.el("class-select").disabled, false);
    assert.equal(page.status("class-status"), "");
    const freshness = page.el("class-freshness");
    assert.equal(freshness.hidden, false);
    assert.match(freshness.textContent, /^Class list from Neon at .+\.$/);
    assert.ok(!freshness.textContent.includes(pageText("STALE_LIST_MESSAGE")));
    assert.equal(page.focused, page.document.body, "a first load moves no focus");
  },

  async classes_stale_list_says_out_of_date() {
    const page = await loadedPage({}, classesAnswer({ stale: true }));
    const text = page.el("class-freshness").textContent;
    assert.match(text, /^Class list from Neon at /);
    assert.ok(text.endsWith(" " + pageText("STALE_LIST_MESSAGE")), text);
    const missing = await loadedPage({}, classesAnswer({ refreshedAt: "not a time" }));
    assert.equal(missing.el("class-freshness").hidden, true, "no time, no line");
    // A line already shown is emptied too: aria-describedby reads hidden text.
    await page.click("class-refresh");
    await page.pending().respond(200, classesAnswer({ refresh: "refreshed", refreshedAt: "not a time" }));
    assert.equal(page.el("class-freshness").hidden, true);
    assert.equal(page.el("class-freshness").textContent, "");
  },

  async submit_disables_controls_and_shows_steps(photo) {
    const page = await readyPage(photo);
    const submit = page.el("submit");
    submit.focus();
    page.el("submit-status").textHistory = [];
    await page.click("submit");
    assert.ok(isUnavailable(submit), "Submit is unavailable");
    assert.equal(page.focused, submit, "focus stays on Submit");
    assert.equal(page.el("class-select").disabled, true);
    assert.equal(page.el("photo-input").disabled, true);
    assert.ok(isBusy(page.el("result")));
    assert.equal(page.el("submit-progress").hidden, false);
    assert.equal(page.el("submit-elapsed").hidden, false);
    assert.equal(page.status("submit-status"), pageText("SENDING_MESSAGE"));
    const request = page.pending();
    assert.equal(request.method, "POST");
    assert.equal(request.url, PAGE_URL + "/submit");
    assert.equal(request.headers.Authorization, "header.payload.signature");
    assert.equal(request.headers["Content-Type"], "application/json");
    assert.equal(request.xhr.withCredentials, false);
    assert.equal(request.json().class_name, CLASS_A);
    await request.finishUpload();
    assert.equal(page.status("submit-status"), pageText("WAITING_MESSAGE"));
    await page.clock.advance(3000);
    assert.equal(page.status("submit-elapsed"), "3 s");
    assert.ok(!page.el("submit-status").textHistory.some((text) => text.endsWith(" s")), "the seconds aren't announced");
    assert.deepEqual(
      page.el("submit-status").textHistory,
      [pageText("PREPARING_MESSAGE"), pageText("SENDING_MESSAGE"), pageText("WAITING_MESSAGE")],
      "each step is set once",
    );
    await request.respond(200, OPENED_ANSWER);
    assertSubmitIdle(page);
  },

  async submit_dry_run_waiting_step(photo) {
    const page = await readyPage(photo, { dryRun: true });
    await page.click("submit");
    await page.pending().finishUpload();
    assert.equal(page.status("submit-status"), pageText("WAITING_DRY_RUN_MESSAGE"));
  },

  async submit_double_click_sends_once(photo) {
    const page = await readyPage(photo);
    const before = page.status("photo-status");
    await page.click("submit");
    await page.click("submit");
    page.el("submit").dispatch("click");
    await settle();
    await page.dropPhoto(new Uint8Array([1, 2, 3]));
    await page.choosePhoto(new Uint8Array([1, 2, 3]));
    page.el("drop-zone").dispatch("dragover");
    assert.equal(page.el("drop-zone").classList.contains("dragging"), false, "no dragging look while submitting");
    assert.equal(submissions(page).length, 1, "one POST");
    assert.equal(page.status("photo-status"), before, "the photo is unchanged");
    await page.pending().respond(200, OPENED_ANSWER);
    assert.equal(page.el("submit").disabled, false);
  },

  async submit_failure_keeps_class_and_photo(photo) {
    const page = await readyPage(photo);
    await page.click("submit");
    const first = page.pending();
    await first.finishUpload();
    await first.respond(502, { error: pageText("GENERIC_ERROR") });
    assert.equal(page.el("result").hidden, false);
    assert.equal(page.status("result"), pageText("GENERIC_ERROR"));
    assert.equal(page.el("class-select").value, CLASS_A);
    assert.equal(page.el("class-select").disabled, false);
    assert.equal(page.el("photo-input").disabled, false);
    assert.equal(page.el("submit").disabled, false);
    assert.ok(!isUnavailable(page.el("submit")));
    assertSubmitIdle(page);
    await page.click("submit");
    const second = page.pending();
    assert.equal(submissions(page).length, 2, "one click submits again");
    assert.equal(second.json().class_name, CLASS_A);
    assert.equal(second.bodyLength(), first.bodyLength(), "the same photo");
  },

  async submit_gateway_timeout_is_unconfirmed(photo) {
    const page = await readyPage(photo);
    await page.click("submit");
    await page.pending().finishUpload();
    await page.pending().respond(504, { message: "Endpoint request timed out" });
    assert.equal(page.status("result"), pageText("UNCONFIRMED_MESSAGE"));
    const badGateway = await readyPage(photo);
    await badGateway.click("submit");
    await badGateway.pending().respond(502, "<html>Bad gateway</html>");
    assert.equal(badGateway.status("result"), pageText("UNCONFIRMED_MESSAGE"));
  },

  async submit_network_error_is_unconfirmed(photo) {
    const page = await readyPage(photo);
    await page.click("submit");
    await page.pending().finishUpload();
    await page.pending().fail();
    assert.equal(page.status("result"), pageText("UNCONFIRMED_MESSAGE"));
    assert.ok(page.el("result").firstElementChild.classList.contains("error"));
    assert.equal(page.el("submit").disabled, false);
  },

  async submit_timeout_on_dry_run_says_nothing_opened(photo) {
    const page = await readyPage(photo, { dryRun: true });
    await page.click("submit");
    await page.pending().finishUpload();
    await page.clock.advance(REQUEST_TIMEOUT_MS - 1);
    assert.equal(page.el("result").hidden, true, "still waiting");
    await page.clock.advance(1);
    assert.equal(page.status("result"), pageText("DRY_RUN_TIMEOUT_MESSAGE"));
    assertSubmitIdle(page);
    const prod = await readyPage(photo);
    await prod.click("submit");
    await prod.pending().finishUpload();
    await prod.clock.advance(REQUEST_TIMEOUT_MS);
    assert.equal(prod.status("result"), pageText("UNCONFIRMED_MESSAGE"));
  },

  async submit_failure_before_sending_is_network_error(photo) {
    const offline = await readyPage(photo);
    await offline.click("submit");
    await offline.pending().fail();
    assert.equal(offline.status("result"), pageText("NETWORK_MESSAGE"), "the API never ran");
    assertSubmitIdle(offline);
    const stalled = await readyPage(photo);
    await stalled.click("submit");
    await stalled.clock.advance(REQUEST_TIMEOUT_MS);
    assert.equal(stalled.status("result"), pageText("NETWORK_MESSAGE"), "an upload that stalls is given up");
    assert.equal(stalled.el("submit").disabled, false);
  },

  async submit_slow_upload_keeps_waiting(photo) {
    const page = await readyPage(photo);
    await page.click("submit");
    const request = page.pending();
    for (let second = 0; second < 60; second += 10) {
      await page.clock.advance(10 * SECOND_MS);
      await request.uploadProgress();
    }
    assert.equal(page.el("result").hidden, true, "a slow upload that moves is not cut short");
    await request.finishUpload();
    await page.clock.advance(REQUEST_TIMEOUT_MS - 1);
    assert.equal(page.status("submit-status"), pageText("WAITING_MESSAGE"));
    await request.respond(200, OPENED_ANSWER);
    assert.equal(page.el("result").firstElementChild.textContent, "Opened pull request #12");
  },

  async submit_server_says_nothing_changed(photo) {
    const page = await readyPage(photo);
    await page.click("submit");
    await page.pending().finishUpload();
    await page.pending().respond(502, { error: NOTHING_CHANGED });
    assert.equal(page.status("result"), NOTHING_CHANGED);
  },

  async submit_success_shows_result(photo) {
    const page = await readyPage(photo);
    await page.click("submit");
    await page.pending().finishUpload();
    await page.pending().respond(200, OPENED_ANSWER);
    const line = page.el("result").firstElementChild;
    assert.equal(line.textContent, "Opened pull request #12");
    assert.equal(line.firstElementChild.getAttribute("href"), OPENED_ANSWER.pull_request.url);
    assert.equal(page.el("result").hidden, false);
    assertSubmitIdle(page);
  },

  async classes_401_signs_in_again() {
    const page = new Page();
    await settle();
    await page.pending().respond(401, { message: "Unauthorized" });
    assert.equal(page.navigations.length, 1, "one trip to the sign-in");
    assert.ok(page.navigations[0].startsWith("https://auth.example/oauth2/authorize?"), page.navigations[0]);
    assertClassListIdle(page);
    assert.equal(page.el("class-retry").hidden, true);
    // A second 401 in the same tab stops, so the page never loops.
    const again = new Page({ reauthenticated: true });
    await settle();
    await again.pending().respond(401, { message: "Unauthorized" });
    assert.deepEqual(again.navigations, []);
    assert.equal(again.el("sign-in-problem").hidden, false);
    assert.equal(again.el("app").hidden, true);
  },

  async submit_401_signs_in_again(photo) {
    const page = await readyPage(photo);
    await page.click("submit");
    await page.pending().finishUpload();
    await page.pending().respond(401, { message: "Unauthorized" });
    assert.equal(page.navigations.length, 1, "one trip to the sign-in");
    assert.ok(page.navigations[0].startsWith("https://auth.example/oauth2/authorize?"));
    assert.equal(page.el("result").hidden, true, "nothing is rendered");
    assertSubmitIdle(page);
    assert.equal(page.storage.get("classPhoto.reauthenticated"), "1");
  },

  async classes_refresh_button_shown_after_load() {
    const page = new Page();
    await settle();
    assert.equal(page.el("class-refresh").hidden, true, "hidden while loading");
    await page.pending().respond(502, { error: pageText("NEON_ERROR") });
    assert.equal(page.el("class-refresh").hidden, true, "hidden after a failure");
    await page.click("class-retry");
    await page.pending().respond(200, classesAnswer());
    const refresh = page.el("class-refresh");
    assert.equal(refresh.hidden, false, "shown once the list loads");
    assert.equal(refresh.getAttribute("aria-label"), null);
    assert.ok(!isUnavailable(refresh));
  },

  async classes_refresh_reloads_from_neon() {
    const page = await loadedPage();
    const refresh = page.el("class-refresh");
    refresh.focus();
    await page.click("class-refresh");
    const request = page.pending();
    assert.equal(request.method, "GET");
    assert.equal(request.path, "/classes?refresh=1");
    assertClassListBusy(page, pageText("REFRESHING_CLASSES_MESSAGE"));
    assert.ok(isUnavailable(refresh));
    assert.equal(page.focused, refresh, "focus stays on the button");
    await page.click("class-refresh");
    assert.equal(page.requests.length, 2, "a click while refreshing does nothing");
    await page.clock.advance(5000);
    assert.equal(page.status("class-status"), pageText("STILL_LOADING_CLASSES_MESSAGE"));
    await request.respond(200, classesAnswer({ names: [CLASS_A, CLASS_B, CLASS_C], refresh: "refreshed", refreshedAt: "2026-10-17T14:00:05Z" }));
    assertClassListIdle(page);
    assert.equal(page.status("class-status"), pageText("REFRESHED_MESSAGE"));
    assert.ok(!page.el("class-status").classList.contains("error"));
    assert.deepEqual(page.optionValues(), ["", CLASS_A, CLASS_B, CLASS_C]);
    assert.match(page.el("class-freshness").textContent, /^Class list from Neon at /);
    assert.ok(!isUnavailable(refresh));
    assert.equal(page.focused, refresh, "focus is still on the button");
    assert.deepEqual(page.navigations, []);
  },

  async classes_refresh_too_soon_says_so() {
    const page = await loadedPage();
    await page.click("class-refresh");
    await page.pending().respond(200, classesAnswer({ names: [CLASS_B], refresh: "too_soon" }));
    assert.equal(page.status("class-status"), pageText("REFRESH_TOO_SOON_MESSAGE"));
    assert.deepEqual(page.optionValues(), ["", CLASS_B], "the list is the answer's");
    await page.click("class-refresh");
    await page.pending().respond(200, classesAnswer({ refresh: "constructor" }));
    assert.equal(page.status("class-status"), "", "an outcome the page doesn't know says nothing");
    assert.ok(!isUnavailable(page.el("class-refresh")));
  },

  async classes_refresh_failed_keeps_list() {
    const page = await loadedPage();
    await page.click("class-refresh");
    await page.pending().respond(200, classesAnswer({ stale: true, refresh: "failed" }));
    assert.equal(page.status("class-status"), pageText("REFRESH_FAILED_MESSAGE"));
    assert.ok(page.el("class-status").classList.contains("error"));
    assert.ok(page.el("class-freshness").textContent.endsWith(pageText("STALE_LIST_MESSAGE")));

    const empty = await loadedPage();
    await empty.click("class-refresh");
    await empty.pending().respond(200, classesAnswer({ names: [], refresh: "failed", refreshedAt: "2026-10-17T14:00:30Z" }));
    assert.deepEqual(empty.optionValues(), ["", CLASS_A, CLASS_B], "an empty failed answer keeps the list");
    assert.equal(empty.status("class-status"), pageText("REFRESH_FAILED_MESSAGE"));
    assert.equal(empty.el("class-freshness").textContent, page.el("class-freshness").textContent.replace(" " + pageText("STALE_LIST_MESSAGE"), ""), "and its time");

    const noCopy = await loadedPage();
    await noCopy.click("class-refresh");
    await noCopy.pending().respond(502, { error: pageText("NEON_ERROR") });
    assert.equal(noCopy.status("class-status"), pageText("NEON_ERROR"));
    assert.ok(noCopy.el("class-status").classList.contains("error"));
    assert.deepEqual(noCopy.optionValues(), ["", CLASS_A, CLASS_B], "the earlier options stay");
    assert.equal(noCopy.el("class-select").disabled, false, "and can be chosen");
    assert.ok(!isUnavailable(noCopy.el("class-refresh")));
    assert.equal(noCopy.el("class-retry").hidden, true, "a failed refresh doesn't offer Try again");
    await noCopy.chooseClass(CLASS_B);
    assert.equal(noCopy.el("class-select").value, CLASS_B);
  },

  async classes_refresh_keeps_chosen_class(photo) {
    const page = await readyPage(photo);
    await page.click("class-refresh");
    assert.equal(page.el("submit").disabled, true, "no submission while the list refreshes");
    await page.pending().respond(200, classesAnswer({ names: [CLASS_C, CLASS_A], refresh: "refreshed" }));
    assert.equal(page.el("class-select").value, CLASS_A, "still listed: still chosen");
    assert.equal(page.el("submit").disabled, false);
    await page.click("class-refresh");
    await page.pending().respond(200, classesAnswer({ names: [CLASS_C], refresh: "refreshed" }));
    assert.equal(page.el("class-select").value, "", "gone: back to the placeholder");
    assert.equal(page.el("submit").disabled, true);
  },

  async submit_disables_refresh(photo) {
    const page = await readyPage(photo);
    await page.click("submit");
    assert.ok(isUnavailable(page.el("class-refresh")), "Refresh is unavailable while submitting");
    await page.click("class-refresh");
    page.el("class-refresh").dispatch("click");
    await settle();
    assert.equal(page.requests.filter((request) => request.path.startsWith("/classes")).length, 1, "a click sends nothing");
    await page.pending().respond(200, OPENED_ANSWER);
    assert.ok(!isUnavailable(page.el("class-refresh")));
  },
};

async function main(argv) {
  if (argv[0] === "--list") {
    console.log(Object.keys(SCENARIOS).join("\n"));
    return 0;
  }
  const [name, photoPath] = argv;
  const scenario = SCENARIOS[name];
  if (!scenario || !photoPath) {
    console.error(`usage: page_script_harness.mjs <scenario> <jpeg path> | --list (unknown scenario ${name})`);
    return 2;
  }
  await scenario(new Uint8Array(readFileSync(photoPath)));
  return 0;
}

main(process.argv.slice(2)).then(
  (code) => process.exit(code),
  (error) => {
    console.error(error && error.stack ? error.stack : error);
    process.exit(1);
  },
);
