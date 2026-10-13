// Minimal DOM helpers — no framework; each view renders into a container.

export type Child = Node | string | number | null | undefined | false | Child[];
type Attrs = Record<string, unknown> & { class?: string };

export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Attrs | null = null,
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k.startsWith("on") && typeof v === "function") {
        el.addEventListener(k.slice(2).toLowerCase(), v as EventListener);
      } else if (k === "class") {
        el.className = String(v);
      } else if (k === "style" && typeof v === "object") {
        Object.assign(el.style, v);
      } else if (k in el && typeof v !== "string") {
        (el as unknown as Record<string, unknown>)[k] = v;
      } else {
        el.setAttribute(k, v === true ? "" : String(v));
      }
    }
  }
  append(el, ...children);
  return el;
}

function nodes(children: Child[]): (Node | string)[] {
  const out: (Node | string)[] = [];
  const walk = (c: Child) => {
    if (c === null || c === undefined || c === false) return;
    if (Array.isArray(c)) c.forEach(walk);
    else out.push(c instanceof Node ? c : String(c));
  };
  children.forEach(walk);
  return out;
}

/** Element.append / replaceChildren that skip null/false and flatten arrays. */
export function append(el: Element, ...children: Child[]): void {
  el.append(...nodes(children));
}

export function replace(el: Element, ...children: Child[]): void {
  el.replaceChildren(...nodes(children));
}

let toastTimer: number | undefined;
export function toast(msg: string, kind: "ok" | "err" = "ok"): void {
  let t = document.getElementById("toast");
  if (!t) {
    t = h("div", { id: "toast", role: "status", "aria-live": "polite" });
    document.body.append(t);
  }
  t.textContent = msg;
  t.className = `toast show ${kind}`;
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => t?.classList.remove("show"), kind === "err" ? 5000 : 2600);
}

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** Bottom sheet. Resolves when closed; `close` lets content dismiss it. */
export function sheet(title: string, build: (close: () => void) => Node): Promise<void> {
  return new Promise((resolve) => {
    const prevFocus = document.activeElement as HTMLElement | null;
    const close = () => {
      wrap.classList.remove("open");
      window.setTimeout(() => wrap.remove(), 200);
      document.removeEventListener("keydown", onKey);
      prevFocus?.focus();
      resolve();
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    const panel = h(
      "div",
      { class: "sheet", role: "dialog", "aria-modal": "true", "aria-label": title },
      h("div", { class: "sheet-head" }, h("h2", null, title), h("button", { class: "icon-btn", onclick: close, "aria-label": "Close" }, "✕")),
      build(close),
    );
    const wrap = h("div", { class: "sheet-wrap", onclick: (e: Event) => e.target === wrap && close() }, panel);
    document.body.append(wrap);
    document.addEventListener("keydown", onKey);
    requestAnimationFrame(() => {
      wrap.classList.add("open");
      panel.querySelector<HTMLElement>("input, button:not(.icon-btn)")?.focus();
    });
  });
}

export function confirmSheet(title: string, body: string, action: string, danger = false): Promise<boolean> {
  let ok = false;
  return sheet(title, (close) =>
    h(
      "div",
      { class: "stack" },
      h("p", null, body),
      h("button", { class: danger ? "btn danger" : "btn primary", onclick: () => ((ok = true), close()) }, action),
      h("button", { class: "btn", onclick: close }, "Cancel"),
    ),
  ).then(() => ok);
}

/** A bin code rendered as a tiny thermal label — the app's recurring motif. */
export function binChip(code: string | null, opts: { href?: boolean; big?: boolean } = {}): HTMLElement {
  if (!code) return h("span", { class: "chip none" }, "No bin");
  const cls = `chip${opts.big ? " big" : ""}`;
  return opts.href === false
    ? h("span", { class: cls }, code)
    : h("a", { class: cls, href: `/b/${code}`, "data-link": true }, code);
}

export function relTime(iso: string | null): string {
  if (!iso) return "";
  const s = (Date.now() - Date.parse(iso)) / 1000;
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400 * 1.5) return `${Math.round(s / 3600)} h ago`;
  const d = Math.round(s / 86400);
  return d < 45 ? `${d} days ago` : new Date(iso).toLocaleDateString();
}
