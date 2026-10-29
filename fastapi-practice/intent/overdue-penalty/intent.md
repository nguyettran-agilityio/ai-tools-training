# Overdue Penalty Policy

Author: Lead
Status: Accepted

## Problem

Members who return books late face no consequence. A member who is still holding an overdue book can keep borrowing more books. Librarians have no consolidated view of who is overdue or who returned late.

### Current system behavior

- A loan becomes overdue once its due date passes. Overdue status is worked out whenever the data is read, with no scheduled background process.
- A member holding an overdue book can still borrow more books, as long as they are under the borrowing limit.
- An overdue loan cannot be renewed.
- Librarians can manually send overdue reminders to members who hold overdue books.

## Proposed outcome

### Scope

- **Borrowing ban for late returns.** A member who returns a book after its due date is banned from borrowing for N days, counted from the day of the return. Any delay counts, with no grace period.
- **N is configurable.** The default is 7 days.
- **Repeat late returns during a ban.** The ban is recalculated as N days from the latest late return, and the later of the two end dates applies. Bans do not stack.
- **Block while holding an overdue book.** A member who holds at least one overdue, unreturned book cannot borrow another book until it is returned.
- **Reservations are not affected.** A banned member can still place reservations.
- **Telling the member.** When a borrow attempt is refused because of a ban, the member is told when they can borrow again. No other notification is sent.
- **Overdue report for librarians**, which includes:
  - loans that are currently overdue and not yet returned;
  - loans that were returned late, filterable by date range;
  - members who are currently banned.

### Out of scope

- Monetary fines, fine calculation, and payments.
- Applying bans retroactively. Only returns made after the feature is released count.
- Proactive notification of bans by email or real-time message.

### Success criteria

1. A member who returns a book late cannot borrow for N days, and knows when they can borrow again.
2. A member who holds an overdue book cannot borrow more books.
3. A librarian can see who is currently overdue and who is currently banned.

## Affected users and systems

- **Members** may be blocked from borrowing after a late return or while holding an overdue book. They must be able to find out when they can borrow again.
- **Librarians** use the new report to see overdue loans, late returns, and banned members.
- **The borrowing process** gains new eligibility checks.

## Constraints

- Librarians may later need to lift a ban (see Open questions). The design must not rule that out.
- Whether a ban is worked out from borrowing history or recorded separately is left to the spec.

## Open questions

1. Should members be able to view their own ban status and when it ends, outside of a refused borrow attempt?
2. Can librarians intervene in bans, for example by lifting a ban early or by creating one manually?
3. The Lead used "librarian", but the system only has an admin role. Is a librarian the same as an admin, or is a separate role needed?
