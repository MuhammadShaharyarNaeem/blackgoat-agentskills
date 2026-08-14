# Notifications — Implementation Plan

## Task 1: Delivery worker

**Requirements covered:** FR-1, NFR-1

**Boundary contracts:** consumes: db.schema, queue.topic; provides: notify.worker

Drains the queue and delivers notifications.

## Task 2: Subscription management endpoints

**Requirements covered:** FR-2

**Boundary contracts:** consumes: notify.worker; provides: notify.subscriptions

Lets a user add and remove subscriptions.

## Task 3: Database schema and queue provisioning

**Requirements covered:** None

**Boundary contracts:** provides: db.schema

Creates the notifications schema.

## Task 4: Admin dashboard panel

**Requirements covered:** None

Read-only panel over the subscription list; no boundary contracts field on purpose.
