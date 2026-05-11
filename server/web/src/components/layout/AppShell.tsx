import { NavLink, Outlet, useLocation } from "react-router-dom";
import { ToastRegion } from "../feedback/ToastRegion";

function navClass({ isActive }: { isActive: boolean }) {
  return `nav-link${isActive ? " active" : ""}`;
}

function getContextLine(pathname: string) {
  if (pathname.startsWith("/runs/")) {
    return "Operations / Run detail";
  }
  if (pathname === "/runs") {
    return "Operations / Runs";
  }
  if (pathname.startsWith("/graphs/new")) {
    return "Authoring / New graph";
  }
  if (pathname.startsWith("/graphs/") && pathname.endsWith("/edit")) {
    return "Authoring / Graph editor";
  }
  if (pathname === "/graphs") {
    return "Authoring / Graphs";
  }
  return "Operations";
}

export function AppShell() {
  const location = useLocation();

  return (
    <div className="shell">
      <div className="shell-frame">
        <aside className="sidebar">
          <div className="brand-block">
            <div className="brand-mark">AF</div>
            <div className="brand-copy">
              <strong>AgentFlow</strong>
              <span>Operational control plane</span>
            </div>
          </div>
          <nav className="nav nav-stack">
            <NavLink className={navClass} to="/runs">
              Runs
            </NavLink>
            <NavLink className={navClass} to="/graphs">
              Graphs
            </NavLink>
            <NavLink className={navClass} to="/graphs/new/edit">
              New Graph
            </NavLink>
          </nav>
          <div className="sidebar-context">
            <span className="field-label">Workspace</span>
            <strong>server-web-frontend</strong>
            <span>{getContextLine(location.pathname)}</span>
          </div>
        </aside>
        <div className="shell-main">
          <header className="shell-topbar">
            <div>
              <div className="field-label">Context</div>
              <strong>{getContextLine(location.pathname)}</strong>
            </div>
          </header>
          <main className="shell-content">
            <Outlet />
          </main>
        </div>
      </div>
      <ToastRegion />
    </div>
  );
}
