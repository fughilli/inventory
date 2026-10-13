// History-API router. Links with data-link are intercepted; QR codes point at
// real URLs (/b/B007) which the server answers with the app shell.

export type View = (root: HTMLElement, params: Record<string, string>, query: URLSearchParams) =>
  void | (() => void) | Promise<void | (() => void)>;

interface Route {
  re: RegExp;
  keys: string[];
  view: View;
}

const routes: Route[] = [];
let cleanup: (() => void) | void;
let root: HTMLElement;
let onNavigate: (path: string) => void = () => {};

export function route(pattern: string, view: View): void {
  const keys: string[] = [];
  const re = new RegExp(
    "^" + pattern.replace(/:(\w+)/g, (_, k: string) => (keys.push(k), "([^/]+)")) + "/?$",
  );
  routes.push({ re, keys, view });
}

export function navigate(to: string, replace = false): void {
  if (replace) history.replaceState(null, "", to);
  else history.pushState(null, "", to);
  void render();
}

export async function render(): Promise<void> {
  const path = location.pathname;
  if (typeof cleanup === "function") cleanup();
  cleanup = undefined;
  onNavigate(path);
  for (const r of routes) {
    const m = path.match(r.re);
    if (!m) continue;
    const params: Record<string, string> = {};
    r.keys.forEach((k, i) => (params[k] = decodeURIComponent(m[i + 1] ?? "")));
    const container = document.createElement("main");
    container.className = "view";
    root.replaceChildren(container);
    window.scrollTo(0, 0);
    cleanup = await r.view(container, params, new URLSearchParams(location.search));
    container.querySelector<HTMLElement>("h1")?.setAttribute("tabindex", "-1");
    return;
  }
  navigate("/", true);
}

export function startRouter(el: HTMLElement, navHook: (path: string) => void): void {
  root = el;
  onNavigate = navHook;
  window.addEventListener("popstate", () => void render());
  document.addEventListener("click", (e) => {
    const a = (e.target as Element).closest?.("a[data-link]") as HTMLAnchorElement | null;
    if (!a || e.metaKey || e.ctrlKey || e.shiftKey || a.target) return;
    e.preventDefault();
    navigate(a.getAttribute("href")!);
  });
  void render();
}
