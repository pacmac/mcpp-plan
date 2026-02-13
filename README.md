# Plan: Task Manager

A persistent task manager that tracks your work across sessions. Just tell the agent what you want in plain English -- it handles the rest.

---

## Two Things to Know

### 1. Task

A **task** is what you're working on. Think of it as a project or focus area.

Examples:
- "Build the login page"
- "Fix broken search results"
- "Add CSV export feature"

A task contains a list of steps -- the actions to get it done.

### 2. Step

A **step** is one action within a task.

Example -- a "Build the login page" task might have:
1. Create user database table
2. Build login form
3. Add password validation
4. Write tests

Each step tracks its own status: planned, started, or complete.

---

## One Thing at a Time

The agent focuses on **one task** and **one step** at a time. This is the core rule.

```
You are working on:
  Task: Build the login page
  Step:  #2 "Build login form" [started]
```

When you come back later, the agent remembers exactly where you left off.

---

## How to Use It

You talk to the agent in plain language. Here are examples of what you can say:

### Start a new task

> "Create a new task called build-login with title Build Login Page.
> The steps are: create user database table, build login form,
> add password validation, write tests."

The agent creates the task, saves the steps, and sets step #1 as current.

### Work through steps

> "Show me step 1"

> "What are the notes on this step?"

> "Mark step 1 as done"

> "Switch to step 2"

### Add notes

Notes can go on tasks or steps.

> "Add a note to this task: Decided to use OAuth2 instead of custom auth"

> "Add a note to step 3: Used bcrypt for password hashing"

> "Show me the notes on this task"

### Check where you are

> "What am I working on?"

> "Show me all steps"

### Switch between tasks

> "Show me all my tasks"

> "Switch to the fix-search task"

When you switch back later, the agent remembers which step you were on.

---

## Step Lifecycle

Every step moves through these states:

```
planned  -->  started  -->  complete
```

- **planned** -- Created but not started yet
- **started** -- The step you are currently working on
- **complete** -- Done

Only one step can be started at a time within a task.

---

## Project Identity

Each workspace has a **project** record -- a name, path, and description. This is set once and included in every response so the agent always knows what project it's working in.

On first use, the project name defaults to the directory name. The agent will be prompted to provide a proper name and description via `plan_project_set`.

> "Set the project name to my-app and description to E-commerce platform backend"

> "Show the project info"

---

## Where Data Lives

Everything is stored in a database in your project directory. One file, one source of truth. No markdown files to manage, no notes to lose, no status to remember.
