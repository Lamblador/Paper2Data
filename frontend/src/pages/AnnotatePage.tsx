import { Link } from "react-router-dom";

/** Устаревшая страница: разметка перенесена в рабочее место статьи. */
export default function AnnotatePage() {
  return (
    <section className="panel">
      <h1>Разметка</h1>
      <p>
        PDF, граф, извлечение и очередь проверки объединены в{" "}
        <strong>рабочем месте статьи</strong>.
      </p>
      <p className="muted">
        Откройте статью → вкладки «Граф», «Извлечение», «Проверка». Редактор
        рецепта — в меню «Рецепты».
      </p>
      <div className="row">
        <Link className="btn" to="/papers">
          К списку статей
        </Link>
        <Link className="btn secondary" to="/recipes">
          Редактор рецептов
        </Link>
      </div>
    </section>
  );
}
