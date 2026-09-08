# SOLID and Separation of Concerns — how this contract already encodes them

Depth for `../SKILL.md` § *Design Principles — SOLID & Separation of Concerns*. Read on demand; the spine is executable without it. Nothing here is a new rule — each item names the section of the contract that already enforces the principle, so that a reader who knows SOLID by name can see where it lives and a reviewer can say *which structural rule* an erosion violated.

- **Separation of Concerns** — enforced by *Solution Segregation* and, in Mode B, by vertical slices (Locality of Behavior). Framework and IO concerns (EF Core, ASP.NET, vendor SDKs) stay out of `Domain`/`Core`. Do not leak persistence or transport types into domain logic.
- **DIP (dependency inversion)** — dependencies point *inward*: `Domain`/`Core` defines the interfaces (`IEmailService`, `IPaymentGateway`, …), `Infrastructure` implements them, and the composition root (`Program.cs` / DI registration) is the only place a concrete binds. `Core` depends on nothing.
- **SRP** — one reason to change per unit: one handler or endpoint per use case; no god services. A 20-method `CustomerService` is the smell; the fix is extracting a `{Feature}Service`.
- **ISP** — `Core` interfaces stay narrow and role-specific. Never force an implementer to stub members it does not use — that pressure is what produces the `NotImplementedException` the spine forbids.
- **OCP/LSP** — extend via new handlers, slices or behaviors rather than editing shared cross-cutting code, and honour an interface's contract fully wherever it is implemented.

**Why this is depth rather than spine.** Every bullet above is a restatement of a structural rule the contract already states mechanically — which project may reference which, which mode a file follows, which envelope a response uses. A reviewer enforces the structural rule; the principle name is vocabulary for explaining *why* the structural rule exists. Keeping the vocabulary here and the rules in the spine is what stops the two drifting into two competing checklists.
