import { BrowserRouter, Navigate, Routes, Route } from "react-router-dom";
import { Layout } from "./components/Layout";
import { UploadPage } from "./pages/UploadPage";
import { TranslatePage } from "./pages/TranslatePage";
import { PreviewPage } from "./pages/PreviewPage";
import { HistoryPage } from "./pages/HistoryPage";
import { ProvidersPage } from "./pages/ProvidersPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<UploadPage />} />
          <Route path="/translate/:bookId" element={<TranslatePage />} />
          <Route path="/preview/:bookId" element={<PreviewPage />} />
          <Route path="/library" element={<HistoryPage />} />
          <Route path="/providers" element={<ProvidersPage />} />
          {/* old addresses */}
          <Route path="/history" element={<Navigate to="/library" replace />} />
          <Route path="/settings" element={<Navigate to="/providers" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
