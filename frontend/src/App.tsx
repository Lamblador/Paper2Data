import { NavLink, Route, Routes } from "react-router-dom";
import { useProject } from "./store/project";
import ProjectsPage from "./pages/ProjectsPage";
import SettingsPage from "./pages/SettingsPage";
import PapersPage from "./pages/PapersPage";
import PaperWorkspacePage from "./pages/PaperWorkspacePage";
import SchemaPage from "./pages/SchemaPage";
import AnnotatePage from "./pages/AnnotatePage";
import RecipePage from "./pages/RecipePage";
import BatchPage from "./pages/BatchPage";

export default function App() {
  const { project } = useProject();

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">P2D</span>
          <div>
            <div className="brand-title">Paper2Data</div>
            <div className="brand-sub">
              {project ? project.name : "Проект не открыт"}
            </div>
          </div>
        </div>
        <nav className="nav">
          <NavLink to="/" end>
            Проекты
          </NavLink>
          <NavLink to="/papers">Статьи</NavLink>
          <NavLink to="/schema">Схема</NavLink>
          <NavLink to="/recipes">Рецепты</NavLink>
          <NavLink to="/annotate">Разметка</NavLink>
          <NavLink to="/batch">Пакет</NavLink>
          <NavLink to="/settings">Настройки</NavLink>
        </nav>
      </header>
      <main className="content wide">
        <Routes>
          <Route path="/" element={<ProjectsPage />} />
          <Route path="/papers" element={<PapersPage />} />
          <Route path="/papers/:paperId" element={<PaperWorkspacePage />} />
          <Route path="/schema" element={<SchemaPage />} />
          <Route path="/recipes" element={<RecipePage />} />
          <Route path="/annotate" element={<AnnotatePage />} />
          <Route path="/batch" element={<BatchPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}
