# Runtime policy provenance

`preview-seccomp.json` derives from Moby's Apache-2.0 default profile:
https://github.com/moby/profiles/blob/6fe7deb1b9fb7c0397a4593480d7d22b9ee8caef/seccomp/default.json
Retrieved October 8, 2026. License retained in `seccomp-LICENSE`.

CodeOps modifications retain the default deny action and capability-dependent
rules, remove `connect`, `socketcall`, `sendmsg` and `sendmmsg`, and replace the
generic socket allowance with Unix sockets, IPv4/IPv6 stream sockets and
NETLINK_ROUTE raw sockets for interface discovery. IP datagram/raw sockets are
not permitted. `sendto` is allowed only without the TCP Fast Open flag, preventing
that alternative outbound connection path. Socket pairs remain available for
local runtime communication. The policy applies to the serving container;
dependency/build containers use Docker's default seccomp policy.

This supports inbound HTTP/WebSockets and network-interface discovery while
disallowing application-initiated network connections. It also restricts Unix
`connect` and message-based IPC, so applications needing those operations may be
unsupported. No relaxed-policy switch is exposed through project profiles.
Docker must support this Linux seccomp policy; refusal fails preview startup,
without falling back to host execution or an unconfined container.

Docker reference: https://docs.docker.com/engine/security/seccomp/
