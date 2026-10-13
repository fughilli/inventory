import "@fontsource/barlow/400.css";
import "@fontsource/barlow/500.css";
import "@fontsource/barlow/600.css";
import "@fontsource/barlow-condensed/600.css";
import "@fontsource/barlow-condensed/800.css";
import "./style.css";

import { pickPhoto } from "./camera";
import { binChip, h } from "./dom";
import { navigate, route, startRouter } from "./router";
import { onChange, refreshStatus, setPacking, state } from "./state";
import { addView } from "./views/add";
import { binView } from "./views/bin";
import { binsView } from "./views/bins";
import { cameraIcon, homeView } from "./views/home";
import { groupsView } from "./views/groups";
import { itemView } from "./views/item";
import { returnsView } from "./views/returns";
import { scanView } from "./views/scan";
import { settingsView } from "./views/settings";

route("/", homeView);
route("/add", addView);
route("/item/:id", itemView);
route("/bins", binsView);
route("/b/:code", binView);
route("/return", returnsView);
route("/groups", groupsView);
route("/scan", scanView);
route("/settings", settingsView);

const app = document.getElementById("app")!;

const packBanner = h("div", { class: "pack-banner", hidden: true, role: "status" });
const badge = h("span", { class: "badge", hidden: true });

function navLink(href: string, label: string, extra?: Node) {
  return h("a", { href, "data-link": true, class: "nav-link" }, h("span", null, label), extra ?? null);
}

const addBtn = h("button", {
  class: "nav-add",
  "aria-label": "Add an item (opens the camera)",
  onclick: async () => {
    // pickPhoto must run inside this tap so the browser allows the camera.
    const f = await pickPhoto();
    if (f) {
      state.pendingPhoto = f;
      navigate("/add");
    }
  },
}, cameraIcon(), h("span", null, "Add"));

const nav = h("nav", { class: "tabbar", "aria-label": "Main" },
  navLink("/", "Find"),
  navLink("/bins", "Bins"),
  addBtn,
  navLink("/scan", "Scan"),
  navLink("/return", "Check in", badge));

const header = h("header", { class: "topbar" },
  h("a", { href: "/", "data-link": true, class: "brand" }, "Garage"),
  h("a", { href: "/settings", "data-link": true, class: "topbar-link" }, "System"));

document.body.prepend(header, packBanner);
document.body.append(nav);

function paint() {
  if (state.packing) {
    packBanner.hidden = false;
    packBanner.replaceChildren(
      h("span", null, "Packing into ", binChip(state.packing)),
      h("button", { class: "btn small", onclick: () => setPacking(null) }, "Stop"));
  } else {
    packBanner.hidden = true;
  }
  badge.hidden = !state.checkedOut;
  badge.textContent = String(state.checkedOut);
}
onChange(paint);
paint();

startRouter(app, (path) => {
  nav.querySelectorAll("a.nav-link").forEach((a) => {
    const href = a.getAttribute("href")!;
    const active = href === "/" ? path === "/" : path.startsWith(href) || (href === "/bins" && path.startsWith("/b/"));
    if (active) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
});

void refreshStatus();
document.addEventListener("visibilitychange", () => document.visibilityState === "visible" && void refreshStatus());

if ("serviceWorker" in navigator && import.meta.env.PROD) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
