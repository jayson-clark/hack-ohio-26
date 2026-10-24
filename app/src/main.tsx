import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import Console from "./console/Console";
import Control from "./control/Control";
import Projector from "./projector/Projector";

// One bundle, three windows: the operator's console (the product), exercise
// control (stands in for the real world: fire, weather, the table) and the
// projector. ?view= picks one; the console is the default.
const view = new URLSearchParams(window.location.search).get("view");

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    {view === "projector" ? <Projector /> : view === "control" ? <Control /> : <Console />}
  </React.StrictMode>,
);
