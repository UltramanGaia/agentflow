import { Suspense, lazy, type ReactNode } from "react";
import { Navigate, RouterProvider, createBrowserRouter } from "react-router-dom";
import { AppShell } from "../components/layout/AppShell";
import { LoadingState } from "../components/feedback/States";

const RunsPage = lazy(() => import("../pages/runs/RunsPage").then((module) => ({ default: module.RunsPage })));
const RunDetailPage = lazy(() =>
  import("../pages/run-detail/RunDetailPage").then((module) => ({ default: module.RunDetailPage })),
);

function withSuspense(element: ReactNode) {
  return <Suspense fallback={<LoadingState>Loading page...</LoadingState>}>{element}</Suspense>;
}

const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/runs" replace /> },
      { path: "runs", element: withSuspense(<RunsPage />) },
      { path: "runs/:runId", element: withSuspense(<RunDetailPage />) },
      { path: "graphs", element: <Navigate to="/runs" replace /> },
      { path: "graphs/:graphId/edit", element: <Navigate to="/runs" replace /> },
      { path: "*", element: <Navigate to="/runs" replace /> },
    ],
  },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
