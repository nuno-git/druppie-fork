"""LLM Service for code generation."""

import os
import json
from pathlib import Path
from typing import Any, Optional
from flask import current_app


class LLMService:
    """Service for LLM-based code generation."""

    def __init__(self):
        self.workspace_path = None

    def get_workspace_path(self) -> Path:
        """Get the workspace path from config."""
        if self.workspace_path is None:
            self.workspace_path = Path(
                current_app.config.get("WORKSPACE_PATH", "/app/workspace")
            )
        return self.workspace_path

    def analyze_request(self, message: str) -> dict[str, Any]:
        """Analyze user request and determine what to build."""
        message_lower = message.lower()

        # Detect app type from message
        if "todo" in message_lower:
            return {
                "app_type": "todo",
                "name": "todo-app",
                "description": "A simple todo application",
                "features": ["add tasks", "mark complete", "delete tasks"],
            }
        elif "calculator" in message_lower:
            return {
                "app_type": "calculator",
                "name": "calculator-app",
                "description": "A simple calculator application",
                "features": ["basic math operations"],
            }
        elif "blog" in message_lower:
            return {
                "app_type": "blog",
                "name": "blog-app",
                "description": "A simple blog application",
                "features": ["create posts", "view posts", "delete posts"],
            }
        else:
            return {
                "app_type": "generic",
                "name": "my-app",
                "description": message,
                "features": [],
            }

    def generate_app(self, plan_id: str, app_info: dict[str, Any]) -> dict[str, Any]:
        """Generate application files based on the analyzed request."""
        workspace = self.get_workspace_path() / plan_id
        workspace.mkdir(parents=True, exist_ok=True)

        app_type = app_info.get("app_type", "generic")
        files_created = []

        if app_type == "todo":
            files_created = self._generate_todo_app(workspace, app_info)
        elif app_type == "calculator":
            files_created = self._generate_calculator_app(workspace, app_info)
        elif app_type == "blog":
            files_created = self._generate_blog_app(workspace, app_info)
        else:
            files_created = self._generate_generic_app(workspace, app_info)

        return {
            "success": True,
            "workspace": str(workspace),
            "files_created": files_created,
            "app_info": app_info,
        }

    def _generate_todo_app(self, workspace: Path, app_info: dict) -> list[str]:
        """Generate a complete todo application."""
        files = []

        # Create directory structure
        (workspace / "src").mkdir(exist_ok=True)
        (workspace / "public").mkdir(exist_ok=True)

        # package.json
        package_json = {
            "name": "todo-app",
            "version": "1.0.0",
            "description": "A simple todo application",
            "scripts": {
                "dev": "vite",
                "build": "vite build",
                "preview": "vite preview"
            },
            "dependencies": {
                "react": "^18.2.0",
                "react-dom": "^18.2.0"
            },
            "devDependencies": {
                "@vitejs/plugin-react": "^4.2.0",
                "vite": "^5.0.0"
            }
        }
        (workspace / "package.json").write_text(json.dumps(package_json, indent=2))
        files.append("package.json")

        # vite.config.js
        vite_config = """import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
})
"""
        (workspace / "vite.config.js").write_text(vite_config)
        files.append("vite.config.js")

        # index.html
        index_html = """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Todo App</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
"""
        (workspace / "index.html").write_text(index_html)
        files.append("index.html")

        # src/main.jsx
        main_jsx = """import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
"""
        (workspace / "src" / "main.jsx").write_text(main_jsx)
        files.append("src/main.jsx")

        # src/App.jsx
        app_jsx = """import { useState } from 'react'

function App() {
  const [todos, setTodos] = useState([])
  const [input, setInput] = useState('')

  const addTodo = (e) => {
    e.preventDefault()
    if (input.trim()) {
      setTodos([...todos, { id: Date.now(), text: input, completed: false }])
      setInput('')
    }
  }

  const toggleTodo = (id) => {
    setTodos(todos.map(todo =>
      todo.id === id ? { ...todo, completed: !todo.completed } : todo
    ))
  }

  const deleteTodo = (id) => {
    setTodos(todos.filter(todo => todo.id !== id))
  }

  return (
    <div className="app">
      <h1>📝 Todo App</h1>

      <form onSubmit={addTodo} className="add-form">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="What needs to be done?"
        />
        <button type="submit">Add</button>
      </form>

      <ul className="todo-list">
        {todos.map(todo => (
          <li key={todo.id} className={todo.completed ? 'completed' : ''}>
            <span onClick={() => toggleTodo(todo.id)}>
              {todo.completed ? '✅' : '⬜'} {todo.text}
            </span>
            <button onClick={() => deleteTodo(todo.id)} className="delete">
              🗑️
            </button>
          </li>
        ))}
      </ul>

      {todos.length === 0 && (
        <p className="empty">No todos yet. Add one above!</p>
      )}

      <p className="count">
        {todos.filter(t => !t.completed).length} items left
      </p>
    </div>
  )
}

export default App
"""
        (workspace / "src" / "App.jsx").write_text(app_jsx)
        files.append("src/App.jsx")

        # src/styles.css
        styles_css = """* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  min-height: 100vh;
  padding: 2rem;
}

.app {
  max-width: 500px;
  margin: 0 auto;
  background: white;
  padding: 2rem;
  border-radius: 16px;
  box-shadow: 0 10px 40px rgba(0,0,0,0.2);
}

h1 {
  text-align: center;
  margin-bottom: 1.5rem;
  color: #333;
}

.add-form {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1.5rem;
}

.add-form input {
  flex: 1;
  padding: 0.75rem 1rem;
  border: 2px solid #e0e0e0;
  border-radius: 8px;
  font-size: 1rem;
  transition: border-color 0.2s;
}

.add-form input:focus {
  outline: none;
  border-color: #667eea;
}

.add-form button {
  padding: 0.75rem 1.5rem;
  background: #667eea;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  cursor: pointer;
  transition: background 0.2s;
}

.add-form button:hover {
  background: #5a6fd6;
}

.todo-list {
  list-style: none;
}

.todo-list li {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem;
  border-bottom: 1px solid #eee;
  transition: background 0.2s;
}

.todo-list li:hover {
  background: #f9f9f9;
}

.todo-list li span {
  cursor: pointer;
  flex: 1;
}

.todo-list li.completed span {
  text-decoration: line-through;
  color: #999;
}

.delete {
  background: none;
  border: none;
  font-size: 1.2rem;
  cursor: pointer;
  opacity: 0.5;
  transition: opacity 0.2s;
}

.delete:hover {
  opacity: 1;
}

.empty {
  text-align: center;
  color: #999;
  padding: 2rem;
}

.count {
  text-align: center;
  color: #666;
  margin-top: 1rem;
  font-size: 0.9rem;
}
"""
        (workspace / "src" / "styles.css").write_text(styles_css)
        files.append("src/styles.css")

        # README.md
        readme = """# Todo App

A simple todo application built with React and Vite.

## Features

- ✅ Add new todos
- ✅ Mark todos as complete
- ✅ Delete todos
- ✅ Track remaining items

## Getting Started

```bash
npm install
npm run dev
```

Then open http://localhost:5173 in your browser.

## Build for Production

```bash
npm run build
```

Generated by Druppie Governance Platform.
"""
        (workspace / "README.md").write_text(readme)
        files.append("README.md")

        return files

    def _generate_calculator_app(self, workspace: Path, app_info: dict) -> list[str]:
        """Generate a calculator application."""
        files = []

        # Simple HTML/CSS/JS calculator
        html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Calculator</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <div class="calculator">
        <div class="display" id="display">0</div>
        <div class="buttons">
            <button onclick="clearDisplay()">C</button>
            <button onclick="appendToDisplay('/')">/</button>
            <button onclick="appendToDisplay('*')">×</button>
            <button onclick="backspace()">⌫</button>
            <button onclick="appendToDisplay('7')">7</button>
            <button onclick="appendToDisplay('8')">8</button>
            <button onclick="appendToDisplay('9')">9</button>
            <button onclick="appendToDisplay('-')">-</button>
            <button onclick="appendToDisplay('4')">4</button>
            <button onclick="appendToDisplay('5')">5</button>
            <button onclick="appendToDisplay('6')">6</button>
            <button onclick="appendToDisplay('+')">+</button>
            <button onclick="appendToDisplay('1')">1</button>
            <button onclick="appendToDisplay('2')">2</button>
            <button onclick="appendToDisplay('3')">3</button>
            <button onclick="calculate()" class="equals">=</button>
            <button onclick="appendToDisplay('0')" class="zero">0</button>
            <button onclick="appendToDisplay('.')">.</button>
        </div>
    </div>
    <script src="script.js"></script>
</body>
</html>
"""
        (workspace / "index.html").write_text(html)
        files.append("index.html")

        css = """* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    min-height: 100vh;
    display: flex;
    justify-content: center;
    align-items: center;
}

.calculator {
    background: #1f1f1f;
    border-radius: 20px;
    padding: 20px;
    box-shadow: 0 10px 40px rgba(0,0,0,0.5);
}

.display {
    background: #2d2d2d;
    color: white;
    font-size: 2.5rem;
    text-align: right;
    padding: 20px;
    border-radius: 10px;
    margin-bottom: 20px;
    min-height: 80px;
    word-break: break-all;
}

.buttons {
    display: grid;
    grid-template-columns: repeat(4, 70px);
    gap: 10px;
}

button {
    width: 70px;
    height: 70px;
    border: none;
    border-radius: 15px;
    font-size: 1.5rem;
    cursor: pointer;
    background: #333;
    color: white;
    transition: all 0.2s;
}

button:hover {
    background: #444;
    transform: scale(1.05);
}

button:active {
    transform: scale(0.95);
}

.equals {
    grid-row: span 2;
    height: 150px;
    background: #4CAF50;
}

.equals:hover {
    background: #45a049;
}

.zero {
    grid-column: span 2;
    width: 150px;
}
"""
        (workspace / "styles.css").write_text(css)
        files.append("styles.css")

        js = """let display = document.getElementById('display');
let currentValue = '0';

function appendToDisplay(value) {
    if (currentValue === '0' && value !== '.') {
        currentValue = value;
    } else {
        currentValue += value;
    }
    display.textContent = currentValue;
}

function clearDisplay() {
    currentValue = '0';
    display.textContent = '0';
}

function backspace() {
    currentValue = currentValue.slice(0, -1) || '0';
    display.textContent = currentValue;
}

function calculate() {
    try {
        currentValue = String(eval(currentValue));
        display.textContent = currentValue;
    } catch (e) {
        display.textContent = 'Error';
        currentValue = '0';
    }
}
"""
        (workspace / "script.js").write_text(js)
        files.append("script.js")

        readme = """# Calculator

A simple calculator built with HTML, CSS, and JavaScript.

## Usage

Open `index.html` in your browser.

Generated by Druppie Governance Platform.
"""
        (workspace / "README.md").write_text(readme)
        files.append("README.md")

        return files

    def _generate_blog_app(self, workspace: Path, app_info: dict) -> list[str]:
        """Generate a blog application."""
        files = []

        # Create Python Flask blog
        (workspace / "templates").mkdir(exist_ok=True)

        app_py = """from flask import Flask, render_template, request, redirect, url_for
from datetime import datetime

app = Flask(__name__)

# In-memory storage (use a database in production)
posts = []

@app.route('/')
def index():
    return render_template('index.html', posts=posts)

@app.route('/post/new', methods=['GET', 'POST'])
def new_post():
    if request.method == 'POST':
        post = {
            'id': len(posts) + 1,
            'title': request.form['title'],
            'content': request.form['content'],
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M')
        }
        posts.insert(0, post)
        return redirect(url_for('index'))
    return render_template('new_post.html')

@app.route('/post/<int:post_id>')
def view_post(post_id):
    post = next((p for p in posts if p['id'] == post_id), None)
    if post:
        return render_template('post.html', post=post)
    return 'Post not found', 404

@app.route('/post/<int:post_id>/delete', methods=['POST'])
def delete_post(post_id):
    global posts
    posts = [p for p in posts if p['id'] != post_id]
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
"""
        (workspace / "app.py").write_text(app_py)
        files.append("app.py")

        index_html = """<!DOCTYPE html>
<html>
<head>
    <title>My Blog</title>
    <style>
        body { font-family: sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
        .post { border: 1px solid #ddd; padding: 20px; margin: 10px 0; border-radius: 8px; }
        .post h2 { margin: 0 0 10px 0; }
        .post .meta { color: #666; font-size: 0.9em; }
        a { color: #0066cc; }
        .btn { padding: 10px 20px; background: #0066cc; color: white; border: none; cursor: pointer; border-radius: 4px; text-decoration: none; display: inline-block; }
        .btn-danger { background: #cc0000; }
    </style>
</head>
<body>
    <h1>📝 My Blog</h1>
    <a href="/post/new" class="btn">New Post</a>
    {% for post in posts %}
    <div class="post">
        <h2><a href="/post/{{ post.id }}">{{ post.title }}</a></h2>
        <p class="meta">{{ post.created_at }}</p>
        <p>{{ post.content[:200] }}...</p>
    </div>
    {% endfor %}
    {% if not posts %}
    <p>No posts yet. Create one!</p>
    {% endif %}
</body>
</html>
"""
        (workspace / "templates" / "index.html").write_text(index_html)
        files.append("templates/index.html")

        new_post_html = """<!DOCTYPE html>
<html>
<head>
    <title>New Post</title>
    <style>
        body { font-family: sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
        input, textarea { width: 100%; padding: 10px; margin: 10px 0; box-sizing: border-box; }
        textarea { height: 200px; }
        .btn { padding: 10px 20px; background: #0066cc; color: white; border: none; cursor: pointer; border-radius: 4px; }
    </style>
</head>
<body>
    <h1>New Post</h1>
    <form method="POST">
        <input type="text" name="title" placeholder="Title" required>
        <textarea name="content" placeholder="Write your post..." required></textarea>
        <button type="submit" class="btn">Publish</button>
        <a href="/">Cancel</a>
    </form>
</body>
</html>
"""
        (workspace / "templates" / "new_post.html").write_text(new_post_html)
        files.append("templates/new_post.html")

        post_html = """<!DOCTYPE html>
<html>
<head>
    <title>{{ post.title }}</title>
    <style>
        body { font-family: sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
        .meta { color: #666; }
        .btn { padding: 10px 20px; background: #0066cc; color: white; border: none; cursor: pointer; border-radius: 4px; text-decoration: none; display: inline-block; }
        .btn-danger { background: #cc0000; }
    </style>
</head>
<body>
    <a href="/">← Back</a>
    <h1>{{ post.title }}</h1>
    <p class="meta">{{ post.created_at }}</p>
    <p>{{ post.content }}</p>
    <form action="/post/{{ post.id }}/delete" method="POST" style="margin-top: 20px;">
        <button type="submit" class="btn btn-danger">Delete Post</button>
    </form>
</body>
</html>
"""
        (workspace / "templates" / "post.html").write_text(post_html)
        files.append("templates/post.html")

        requirements = """flask>=3.0.0
"""
        (workspace / "requirements.txt").write_text(requirements)
        files.append("requirements.txt")

        readme = """# Blog App

A simple blog application built with Flask.

## Getting Started

```bash
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5000 in your browser.

Generated by Druppie Governance Platform.
"""
        (workspace / "README.md").write_text(readme)
        files.append("README.md")

        return files

    def _generate_generic_app(self, workspace: Path, app_info: dict) -> list[str]:
        """Generate a generic starter app."""
        files = []

        readme = f"""# {app_info.get('name', 'My App')}

{app_info.get('description', 'A new application.')}

## Getting Started

This is a starter project. Add your code here!

Generated by Druppie Governance Platform.
"""
        (workspace / "README.md").write_text(readme)
        files.append("README.md")

        return files
