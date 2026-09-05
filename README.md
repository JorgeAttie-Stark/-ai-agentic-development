README.md
# AI Agentic Development

Practical laboratory for learning and experimenting with AI-driven software development using Claude Code.

This repository explores how to use **Context Engineering, Skills, Agents, TDD and Code Review** to build better AI-assisted development workflows.

## 🎯 Goal

The goal of this repository is not to build a production application.

It is a practical environment to understand how AI coding agents work and how to give them the right context, instructions, tools and workflows.

The project evolves as new concepts are learned and tested.

---

## 🧠 Concepts

This repository explores:

- Context Engineering
- Claude Code
- Agentic Development
- Skills
- Agents
- Commands
- Test-Driven Development (TDD)
- Automated Code Review
- AI-assisted software development
- Software engineering workflows

---

## 📁 Structure

```text
.
├── .claude/
│   ├── agents/
│   ├── commands/
│   └── skills/
│       ├── test-driven-development/
│       │   └── SKILL.md
│       └── code-review/
│           └── SKILL.md
│
├── src/
│   ├── __init__.py
│   └── parity.py
│
├── tests/
│   ├── __init__.py
│   └── test_parity.py
│
└── README.md
🛠️ Current Example

The first exercise is intentionally simple.

A Python function determines whether a number is even:

def is_even(number):
    return number % 2 == 0

The implementation was created following a Test-Driven Development workflow.

TDD workflow
Requirement
     ↓
Find existing tests
     ↓
Write test
     ↓
🔴 RED
Test fails
     ↓
Implement
     ↓
🟢 GREEN
Test passes
     ↓
Check regressions
🧩 Skills

Skills provide reusable instructions that teach the AI agent how to perform a specific type of work.

Test-Driven Development

Located at:

.claude/skills/test-driven-development/SKILL.md

The skill instructs Claude to:

Understand the requirement
Look for existing tests
Create or update tests
Run the tests
Implement the functionality
Run the tests again
Fix failures
Check for regressions
Code Review

Located at:

.claude/skills/code-review/SKILL.md

The skill instructs Claude to review changes systematically:

Diff
 ↓
Architecture
 ↓
Bugs
 ↓
Edge Cases
 ↓
Security
 ↓
Missing Tests
 ↓
Regressions
 ↓
Code Review

The objective is to identify real problems rather than simply suggest personal preferences.

🧪 Running Tests

The current test suite uses Python's built-in unittest.

From the project root:

python3 -m unittest discover -s tests -t .

Expected result:

Ran 4 tests ... OK
🔬 Experiments

The repository will be used to experiment with increasingly advanced AI development workflows.

Planned experiments include:

 Create the first TDD Skill
 Create the first Code Review Skill
 Create reusable Claude commands
 Create specialized Agents
 Combine Agents and Skills
 Improve project context
 Experiment with Context Engineering
 Build multi-step development workflows
 Explore automated code review
 Explore multi-agent workflows
📚 Learning Path

The current learning path is:

Prompt Engineering
        ↓
Context Engineering
        ↓
Skills
        ↓
Tools
        ↓
Agents
        ↓
Multi-Agent Systems
        ↓
AI-driven Development

Each concept will be implemented and tested in this repository rather than studied only theoretically.

🚧 Status

This repository is a work in progress.

The code and structure will evolve as new AI-assisted development concepts are explored.

License

MIT


### Eu faria ainda uma pequena mudança

Como esse é um **projeto de estudo que vai evoluir**, eu manteria o README exatamente nessa ideia:

> **"Não estou construindo um app; estou construindo meu laboratório de desenvolvimento com IA."**

Isso deixa muito mais interessante para quem entrar no seu GitHub daqui a alguns meses e encontrar `Skills`, `Agents`, `MCP`, testes, workflows etc.
