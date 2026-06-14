import { createCliRenderer } from "@opentui/core";
import { createRoot } from "@opentui/react";

import { App } from "./App";

const renderer = await createCliRenderer({
  screenMode: "alternate-screen",
  backgroundColor: "#0d0f14",
  consoleMode: "disabled",
  exitOnCtrlC: true,
  useMouse: true,
  targetFps: 30,
});

createRoot(renderer).render(<App />);