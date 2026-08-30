# Blackgoat Idea Honing — Rationale

On-demand companion to the `blackgoat-idea-honing` operational spine (`../SKILL.md`). The spine carries the contract; this file carries the reasoning behind each constraint. Nothing here is needed to execute the contract.

## One question at a time

Listing several questions at once overwhelms the user: the answers come back partial, the unanswered ones look answered, and the transcript records a decision nobody made. The single-question cadence exists so that every question has exactly one recorded answer, and so an unanswered question is visibly unanswered.

## A question must carry its own finding

The user is deciding, not auditing. A question that requires them to reconstruct the analysis behind it — to work out what the two options actually differ on — is answered by whichever option sounds safer, which is not a decision about the system.

Hence the corollary about clarification requests. When the user replies "I don't understand this" instead of choosing, the question was underspecified; that is an authoring defect on the asker's side, not friction on the user's. Treating the request as a decision, or treating silence as consent to the preferred option, converts the asker's preference into a requirement while leaving a transcript that reads as if the user chose it. An unanswered question that reaches the requirements document as a silent assumption is the same failure one step further downstream, where nothing distinguishes it from something the user asked for.

## What the Q&A checklist items catch

- **Visual design and shared component library.** Styling and component-consistency expectations are real non-functional requirements. Left unasked, they arrive after the UI is built, as rework. They go in the normal `NFR-<n>` sequence with a MoSCoW tier because downstream coverage gates recognize only that form.
- **Check-then-act gates on counted state.** Quota, balance, rate, seat, and credit gates all share the read-then-decide shape, and the concurrency question has to be asked of each one: these gates travel in families, so catching one instance is not catching the class.
- **Externally-supplied amounts that move money.** A signed payload proves the sender, not the number. "The provider signs it" answers authenticity and leaves correctness unasked, which is exactly the gap an amount-tampering defect lives in.
- **MoSCoW tiers must discriminate.** MoSCoW is information only if some requirements are not Must. If nearly everything lands in Must-Have, the tiering has failed: the requirement list has been relabelled rather than tiered, and every downstream gate that keys on Must-Have has lost its ability to prioritize.
