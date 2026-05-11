import { NavLink, Outlet } from "react-router-dom";

function navClass({ isActive }: { isActive: boolean }) {
  return `nav-link${isActive ? " active" : ""}`;
}

export function AppShell() {
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          AgentFlow
          <small>server control plane</small>
        </div>
        <nav className="nav">
          <NavLink className={navClass} to="/runs">
            Runs
          </NavLink>
          <NavLink className={navClass} to="/graphs/new/edit">
            New Graph
          </NavLink>
        </nav>
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
