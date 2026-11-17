# Natural-language workflow cards implementation plan

**Goal** — Write or generate editable Android workflow cards in natural language, then compile the current cards for review, saving and testing.

## Card creation and review

- [x] Use one shared card editor for creating and editing workflows and for creating a run from an existing execution. Each card has an instruction and an optional verification. Show the technical editor on demand for existing definitions and advanced editing.
- [x] Add optional assistance through `POST /console/recipes/suggest-cards`. The active provider proposes editable natural-language cards. Give the user a way to review suggestions before adding them to an existing draft.
- [x] Compile through `POST /console/recipes/prepare-cards`. Send the current ordered cards and any known device context. Display the validated result or identify the specific card that needs clarification. A change to the cards requires a new preview before saving or testing. Exercise the exact French Android-version example.

## Persistence and release

- [x] Persist natural-language cards on the draft and copy them to each published version. Keep their exact order and preserve the Android execution contract. Verify that repeating an interrupted save is safe and that a copied execution uses its original cards.
- [x] Check provider prompts with synthetic replies, PostgreSQL persistence, and the desktop and mobile editor. Update the workflow and execution guides and prepare a stable GitHub release.
