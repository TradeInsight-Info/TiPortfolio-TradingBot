import { StrictMode } from "react"
import { createRoot, hydrateRoot } from "react-dom/client"
import App from "./App.jsx"
import "./index.css"

const root = document.getElementById("root")

// Use hydrateRoot when the server has pre-rendered content (SSG build),
// createRoot in dev where the div is empty.
if (root.hasChildNodes()) {
  hydrateRoot(root, <StrictMode><App /></StrictMode>)
} else {
  createRoot(root).render(<StrictMode><App /></StrictMode>)
}
