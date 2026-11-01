export type ApiTransport = (
  path: string,
  init?: RequestInit,
) => Promise<Response>;

// Production defaults to the existing same-origin HTTP boundary. Only the
// showcase entry point installs a local adapter, before mounting React.
let transport: ApiTransport = (path, init) => fetch(path, init);
export function configureTransport(adapter: ApiTransport) {
  transport = adapter;
}
export const apiFetch: ApiTransport = (path, init) => transport(path, init);
