# Spec: task-done-nag

## Problem
Tasks that have all steps marked complete are often forgotten without being closed via
plan_task_complete. They accumulate as zombie tasks — technically done, never closed.
The goal for every project is zero outstanding tasks.

## Solution
Inject a nag into every MCP tool response listing ALL tasks in the current project
where every non-deleted step is complete but the task status is still 'active'.

## Nag condition (per task in current project)
- Task status = 'active' (not 'completed')
- Task has at least one non-deleted step
- All non-deleted steps have status = 'complete'

## Nag message (appended to display field)
    ⚠ N task(s) have all steps complete but are not closed: `name1`, `name2`. Call plan_task_complete for each.

Suppressed when N = 0. Suppressed for the tool call that IS plan_task_complete (avoid
nagging mid-completion).

## Inject point
execute() in mcpptool.py — in the existing try block (lines 795–823) where the DB is
already open, before conn.close().

## Query
For each context in the current project:
  - status = 'active'
  - has at least one task row with is_deleted=0
  - COUNT of non-deleted steps WHERE status != 'complete' = 0

## Files changing
- mcpptool.py: add _nag_done_tasks() helper, call it in execute() before conn.close()

## Source hash
mcpptool.py: d006a69fbe6d6e025e450c727b54cef2658296882b993a8d7f21c5889d3bb73b
