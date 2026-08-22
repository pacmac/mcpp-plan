# Roadmap design rules

Source: roadmap session, 2026-08-22, xsession mcpp-plan--roadmap #40.
Written to survive both repos being deleted — every measurement is included.

Format: RULE / why it exists / what it cost to learn / source test

---

## A. THE THREE-WAY STATUS

The rule that has bitten most often.

**A1** A tool has THREE outcomes, not two: nothing to report / a finding / COULD NOT LOOK.
A caller that cannot tell "clean" from "we never managed to look" reads silence as health.
Surfaced four times in four different places.
`test_cannot_look_is_not_clean_{not_a_repo,no_areas_file,empty_areas_file}`

**A2** "success" means THE TOOL RAN, never that the project is clean.
A finding is a SUCCESSFUL run that found something. Collapsing the two makes every finding
look like a failure and every failure look like a finding.
`mcpptool.py contract; test_the_payload_and_the_display_say_the_same_thing`

**A3** A register you could not READ is not a register holding NOTHING.
If idiot is not callable, every area shows 0 open and the project reads as finished.
Name the failure; never zero it.
`test_an_unreadable_register_is_named_not_counted_as_zero`

**A4** "-" is not "0".
In a count column, "-" means no such register exists for that area; "0" means it exists
and is empty. Collapsing them makes a project with NO specs look like one with CLEAN specs.
`test_the_corpus_column_tells_absent_from_empty`

**A5** A file that will not parse is COULD NOT LOOK, not a finding.
Letting a YAMLError escape exits 1, and 1 means "something needs attention" — so a broken
file reports itself as a defect in the repo.
`test_a_file_that_will_not_parse_is_two_not_one`

Where it has bitten (all four found by calling the tool, not by reading code):
- `plan_task_list --area <unknown>` returned "No tasks." (mcpp-plan #11)
- `plan_area_delete` reported success while orphaning a task (mcpp-plan #15)
- batch `plan_area_new` reported failure after committing rows (mcpp-plan #31)
- roadmap's own wrapper returned `data` not `result` — agent saw "null", human saw listing

---

## B. NOTHING ASKED FOR IS LOST

**B1** An item in NO area is SHOWN, not dropped.
It can never be joined AND never be closed — device's `cli-styling` names no files at all,
so nothing can ever close it. Omitting it silently is exactly how "nothing asked for is
lost" fails.
`test_an_item_in_no_area_is_shown_not_dropped`

**B2** An item straddling TWO areas is NAMED, and counted against both.
Not untidiness: the boundary between those areas is undefined, so NEITHER can be honestly
signed off while it is open. Measured on device: 12 clean, 3 ambiguous, 1 unmappable of 16.
`test_a_straddling_item_is_named_and_counted_against_both`

**B3** It LISTS, it does not summarise.
A count with no id destroys the slug somebody would have grepped for. Print the ids under
their area.
`test_items_are_counted_into_the_area_that_owns_their_files`

**B4** Cross-repo debts carry no area key at all and are in NONE of the rows.
Say so on the output. A reader assuming the table is the whole backlog is wrong, and nothing
else will tell them.
`test_xsession_debts_are_declared_absent_rather_than_forgotten`

---

## C. IT IS NOT A REGISTER

**C1** It holds NO items of its own. Four registers already disagree; one that starts holding
items becomes the fifth thing to reconcile.

**C2** Every count comes from the register that OWNS it.
`idiot list --json` decides what is open in idiot, because idiot owns its verdicts.
Re-deriving "open" from idiot.yaml is a second opinion on a settled question, and two
opinions drift.

---

## D. ORDER

**D1** A GATE OUTRANKS A PRIORITY.
`depends` means "this must WORK before I can be finished", so an area whose dependency is
still open is NOT STARTABLE however good its priority and however big its pile.
`test_an_area_gated_by_an_open_dependency_is_not_startable` — the fixture puts the BETTER
priority on the gated area on purpose.

**D2** `depends` CANNOT BE DERIVED. This one cost the most.
"A watches a file B owns, therefore A depends on B" was tried and INVERTS THE STACK: it
made alarm-application — the composition root — the foundation of everything, because six
areas watch its main.cpp. A composition root is watched by everybody and depended on by
nobody. Humans author these edges.

**D3** `priority` is TYPED by a human, deliberately, against idiot's "derived never typed".
Sorting depends yields TIERS; inside a tier no fact about the code separates two areas. The
tiebreak is a judgement about what matters this month.

**D4** `priority` must not contradict `depends`.
The file would say "do A first" and "A cannot be finished until B works" at once. Not a
judgement — a mistake, and checkable.
`test_priority_may_not_outrank_something_it_depends_on`

**D5** RANK AND EXPLAIN; DO NOT DECIDE.
Every ranked line carries the constraint that put it there. An unprioritised class SAYS it
is unordered rather than letting silence read as a considered order.
`test_every_ranked_line_carries_the_constraint_that_put_it_there`
`test_an_unprioritised_class_says_so_rather_than_pretending_to_be_ordered`

**D6** A stale priority is a FAULT, not a detail.
It goes wrong silently the moment an area closes and nobody re-ranks. Re-stamp the reviewed
date on every edit.
`test_a_stale_recorded_date_is_re_stamped_on_change`

---

## E. CLASS

**E1** `class` is `product | tooling`, a CLOSED SET, and REQUIRED.
Free text drifts. An area that has not said whether it ships has no place in the order, and
the order is the point.
`test_class_is_a_closed_set`, `test_an_area_with_no_class_cannot_be_placed`

**E2** THE DISCRIMINATOR IS "DOES IT SHIP", not "can it be built on a workstation".
An earlier wording used the workstation test and was WRONG about host-tooling, which owns
the only cable to the board and still never reaches it.
`product` = it ships. `tooling` = it builds, proves or reaches the product, never ships.

**E3** PRODUCT BEFORE TOOLING IN EVERY LISTING, and the classes NEVER INTERLEAVE whatever
the priorities say.
A mixed table invites the one comparison with no answer: "do the gates" against "do the
camera". THIS IS THE ONE SOMEBODY FIXES BY SORTING ON PRIORITY ALONE — the test puts tooling
at priority 1 and product at 9 for exactly that reason.
`test_product_lists_before_tooling_whatever_the_priorities_say`

**E4** WHY class EXISTS — not grouping. NOT CHOOSING A SESSION YOU CANNOT FINISH.
Measured on mt-alarm-1/device: all SEVEN product areas carry a needs_hardware block; two of
the three tooling areas carry none. So with the board on the wall, biggest-pile-first picks
power-and-sleep with 15 items — a session that CANNOT CLOSE — while 16 bugs sit in
quality-gates and host-tooling needing no radio at all.
(Honest caveat: that column counts blocks that MENTION the key, not blocks proven unmet.)

---

## F. THE HUMAN CHECKPOINT

**F1** AN AGENT MUST NOT ANSWER, ON A HUMAN'S BEHALF, A QUESTION ONLY THE HUMAN CAN ANSWER.
An agent can derive, count, join, check, and decide which area a file is in. It cannot
decide whether an area SHIPS, what it is FOR, or whether the list is AGREED.
`test_the_check_asks_the_human_the_questions_only_a_human_can_answer`

**F2** Ask it as a QUESTION, in a form answerable in one message, and SEPARATELY from
findings an agent can just fix.
Burying "which of these ship?" in a findings list is how it goes unanswered — measured:
after a full day of building this, all TEN of device's areas were still unclassed.

**F3** A TOOL MUST NOT STAMP "AGREED" ON A LIST NOBODY HAS DESCRIBED.
Otherwise the only human checkpoint in the design becomes a formality.
LIVE NOW: `plan_area_new` accepts an area with no `description_md`.
`test_it_will_not_ratify_a_list_nobody_has_described`

**F4** Set-and-ratify in ONE call is judged on the RESULT, not the prior state.
Otherwise the last area can never be described and agreed together.
`test_set_and_ratify_in_one_call_is_judged_on_the_result`

**F5** A MISSING key is not a FALSE one.
A file with no `ratified` key was written before the key existed and claims nothing either
way. Treating absence as non-ratification turns every hand-authored file red overnight. Only
an explicit false is a finding.
`test_a_missing_ratified_key_is_not_an_accusation`

---

## G. AREAS ARE NOT INDEPENDENT

**G1** CLOSED IS NOT TERMINAL. An area signed off before files in its scope or watch changed
is not signed off any more.
Peter: "it may be re-opened when new code is added and new tooling is needed."

**G2** `watch` is WHY an area re-opens, and it needs saying BEFORE a session starts.
Measured on device: rak/v3/src/main.cpp changed in 60 COMMITS IN 60 DAYS, and SIX of the
ten areas watch it. A commit a day invalidating six areas' proofs. The mechanical explanation
for "a session touched six of ten areas and closed none of them". Not indiscipline — one file.
`test_the_focus_view_names_what_will_re_open_it`

**G3** A TEST BELONGS TO THE AREA IT PROVES.
idiot closes on a test that ran red then green. If the test lives in a different area from
the fix, EVERY closure straddles two areas and the exactly-one-area rule stops being a check
and becomes an obstacle. An area you can sign off INCLUDES its proof.
(Needs scope; here for when it lands.)

---

## H. FOCUS

**H1** FOCUS IS A SESSION SCOPE GATE, NOT A BOOKMARK.
"This session works on X and nothing else. A finding outside it is REPORTED, not fixed" —
the same rule /idiot applies to a file outside an attached spec. Calling it "move the
pointer" undersold it to the point of being wrong.

**H2** ONE POINTER, NOT TWO. If a task carries an area, the active task's area IS the focus.
Two pointers for "what am I working on" is the duplication this project exists to end.

---

## I. IDENTITY

**I1** "that does not exist" and "that is not built" are DIFFERENT ANSWERS, and only one is
the caller's mistake. Name the valid set in the refusal.
`test_a_name_that_is_not_an_area_is_told_so`

**I2** An area name is an IDENTIFIER several tools join on. Case and whitespace collisions
silently split one area into two that read identically in a list.
(mcpp-plan #16 — fixed.)

**I3** A vocabulary you cannot CORRECT is worse than one that is wrong.
A typo'd name that can never be renamed or retired outlives the mistake for ever.
(mcpp-plan #12 — fixed. And it is why RETIRE beats DELETE: the record of what was decided is
worth more than a tidy list, for the same reason idiot keeps withdrawn entries visible.)

---

## J. FILE-BOUND (recorded so nobody wonders if they were forgotten)

- comments survive an edit (ruamel, not pyyaml — a pyyaml round trip destroys every comment,
  and the file carried the reasoning for its own shape)
- a generated file is never written by anybody
- the proposal reads back as valid YAML before being offered
- glob semantics — already inline in xsession #22, needed only if `scope` lands

---

## THE META-RULE

**RE-TEST EVERY BLOCKER YOU INHERIT, INCLUDING MINE.**

I recorded `all` as "waiting on the register join" and `sync` as "blocked on Peter: which
register is authoritative". BOTH WERE FICTION. A session did the join by hand in a few lines;
and looking at the data settled the other — bugs.yaml carries confidence/state/ruled and NO
test, idiot.yaml carries test/trial/fix, so they are an audit stage and a trial stage of ONE
pipeline, not rivals. I was telling Peter he owed an answer he did not.

**AN UNCHECKED CLAIM PROPAGATES.** An inherited docstring said `fnmatch('a/b/c.py','a/**')`
is False. It is TRUE. That sentence was copied into three further places before a test caught
it.

**DOGFOOD IT.** The root-was-never-tested bug was found only by running the tool on its own
repo — every other tree had two real subdirectories and hid it.
