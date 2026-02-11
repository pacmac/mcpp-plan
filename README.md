# Agent: Task Manager

A persistent task manager that tracks your work across sessions. Just tell the agent what you want in plain English -- it handles the rest.

---

## Two Things to Know

### 1. Topic

A **topic** is what you're working on. Think of it as a project or focus area.

Examples:
- "Build the login page"
- "Fix broken search results"
- "Add CSV export feature"

A topic contains a list of tasks -- the steps to get it done.

### 2. Task

A **task** is one step within a topic.

Example -- a "Build the login page" topic might have:
1. Create user database table
2. Build login form
3. Add password validation
4. Write tests

Each task tracks its own status: planned, started, or complete.

---

## One Thing at a Time

The agent focuses on **one topic** and **one task** at a time. This is the core rule.

```
You are working on:
  Topic: Build the login page
  Task:  #2 "Build login form" [started]
```

When you come back later, the agent remembers exactly where you left off.

---

## How to Use It

You talk to the agent in plain language. Here are examples of what you can say:

### Start a new topic

> "Create a new topic called build-login with title Build Login Page.
> The tasks are: create user database table, build login form,
> add password validation, write tests."

The agent creates the topic, saves the tasks, and sets task #1 as current.

### Work through tasks

> "Show me task 1"

> "What are the notes on this task?"

> "Mark task 1 as done"

> "Switch to task 2"

### Add notes

> "Add a note to task 3: Used bcrypt for password hashing"

### Check where you are

> "What am I working on?"

> "Show me all tasks"

### Switch between topics

> "Show me all my topics"

> "Switch to the fix-search topic"

When you switch back later, the agent remembers which task you were on.

---

## Task Lifecycle

Every task moves through these states:

```
planned  -->  started  -->  complete
```

- **planned** -- Created but not started yet
- **started** -- The task you are currently working on
- **complete** -- Done

Only one task can be started at a time within a topic.

---

## Where Data Lives

Everything is stored in a database in your project directory. One file, one source of truth. No markdown files to manage, no notes to lose, no status to remember.
