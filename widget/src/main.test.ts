import { expect, it } from "vitest";
import { widgetVersion } from "./main";
it("exports the foundation version", () => {
  expect(widgetVersion).toBe("0.1.0");
});
