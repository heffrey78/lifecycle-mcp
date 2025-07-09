---
allowed-tools: Bash(pytest:*), Bash/coverage:*), Bash/ruff:*), Bash/mypy:*), Bash(git:*), Bash(pipx:*), Bash(ls:*), Bash(cat:*), Bash(tree:*), Bash(find:*), Bash(toml:*), Bash(python3:*)
description: Evaluate the test suite and codebase against the 30-point test scorecard.
---

## Context

- Current branch: !`git branch --show-current`
- Latest commit: !`git log -1 --oneline`
- Project tree: !`tree -L 3`
- Test files: !`find tests -name "test_*.py"`
- conftest.py: !`ls tests/conftest.py`
- Pytest version: !`pytest --version`
- Pytest plugins: !`pytest --trace-config | grep 'pytest-'`
- Coverage config: !`cat pyproject.toml | grep -A 10 '\[tool.coverage'`
- Coverage report: !`coverage run -m pytest --branch && coverage report --fail-under=80`
- Lint (ruff): !`ruff src tests --select E,F,I`
- Type checks (mypy): !`mypy src tests`
- Test run (parallel, random seed): !`pytest -n auto --randomly-seed=42 -q --maxfail=5`
- Slow tests: !`grep -r '@pytest.mark.slow' tests/`
- Hypothesis usage: !`grep -r 'from hypothesis' tests/`
- GitHub Actions workflow: !`cat .github/workflows/tests.yml 2>/dev/null || echo 'No workflow found'`
- Requirements: !`cat pyproject.toml | grep -A 20 '\[project.optional-dependencies\]'`
- Helper utilities: !`ls tests/_utils.py 2>/dev/null || echo 'No helpers found'`

## Your task

Using the context above, evaluate each test file against the following scorecard (30 points total):

Python Test-Quality Guide

Version 2025-07-08 – distilled from pytest 8 +, Coverage.py, Hypothesis, Freezegun, factory_boy, mutmut, schemathesis, pact-python, Real Python, Obey the Testing Goat, Python Testing with pytest, Automation Panda.

⸻

0  Scorecard (30 pts)

#	Category	Pts	Pass (3 pts)	Fail triggers (0 pts)
1	Structure & Naming	3	tests/ mirrors src/; files test_<unit>.py; fixtures in conftest.py; order-independent	prod+test mixed, hidden state
2	Coverage Gate	3	coverage run -m pytest --branch ≥ 90 % & CI --fail-under=90	< 80 % or no branch data
3	Isolation	3	Deterministic under pytest -n auto --randomly-seed=<any>	sleep, live network, global bleed
4	Clarity	3	AAA layout, ≤ 40 LOC/test, rich assert diff	many opaque asserts
5	Behavioral Depth	3	Hypothesis invariants on critical funcs	only happy-path examples
6	Performance	3	Suite < 60 s; slow tests @pytest.mark.slow; xdist-safe	> 5 min or hangs
7	Maintainability	3	No dupes; helpers; ruff + mypy clean	copy-paste, lint errs
8	Layering	3	≈ 70 % unit / 25 % service / 5 % UI	ice-cream-cone pyramid
9	CI / Reporting	3	GH Actions runs pytest+coverage; PR comment	no automated gate
10	Extensibility	3	pytest ≥ 8 pinned; plugins: pytest-mock, pytest-xdist, pytest-randomly	out-dated or custom hacks

Score < 24 → block; ≥ 27 → green-light.

⸻

1  Structure & Naming

project/
├── src/awesome/
│   └── calc.py
└── tests/
    └── awesome/
        └── test_calc.py

	•	one top-level conftest.py; optional per-package conftest.py
	•	test funcs test_<behavior>; fixtures are nouns (user_factory)

⸻

2  Coverage Strategy

pyproject.toml

[tool.coverage.run]
branch = true
source = ["src"]

[tool.coverage.report]
fail_under = 90
show_missing = true

CI step:

coverage run -m pytest -n auto
coverage combine
coverage report --fail-under=90
coverage xml            # publish artifact


⸻

3  Isolation & Determinism

Problem	Fix
Sleep-based waits	wait_for(lambda: cond(), timeout=2)
Time-dependent code	@freeze_time("2025-01-01")
Randomness	pytest --randomly-seed 0 + session fixture seeding PRNGs
External I/O	mocker.patch("requests.post"); keep domain objects real


⸻

4  Clarity

def test_transfer_funds(bank):
    # Arrange
    acc_from, acc_to = bank.open(), bank.open()
    bank.deposit(acc_from, 100)
    # Act
    bank.transfer(acc_from, acc_to, 30)
    # Assert
    assert bank.balance(acc_from) == 70

	•	Single behaviour per test; prefer parametrization over loops.

⸻

5  Behavioral Depth

from hypothesis import given, strategies as st
@given(a=st.integers(), b=st.integers().filter(lambda x: x != 0))
def test_div_roundtrip(a, b):
    assert div(a, b) * b == a

	•	add hypothesis.strict = true in pytest.ini; deadline = None for slow paths.

⸻

6  Performance & Parallelism

pytest -n auto --dist=loadscope -q

	•	tag ≥ 0.1 s tests @pytest.mark.slow; skip in default CI unless CI_SLOW=1.
	•	after xdist run: coverage combine && coverage report.

⸻

7  Maintainability
	•	ruff check src tests --select E,F,I
	•	mypy src tests --strict
	•	parametrize to avoid duplication:

@pytest.mark.parametrize("raw,expect", [("US", "us"), ("  Ca ", "ca")])
def test_slugify(raw, expect):
    assert slugify(raw) == expect


⸻

8  Layering Strategy

 ▲  UI/E2E            ~5 %
 │  Service/Contract ~25 %
 ▼  Unit             ~70 %

	•	keep UI happy-paths only; everything else below.

⸻

9  CI / Reporting (GitHub Actions)

- uses: actions/setup-python@v5
  with: {python-version: '3.12'}
- run: pip install -r requirements-dev.txt
- run: coverage run -m pytest -n auto
- run: coverage xml
- uses: py-actions/py-coverage-comment@v2


⸻

10  Extensibility

[project.optional-dependencies]
test = [
  "pytest~=8.1",
  "pytest-cov",
  "pytest-xdist",
  "pytest-mock",
  "pytest-randomly",
  "hypothesis",
  "freezegun",
  "factory_boy",
  "mutmut",
]

	•	expose reusable fixtures through tests/plugins/<name>.py; document in tests/README.md.

⸻

11  Behavior-Centric, Anti-Fragile Testing ★

Guideline	Example
Assert observable effects only	queue.pop(); assert queue.is_empty() not assert queue._items == []
Mock only infrastructure (DB, HTTP)	mocker.patch("requests.post"); avoid mocker.patch("Service._helper")
Prefer property-based invariants	see § 5
Use approval / snapshot tests for fuzzy output	verify(render_html())
Mutation score ≥ 85 %	mutmut run
Randomised order in dev, fixed seed in CI	.pytest.ini: addopts = --randomly-seed=20250708
Freeze time / seed RNG / stub UUIDs	with freeze_time("2025-01-01"):
Poll, don’t sleep	wait_for(lambda: job.done(), 2)


⸻

12  Effectiveness Metrics

Metric	Target	Tool
Line + branch coverage	≥ 90 %	coverage.py
Mutation score	≥ 85 % killed	mutmut / cosmic-ray
Flake rate (CI)	0 repeats / 50 runs	pytest-rerunfailures audit
Mean suite time	≤ 60 s on 8-core	xdist
Hypothesis health checks	0 warnings	pytest


⸻

13  Data & Factory Strategy

Need	Solution
Numerous objects	factory_boy + autouse fixtures
Valid random scalars	Hypothesis strategies (st.decimals(…))
External payloads	store in tests/_data/; helper load_json(path)


⸻

14  Contract / Schema Testing
	•	OpenAPI/JSON Schema: schemathesis run openapi.yaml --base-url http://localhost:8000
	•	Consumer-driven: pact-python; verify in CI.

⸻

15  Observability Inside Tests
	•	caplog.at_level("ERROR"); assert on message, not internals.
	•	pytest-rich, pytest-icdiff for diffs.
	•	Emit trace-IDs in test mode to correlate with backend traces.

⸻

16  Anti-Patterns (auto-fail to 0 pts)

Pattern	Replace with
time.sleep()	Freezegun/polling
except: catch-all	explicit exception
assert in loop	@pytest.mark.parametrize
print() debugging	pytest -vv --pdb
stateful globals	fixtures


⸻

17  Reference Snippets

# tests/conftest.py
import pytest, random
@pytest.fixture(scope="session", autouse=True)
def seed():
    random.seed(0)

@pytest.fixture
def client():
    from mypkg.api import Client
    return Client(base_url="http://test")


⸻

18  Automated Audit Script (optional)

#!/usr/bin/env bash
set -e
coverage run -m pytest -n auto --randomly-seed=42
coverage combine && coverage report
ruff src tests --select E,F,I
mypy src tests
mutmut run --runner "python -m pytest -q"
score=$(pipx run nitpick score || true)
[ "${score:-0}" -ge 27 ] || { echo "Quality bar not met"; exit 1; }


⸻

Maintain ≥ 27 / 30; block anything lower. Merge only green suites—technical debt stays out.