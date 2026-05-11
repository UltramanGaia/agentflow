import { Navigate, RouterProvider, createBrowserRouter } from "react-router-dom";
import { AppShell } from "../components/layout/AppShell";
import { GraphEditorPage } from "../pages/graph-editor/GraphEditorPage";
import { RunDetailPage } from "../pages/run-detail/RunDetailPage";
import { RunsPage } from "../pages/runs/RunsPage";

const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/runs" replace /> },
      { path: "runs", element: <RunsPage /> },
      { path: "runs/:runId", element: <RunDetailPage /> },
      { path: "graphs/:graphId/edit", element: <GraphEditorPage /> },
      { path: "*", element: <Navigate to="/runs" replace /> },
    ],
  },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
