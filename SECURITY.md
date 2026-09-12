# Security policy

Jotline is a local, offline notes app. The latest published release receives
security fixes; older releases are not maintained as separate support branches.

Report suspected vulnerabilities through
[GitHub private vulnerability reporting](https://github.com/CaulShiver/jotline/security/advisories/new).
Include the affected version, platform, reproduction steps using synthetic notes,
and the expected impact. Do not attach personal vaults, credentials, or sensitive
note bodies. Please allow time for assessment before public disclosure; this
volunteer project does not promise a response SLA.

For ordinary bugs, use the bug-report template. `jotline doctor --json` excludes
note bodies but includes local paths; review it before sharing.

Vaults are user-owned local storage. Workspaces are organizational boundaries,
not access controls. Backups in the vault do not protect against device loss.
Jotline's locks coordinate Jotline writers; external editors and sync tools do not
participate in that protocol. Keep independent backups when synchronizing files.
