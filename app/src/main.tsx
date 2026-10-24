import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import Console from "./console/Console";
import Projector from "./projector/Projector";

// One bundle, two windows: ?view=projector picks the projector view.
const view = new URLSearchParams(window.location.search).get("view");

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>{view === "projector" ? <Projector /> : <Console />}</React.StrictMode>,
);
