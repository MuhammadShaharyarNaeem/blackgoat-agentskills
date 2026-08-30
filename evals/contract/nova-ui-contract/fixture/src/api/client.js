// The API client layer. The UI consumes these functions - it never reaches
// around them for direct data access (layered import rule, detailed-design.md
// "Component Breakdown"). All transport concerns (base URL, envelope
// unwrapping, error normalization) live here and only here.

const BASE = '/api';

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request(path) {
  const res = await fetch(BASE + path, {
    headers: { Accept: 'application/json' }
  });
  if (!res.ok) {
    throw new ApiError(res.status, 'request failed: ' + res.status);
  }
  const envelope = await res.json();
  // Envelope: { data: <payload>, error: null } | { data: null, error: { message } }
  if (envelope.error) {
    throw new ApiError(res.status, envelope.error.message);
  }
  return envelope.data;
}

export async function getSupplier(supplierId) {
  return request('/suppliers/' + supplierId);
}

export async function getSupplierContacts(supplierId) {
  return request('/suppliers/' + supplierId + '/contacts');
}

export { ApiError };
