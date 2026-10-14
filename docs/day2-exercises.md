# Day 2 – Ticket analysis, reproduce and understand

## Part 1 – Ticket analysis

I wrote 5 sample tickets for the library app. Each one leaves out some details on purpose (no steps, no error message, no rule). I ran three prompts on every ticket, each prompt in a new chat. I worked alone, so Claude played the reporter instead of a partner.

**The three prompts**

v1 (typed as a quick question, with the typo):

```
Please help me analysis this ticket: [ticket]
```

v2 adds a role, "use ONLY the ticket text", a fixed 3-sentence format and questions for the reporter:

```
I'm a developer analyzing a ticket before starting work. Use ONLY the ticket text below; do not assume anything not written.
Answer in exactly 3 numbered sentences:
1. What the ticket asks for.
2. What is ambiguous or missing.
3. The first step I should take.
Then list up to 5 clarifying questions for the reporter, ordered by which one blocks work the most. Mark any assumption you make.
Ticket: [ticket]
```

v3 is v2 plus three things: a `<context>` block (app, modules, roles), a line "Type: bug / feature request / possibly by design", and "write the questions in plain language". I ran v3 only on tickets 1, 4 and 5.

**Me vs v1 vs v2 on the 5 tickets**

| Ticket                               | Me                                                                                                                   | v1                                                                                                                                      | v2                                                                                                                                                         | v2 is better because                                                        |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| 1 Notify overdue (business rule)     | Not written for this version of the ticket                                                                           | Listed likely causes and sample code as facts, with names that are not in my app (`Loan`, `returned_at`). Asked the reporter nothing.   | 3 short sentences and 5 questions: which account and book, the exact message, how the book was returned, what "very long time" means, sent more than once. | No made-up causes. It asks the reporter instead of guessing.                |
| 2 Cancel reservation (bug)           | Asked for the error message, account and book. Missed what "available" means and whether cancelling is allowed.      | Decided that "available" means a READY state. Wrote code for a route that does not exist (`POST /reservations/{id}/cancel`).            | Said "what does available mean?" and "is cancelling allowed?" are missing, and asked both. Marked its one assumption.                                      | It asks when a word has two meanings instead of picking one.                |
| 3 Delete category (related data)     | Misread it: I thought the books should be deleted with the category. Asked if the delete showed an error or success. | Picked a rule by itself (block the delete with 409). Wrote a fix, SQL and tests. Its only question was for the developer.               | Asked what the rule should be (block, move the books or allow no category), what to do with books already without a category, and how the page fails.      | It asks for the missing rule first. Its first step is an action in the app. |
| 4 Search by author (feature request) | Not written (I only wrote the answer key)                                                                            | Wrote a full requirements document (under 1 second, 300 ms debounce, API route, code). Decided that "easier" means a search box.        | Asked what "easier" means (search box, filter or sort), which screen, and how the name is typed. Saw that the title already says "search".                 | It does not choose the solution for the reporter.                           |
| 5 Member sees all users (permission) | Asked for the steps and typed address vs button. Missed which fields were shown and whether the rule is real.        | Said "yes, a real problem" and believed the friend. Added OWASP, GDPR, a severity rating, a guessed address (`/admin/users`) and a fix. | Did not trust the claim yet. Asked how the list was reached, which fields were shown, and who can confirm the rule.                                        | It checks the rule before judging.                                          |

It is the same every time: v1 fills the gaps itself with causes, code and a fix. v2 uses only the ticket and asks questions.

v3 (run on tickets 1, 4 and 5 only) was close to v2. It helped most on ticket 4: the type line was correct, the questions were plainer ("is there a search box today?"), and the first step included a check in the app. I did not test the lines one by one, so I am not sure which line did it.

**Role-play (ticket 5, Claude as the reporter)**

- Best question: "step by step for this bug". It gave the whole path: `/docs`, "users", "Try it out", "Execute".
- My mistakes: I asked the same question twice, and "when you reload have page show?" was unclear. I forgot to ask if the reporter logged in on the `/docs` page.
- Questions I would send:
  1. On that page, did you type your username and password (a button may say "Authorize") before pressing "Execute"?
  2. Which line did you press "Try it out" on? Please copy it or send a screenshot.
  3. When did you do this, and can you see the same list now?

## Part 2 – Reproduce the bug

- Bug ticket:
- Seeded bug (written in a file outside the repo):
- Setup: `cp .env.example .env`, `uv sync`, `uv run pytest` (313 passed)
- Stack trace:
- Repro steps / expected / actual:

Hypotheses. v1 was "Fix this error for me", v2 was "give me 3 hypotheses and one check for each, do not fix anything".

| Hypothesis | From (me / v1 / v2) | How I checked | Result |
| ---------- | ------------------- | ------------- | ------ |
|            |                     |               |        |
|            |                     |               |        |
|            |                     |               |        |

Real cause:

## Part 3 – Failing test

```python

```

Fails for the right reason?

## Part 4 – Git

- How I made the conflict:
- `pull --rebase`:
- `git log` / `git diff`:
- How I solved the conflict:

## Summary

- Where AI beat me: it found gaps I missed: what "available" means, which fields the list showed, whether the rule is real.
- Where I beat AI: I know the real app, so I spotted the invented routes (`POST /reservations/{id}/cancel`, `/admin/users`).
- Prompts I will reuse: "use ONLY the text I give", "mark every assumption", a fixed format, questions ordered by what blocks work, plain language for non-technical readers.
- Lesson learned: telling Claude to use only the ticket and mark assumptions changed the most. Without it, Claude fills the gaps itself with a cause and a fix.

## Appendix – Tickets

For each ticket: the text, the gaps I left in it on purpose, and my own 3-sentence analysis.

**Ticket 1: Notify overdue**

- Ticket: "Hi, I got a message saying my book is overdue, but I returned it last week. Also the message says I have been late for a very long time, which is not true. Please fix."
- Gaps left: how the book was returned, how the message arrived, the number of days it showed vs the real number.
- My analysis: not written for this version of the ticket.

**Ticket 2: Cancel reservation**

- Ticket: "I tried to cancel my reservation for a book that is already available. The app showed an error and the reservation is still there."
- Gaps left: what "available" means, whether cancelling is allowed in that state, the exact error message.
- My analysis: (1) Is the ticket about not being able to cancel reservations for some books? (2) What error appears when the user clicks? Is there a loading state? Did they reload and try again? (3) Ask the user for the account, the book, and the error message.

**Ticket 3: Delete category**

- Ticket: "An admin deleted a category that still has books. Now those books have no category and the book list page fails to load."
- Gaps left: the rule for deleting a category with books, what "fails to load" looks like, what to do with books that already lost their category.
- My analysis: (1) It is about deleting a category, but the books in that category are not deleted along with it. (2) What kind of category was deleted? Was there an error or a success message? Does the category come back after a reload? (3) Ask for the steps, the delete status, and reproduce the bug.

**Ticket 4: Search books by author**

- Title: "search book my author". Ticket: "I work at the front desk and members often ask me for books by a specific writer. Right now I have to scroll through the whole list, which takes a long time when the library is busy. Could we make it easier to find books by writer? It would really help us during peak hours."
- Gaps left: what "easier" means (search box, filter or sort), who uses it and on which screen, how the author name is typed. The title already gives away "search".
- My analysis: not written.

**Ticket 5: Member sees all users**

- Ticket: "I logged in with my normal member account (not the librarian one) and I was able to see the full list of users, including names and emails of other members. My friend says this should only be visible to librarians. Is this a problem? I'm not sure how I got to that list, I think I tried something in the browser."
- Gaps left: how the list was reached, which fields were shown, whether "librarians only" is the real rule.
- My analysis: (1) A normal user can see the list of users, which only an admin should be able to see. (2) Which account was logged in? What were the steps? Did the person type the address or click a button? (3) Reproduce the bug.
