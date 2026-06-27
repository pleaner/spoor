---
name: grill-me
description: Interview the user relentlessly about a plan or design. Use when the user wants to stress-test a plan before building, or uses any 'grill' trigger phrases.
---

Interview me relentlessly about the **product and architectural decisions** in this plan until we reach a shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one-by-one. For each question, provide your recommended answer.

Restrict your questions to product and architectural decisions only:
- **Product**: what we are building and why — scope, user needs, requirements, trade-offs in behaviour, what's in and out, success criteria.
- **Architectural**: how the system is structured — component boundaries, data models, interfaces, dependencies, technology choices, and the consequences of each.

Do not ask about implementation minutiae — naming, formatting, low-level coding tactics, or anything that does not change the product's behaviour or the system's architecture. If such a question arises, decide it yourself with a sensible default and move on.

Ask the questions one at a time, waiting for feedback on each question before continuing. Asking multiple questions at once is bewildering.

If a question can be answered by exploring the codebase, explore the codebase instead.