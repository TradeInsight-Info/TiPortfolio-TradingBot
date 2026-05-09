import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import BenchmarkPage from "./pages/BenchmarkPage";
import DeltaPage from "./pages/DeltaPage";
import HomePage from "./pages/HomePage";

// Active link styling helper
const navClass = ({ isActive }) =>
  isActive ? "font-semibold text-primary underline" : "text-base-content";

function App() {

  return (
    <>
      <BrowserRouter>
        {/* Top navigation bar */}
        <nav className="navbar bg-base-100 shadow px-6 gap-4">
          <NavLink to="/" className="text-xl font-bold mr-6" style={{ textDecoration: "none" }}>
            TradeInsight
          </NavLink>
          <NavLink to="/delta" className={navClass}>
            Trade Records
          </NavLink>
          <NavLink to="/benchmark" className={navClass}>
            Performance
          </NavLink>
        </nav>

        <Routes>
          {/* Default route redirects to /delta */}
          <Route path="/" element={<HomePage />} />
          <Route path="/benchmark" element={<BenchmarkPage />} />
          <Route path="/delta" element={<DeltaPage />} />
        </Routes>
      </BrowserRouter>
    </>
  )
}

export default App
