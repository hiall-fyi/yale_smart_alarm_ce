# Security Policy

## Supported versions

Security fixes go into the latest release. If you're on an older version, update first and check whether the problem is still there.

## Reporting a vulnerability

Please don't open a public issue for a security problem. Use **Security → Report a vulnerability** on the [repository page](https://github.com/hiall-fyi/yale_smart_alarm_ce/security/advisories/new) so the report stays private until a fix is out.

A useful report says what you found, how to reproduce it, and which version and Home Assistant release you were running. You'll get a reply once it has been read, and a fixed release is credited to you unless you'd rather it wasn't.

This integration controls a home alarm and door locks, so anything that lets someone arm, disarm, lock or unlock without your Yale account is worth reporting.

## Keep these out of public issues and logs

When you file an ordinary bug report, remove or replace:

- Your Yale password, verification codes and any access or refresh tokens.
- Your install ID, lock PIN codes and encryption keys.
- Your account email, alarm ID, lock IDs and serial numbers.

The diagnostics download redacts identifiers for you, so attach that rather than copying values out of the logs by hand. Debug logs are not redacted, so read them through before posting.
