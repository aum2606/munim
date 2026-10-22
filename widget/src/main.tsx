import { render } from "preact";
import { useState } from "preact/hooks";
import { Widget } from "./Widget";
import { en } from "./i18n";
import { styles } from "./styles";
export { WidgetClient } from "./client";
export const widgetVersion = "0.2.0";
export function mountWidget(publicKey: string, apiBase: string) {
  const host = document.createElement("div");
  host.setAttribute("data-munim-widget", "");
  document.body.appendChild(host);
  const shadow = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = styles;
  shadow.appendChild(style);
  const root = document.createElement("div");
  shadow.appendChild(root);
  render(<Widget publicKey={publicKey} apiBase={apiBase} />, root);
  return () => {
    render(null, root);
    host.remove();
  };
}
function Preview() {
  const params = new URLSearchParams(location.search);
  const [key, setKey] = useState(params.get("key") || "");
  const [active, setActive] = useState(false);
  return (
    <main
      style={{ fontFamily: "system-ui", padding: "24px", maxWidth: "500px" }}
    >
      <h1>{en.preview}</h1>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setActive(true);
        }}
      >
        <label>
          {en.key}
          <input
            value={key}
            onInput={(event) => setKey(event.currentTarget.value)}
            required
            minLength={20}
          />
        </label>
        <button>{en.open}</button>
      </form>
      {active && (
        <Widget
          publicKey={key}
          apiBase={params.get("api") || "http://localhost:18000"}
          initiallyOpen
        />
      )}
    </main>
  );
}
const script = document.currentScript as HTMLScriptElement | null;
if (script?.dataset.key)
  mountWidget(
    script.dataset.key,
    script.dataset.api || new URL(script.src).origin,
  );
else if (import.meta.env.DEV && document.getElementById("root"))
  render(<Preview />, document.getElementById("root")!);
