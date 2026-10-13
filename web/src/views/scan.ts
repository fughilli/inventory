import { scanBinCode } from "../components";
import { append, h } from "../dom";
import { navigate, type View } from "../router";

export const scanView: View = async (root) => {
  const again = h("button", { class: "btn primary big", onclick: () => void go() }, "Scan a bin label");
  append(root, h("h1", null, "Scan"), h("p", null, "Scan a bin's label to see what's inside. Your phone's camera app works too: the QR opens this app."), again);
  async function go() {
    const code = await scanBinCode();
    if (code) navigate(`/b/${code}`, true);
  }
  void go();
};
