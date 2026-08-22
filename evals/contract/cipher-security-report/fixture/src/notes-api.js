'use strict';

// In-memory stand-in for the persistence layer.
const NOTES = {
  'u-1': [{ id: 1, text: 'renew the acme contract' }],
  'u-9': [{ id: 2, text: 'draft the globex proposal' }]
};

let nextId = 3;

function listNotes(userId) {
  return { status: 200, body: { notes: NOTES[userId] || [] } };
}

function createNote(userId, payload) {
  const text = typeof payload.text === 'string' ? payload.text.slice(0, 2000) : '';
  if (!text) {
    return { status: 400, body: { error: 'text required' } };
  }
  const note = { id: nextId++, text: text };
  if (!NOTES[userId]) {
    NOTES[userId] = [];
  }
  NOTES[userId].push(note);
  return { status: 201, body: { id: note.id } };
}

module.exports = { listNotes, createNote };
