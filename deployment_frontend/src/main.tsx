import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { ErrorScreen, LoadingScreen, Root, rootLoader } from "./routes/root";
import { Explore } from "./routes/explore";
import { Watch } from "./routes/watch";
import "./styles.css";

const router = createBrowserRouter([
  {
    id: "root",
    path: "/",
    loader: rootLoader,
    // Selecting an event or switching camera changes only search params; reuse the loaded run.
    shouldRevalidate: ({ currentUrl, nextUrl, defaultShouldRevalidate }) =>
      currentUrl.search !== nextUrl.search ? false : defaultShouldRevalidate,
    Component: Root,
    HydrateFallback: LoadingScreen,
    ErrorBoundary: ErrorScreen,
    children: [
      { index: true, Component: Explore },
      { path: "watch", Component: Watch },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode><RouterProvider router={router} /></StrictMode>,
);
