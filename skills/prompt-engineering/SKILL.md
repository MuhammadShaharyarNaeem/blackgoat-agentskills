---
name: prompt-engineering
description: "Refines a rough prompt through interactive one-question-at-a-time honing, then transforms it into an optimized prompt using frameworks (RTF, RISEN, Chain of Thought, RODES, Chain of Density, RACE, RISE, STAR, SOAP, CLEAR, GROW). Use whenever the user wants to improve, refine, optimize, or create a prompt for any AI model — including phrasings like 'make me a prompt', 'how do I ask AI to...', or when they hand over a vague prompt and want it sharpened."
category: automation
risk: safe
source: community
tags: "[prompt-engineering, optimization, frameworks, ai-enhancement]"
date_added: "2026-02-27"
---

## Purpose

Transforms raw, unstructured prompts into optimized ones: analyze intent, hone it interactively, then apply the best-fitting prompting framework(s).

- **Framework selection is silent ("magic mode")** — the user gets a polished, ready-to-use prompt, never framework jargon or an explanation of the choice.
- **Requirements gathering is interactive** — hone intent through one-at-a-time questions before generating anything.

## When to Use
Invoke this skill when:

- User provides a vague or generic prompt (e.g., "help me code Python")
- User has a complex idea but struggles to articulate it clearly
- User's prompt lacks structure, context, or specific requirements
- Task requires step-by-step reasoning (debugging, analysis, design)
- User needs a prompt for a specific AI task but doesn't know prompting frameworks
- User wants to improve an existing prompt's effectiveness
- User asks variations of "how do I ask AI to..." or "create a prompt for..."

## Workflow

### Step 1: Analyze Intent

**Objective:** Understand what the user truly wants to accomplish.

Read the raw prompt, then classify it:
- **Type:** coding, writing, analysis, design, learning, planning, decision-making, creative, etc.
- **Complexity:** simple (one-step), moderate (multi-step), complex (requires reasoning/design)
- **Clarity:** clear intention vs. ambiguous/vague
- **Domain:** technical, business, creative, academic, personal, etc.

Then name the implicit requirements: examples needed? output format specified? constraints (time, resources, scope)? exploratory or execution-focused?

**Detection Patterns:**
- **Simple tasks:** Short prompts (<50 chars), single verb, no context
- **Complex tasks:** Long prompts (>200 chars), multiple requirements, conditional logic
- **Ambiguous tasks:** Generic verbs ("help", "improve"), missing object/context
- **Structured tasks:** Mentions steps, phases, deliverables, stakeholders


### Step 2: Interactive Questioning (Idea Honing)

**Objective:** Refine the raw prompt into a fully specified intent through targeted Q&A — never assume what the user did not say.

**Constraints:**
- **ONE question at a time.** Ask, wait for the complete response, then ask the next. NEVER list multiple questions at once — it overwhelms the user.
- **Every question is multiple-choice.** 2-4 concrete, mutually exclusive options, so the user picks instead of composing. In Claude Code use the AskUserQuestion tool when available (native options, automatic "Other"); otherwise a lettered list (A/B/C/D). A free-form reply outside the options is always valid.
- NEVER pre-populate answers or assume user preferences.
- **A question must carry its own finding.** State each option's concrete consequence for the final prompt and what actually differs between them — the user must not have to reconstruct your analysis to answer.
- **Teach the finding when asked, then re-ask.** A reply asking for explanation ("I don't understand this", "explain more") is a defect in how you posed the question, not user friction. Explain what each option changes about the final prompt, then re-ask. NEVER read a request for clarification as a decision. NEVER let an unanswered question fall through into the generated prompt as a silent assumption.
- **Follow the thread.** No cap on question count or depth. An answer that raises a new question, surfaces a contradiction, or opens an unclear area gets drilled first — depth over breadth, one thread fully resolved before the next.
- Per-question sequence: formulate one targeted question → present it → wait for the complete response → ask any follow-ups (one at a time) until the thread resolves → move to the next topic.

**What to probe** (in rough priority order, skipping anything already answered by the raw prompt):
- Task type — coding vs. writing vs. analysis vs. design, if ambiguous
- Target audience/model and how it materially affects the output
- Scope boundaries — what is in and out
- Desired output format and level of detail
- Constraints — time, resources, tone, length, technology
- Edge cases and failure behavior the prompt should handle

**Example Exchange:**

```
User: "help me with AI"

Q1: "What do you want to do with AI?
  A) Build something with it — the prompt will target system design
  B) Learn about it — the prompt will target a study path
  C) Use an AI tool for a task — the prompt will target task instructions"

User: "A"

Q2: "What are you building?
  A) An app that calls an AI model — prompt covers API integration design
  B) An agent/automation — prompt covers agent architecture and tool use
  C) Fine-tuning a model — prompt covers data prep and training strategy"
```

**Completion:** Continue — however many rounds it takes — until every critical uncertainty is resolved and no thread dangles, then go straight to Step 3 and deliver the optimized prompt. No summaries, no confirmation round-trips, no transcript files — just questions, then the prompt.


### Step 3: Select Framework(s)

**Objective:** Map task characteristics to optimal prompting framework(s).

**Framework Mapping Logic:**

| Task Type | Recommended Framework(s) | Rationale |
|-----------|-------------------------|-----------|
| **Role-based tasks** (act as expert, consultant) | **RTF** (Role-Task-Format) | Clear role definition + task + output format |
| **Step-by-step reasoning** (debugging, proof, logic) | **Chain of Thought** | Encourages explicit reasoning steps |
| **Structured projects** (multi-phase, deliverables) | **RISEN** (Role, Instructions, Steps, End goal, Narrowing) | Comprehensive structure for complex work |
| **Complex design/analysis** (systems, architecture) | **RODES** (Role, Objective, Details, Examples, Sense check) | Balances detail with validation |
| **Summarization** (compress, synthesize) | **Chain of Density** | Iterative refinement to essential info |
| **Communication** (reports, presentations, storytelling) | **RACE** (Role, Audience, Context, Expectation) | Audience-aware messaging |
| **Investigation/analysis** (research, diagnosis) | **RISE** (Research, Investigate, Synthesize, Evaluate) | Systematic analytical approach |
| **Contextual situations** (problem-solving with background) | **STAR** (Situation, Task, Action, Result) | Context-rich problem framing |
| **Documentation** (medical, technical, records) | **SOAP** (Subjective, Objective, Assessment, Plan) | Structured information capture |
| **Goal-setting** (OKRs, objectives, targets) | **CLEAR** (Collaborative, Limited, Emotional, Appreciable, Refinable) | Goal clarity and actionability |
| **Coaching/development** (mentoring, growth) | **GROW** (Goal, Reality, Options, Will) | Developmental conversation structure |

**Selection rules:**
- Primary framework = best match to the core task type; secondary framework(s) cover additional complexity dimensions.
- **Blend 2-3 frameworks** when the task spans multiple types. Complex technical project → **RODES + Chain of Thought**; leadership decision → **CLEAR + GROW**.
- Avoid over-engineering: simple tasks get simple frameworks.
- **Critical Rule:** selection happens **silently** — never explain the framework choice to the user.

### Step 4: Generate the Optimized Prompt

**Objective:** Compose the final prompt in a Markdown code block, weaving the selected framework(s) in without naming them.

Example composition (the bracketed framework tags are authoring notes — they never appear in the delivered prompt):

```
Role: You are a senior software architect. [RTF - Role]

Objective: Design a microservices architecture for [system]. [RODES - Objective]

Approach this step-by-step: [Chain of Thought]
1. Analyze current monolithic constraints
2. Identify service boundaries
3. Design inter-service communication
4. Plan data consistency strategy

Details: [RODES - Details]
- Expected traffic: [X]
- Data volume: [Y]
- Team size: [Z]

Output Format: [RTF - Format]
Provide architecture diagram description, service definitions, and migration roadmap.

Sense Check: [RODES - Sense check]
Validate that services are loosely coupled, independently deployable, and aligned with business domains.
```

**4.5. Language Adaptation**
- If original prompt is in Portuguese, generate prompt in Portuguese
- If original prompt is in English, generate prompt in English
- If mixed, default to English (more universal for AI models)

**4.6. Quality Checks**
Before finalizing, verify:
- [ ] Prompt is self-contained (no external context needed)
- [ ] Task is specific and measurable
- [ ] Output format is clear
- [ ] No ambiguous language
- [ ] Appropriate level of detail for task complexity


## Critical Rules

### **NEVER:**

- ❌ Assume information that wasn't provided - ALWAYS ask if critical details are missing
- ❌ Explain which framework was selected or why (magic mode - keep it invisible)
- ❌ Generate generic, one-size-fits-all prompts - always customize to context
- ❌ Use technical jargon in the final prompt (unless user's domain is technical)
- ❌ Ask more than ONE question at a time (one question, wait for answer, then the next)
- ❌ Include meta-commentary in the output ("This prompt uses...", "Note that...")
- ❌ Present output without code block formatting
- ❌ Mix languages inconsistently (if user writes in PT, respond in PT)

### **ALWAYS:**

- ✅ Analyze intent before generating (Step 1 is mandatory)
- ✅ Hone intent through one-at-a-time multiple-choice questions until critical uncertainties are resolved (Step 2)
- ✅ Select framework(s) based on task type and complexity (Step 3 mapping)
- ✅ Blend multiple frameworks when it improves prompt quality
- ✅ Adapt prompt length to original input complexity (simple → short, complex → detailed)
- ✅ Include output format specification in generated prompts
- ✅ Present final prompt in clean Markdown code block
- ✅ Make prompts self-contained (no dependency on external context)
- ✅ Use examples in complex prompts to illustrate expected output
- ✅ Validate prompt completeness before presenting (quality checks in Step 4.6)


### **Example 2: Complex Clear Prompt → RODES + Chain of Thought (No Clarification)**

**User Input:**
```
copilot> create prompt for: I need to build a product recommendation system considering purchase history, user preferences, and market trends
```

**Skill Internal Process:**
1. **Analyze:** Clear intent, complex task (ML system design), technical domain
2. **Clarify:** Skip (sufficient information)
3. **Select:** RODES (complex design) + Chain of Thought (reasoning needed)

**Skill Output:**

````markdown
```
Role: You are a senior machine learning engineer specializing in recommendation systems.

Objective: Design a product recommendation system that combines user purchase history, preferences, and market trends.

Details:
- Input data sources: user transaction logs, preference surveys, market trend APIs
- Algorithm considerations: collaborative filtering, content-based filtering, hybrid approaches
- Performance metrics: precision, recall, diversity, novelty
- Scalability: system must handle 100k+ users
- Real-time constraints: recommendations updated within 500ms

Approach step-by-step:
1. Analyze the three data sources and their relationships
2. Propose 2-3 algorithm approaches with trade-offs analysis
3. Design data pipeline architecture (ingestion, processing, serving)
4. Define evaluation metrics and A/B testing strategy
5. Outline implementation roadmap with phases

Examples:
- Show pseudocode for core recommendation logic
- Illustrate data flow diagram
- Provide sample API response structure

Sense Check: Validate that the proposed solution balances personalization with discovery, scales to production load, and incorporates real-time market trends effectively.

Output format: Technical design document with architecture diagrams, algorithm justification, and implementation roadmap.
```
````


### **Example 4: Code Debugging → Chain of Thought**

**User Input:**
```
copilot> optimize prompt: my Python code isn't working, needs debugging
```

**Skill Internal Process:**
1. **Analyze:** Debugging task, needs step-by-step reasoning
2. **Clarify:** Skip (user will provide code context later)
3. **Select:** Chain of Thought

**Skill Output:**

````markdown
```
You are an expert Python debugger.

Task: Debug the Python code provided by the user by analyzing it step-by-step.

Debugging approach:
1. Read and understand the code's intended purpose
2. Identify the error or unexpected behavior
3. Trace variable states at each execution step
4. Locate the root cause of the issue
5. Propose fix with explanation
6. Suggest preventive measures to avoid similar bugs

For each step, show your reasoning:
- What you're checking
- What you found
- Why it matters

Output format:
- **Issue identified:** [Describe the bug]
- **Root cause:** [Why it's happening]
- **Fix:** [Corrected code with comments]
- **Prevention:** [Best practices to avoid this in the future]

Include a working example to verify the fix.
```
````


## Notes

Platform-agnostic and entirely self-contained: operates purely on user input and framework knowledge. No dependency on Obsidian vault structure, specific project configurations, or external files and templates.

## Limitations
- Use this skill only when the task clearly matches the scope described above.
- Do not treat the output as a substitute for environment-specific validation, testing, or expert review.
- Stop and ask for clarification if required inputs, permissions, safety boundaries, or success criteria are missing.
