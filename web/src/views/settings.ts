import { api } from "../api";
import { spinner } from "../components";
import { append, errorText, h, replace } from "../dom";
import type { View } from "../router";

export const settingsView: View = async (root) => {
  append(root, h("h1", null, "System"), spinner());
  try {
    const s = await api.status(true);
    const ok = (b: boolean | undefined) => h("span", { class: b ? "ok" : "bad" }, b ? "On" : "Off");
    const p = s.printer;
    replace(root, 
      h("h1", null, "System"),
      h("dl", { class: "facts" },
        h("dt", null, "Items"), h("dd", null, String(s.items)),
        h("dt", null, "Bins"), h("dd", null, String(s.bins)),
        h("dt", null, "Checked out"), h("dd", null, String(s.checked_out)),
        h("dt", null, "Not in a bin"), h("dd", null, String(s.unbinned)),
        h("dt", null, "Google reverse image search"), h("dd", null, ok(s.identify.google)),
        h("dt", null, "Claude identification"), h("dd", null, ok(s.identify.claude)),
        h("dt", null, "Visual search model"), h("dd", null, s.embedder),
        h("dt", null, "Label printer"),
        h("dd", null, !p?.reachable ? h("span", { class: "bad" }, `Print service unreachable${p?.error ? ` (${p.error})` : ""}`)
          : p.present ? h("span", { class: "ok" }, `Connected (${p.device})`) : h("span", { class: "bad" }, "Print service up, printer not plugged in"))),
      h("p", { class: "muted small" }, "Keys and printer settings live on the server; see the README."),
    );
  } catch (e) {
    replace(root, h("h1", null, "System"), h("p", { class: "error" }, errorText(e)));
  }
};
