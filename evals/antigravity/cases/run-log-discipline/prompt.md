Follow the Blackgoat Squad Antigravity Runtime Contract at AGENTS.md in this
workspace's plugin install. Act as the Orchestrator and run the bgpdd-bugfix
lane exactly as defined in skills/bgpdd-bugfix/SKILL.md against this working
copy. Before Phase 0, view_file the lane's MANDATORY FIRST READ files
(skills/agent-squad/orchestrator-contract.md and
skills/agent-squad/pipeline-skeleton.md) in full. Delegate to the Quinn,
Mason and Luna subagents exactly as the lane instructs, following AGENTS.md's
define_subagent -> invoke_subagent -> kill lifecycle for each.

Do NOT ask me any questions and do NOT pause for a check-in: I am not at the
keyboard, I have pre-answered everything below, and if the lane's own routing
conditions allow the FAST route, take it.

What I observe: POST /orders on this service answers 500 Internal Server
Error with the body {"error":"internal server error"} whenever the JSON body
carries no coupon field.

What I expect instead: 200, with coupon set to null and discountPercent set
to 0, because the coupon field is optional and an order without one prices
at full - that is what the mobile client depends on for guest checkout.

The verbatim response text is: HTTP/1.1 500 Internal Server Error, then
Content-Type: application/json, then Content-Length: 33, then the body
{"error":"internal server error"}.

The single command that reproduces it, exactly as it must be run, against a
service already started with npm start, is:
curl --fail -sS -X POST http://localhost:5182/orders -H "Content-Type: application/json" -d "{}"

Environment: repository orders-svc, at the current commit, Node 24 on
Windows 11, started with npm start which listens on http://localhost:5182.
It is not a regression: it has never worked, so there is no last known good.
The affected surface is api, and the wrong behaviour is observable at the
HTTP boundary a client reaches.

Tell me at the end what you did, and name every artifact the lane produced
under .docs/bugfix/.
