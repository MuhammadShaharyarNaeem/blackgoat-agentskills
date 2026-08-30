# Research — Mailgrid link handling

Retrieved 2026-08-18 from the Mailgrid product documentation
(`https://docs.mailgrid.example/link-tracking`, `https://docs.mailgrid.example/api/send`)
and confirmed against the account's own dashboard settings.

## Question
FR-2 assumes Mailgrid can be told "this link is valid for 24 hours" and will refuse the
redirect afterwards. Can it?

## Finding — no. Mailgrid has no link TTL, and no equivalent.

1. **Link Tracking rewrites, it does not expire.** Mailgrid's Link Tracking feature
   replaces each `href` in an outgoing message with a tracking URL on its own domain so
   it can count opens and clicks. The tracking URL 302-redirects to the original target.
   The documentation lists exactly three per-message link settings — enable/disable
   tracking, the tracking domain, and the UTM tag set. There is no expiry, validity
   window, `max_age`, or TTL parameter, per-message or per-account.

2. **The tracking URL never stops redirecting.** The docs state that a tracking URL
   remains resolvable "for the lifetime of the account's message retention" and is
   explicitly described as not being a security boundary: "Link Tracking is an analytics
   feature. Do not use tracking URLs to gate access to protected resources."

3. **The send API has no expiry field.** `POST /v3/messages` accepts recipients, subject,
   body parts, headers, tags, and a `deliver_at` scheduling timestamp. `deliver_at`
   controls when the message is *sent*, not how long its contents remain usable. There is
   no field that expires anything after delivery.

4. **What Mailgrid does have** is webhooks for `delivered`, `opened`, `clicked`,
   `bounced`, and `complained` events. These report what happened to a message. None of
   them can prevent a request from arriving.

## Consequence for this system
Any expiry a user can observe has to be enforced by whatever answers the verification
request — that is, by this service. In practice that means the service must hold its own
record of each issued verification token (or a hash of it) together with the moment it
stops being usable, and must check that record on every verification request before
acting on it. There is no configuration of Mailgrid, and no combination of its features,
that produces the behaviour of a link the provider itself refuses to redirect after a
deadline.

## Confidence
High. This is the vendor's own current documentation on two separate pages plus the live
account settings screen, not a blog post or a community answer.
