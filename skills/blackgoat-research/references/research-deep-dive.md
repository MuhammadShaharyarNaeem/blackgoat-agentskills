# Blackgoat Research — Deep Dive

On-demand companion to the `blackgoat-research` operational spine (`../SKILL.md`). The spine carries the contract; this file carries the rationale and the observed failures behind each rule. Nothing here is needed to execute the contract.

## Why one principle, five corollaries

The spine's step 6 states a single obligation — *the document must be true wherever a reader lands* — and derives the rest from it. That shape is not tidiness; it is the shared cause of every failure recorded below. A blueprint is not read linearly. A downstream agent arrives at the sample, the table, the diagram, the numbered step, or the Open Questions list that answers its question, implements what it finds, and never learns that some other passage contradicts it. Every corollary is the same rule applied to a different landing spot: samples (what gets copied), frozen sections (what gets transcribed literally), `requirements.md` (what still reads as a live mandate), retracted text (what a banner fails to reach), and members of an assertion set (what looks fine alone).

Two consequences follow that are easy to miss when the rules are read as five separate items. First, the obligation is *after every edit*, not at first authoring — a revision pass is exactly when the document is most likely to acquire contradictions, because the author is thinking about the change and not about the passages that describe the change's absence. Second, an obligation an author can satisfy by relabelling is not an obligation; that is why the supersession trigger keys on a semantic test rather than on which register table a row lands in (see [the routing test](#the-routing-test)).

## Samples are normative

A blueprint states invariants in prose and illustrates them in samples. When the two disagree, the document **will be implemented as the sample** — downstream agents copy samples and only skim prose. That is why the rule is "fix the sample, not the prose beside it": restating the invariant next to a wrong sample leaves the wrong sample in place, and the wrong sample is what ships.

Payload-reshaping samples (unwrapping, mapping, projecting) are the highest-risk class, because a sibling field silently dropped in an example becomes a sibling field silently dropped in the implementation, and nothing downstream knows it was ever supposed to be there.

The boundary-resolvability check exists for a related reason: a design can mandate crossing a module, package, or process boundary that the consuming side has no declared way to resolve. A mandated import with no declared dependency is a blueprint that cannot be built, and the failure surfaces at build time in the builder's context — far from the design decision that caused it.

## Frozen means literal

A section labelled frozen, authoritative, or normative carries a promise that it can be implemented exactly as written. An elision breaks that promise silently: a downstream agent materialising a frozen contract **transcribes the ellipsis as content**. In practice `…` becomes an empty schema, "same as above" becomes a bare `string` where a real type belonged, and "etc." becomes a junk type parsed out of the sentence.

This is not a style preference. Prose elisions inside a section that read as authoritative are how one contract produced dozens of broken definitions downstream. Hence the hard test: if a section is too long to write out in full, it is too long to freeze.

## Revision integrity

Observed on the Travel-Goat v8 run, in the first live pass of the Phase 2.5 design gate. The revision responded to the gate's findings by **layering amendment banners and a new "Revision R1" section over the stale normative text**, rather than rewriting the affected passages in place. The document grew from 4,908 to 8,716 lines — 78% — in a single gate pass, and the contradictions the revision existed to remove were still standing afterwards in tables, diagrams, and numbered steps.

The failure mode is specific and worth understanding: a reader does not arrive at a document's top and read forward. They arrive at the table, the diagram, or the numbered step that answers their question, implement what it says, and never learn that a later section retracted it. An amendment banner protects only readers who read linearly, which is nobody working from a blueprint.

The same run left the document's own table of contents listing sections 1–18 and omitting section 19 — the very section a banner at the top declared authoritative over everything before it. That is the state-section half of the rule: an amendment that answers a question while leaving it listed under Open Questions makes the document lie about itself, and the stale section is the one a reader trusts for "what is left". On the same run, `requirements.md` still described the payment gateway as unnamed after honing had pinned a specific vendor, in a file that had been edited *after* that decision.

If a retraction is too large to integrate in place, that is information: the document needs re-authoring, not a banner.

## The routing test

Observed on the same run. The design deleted a set of Cognito custom attributes that `FR-29` still mandated. The contradiction was recorded — in the Divergence table — and therefore never triggered the supersession obligations, because those attach to the register's supersession rows rather than to its divergence rows. `FR-29` sat in `requirements.md` with no strikethrough and no "superseded by" note, still reading as a live Must-Have mandating attributes the design had removed.

The lesson is about gate design, not about that FR. A register whose completeness claim is satisfiable by **writing the row in the other table** is not a gate. The obligation therefore has to key on a semantic test the author cannot route around — *does this decision make any sentence of an existing requirement false?* — rather than on which heading the author filed the row under. Editorial framing ("this is really just a clarification", "that's an implementation detail") is precisely the move the test is designed to defeat.

Note what worked, for contrast: on the same run, ten well-formed annotations were written correctly, and one requirement was **deliberately left unannotated** because annotating it would have enacted a supersession the user had not approved. Annotation-as-consent held under pressure. The mechanism is sound; only its trigger was evadable.

## Sets as sets

Also observed on the Travel-Goat v8 run, and self-flagged in that run's own blockers ledger as a recurring class. Three separate instances appeared of an assertion or enumeration that was individually plausible but **mutually unsatisfiable with another member of its own set**:

- Two infrastructure assertions in direct conflict — one forbidding compute in a tier, another requiring a trigger function in that same tier.
- A phantom id in an anonymous-route allow-list, naming no route that existed. Its cost is not cosmetic: it fails the endpoint enumeration test, and the natural developer response is to widen the allow-list by hand until the test passes.
- An assertion claiming read access to custom attributes that a later section of the same document deleted.

The ledger's own conclusion was that the assertion set "has never been walked against itself as a whole." That is the gap the rule closes. Checking each assertion against the design is pairwise review; checking the assertion set against itself is set review, and only the latter catches mutual unsatisfiability or a member that references nothing.

`bgpdd-plan` Phase 2.5's attack item 5 now carries the set-walk explicitly, so the same check exists at gate time as well as here. The division of labour is deliberate: the gate is the backstop, this rule is the obligation, and satisfying it at authoring time is far cheaper than discovering the contradiction in a review round that is bounded to one revision pass.
