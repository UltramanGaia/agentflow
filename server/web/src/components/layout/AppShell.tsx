import { Outlet } from "react-router-dom";
import { ToastRegion } from "../feedback/ToastRegion";

export function AppShell() {
  return (
    <div className="shell">
      <div className="shell-frame">
        <main className="shell-content shell-content-plain">
          <Outlet />
        </main>
      </div>
      <ToastRegion />
    </div>
  );
}
