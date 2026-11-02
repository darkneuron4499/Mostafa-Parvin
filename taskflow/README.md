<div align="center">

# ✅ TaskFlow

**A tiny, clean, object-oriented task manager for your terminal.**

![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-pytest-brightgreen)
![Code style](https://img.shields.io/badge/code%20style-ruff-black)

</div>

---

## ✨ Features

- Add, list, complete and remove tasks from the command line
- Three priority levels (`low`, `medium`, `high`)
- Persistent storage in a human-readable JSON file
- Clean OOP design with a swappable storage backend
- Fully typed, tested with `pytest`, CI via GitHub Actions

## 📦 Installation

```bash
git clone https://github.com/<your-username>/taskflow.git
cd taskflow
pip install -e .
```

## 🚀 Usage

```bash
taskflow add "Write README" -p high
taskflow add "Buy milk" -p low
taskflow list
taskflow done 1
taskflow list --pending
taskflow stats
taskflow remove 2
```

Example output:

```
[○] #1   Write README  (high)
[○] #2   Buy milk  (low)
```

## 🧱 Architecture

```
src/taskflow/
├── models.py    # Task dataclass + Priority enum
├── storage.py   # Storage (ABC) and JsonStorage implementation
├── manager.py   # TaskManager: business logic
└── cli.py       # argparse command-line interface
```

| Principle | How it is applied |
|-----------|-------------------|
| **Encapsulation** | `TaskManager` hides its internal task list |
| **Abstraction** | `Storage` is an abstract base class |
| **Polymorphism** | Any `Storage` subclass (SQLite, API...) can be injected |
| **Single responsibility** | Models, storage, logic and CLI are separate modules |

## 🧪 Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

## 🗺️ Roadmap

- [ ] Due dates
- [ ] SQLite storage backend
- [ ] Colored terminal output

## 🤝 Contributing

Pull requests are welcome. Please open an issue first to discuss major changes.

## 📄 License

[MIT](LICENSE)
