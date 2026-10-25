import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { setEntryTitles } from "./lib/markdown";
import { connect, getState } from "./lib/store";
import { trackVisits } from "./views/Dashboard";
import "./styles.css";

setEntryTitles((id) => getState().entries.find((e) => e.id === id)?.title);
trackVisits();
connect();
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
